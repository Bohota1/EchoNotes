"""Vector storage for retrieval (Phase 4).

One interface, three backends, selected by `VECTOR_STORE`:

  ``chroma``   (default) - ChromaDB, persisted under `CHROMA_DIR`. Survives
               restarts and does metadata filtering in the engine.
  ``pgvector`` - the same Postgres database the notes live in, via the pgvector
               extension. One store to back up, and the whole team shares one
               index. See `app/rag/pgvector_store.py`.
  ``memory``   - brute-force cosine over numpy. No persistence, no dependency,
               instant startup. What the test suite uses, and a working fallback
               when the configured backend cannot be reached.

Filtering is expressed as a `RetrievalFilter`, not as a raw backend query. That
matters: "what did I write about databases *last week*" has to be a filter
applied *before* ranking, or the date constraint degenerates into a hint that
the top-k silently ignores. Each backend translates the filter itself, so the
retriever never learns Chroma's `$and`/`$gte` syntax and a third backend can be
added without touching callers.

Distance vs. similarity: Chroma returns cosine *distance* (0 = identical). Every
score leaving this module is a *similarity* in 0-1, higher is better, so callers
never have to remember which convention a backend used.
"""

from __future__ import annotations

import abc
import logging
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

#: Chroma requires 3-63 chars, alphanumeric plus _ and -.
COLLECTION_NAME = "echonotes_notes"


@dataclass
class VectorMatch:
    """One retrieved chunk, with its similarity and the metadata it was
    filtered on."""

    id: str
    document: str
    metadata: dict[str, Any]
    score: float  # cosine similarity in 0-1, higher is better

    @property
    def note_id(self) -> str:
        """The note this chunk belongs to. Chunk ids are ``<note_id>::<n>``."""
        return str(self.metadata.get("note_id") or self.id.split("::")[0])


@dataclass
class RetrievalFilter:
    """Hierarchy and time constraints applied before ranking.

    Every field is optional; an empty filter matches everything.
    """

    subject_ids: list[str] = field(default_factory=list)
    topic_ids: list[str] = field(default_factory=list)
    note_types: list[str] = field(default_factory=list)
    note_ids: list[str] = field(default_factory=list)
    created_after: datetime | None = None
    created_before: datetime | None = None

    def is_empty(self) -> bool:
        return not any(
            [
                self.subject_ids,
                self.topic_ids,
                self.note_types,
                self.note_ids,
                self.created_after,
                self.created_before,
            ]
        )

    def describe(self) -> str:
        """Human-readable summary, used in spoken responses and in logs."""
        parts: list[str] = []
        if self.note_types:
            parts.append(" or ".join(self.note_types))
        if self.subject_ids:
            parts.append(f"{len(self.subject_ids)} subject(s)")
        if self.topic_ids:
            parts.append(f"{len(self.topic_ids)} topic(s)")
        if self.created_after and self.created_before:
            parts.append(
                f"{self.created_after:%d %b} to {self.created_before:%d %b}"
            )
        elif self.created_after:
            parts.append(f"since {self.created_after:%d %b}")
        elif self.created_before:
            parts.append(f"before {self.created_before:%d %b}")
        return ", ".join(parts)


def to_epoch(value: datetime | None) -> int | None:
    """Chroma metadata values must be scalars, so timestamps are stored as
    epoch seconds to stay range-queryable."""
    if value is None:
        return None
    return int(value.timestamp())


class VectorStore(abc.ABC):
    """Minimal vector index: upsert, delete, query, count, clear."""

    name: str = "base"

    @abc.abstractmethod
    def upsert(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[dict[str, Any]],
    ) -> None: ...

    @abc.abstractmethod
    def delete(self, ids: list[str]) -> None: ...

    @abc.abstractmethod
    def delete_by_note(self, note_id: str) -> None:
        """Remove every chunk belonging to a note."""

    @abc.abstractmethod
    def query(
        self,
        embedding: list[float],
        n_results: int = 5,
        where: RetrievalFilter | None = None,
    ) -> list[VectorMatch]: ...

    @abc.abstractmethod
    def count(self) -> int: ...

    @abc.abstractmethod
    def clear(self) -> None:
        """Drop everything. Used by `reindex_all` and by tests."""


# ---------------------------------------------------------------------------
# In-memory backend
# ---------------------------------------------------------------------------


class InMemoryVectorStore(VectorStore):
    """Brute-force cosine over a dict. Correct, not scalable - which is the
    right trade for a test suite and for a fallback."""

    name = "memory"

    def __init__(self) -> None:
        self._vectors: dict[str, list[float]] = {}
        self._documents: dict[str, str] = {}
        self._metadatas: dict[str, dict[str, Any]] = {}

    def upsert(self, ids, embeddings, documents, metadatas) -> None:
        for id_, embedding, document, metadata in zip(
            ids, embeddings, documents, metadatas
        ):
            self._vectors[id_] = list(embedding)
            self._documents[id_] = document
            self._metadatas[id_] = dict(metadata)

    def delete(self, ids) -> None:
        for id_ in ids:
            self._vectors.pop(id_, None)
            self._documents.pop(id_, None)
            self._metadatas.pop(id_, None)

    def delete_by_note(self, note_id: str) -> None:
        doomed = [
            id_
            for id_, metadata in self._metadatas.items()
            if metadata.get("note_id") == note_id
        ]
        self.delete(doomed)

    def query(self, embedding, n_results=5, where=None) -> list[VectorMatch]:
        import numpy as np

        query_vector = np.asarray(embedding, dtype=np.float64)
        query_norm = float(np.linalg.norm(query_vector))
        if query_norm == 0:
            return []

        matches: list[VectorMatch] = []
        for id_, vector in self._vectors.items():
            metadata = self._metadatas[id_]
            if where is not None and not _matches_filter(metadata, where):
                continue
            candidate = np.asarray(vector, dtype=np.float64)
            candidate_norm = float(np.linalg.norm(candidate))
            if candidate_norm == 0:
                continue
            score = float(np.dot(query_vector, candidate) / (query_norm * candidate_norm))
            matches.append(
                VectorMatch(
                    id=id_,
                    document=self._documents[id_],
                    metadata=metadata,
                    score=max(0.0, min(1.0, score)),
                )
            )

        matches.sort(key=lambda m: m.score, reverse=True)
        return matches[:n_results]

    def count(self) -> int:
        return len(self._vectors)

    def clear(self) -> None:
        self._vectors.clear()
        self._documents.clear()
        self._metadatas.clear()


def _matches_filter(metadata: dict[str, Any], where: RetrievalFilter) -> bool:
    """Apply a `RetrievalFilter` to one metadata dict, in Python."""
    if where.subject_ids and metadata.get("subject_id") not in where.subject_ids:
        return False
    if where.topic_ids and metadata.get("topic_id") not in where.topic_ids:
        return False
    if where.note_types and metadata.get("note_type") not in where.note_types:
        return False
    if where.note_ids and metadata.get("note_id") not in where.note_ids:
        return False

    created = metadata.get("created_epoch")
    if where.created_after is not None:
        if created is None or created < to_epoch(where.created_after):
            return False
    if where.created_before is not None:
        if created is None or created > to_epoch(where.created_before):
            return False
    return True


# ---------------------------------------------------------------------------
# ChromaDB backend
# ---------------------------------------------------------------------------


def _chroma_where(where: RetrievalFilter | None) -> dict[str, Any] | None:
    """Translate a `RetrievalFilter` into Chroma's `where` syntax.

    Chroma rejects a multi-key dict without an explicit `$and`, and rejects an
    `$and` with fewer than two clauses, so both cases are handled here rather
    than by every caller.
    """
    if where is None or where.is_empty():
        return None

    clauses: list[dict[str, Any]] = []
    if where.subject_ids:
        clauses.append({"subject_id": {"$in": list(where.subject_ids)}})
    if where.topic_ids:
        clauses.append({"topic_id": {"$in": list(where.topic_ids)}})
    if where.note_types:
        clauses.append({"note_type": {"$in": list(where.note_types)}})
    if where.note_ids:
        clauses.append({"note_id": {"$in": list(where.note_ids)}})
    if where.created_after is not None:
        clauses.append({"created_epoch": {"$gte": to_epoch(where.created_after)}})
    if where.created_before is not None:
        clauses.append({"created_epoch": {"$lte": to_epoch(where.created_before)}})

    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


class ChromaVectorStore(VectorStore):
    """Persistent ChromaDB collection, cosine space."""

    name = "chroma"

    def __init__(self, path: str, collection_name: str = COLLECTION_NAME):
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        # Chroma 0.6 raises inside its own telemetry thread on some versions.
        # It is noise on every call and unrelated to whether the query worked.
        logging.getLogger("chromadb.telemetry").setLevel(logging.CRITICAL)

        self._client = chromadb.PersistentClient(
            path=path,
            settings=ChromaSettings(anonymized_telemetry=False, allow_reset=True),
        )
        self._collection_name = collection_name
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def upsert(self, ids, embeddings, documents, metadatas) -> None:
        if not ids:
            return
        self._collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=[_scalar_only(m) for m in metadatas],
        )

    def delete(self, ids) -> None:
        if ids:
            self._collection.delete(ids=ids)

    def delete_by_note(self, note_id: str) -> None:
        self._collection.delete(where={"note_id": {"$eq": note_id}})

    def query(self, embedding, n_results=5, where=None) -> list[VectorMatch]:
        if self._collection.count() == 0:
            return []

        result = self._collection.query(
            query_embeddings=[list(embedding)],
            n_results=max(1, n_results),
            where=_chroma_where(where),
        )

        ids = (result.get("ids") or [[]])[0]
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]

        matches: list[VectorMatch] = []
        for index, id_ in enumerate(ids):
            distance = distances[index] if index < len(distances) else 1.0
            matches.append(
                VectorMatch(
                    id=id_,
                    document=documents[index] if index < len(documents) else "",
                    metadata=dict(metadatas[index] or {}) if index < len(metadatas) else {},
                    # Cosine distance -> similarity, clamped: floating point
                    # can put an identical vector a hair outside 0-1.
                    score=max(0.0, min(1.0, 1.0 - float(distance))),
                )
            )
        return matches

    def count(self) -> int:
        return int(self._collection.count())

    def clear(self) -> None:
        self._client.delete_collection(self._collection_name)
        self._collection = self._client.get_or_create_collection(
            name=self._collection_name,
            metadata={"hnsw:space": "cosine"},
        )


def _scalar_only(metadata: dict[str, Any]) -> dict[str, Any]:
    """Chroma only stores str/int/float/bool. Drop None, stringify the rest.

    A dropped key is safer than a rejected write: a missing `topic_id` means
    the note is unfiled, which the filter already treats as "no match".
    """
    clean: dict[str, Any] = {}
    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            clean[key] = value
        else:
            clean[key] = str(value)
    return clean


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def _build_store() -> VectorStore:
    settings = get_settings()
    backend = (settings.vector_store or "chroma").strip().lower()

    if backend == "memory":
        return InMemoryVectorStore()

    if backend == "pgvector":
        # The vector index lives in the same Postgres database as the notes.
        # Dimension has to match the configured embedding backend exactly - a
        # column declared VECTOR(n) rejects anything else - so it is read from
        # the provider rather than configured separately and allowed to drift.
        from app.rag.embeddings import get_embedding_provider

        if not settings.database_url.startswith("postgres"):
            logger.error(
                "VECTOR_STORE=pgvector needs DATABASE_URL to be Postgres, but it is %r; "
                "falling back to the in-memory store",
                settings.database_url.split("://")[0],
            )
            return InMemoryVectorStore()
        try:
            from app.rag.pgvector_store import PgVectorStore

            return PgVectorStore(
                settings.database_url, get_embedding_provider().dimension
            )
        except Exception:
            # Same principle as every other optional backend: a database that
            # cannot be reached degrades retrieval, it does not stop the app
            # from starting or lose a note.
            logger.exception(
                "pgvector unavailable, falling back to the in-memory vector store; "
                "the index will not survive a restart"
            )
            return InMemoryVectorStore()

    if backend == "chroma":
        try:
            settings.chroma_dir.mkdir(parents=True, exist_ok=True)
            return ChromaVectorStore(str(settings.chroma_dir))
        except Exception:
            # Same principle as the LLM abstraction: a missing or broken
            # optional backend degrades retrieval, it does not stop the app
            # from starting and it never loses a note.
            logger.exception(
                "ChromaDB unavailable, falling back to the in-memory vector store; "
                "the index will not survive a restart"
            )
            return InMemoryVectorStore()

    logger.warning("unknown VECTOR_STORE %r, using in-memory", backend)
    return InMemoryVectorStore()


@lru_cache
def get_vector_store() -> VectorStore:
    """The configured store. Cached: a Chroma client is expensive to build."""
    return _build_store()


def reset_vector_store_cache() -> None:
    """Drop the cached store. Tests use this after changing settings."""
    get_vector_store.cache_clear()
