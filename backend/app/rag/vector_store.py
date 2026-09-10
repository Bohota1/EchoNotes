"""ChromaDB vector store - EchoNotes Feature 4.

One collection, `notes`, one document per note. Metadata carries the hierarchy so a voice query
like "what did I note about deadlock in Operating Systems last week" becomes a *filtered* vector
search rather than a pure similarity search.

SQLite stays authoritative. This index is always rebuildable from it (`indexer.reindex_all`).
"""

from __future__ import annotations

from typing import Any

COLLECTION = "notes"


def get_collection():
    """Open (or create) the persistent Chroma collection at CHROMA_DIR."""
    raise NotImplementedError


def upsert(note_id: str, text: str, metadata: dict[str, Any]) -> None:
    raise NotImplementedError


def delete(note_id: str) -> None:
    raise NotImplementedError


def query(
    text: str,
    n_results: int = 5,
    where: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Similarity search with optional metadata filter on subject, topic, type or date."""
    raise NotImplementedError
