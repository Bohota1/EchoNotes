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
    #: A clock time ("3:30 am"), additive for the event-mention reminder
    #: pathway in app/reminders/clarify.py - see app/understanding/entities.py.
    TIME = "time"


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
    """A node in the course knowledge graph (NexaNota Sections 4.1/4.3.2,
    replacing the Idea11y-based "AI-generated cluster summary" design this
    table used to carry).

    A Topic no longer holds its own rolling summary: NexaNota generates
    content per *note* (`NoteContent`, three areas), not per topic. What a
    Topic now carries is its place in the graph - which notes touch it
    (`NoteTopic`) and which other topics it connects to (`TopicConnection`).
    """

    __tablename__ = "topics"
    __table_args__ = (UniqueConstraint("subject_id", "name", name="uq_topic_subject_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    subject_id: Mapped[str] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20), default=TopicKind.TOPIC.value)
    #: True for a topic the LLM suggested as cross-disciplinary "further
    #: reading" (NexaNota 4.3.2) rather than one extracted from a note's own
    #: text - lets the graph view show these differently.
    is_recommended: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )

    subject: Mapped[Subject] = relationship(back_populates="topics")
    #: The note this topic was first extracted from is `Note.topic_id`
    #: (kept as the "primary" placement so every existing single-topic
    #: consumer - RAG metadata, reminders - keeps working unchanged); the
    #: full 2-3 topics a note maps to live in `NoteTopic` below.
    notes: Mapped[list[Note]] = relationship(
        back_populates="topic",
        order_by="Note.created_at.desc()",
    )
    note_links: Mapped[list[NoteTopic]] = relationship(
        back_populates="topic", cascade="all, delete-orphan"
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
    #: JSON list of {"start", "end", "text"} - the per-segment transcript
    #: `app.asr.transcriber.TranscriptSegment` already produces, persisted so
    #: `app.graph.replay` can rebuild the timestamped view (NexaNota 4.3.1).
    #: "[]" when the note was not captured from timed audio (e.g. typed text).
    asr_segments_json: Mapped[str] = mapped_column(Text, default="[]")

    # --- LNT multilanguage evidence (paper Sections 3.2-3.3) ---
    #: What the speaker actually spoke, before any translation. `language`
    #: above is the language of the stored text, which is English whenever a
    #: translation happened - keeping both is what makes the multilanguage
    #: path auditable rather than invisible.
    source_language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    translated: Mapped[bool] = mapped_column(Boolean, default=False)
    #: Number of silence-split chunks the recording produced.
    chunk_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

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

    # --- Knowledge graph (NexaNota redesign): the 2-3 topics this note maps
    # to, and its generated 3-area content. `topic_id` above stays the first
    # (primary) of these, kept for every consumer that only needs one.
    topic_links: Mapped[list[NoteTopic]] = relationship(
        back_populates="note", cascade="all, delete-orphan"
    )
    content: Mapped[NoteContent | None] = relationship(
        back_populates="note", cascade="all, delete-orphan", uselist=False
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
    # Table 2 defines four metrics; cohesion and entropy were missing while the
    # quality score used a different formula.
    cohesion: Mapped[float] = mapped_column(Float, default=0.0)
    coherence: Mapped[float] = mapped_column(Float, default=0.0)
    entropy: Mapped[float] = mapped_column(Float, default=0.0)
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


class PendingReminder(Base):
    """An event-style reminder ("I have a meeting...") caught mid-sentence,
    waiting on the date or time the speaker left out.

    Purely additive alongside `Reminder`/`detect_reminders` above: those
    detect a *task* paired with a date, which "I have a meeting" is not - it
    has no task verb and no deadline cue, so the existing pathway never sees
    it. `app/reminders/clarify.py` is the separate, minimal pathway that
    detects an event mention directly and, when it is missing its date or its
    time, asks the one question needed and remembers the answer here until it
    can save a real `Reminder`.

    There is at most one live row at a time: this is a single voice console
    for one user, not a multi-session server, so the newest un-finalized row
    is always what the very next captured note answers.
    """

    __tablename__ = "pending_reminders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(Text)
    #: ISO date ("2026-09-13") once known, else None.
    date_iso: Mapped[str | None] = mapped_column(String(10), nullable=True)
    #: ISO time ("03:30:00") once known, else None.
    time_iso: Mapped[str | None] = mapped_column(String(8), nullable=True)
    #: "need_time" | "need_date" - which half is still missing.
    stage: Mapped[str] = mapped_column(String(20))
    #: The note whose event mention (or latest answer) started/advanced this.
    note_id: Mapped[str | None] = mapped_column(
        ForeignKey("notes.id", ondelete="SET NULL"), nullable=True
    )
    #: Naive **local** time on purpose, not `_utcnow()` - `clarify.py`'s
    #: staleness check compares this against `datetime.now()` (also local),
    #: same as `Reminder.due_at` elsewhere. Mixing UTC here against a local
    #: comparison would make every fresh row look hours old on any machine
    #: whose local clock isn't UTC, so it would get deleted as "stale" and
    #: dropped almost immediately - the very next answer would then find no
    #: pending row and get saved as an ordinary note instead of continuing
    #: the question.
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class ReminderAlert(Base):
    """Marks a reminder as already spoken by the one-hour-before voice alert
    (`ReminderService.due_soon`).

    A new table rather than a column on `Reminder`, because `init_db()`
    (`app/db/session.py`) only creates missing tables - it never alters an
    existing table's columns - so a new column here would crash on every
    user's existing database. A new table is always safe to add.
    """

    __tablename__ = "reminder_alerts"

    reminder_id: Mapped[str] = mapped_column(
        ForeignKey("reminders.id", ondelete="CASCADE"), primary_key=True
    )
    alerted_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


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


class NoteTopic(Base):
    """One of the 2-3 topics a note maps to (NexaNota 4.1: "2 to 3 topics
    could be subtracted from the transcribed text" per capture).

    A link table rather than widening `Note.topic_id` to a list, because a
    note's relationship to each of its topics needs its own rank (which one
    the extractor named first/most central) and confidence.
    """

    __tablename__ = "note_topics"
    __table_args__ = (UniqueConstraint("note_id", "topic_id", name="uq_note_topic"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    note_id: Mapped[str] = mapped_column(
        ForeignKey("notes.id", ondelete="CASCADE"), index=True
    )
    topic_id: Mapped[str] = mapped_column(
        ForeignKey("topics.id", ondelete="CASCADE"), index=True
    )
    #: 0 = the topic also recorded as `Note.topic_id` (the primary one).
    rank: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    note: Mapped[Note] = relationship(back_populates="topic_links")
    topic: Mapped[Topic] = relationship(back_populates="note_links")


class TopicConnection(Base):
    """One edge of the course knowledge graph (NexaNota 4.3.2/D3): a
    connection the LLM identified between two topics.

    Scoped to a Subject (the paper's per-course graph), undirected in
    meaning - `topic_a_id`/`topic_b_id` order is not significant, but is
    kept as an ordered pair with a matching unique constraint so the same
    connection is never stored twice in either direction.
    """

    __tablename__ = "topic_connections"
    __table_args__ = (
        UniqueConstraint("topic_a_id", "topic_b_id", name="uq_topic_connection_pair"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    subject_id: Mapped[str] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), index=True
    )
    topic_a_id: Mapped[str] = mapped_column(
        ForeignKey("topics.id", ondelete="CASCADE"), index=True
    )
    topic_b_id: Mapped[str] = mapped_column(
        ForeignKey("topics.id", ondelete="CASCADE"), index=True
    )
    #: What the LLM says connects them, e.g. "both covered under Deadlock
    #: avoidance". Empty when found by the non-LLM fallback (co-occurrence
    #: in one note), which has no rationale to give.
    label: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    method: Mapped[str] = mapped_column(String(20), default="llm")  # "llm" | "co-occurrence"

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    topic_a: Mapped[Topic] = relationship(foreign_keys=[topic_a_id])
    topic_b: Mapped[Topic] = relationship(foreign_keys=[topic_b_id])


class WebResource(Base):
    """An external resource suggested for a topic (NexaNota 4.3.2: "searched
    for ... online resources", System overview: "academic paper or
    professional blogs").

    `url` is nullable: the LLM has no real web access through this project's
    Anthropic integration, so a resource the model could not verify is
    stored as a search suggestion (title + `search_query`, `url=None`)
    rather than risk showing a fabricated link as if it were real. See the
    redesign plan, section 6.
    """

    __tablename__ = "web_resources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    topic_id: Mapped[str] = mapped_column(
        ForeignKey("topics.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    search_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    resource_type: Mapped[str] = mapped_column(String(20), default="paper")  # "paper" | "blog"
    verified: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    topic: Mapped[Topic] = relationship()


class NoteContent(Base):
    """A note's generated three-area content (NexaNota 4.3.3, D2):
    Note-Taking Area, Link Area and Edit Area.

    `edit_markdown` starts as a copy of the generated Note-Taking Area text
    and then diverges the moment a student edits it - regeneration must
    never overwrite it silently (see `app/graph/note_generator.py`).
    """

    __tablename__ = "note_content"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    note_id: Mapped[str] = mapped_column(
        ForeignKey("notes.id", ondelete="CASCADE"), unique=True, index=True
    )

    # --- Note-Taking Area (the needfinding's 3 required subsections) ---
    definition: Mapped[str] = mapped_column(Text, default="")
    example_analysis: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")

    # --- Link Area: related-topic-note links; web-resource URLs live on
    # WebResource, reached through this note's topics. ---
    related_note_ids: Mapped[str] = mapped_column(Text, default="[]")  # JSON list[str]

    # --- Edit Area ---
    edit_markdown: Mapped[str] = mapped_column(Text, default="")
    edited_by_user: Mapped[bool] = mapped_column(Boolean, default=False)

    method: Mapped[str] = mapped_column(String(20), default="llm")  # "llm" | "extractive"
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )

    note: Mapped[Note] = relationship(back_populates="content")
