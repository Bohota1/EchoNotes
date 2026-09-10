"""Note request and response schemas. Mirrored by `frontend/src/types/index.ts`."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class NoteType(str, Enum):
    ACADEMIC = "academic"
    BRAINSTORM = "brainstorm"
    TODO = "todo"


class NoteSource(str, Enum):
    VOICE = "voice"
    OCR = "ocr"
    MANUAL = "manual"


class NoteCreate(BaseModel):
    text: str
    topic_id: str | None = None
    note_type: NoteType | None = None
    source: NoteSource = NoteSource.MANUAL


class NoteUpdate(BaseModel):
    text: str | None = None
    note_type: NoteType | None = None


class NoteMove(BaseModel):
    """Idea11y Section 4.2: re-file a note through the drop-down of current topics."""

    target_topic_id: str


class NoteOut(BaseModel):
    id: str
    topic_id: str
    text: str
    note_type: NoteType
    source: NoteSource
    created_at: datetime
    updated_at: datetime
    quality_score: float | None = None


class NoteInfo(BaseModel):
    """Answer to the note-info shortcut, Ctrl+Alt+I (Idea11y Section 4.3)."""

    note_id: str
    spoken: str = Field(description="The full sentence to announce")
    note_type: NoteType
    subject: str
    topic: str
    source: NoteSource
    source_language: str | None
    created_at: datetime
    quality_score: float | None
