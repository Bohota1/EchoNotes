"""Retrieval - EchoNotes Feature 4.

Hybrid: a metadata filter built from the intent slots narrows the candidate set, then vector
similarity ranks within it. Filtering first is what makes "in Operating Systems last week"
actually constrain the answer instead of merely nudging the ranking.
"""

from __future__ import annotations

from typing import Any


def build_filter(slots: dict[str, Any]) -> dict[str, Any] | None:
    """Turn intent slots into a Chroma `where` clause."""
    raise NotImplementedError


def retrieve(query: str, slots: dict[str, Any], top_k: int = 5) -> list[dict[str, Any]]:
    """Return ranked notes with their hierarchy path, so the answer can cite where each came from."""
    raise NotImplementedError
