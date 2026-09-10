"""Outline, hierarchy and voice-command schemas - Idea11y Section 4.1, Phase 3.

`level` is carried explicitly on `TopicOut` / `SubjectOut` so the client
renders real h1/h2 elements. Heading level is not a styling detail here; it
is how the user navigates (`docs/accessibility.md`, non-negotiable #2).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.note import NoteOut


class OverviewOut(BaseModel):
    """Library Overview - the board-overview analogue."""

    subject_count: int
    topic_count: int
    note_count: int
    notes_by_type: dict[str, int]
    spoken: str


class TopicOut(BaseModel):
    id: str
    name: str
    kind: str
    level: int = 2
    summary: str
    summary_stale: bool
    notes: list[NoteOut]


class SubjectOut(BaseModel):
    id: str
    name: str
    is_unfiled: bool
    level: int = 1
    topics: list[TopicOut]


class OutlineOut(BaseModel):
    """`GET /hierarchy` and `GET /hierarchy/outline` - nested JSON plus a full
    spoken narration of the same structure, per the Phase 3 spec's example:

        "You have 3 subjects. Under Discrete Structure, there are 4 topics.
        Under Graph Theory, there are 6 notes. The topic summary is: ..."
    """

    overview: OverviewOut
    subjects: list[SubjectOut]
    narration: str = Field(
        description="Full voice/screen-reader script for the whole hierarchy."
    )


class SubjectCreate(BaseModel):
    name: str = Field(min_length=1)


class TopicCreate(BaseModel):
    subject_id: str
    name: str = Field(min_length=1)
    kind: str = "topic"


class NoteMoveByName(BaseModel):
    """Re-file a note by a spoken/typed topic or subject name rather than an
    id - fuzzy-matched, creating a new topic if nothing close enough exists.
    Same resolution `app.hierarchy.commands` uses for the "move this note to
    X" voice command."""

    target_name: str = Field(min_length=1)


class TopicAssignmentOut(BaseModel):
    """What `app.understanding.organizer.organize()` decided for one note -
    the topic-assignment algorithm's own output, exposed for inspection
    (Phase 3: "the assignment logic should be inspectable")."""

    note_id: str
    subject_id: str
    subject_name: str
    topic_id: str
    topic_name: str
    created_new_subject: bool
    created_new_topic: bool
    confidence: float
    method: str
    reason: str


class CommandRequest(BaseModel):
    """Body for `POST /hierarchy/command` - one spoken organization command,
    already transcribed to text by Team Member 3's voice pipeline."""

    text: str = Field(min_length=1)
    focused_note_id: str | None = Field(
        default=None,
        description="The note currently in focus, needed for a bare 'move this note to X'.",
    )


class CommandResponse(BaseModel):
    intent: str
    ok: bool
    spoken: str
    data: dict[str, Any] | None = None
