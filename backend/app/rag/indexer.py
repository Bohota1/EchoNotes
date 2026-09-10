"""Keeping the vector index in step with SQLite (Phase 4).

SQLite is authoritative. This index is a derived artefact and is always
rebuildable with `reindex_all` - so if indexing fails, a note is still captured,
still filed, and still readable; it is only temporarily unfindable by semantic
search. Every entry point here follows that rule: nothing raises into the
capture path.

**Chunking.** A short voice note is one chunk. A lecture-length capture is split
into overlapping windows, because embedding 2000 words into a single vector
averages away everything specific - the exact failure that makes "what did the
lecturer say about mutexes" return a whole lecture instead of the sentence that
answers it. Chunk ids are ``<note_id>::<index>`` so every chunk maps back to its
note, and `delete_by_note` can clear them all without knowing how many there
were.

**Metadata is the hierarchy.** Subject and topic ids/names travel with each
chunk, which is what lets the retriever apply "in Operating Systems, last week"
as a pre-filter rather than as a hint. Team Member 2's hierarchy stays the one
source of truth; this is a denormalised copy that `reindex_note_metadata`
refreshes when a note moves.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Note
from app.rag.embeddings import get_embedding_provider
from app.rag.vector_store import get_vector_store, to_epoch

logger = logging.getLogger(__name__)


def chunk_text(text: str, max_chars: int, overlap: int) -> list[str]:
    """Split text into overlapping windows on sentence boundaries.

    Falls back to hard character slicing only when a single "sentence" is longer
    than the window, which happens with transcripts that lost their punctuation.
    """
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    # Sentence-ish split. The capture pipeline appends periods per audio chunk,
    # so transcripts do carry usable boundaries.
    sentences: list[str] = []
    current = ""
    for piece in text.replace("!", ".").replace("?", ".").split("."):
        piece = piece.strip()
        if not piece:
            continue
        current = f"{current} {piece}." if current else f"{piece}."
        if len(current) >= max_chars:
            sentences.append(current.strip())
            current = ""
    if current.strip():
        sentences.append(current.strip())

    chunks: list[str] = []
    for sentence in sentences:
        if len(sentence) <= max_chars:
            chunks.append(sentence)
            continue
        for start in range(0, len(sentence), max_chars - overlap):
            window = sentence[start : start + max_chars].strip()
            if window:
                chunks.append(window)

    # Overlap consecutive chunks so a fact spanning a boundary is still findable
    # from either side.
    if overlap > 0 and len(chunks) > 1:
        overlapped = [chunks[0]]
        for index in range(1, len(chunks)):
            tail = chunks[index - 1][-overlap:]
            overlapped.append(f"{tail} {chunks[index]}".strip())
        chunks = overlapped

    return [c for c in chunks if c]


def ensure_fresh_topic(db: Session, note: Note) -> None:
    """Reload `note` if its `topic` relationship disagrees with `topic_id`.

    `SessionLocal` is built with `expire_on_commit=False`, so objects keep their
    loaded state after a commit and SQLAlchemy will not overwrite an
    already-loaded relationship when the row is selected again. Moving a note
    sets the `topic_id` *column*; within the same session the `topic`
    *relationship* still points at the old Topic until something forces a
    reload.

    That matters here more than anywhere else: `build_metadata` reads
    `note.topic` to denormalise the hierarchy into the index, so without this
    the reindex triggered by a move would faithfully record where the note used
    to be - and then filter searches on it.

    Comparing the FK to the loaded object is cheap and only issues a query in
    the case that is actually stale.
    """
    if note.topic_id and (note.topic is None or note.topic.id != note.topic_id):
        db.refresh(note)


def build_metadata(note: Note) -> dict[str, Any]:
    """Denormalise the note's hierarchy placement and classification.

    Reads through the ORM relationships Team Member 2 defined, so there is no
    second query path into the hierarchy and no chance of this drifting from
    what `GET /hierarchy` reports.
    """
    topic = note.topic
    subject = topic.subject if topic is not None else None
    understanding = note.understanding

    metadata: dict[str, Any] = {
        "note_id": note.id,
        "source": note.source,
        "created_epoch": to_epoch(note.created_at),
        "created_at": note.created_at.isoformat() if note.created_at else None,
        "embedding_backend": get_embedding_provider().name,
    }
    if topic is not None:
        metadata["topic_id"] = topic.id
        metadata["topic_name"] = topic.name
    if subject is not None:
        metadata["subject_id"] = subject.id
        metadata["subject_name"] = subject.name
    if understanding is not None:
        metadata["note_type"] = understanding.note_type
        metadata["quality_score"] = float(understanding.quality_score or 0.0)
    return metadata


def index_note(db: Session, note: Note) -> int:
    """Embed and store one note's chunks. Returns the number of chunks written.

    Replaces any chunks the note previously had, so re-indexing after an edit
    never leaves stale text behind that would still be retrievable.
    """
    settings = get_settings()
    store = get_vector_store()

    ensure_fresh_topic(db, note)

    text = (note.cleaned_text or note.raw_transcript or "").strip()
    store.delete_by_note(note.id)
    if not text:
        # An empty capture is a normal user mistake (Team Member 1 stores it
        # rather than rejecting it). There is nothing to retrieve, so it is
        # simply absent from the index.
        return 0

    chunks = chunk_text(text, settings.rag_chunk_chars, settings.rag_chunk_overlap)
    if not chunks:
        return 0

    embeddings = get_embedding_provider().embed_many(chunks)
    base_metadata = build_metadata(note)

    ids = [f"{note.id}::{index}" for index in range(len(chunks))]
    metadatas = []
    for index in range(len(chunks)):
        metadata = dict(base_metadata)
        metadata["chunk_index"] = index
        metadata["chunk_count"] = len(chunks)
        metadatas.append(metadata)

    store.upsert(ids=ids, embeddings=embeddings, documents=chunks, metadatas=metadatas)
    logger.info("indexed note=%s chunks=%d", note.id, len(chunks))
    return len(chunks)


def index_note_safe(db: Session, note: Note) -> int:
    """`index_note` that never raises.

    This is what the capture pipeline calls. Indexing is derived state; losing
    it costs searchability until the next reindex, and that is never worth
    failing a capture the user already spoke.
    """
    try:
        return index_note(db, note)
    except Exception:
        logger.exception("indexing failed for note %s; note kept, search stale", note.id)
        return 0


def reindex_note_metadata(db: Session, note: Note) -> int:
    """Refresh a note's chunks after it moved topic.

    Currently a full re-index. The text is unchanged so only metadata needs
    rewriting, but neither backend exposes a metadata-only update, and
    re-embedding a single note is cheap on both backends.
    """
    return index_note_safe(db, note)


def remove_note(note_id: str) -> None:
    """Drop every chunk for a deleted note."""
    try:
        get_vector_store().delete_by_note(note_id)
    except Exception:
        logger.exception("failed to remove note %s from the index", note_id)


def reindex_all(db: Session) -> dict[str, int]:
    """Rebuild the whole index from SQLite.

    Needed after switching `EMBEDDING_BACKEND` - vectors from two different
    models are not comparable, and a half-migrated index silently returns
    nonsense rather than failing loudly.
    """
    from app.db.repositories import NoteRepository

    store = get_vector_store()
    store.clear()

    repo = NoteRepository(db)
    total_notes = 0
    total_chunks = 0
    offset = 0
    batch_size = 200

    while True:
        notes = repo.list(limit=batch_size, offset=offset)
        if not notes:
            break
        for note in notes:
            chunks = index_note_safe(db, note)
            total_notes += 1
            total_chunks += chunks
        offset += batch_size

    logger.info("reindexed %d notes into %d chunks", total_notes, total_chunks)
    return {
        "notes": total_notes,
        "chunks": total_chunks,
        "backend": get_vector_store().name,
    }


def index_stats() -> dict[str, Any]:
    """What the index currently holds, for `/retrieval/status` and diagnostics."""
    provider = get_embedding_provider()
    store = get_vector_store()
    return {
        "vector_store": store.name,
        "embedding_backend": provider.name,
        "chunk_count": store.count(),
    }
