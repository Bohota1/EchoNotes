"""Retrieval schemas - EchoNotes Feature 4."""

from __future__ import annotations

from pydantic import BaseModel

from app.schemas.note import NoteOut


class VoiceQuery(BaseModel):
    """Either an already-transcribed utterance, or audio uploaded to be transcribed first."""

    utterance: str
    subject_id: str | None = None
    top_k: int = 5


class RetrievedNote(BaseModel):
    note: NoteOut
    subject_name: str
    topic_name: str
    score: float


class QueryResult(BaseModel):
    intent: str
    spoken: str  # the complete response to speak
    answer: str | None = None
    results: list[RetrievedNote] = []
    sources: list[str] = []
    navigate_to: str | None = None  # element id for the client to focus
