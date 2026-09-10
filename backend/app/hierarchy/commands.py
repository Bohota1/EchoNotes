"""Voice-based organization commands - Phase 3 spec:

    "Move this note to Machine Learning."
    "Move this note to my Project Ideas topic."
    "What topics are under Machine Learning?"
    "What notes are under Graph Theory?"

These are follow-up utterances about a note that already exists. Team Member
3's voice-query system captures and transcribes the utterance and hands the
resulting text - plus the currently-focused note id, when the command needs
one - to `handle_command` below. This module never builds its own
representation of the hierarchy; every branch reads or writes through
`app.hierarchy.service` / `app.db.repositories`, the same canonical tables
the outline and the automatic per-note filing (`app.understanding.organizer`)
use. That is what "one source of truth, never a second hierarchy
representation that can drift" (Phase 3 spec) means for this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_MOVE_RE = re.compile(
    r"^\s*move\s+(?:this\s+note|the\s+note|this|it)\s+to\s+(?:my\s+)?(?P<name>.+?)"
    r"(?:\s+(?:topic|project))?\s*[.!]?\s*$",
    re.IGNORECASE,
)
_TOPICS_UNDER_RE = re.compile(
    r"^\s*what\s+topics\s+(?:are\s+)?under\s+(?P<name>.+?)\s*\??\s*$", re.IGNORECASE
)
_NOTES_UNDER_RE = re.compile(
    r"^\s*what\s+notes\s+(?:are\s+)?under\s+(?P<name>.+?)\s*\??\s*$", re.IGNORECASE
)


@dataclass
class CommandResult:
    intent: str  # "move" | "topics_under" | "notes_under" | "unrecognized"
    ok: bool
    spoken: str
    data: dict[str, Any] | None = None


def handle_command(db, text: str, *, focused_note_id: str | None = None) -> CommandResult:
    """Parse and execute one organization command. Never raises: an
    unrecognized or failed command comes back as `ok=False` with a spoken
    explanation, since this is meant to be read aloud, not shown as an error
    page."""
    stripped = (text or "").strip()

    match = _MOVE_RE.match(stripped)
    if match:
        return _handle_move(db, match.group("name").strip(), focused_note_id)

    match = _TOPICS_UNDER_RE.match(stripped)
    if match:
        return _handle_topics_under(db, match.group("name").strip())

    match = _NOTES_UNDER_RE.match(stripped)
    if match:
        return _handle_notes_under(db, match.group("name").strip())

    return CommandResult(
        intent="unrecognized",
        ok=False,
        spoken="I didn't recognize that as an organization command.",
    )


def _handle_move(db, target_name: str, focused_note_id: str | None) -> CommandResult:
    if not focused_note_id:
        return CommandResult(
            intent="move",
            ok=False,
            spoken="I need to know which note you mean before I can move it.",
        )

    from app.hierarchy.service import move_note_by_name

    try:
        _note, topic, subject, created = move_note_by_name(db, focused_note_id, target_name)
    except LookupError as exc:
        return CommandResult(intent="move", ok=False, spoken=str(exc))

    if created:
        spoken = f"Created a new topic, {topic.name}, and moved the note there."
    elif subject.name != topic.name:
        spoken = f"Moved to {topic.name}, under {subject.name}."
    else:
        spoken = f"Moved to {topic.name}."

    return CommandResult(
        intent="move",
        ok=True,
        spoken=spoken,
        data={
            "note_id": focused_note_id,
            "topic_id": topic.id,
            "topic_name": topic.name,
            "subject_id": subject.id,
            "subject_name": subject.name,
            "created_new_topic": created,
        },
    )


def _handle_topics_under(db, subject_name: str) -> CommandResult:
    from app.db.repositories import SubjectRepository, TopicRepository

    subject = SubjectRepository(db).find_best_name_match(subject_name)
    if subject is None:
        return CommandResult(
            intent="topics_under",
            ok=False,
            spoken=f"I don't have a subject called {subject_name}.",
        )

    topics = TopicRepository(db).list_for_subject(subject.id)
    names = [t.name for t in topics]
    if not names:
        spoken = f"There are no topics yet under {subject.name}."
    elif len(names) == 1:
        spoken = f"Under {subject.name}, there is 1 topic: {names[0]}."
    else:
        spoken = f"Under {subject.name}, there are {len(names)} topics: {', '.join(names)}."

    return CommandResult(
        intent="topics_under",
        ok=True,
        spoken=spoken,
        data={"subject_id": subject.id, "subject_name": subject.name, "topics": names},
    )


def _handle_notes_under(db, topic_name: str) -> CommandResult:
    from app.db.repositories import NoteRepository, TopicRepository

    topic = TopicRepository(db).find_best_name_match(topic_name)
    if topic is None:
        return CommandResult(
            intent="notes_under",
            ok=False,
            spoken=f"I don't have a topic called {topic_name}.",
        )

    notes = NoteRepository(db).list_by_topic(topic.id, limit=50)
    if not notes:
        spoken = f"There are no notes yet under {topic.name}."
    else:
        spoken = f"Under {topic.name}, there are {len(notes)} note{'s' if len(notes) != 1 else ''}."

    return CommandResult(
        intent="notes_under",
        ok=True,
        spoken=spoken,
        data={
            "topic_id": topic.id,
            "topic_name": topic.name,
            "notes": [{"id": n.id, "text": n.cleaned_text} for n in notes],
        },
    )
