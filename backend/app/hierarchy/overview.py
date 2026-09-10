"""Library Overview - Idea11y Section 4.1, the board-overview analogue.

Idea11y opened with "0 Frames, 3 Clusters, 3 Color" plus the active
collaborators. It comes first because a screen reader user cannot glance at a
board to gauge its size; they need the shape of the thing before they start
walking it.

EchoNotes is single-user, so the collaborator half is dropped and the counts
describe the note library instead.
"""

from __future__ import annotations

from typing import Any

from app.hierarchy.tree import Hierarchy


def _plural(n: int, word: str) -> str:
    return word if n == 1 else f"{word}s"


def build_overview(hierarchy: Hierarchy) -> dict[str, Any]:
    """Counts of subjects, topics and notes, plus the note-type breakdown."""
    counts = hierarchy.counts()
    overview = {
        "subject_count": counts["subject_count"],
        "topic_count": counts["topic_count"],
        "note_count": counts["note_count"],
        "notes_by_type": counts["notes_by_type"],
    }
    overview["spoken"] = spoken_overview(overview)
    return overview


def spoken_overview(overview: dict[str, Any]) -> str:
    """One or two sentences: "You have 4 subjects, 11 topics, 63 notes. 40
    academic, 15 to-do, 8 brainstorm."."""
    subject_count = overview["subject_count"]
    topic_count = overview["topic_count"]
    note_count = overview["note_count"]

    parts = [
        f"You have {subject_count} {_plural(subject_count, 'subject')}, "
        f"{topic_count} {_plural(topic_count, 'topic')}, "
        f"{note_count} {_plural(note_count, 'note')}."
    ]

    by_type: dict[str, int] = overview.get("notes_by_type") or {}
    if by_type:
        ordered = sorted(by_type.items(), key=lambda kv: (-kv[1], kv[0]))
        type_phrase = ", ".join(
            f"{count} {_type_label(kind, count)}" for kind, count in ordered
        )
        parts.append(f"{type_phrase}.")

    return " ".join(parts)


def _type_label(kind: str, count: int) -> str:
    labels = {
        "academic": "academic",
        "brainstorm": "brainstorm",
        "todo": "to-do",
    }
    label = labels.get(kind, kind)
    # "1 to-do" not "1 to-dos"; the type words above are already the singular
    # form used as an adjective, so no pluralisation is needed here.
    return label
