"""Library Overview - Idea11y Section 4.1, the board-overview analogue.

Idea11y opened with "0 Frames, 3 Clusters, 3 Color" plus the active collaborators. It comes first
because a screen reader user cannot glance at a board to gauge its size; they need the shape of
the thing before they start walking it.

EchoNotes is single-user, so the collaborator half is dropped and the counts describe the note
library instead.
"""

from __future__ import annotations

from typing import Any

from app.hierarchy.tree import Hierarchy


def build_overview(hierarchy: Hierarchy) -> dict[str, Any]:
    """Counts of subjects, topics and notes, plus the note-type breakdown and recent activity."""
    raise NotImplementedError


def spoken_overview(overview: dict[str, Any]) -> str:
    """One sentence: "4 subjects, 11 topics, 63 notes. 40 academic, 15 to-do, 8 brainstorm."."""
    raise NotImplementedError
