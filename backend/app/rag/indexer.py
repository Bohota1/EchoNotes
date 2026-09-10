"""Keeping the vector index in step with SQLite."""

from __future__ import annotations


def index_note(note_id: str) -> None:
    """Embed and upsert one note."""
    raise NotImplementedError


def reindex_note_metadata(note_id: str) -> None:
    """Update metadata only. A move changes the hierarchy, not the text, so no re-embedding."""
    raise NotImplementedError


def remove_note(note_id: str) -> None:
    raise NotImplementedError


def reindex_all() -> int:
    """Rebuild the whole index from SQLite. Returns the number of notes indexed."""
    raise NotImplementedError
