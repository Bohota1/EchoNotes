"""SQLAlchemy models for capture (Phase 1), understanding (Phase 2) and the
Subject / Topic hierarchy (Phase 3, Idea11y Section 4.1 adapted).

Scope note (Phase 1/2 section below): originally written with no hierarchy
tables and a bare, un-constrained `Note.topic_id` left as the hand-off point
for the hierarchy work (see `docs/pipeline-handoff.md`). Phase 3 fills that
in: `Subject` and `Topic` are added below, and `Note.topic_id` becomes a real
foreign key plus three columns that record *why* a note landed where it did,
so the assignment algorithm in `app/understanding/organizer.py` is
inspectable from the data, not just from logs.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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


class TopicKind(str, Enum):
    """Idea11y's Cluster, adapted: a Topic groups related notes, a Project
    groups notes toward a goal. Same table, same behaviour, different label."""

    TOPIC = "topic"
    PROJECT = "project"


class Subject(Base):
    """Idea11y Section 4.1's Frame, adapted: the top level of the hierarchy.

    Exactly one row has `is_unfiled=True` - the analogue of Idea11y's
    "Unframed Section" - and it always exists (see
    `TopicRepository.get_or_create_unfiled` / `SubjectRepository.get_or_create_unfiled`).
    Every note always has exactly one parent Topic, and every Topic always
    has exactly one parent Subject, so a note with nowhere better to go still
    has a home to be listed and re-filed from.
    """

    __tablename__ = "subjects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    is_unfiled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    topics: Mapped[list[Topic]] = relationship(
        back_populates="subject",
        cascade="all, delete-orphan",
        order_by="Topic.name",
    )


class Topic(Base):
    """Idea11y Section 4.1's Cluster, adapted: a Topic or Project under a Subject.

    `summary` is the Idea11y "AI-generated cluster summary" (Section 4.1),
    regenerated whenever a child note is added, edited or moved -
    `summary_stale` marks it for lazy regeneration rather than blocking the
    write that triggered it on an LLM call (see `app/hierarchy/cluster_summary.py`).
    """

    __tablename__ = "topics"
    __table_args__ = (UniqueConstraint("subject_id", "name", name="uq_topic_subject_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    subject_id: Mapped[str] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20), default=TopicKind.TOPIC.value)
    summary: Mapped[str] = mapped_column(Text, default="")
    summary_stale: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )

    subject: Mapped[Subject] = relationship(back_populates="topics")
    notes: Mapped[list[Note]] = relationship(
        back_populates="topic",
        order_by="Note.created_at.desc()",
    )


class Note(Base):
    """One capture: the audio that came in and the text that came out of it,
    plus (Phase 3) where it was filed and why."""

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

    # --- Phase 3: hierarchy placement ---
    # Nullable because a note exists (with its transcript) the instant it is
    # captured, before understanding or organization have run. In steady
    # state every note is filed under the Unfiled topic at worst, never left
    # NULL - see `app/understanding/organizer.py`.
    topic_id: Mapped[str | None] = mapped_column(
        ForeignKey("topics.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # How `organize()` decided, for inspectability without reading logs:
    # "explicit" | "embedding" | "llm" | "lnt-theme" | "lnt-lda" | "heuristic" | "unfiled"
    topic_assignment_method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    topic_assignment_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    topic_assignment_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

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
    topic: Mapped[Topic | None] = relationship(back_populates="notes")

    # --- Phase 5 (Team Member 3): derived reminders and person mentions ---
    reminders: Mapped[list[Reminder]] = relationship(
        back_populates="note", cascade="all, delete-orphan"
    )
    contact_links: Mapped[list[NoteContact]] = relationship(
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


# ---------------------------------------------------------------------------
# Phase 5: reminders and contacts (Team Member 3)
#
# Both tables hang off `notes` and neither is required for a note to exist:
# reminder and contact detection runs after understanding, is wrapped in the
# same try/except as every other post-capture stage, and a failure there leaves
# the note untouched. `Reminder.note_id` and the link table use CASCADE, so
# deleting a note takes its derived reminders and mentions with it - they have
# no meaning without the note they came from.
#
# `Contact` is deliberately thin. The brief was explicitly "keep this simple;
# do not build a full contact-management application", so this stores just
# enough to recognise the same person across notes and to offer an action.
# ---------------------------------------------------------------------------


class ReminderStatus(str, Enum):
    PENDING = "pending"
    DONE = "done"
    DISMISSED = "dismissed"


class ReminderSource(str, Enum):
    DETECTED = "detected"  # found in a note by the extraction pipeline
    MANUAL = "manual"      # created through the API


class Reminder(Base):
    """A task with a time, derived from a note or created directly.

    `note_id` is nullable so a reminder can be created on its own, but in
    practice almost all of them come from a note - which is why `source` and
    `confidence` are recorded: a reminder built from a 0.6-confidence "next
    Friday" should be presented differently from one the user typed.
    """

    __tablename__ = "reminders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    note_id: Mapped[str | None] = mapped_column(
        ForeignKey("notes.id", ondelete="CASCADE"), nullable=True, index=True
    )

    title: Mapped[str] = mapped_column(Text)
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    status: Mapped[str] = mapped_column(
        String(20), default=ReminderStatus.PENDING.value, index=True
    )

    source: Mapped[str] = mapped_column(String(20), default=ReminderSource.DETECTED.value)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    #: The phrase the date came from ("next Friday"), kept so the reminder can
    #: be spoken back the way it was said and so a wrong parse is diagnosable.
    detected_phrase: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )

    note: Mapped[Note | None] = relationship(back_populates="reminders")


class Contact(Base):
    """A person mentioned in notes.

    `normalized_name` is the lowercased match key and is unique, so "Professor
    Raman" and "professor raman" are one contact rather than two. Fuzzy matching
    on top of that lives in `app/reminders/contacts.py`, because ASR spelling
    varies between captures of the same name.
    """

    __tablename__ = "contacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200))
    normalized_name: Mapped[str] = mapped_column(String(200), unique=True, index=True)

    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )

    mentions: Mapped[list[NoteContact]] = relationship(
        back_populates="contact", cascade="all, delete-orphan"
    )


class NoteContact(Base):
    """Which notes mention which people.

    A link table rather than a column, because one note mentions several people
    and one person appears across many notes - and "what did I note about
    Sarah" needs the second direction.
    """

    __tablename__ = "note_contacts"
    __table_args__ = (
        UniqueConstraint("note_id", "contact_id", name="uq_note_contact"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    note_id: Mapped[str] = mapped_column(
        ForeignKey("notes.id", ondelete="CASCADE"), index=True
    )
    contact_id: Mapped[str] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), index=True
    )
    #: The exact surface form in this note, which may differ from the canonical
    #: contact name ("Prof. Raman" vs "Professor Raman").
    mention_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    note: Mapped[Note] = relationship(back_populates="contact_links")
    contact: Mapped[Contact] = relationship(back_populates="mentions")
