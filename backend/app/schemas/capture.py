"""Capture request/response schemas (Phase 1)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.understanding import UnderstandingOut


class TriggerRequest(BaseModel):
    """Body for POST /trigger. Every field is optional - an empty body is valid
    and uses the configured capture source with auto language detection."""

    source: str | None = Field(
        default=None,
        description="Capture source override: dummy | microphone. Defaults to CAPTURE_SOURCE.",
    )
    language: str | None = Field(
        default=None,
        description="ISO-639-1 hint for the recognizer. Omit to auto-detect.",
    )
    max_seconds: int | None = Field(
        default=None, ge=1, le=3600, description="Recording length cap for live sources."
    )
    run_understanding: bool = Field(
        default=True,
        description="Run Phase 2 (entities, classification, quality). False = transcript only.",
    )


class TranscriptionOut(BaseModel):
    """What the ASR stage reported about the recording."""

    model_config = ConfigDict(protected_namespaces=())

    model: str | None = None
    language: str | None = None
    language_probability: float | None = None
    confidence: float = Field(description="0-1, derived from mean token log probability")
    no_speech_probability: float | None = None
    segment_count: int | None = None
    source_language: str | None = Field(
        default=None, description="Language actually spoken, before translation"
    )
    translated: bool = Field(
        default=False, description="True when the text was translated into English"
    )
    chunk_count: int | None = Field(
        default=None, description="Silence-split chunks the recording produced"
    )


class CaptureResponse(BaseModel):
    """Result of a capture. This is what POST /trigger returns."""

    model_config = ConfigDict(from_attributes=True)

    note_id: str
    source: str
    raw_transcript: str
    cleaned_text: str
    duration_seconds: float | None = None
    audio_path: str | None = None
    created_at: datetime
    transcription: TranscriptionOut
    understanding: UnderstandingOut | None = None


class CaptureSourceOut(BaseModel):
    """One registered capture source and whether it can run right now."""

    name: str
    available: bool
    detail: str
    is_default: bool


class NoteSummary(BaseModel):
    """Compact row for note listings."""

    model_config = ConfigDict(from_attributes=True)

    note_id: str
    cleaned_text: str
    source: str
    note_type: str | None = None
    quality_score: float | None = None
    created_at: datetime


class RecordingState(BaseModel):
    """Whether a live recording is running, and for how long."""

    recording: bool
    capture_id: str | None = None
    elapsed_seconds: float = 0.0
    max_seconds: int = 0
    hit_limit: bool = Field(
        default=False, description="True once the recording reached the length cap"
    )
    spoken: str = Field(default="", description="Sentence to announce")
