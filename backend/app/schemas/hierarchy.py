"""Outline and hierarchy schemas - Idea11y Section 4.1.

`level` is carried explicitly so the client renders real h1/h2 elements. Heading level is not a
styling detail here; it is how the user navigates.
"""

from __future__ import annotations

from pydantic import BaseModel

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
    overview: OverviewOut
    subjects: list[SubjectOut]


class TopicCreate(BaseModel):
    subject_id: str
    name: str
    kind: str = "topic"
