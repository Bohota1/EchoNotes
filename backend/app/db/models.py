"""SQLAlchemy models for capture (Phase 1) and understanding (Phase 2).

Scope note: this file deliberately contains no Subject/Topic hierarchy. That
is owned by another team member. `Note.topic_id` is left here as a nullable,
un-constrained column so the hierarchy work can start filling it (and add the
real FK) without having to alter an existing table.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import Enum

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class NoteType(str, Enum):
    ACADEMIC = "academic"
    BRAINSTORM = "brainstorm"
    TODO = "todo"


class EntityKind(str, Enum):
    PERSON = "person"
    DATE = "date"
    DEADLINE = "deadline"
    TASK = "task"
    KEY_PHRASE = "key_phrase"


class CaptureSource(str, Enum):
    DUMMY = "dummy"
    MICROPHONE = "microphone"
    UPLOAD = "upload"
    TEXT = "text"


class Note(Base):
    """One capture: the audio that came in and the text that came out of it."""

    __tablename__ = "notes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)

    # --- Phase 1: transcripts ---
    raw_transcript: Mapped[str] = mapped_column(Text, default="")
    cleaned_text: Mapped[str] = mapped_column(Text, default="")

    # --- Capture provenance ---
    source: Mapped[str] = mapped_column(String(20), default=CaptureSource.DUMMY.value)
    audio_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- ASR detail, feeds the Phase 2 transcription-confidence metric ---
    asr_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    language_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    asr_avg_logprob: Mapped[float | None] = mapped_column(Float, nullable=True)
    asr_no_speech_prob: Mapped[float | None] = mapped_column(Float, nullable=True)
    asr_segment_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- Owned by the hierarchy work, not written by this pipeline ---
    topic_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )

    understanding: Mapped[Understanding | None] = relationship(
        back_populates="note", cascade="all, delete-orphan", uselist=False
    )
    entities: Mapped[list[Entity]] = relationship(
        back_populates="note", cascade="all, delete-orphan"
    )


class Understanding(Base):
    """Phase 2 result for a note: classification plus quality scoring."""

    __tablename__ = "note_understanding"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    note_id: Mapped[str] = mapped_column(
        ForeignKey("notes.id", ondelete="CASCADE"), unique=True, index=True
    )

    # --- Classification ---
    note_type: Mapped[str] = mapped_column(String(20))
    note_type_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    classification_method: Mapped[str] = mapped_column(String(20), default="rules")
    classification_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Quality scoring ---
    readability: Mapped[float] = mapped_column(Float, default=0.0)
    coherence: Mapped[float] = mapped_column(Float, default=0.0)
    transcription_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    quality_score: Mapped[float] = mapped_column(Float, default=0.0)

    word_count: Mapped[int] = mapped_column(Integer, default=0)
    sentence_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    note: Mapped[Note] = relationship(back_populates="understanding")


class Entity(Base):
    """One extracted item: a person, date, deadline, task or key phrase.

    `span_start` / `span_end` index into `Note.cleaned_text`, so a caller can
    highlight or re-read the exact phrase the value came from.
    """

    __tablename__ = "note_entities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    note_id: Mapped[str] = mapped_column(
        ForeignKey("notes.id", ondelete="CASCADE"), index=True
    )

    kind: Mapped[str] = mapped_column(String(20), index=True)
    value: Mapped[str] = mapped_column(Text)
    normalized: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    extractor: Mapped[str] = mapped_column(String(20), default="rules")

    span_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    span_end: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    note: Mapped[Note] = relationship(back_populates="entities")
