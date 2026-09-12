"""pgvector backend for the retrieval index.

Keeps the vector index in the same Postgres database as the notes, so the whole
system has one source of truth and one thing to back up. Implements the same
`VectorStore` contract as the Chroma and in-memory backends, so nothing that
retrieves notes knows or cares which one is configured.

**Why a separate table rather than a column on `notes`.** A long note is split
into several chunks, each with its own vector (see `app/rag/indexer.py`), so the
relationship is one note to many vectors. The chunk id stays `<note_id>::<n>`
and `note_id` is stored alongside it, which is what lets `delete_by_note` clear
every chunk without knowing how many there were.

**The index is still derived.** Sharing a database with the notes does not make
these rows authoritative - they are rebuildable at any time with
`POST /api/v1/retrieval/reindex`. That is what keeps an indexing failure a
degradation rather than data loss.

Distances: pgvector's `<=>` is cosine *distance* (0 = identical). Every score
leaving this module is converted to a similarity in 0-1, higher is better, so
callers never have to remember which convention a backend used.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.rag.vector_store import RetrievalFilter, VectorMatch, VectorStore, to_epoch

logger = logging.getLogger(__name__)

TABLE = "note_vectors"


class PgVectorStore(VectorStore):
    """Vector index stored in Postgres via the pgvector extension."""

    name = "pgvector"

    def __init__(self, database_url: str, dimension: int):
        self.dimension = dimension
        # SQLAlchemy-style URLs carry a driver ("postgresql+psycopg://"); the
        # psycopg connection string must not.
        self._dsn = database_url.replace("postgresql+psycopg://", "postgresql://")
        self._ensure_schema()

    # --- connection -----------------------------------------------------

    def _connect(self):
        import psycopg

        return psycopg.connect(self._dsn)

    def _ensure_schema(self) -> None:
        """Create the extension, table and indexes if they are not there yet.

        Safe to run on every startup and from several machines at once: every
        statement is IF NOT EXISTS, so whoever gets there first wins and the
        rest no-op. That matters with a shared database and three developers
        starting their backends independently.
        """
        create_table = (
            "CREATE TABLE IF NOT EXISTS " + TABLE + " ("
            "  id            TEXT PRIMARY KEY,"
            "  note_id       TEXT NOT NULL,"
            "  document      TEXT NOT NULL,"
            "  metadata      JSONB NOT NULL DEFAULT '{}'::jsonb,"
            "  embedding     VECTOR(" + str(self.dimension) + "),"
            "  subject_id    TEXT,"
            "  topic_id      TEXT,"
            "  note_type     TEXT,"
            "  created_epoch BIGINT"
            ")"
        )
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute(create_table)
            # note_id is the only lookup that is not by primary key, and
            # delete_by_note runs on every re-index of an edited note.
            cur.execute(
                "CREATE INDEX IF NOT EXISTS " + TABLE + "_note_id_idx "
                "ON " + TABLE + " (note_id)"
            )
            # Filters narrow the candidate set before ranking, so they are worth
            # indexing.
            cur.execute(
                "CREATE INDEX IF NOT EXISTS " + TABLE + "_filter_idx "
                "ON " + TABLE + " (subject_id, topic_id, note_type, created_epoch)"
            )
            conn.commit()
        logger.info("pgvector schema ready (dimension=%d)", self.dimension)

    # --- writes ---------------------------------------------------------

    def upsert(self, ids, embeddings, documents, metadatas) -> None:
        if not ids:
            return

        rows = []
        for id_, embedding, document, metadata in zip(
            ids, embeddings, documents, metadatas
        ):
            metadata = dict(metadata or {})
            rows.append(
                (
                    id_,
                    str(metadata.get("note_id") or id_.split("::")[0]),
                    document,
                    json.dumps(metadata),
                    list(embedding),
                    metadata.get("subject_id"),
                    metadata.get("topic_id"),
                    metadata.get("note_type"),
                    metadata.get("created_epoch"),
                )
            )

        statement = (
            "INSERT INTO " + TABLE + " (id, note_id, document, metadata, embedding,"
            " subject_id, topic_id, note_type, created_epoch)"
            " VALUES (%s, %s, %s, %s::jsonb, %s::vector, %s, %s, %s, %s)"
            " ON CONFLICT (id) DO UPDATE SET"
            "   note_id = EXCLUDED.note_id,"
            "   document = EXCLUDED.document,"
            "   metadata = EXCLUDED.metadata,"
            "   embedding = EXCLUDED.embedding,"
            "   subject_id = EXCLUDED.subject_id,"
            "   topic_id = EXCLUDED.topic_id,"
            "   note_type = EXCLUDED.note_type,"
            "   created_epoch = EXCLUDED.created_epoch"
        )
        with self._connect() as conn, conn.cursor() as cur:
            cur.executemany(statement, rows)
            conn.commit()

    def delete(self, ids) -> None:
        if not ids:
            return
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM " + TABLE + " WHERE id = ANY(%s)", (list(ids),))
            conn.commit()

    def delete_by_note(self, note_id: str) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM " + TABLE + " WHERE note_id = %s", (note_id,))
            conn.commit()

    def clear(self) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE " + TABLE)
            conn.commit()

    # --- reads ----------------------------------------------------------

    def count(self) -> int:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM " + TABLE)
            return int(cur.fetchone()[0])

    def query(self, embedding, n_results=5, where=None) -> list[VectorMatch]:
        clauses, params = _where_sql(where)

        sql = (
            "SELECT id, document, metadata, embedding <=> %s::vector AS distance"
            " FROM " + TABLE
        )
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY distance ASC LIMIT %s"

        # Placeholder order follows the statement: query vector, filters, limit.
        args: list[Any] = [list(embedding), *params, max(1, n_results)]

        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql, args)
            rows = cur.fetchall()

        matches: list[VectorMatch] = []
        for id_, document, metadata, distance in rows:
            matches.append(
                VectorMatch(
                    id=id_,
                    document=document or "",
                    metadata=dict(metadata or {}),
                    # Cosine distance -> similarity, clamped: floating point can
                    # put an identical vector a hair outside 0-1.
                    score=max(0.0, min(1.0, 1.0 - float(distance))),
                )
            )
        return matches


def _where_sql(where: RetrievalFilter | None) -> tuple[list[str], list[Any]]:
    """Translate a `RetrievalFilter` into SQL applied before ranking.

    Filtering in the WHERE clause rather than after the top-k is the whole
    point: "about databases, last week" has to narrow the candidate set, or the
    date constraint degenerates into a hint that the ranking ignores.
    """
    if where is None or where.is_empty():
        return [], []

    clauses: list[str] = []
    params: list[Any] = []

    if where.subject_ids:
        clauses.append("subject_id = ANY(%s)")
        params.append(list(where.subject_ids))
    if where.topic_ids:
        clauses.append("topic_id = ANY(%s)")
        params.append(list(where.topic_ids))
    if where.note_types:
        clauses.append("note_type = ANY(%s)")
        params.append(list(where.note_types))
    if where.note_ids:
        clauses.append("note_id = ANY(%s)")
        params.append(list(where.note_ids))
    if where.created_after is not None:
        clauses.append("created_epoch >= %s")
        params.append(to_epoch(where.created_after))
    if where.created_before is not None:
        clauses.append("created_epoch <= %s")
        params.append(to_epoch(where.created_before))

    return clauses, params
