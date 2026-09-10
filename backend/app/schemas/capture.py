"""Capture schemas - EchoNotes Feature 1."""

from __future__ import annotations

from pydantic import BaseModel

from app.schemas.note import NoteOut


class CaptureStatus(BaseModel):
    """Progress for a running capture, polled or streamed while a long lecture is processed."""

    capture_id: str
    stage: str  # transcribe | understand | organize | store | respond
    progress: float
    spoken: str  # what to announce right now, e.g. "Transcribing, chunk 4 of 12"


class CaptureResult(BaseModel):
    capture_id: str
    note: NoteOut
    subject_name: str
    topic_name: str
    cluster_summary: str
    detected_language: str | None
    announcement: str
    earcon: str | None
    stage_timings: dict[str, float]
