"""Turning OCR output into structured text - EchoNotes Feature 7.

Raw OCR is a flat blob with the page's visual layout baked in as whitespace. This module recovers
the structure - headings, list items, paragraphs - so the note reads sensibly aloud and can be
filed like any other note. It is the OCR counterpart of what silence chunking does for audio.
"""

from __future__ import annotations

from typing import Any


def detect_structure(raw_text: str) -> list[dict[str, Any]]:
    """Label each line as heading, bullet, numbered item or paragraph."""
    raise NotImplementedError


def to_note_text(blocks: list[dict[str, Any]]) -> str:
    """Join structured blocks into readable note text with real line and list breaks."""
    raise NotImplementedError
