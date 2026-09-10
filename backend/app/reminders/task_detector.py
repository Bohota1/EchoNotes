"""Task detection - EchoNotes Feature 5.

Decides whether a note contains a commitment that deserves a reminder, and what the reminder
should be called. Runs on notes the classifier marked `todo`, and on any note where the extractor
found a deadline.

The reminder title is spoken back for confirmation before it is created. A reminder the user did
not intend is worse than a missed one, because they cannot see the list to notice it.
"""

from __future__ import annotations

from typing import Any


def detect_tasks(text: str, entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return [{"title", "due_at", "confidence", "span"}, ...]."""
    raise NotImplementedError


def title_for_task(text: str, span: tuple[int, int]) -> str:
    """A short imperative title: "Submit the assignment", not the whole sentence."""
    raise NotImplementedError
