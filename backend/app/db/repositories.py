"""Data access. Every query lives here so services stay free of SQLAlchemy.

Covers the capture + understanding tables (`NoteRepository`,
`UnderstandingRepository`, `EntityRepository`) and, as of Phase 3, the
Subject / Topic hierarchy (`SubjectRepository`, `TopicRepository`). The
hierarchy repositories live in this same file rather than a separate one on
purpose: `notes.topic_id` is written from exactly one place
(`NoteRepository.move_to_topic` / `.set_assignment`), which is what "one
source of truth, no separate hierarchy representation" (Phase 3 spec) means
at the code level.
"""

from __future__ import annotations

import difflib
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.db.models import (
    Entity,
    Note,
    NoteContent,
    NoteTopic,
    Subject,
    Topic,
    TopicConnection,
    Understanding,
    WebResource,
)


class NoteRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **fields) -> Note:
        note = Note(**fields)
        self.db.add(note)
        self.db.flush()
        return note

    def get(self, note_id: str) -> Note | None:
        stmt = (
            select(Note)
            .where(Note.id == note_id)
            .options(
                selectinload(Note.entities),
                selectinload(Note.understanding),
                selectinload(Note.topic).selectinload(Topic.subject),
            )
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list(self, limit: int = 50, offset: int = 0) -> list[Note]:
        stmt = (
            select(Note)
            .order_by(Note.created_at.desc())
            .limit(limit)
            .offset(offset)
            .options(selectinload(Note.entities), selectinload(Note.understanding))
        )
        return list(self.db.execute(stmt).scalars().all())

    def count(self) -> int:
        return self.db.execute(select(func.count(Note.id))).scalar_one()

    def delete(self, note_id: str) -> bool:
        note = self.db.get(Note, note_id)
        if note is None:
            return False
        self.db.delete(note)
        return True

    # --- Phase 3: hierarchy -------------------------------------------------

    def list_by_topic(self, topic_id: str, limit: int = 200, offset: int = 0) -> list[Note]:
        stmt = (
            select(Note)
            .where(Note.topic_id == topic_id)
            .order_by(Note.created_at.desc())
            .limit(limit)
            .offset(offset)
            .options(selectinload(Note.understanding))
        )
        return list(self.db.execute(stmt).scalars().all())

    def list_by_subject(self, subject_id: str, limit: int = 1000) -> list[Note]:
        stmt = (
            select(Note)
            .join(Topic, Note.topic_id == Topic.id)
            .where(Topic.subject_id == subject_id)
            .order_by(Note.created_at.desc())
            .limit(limit)
            .options(selectinload(Note.understanding))
        )
        return list(self.db.execute(stmt).scalars().all())

    def list_between(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        subject_id: str | None = None,
        topic_id: str | None = None,
        limit: int = 5000,
    ) -> list[Note]:
        """Notes captured in `[start, end)`, optionally scoped to a subject or
        topic. Phase 5's time-range summarizer. Ordered oldest-first so a
        roll-up summary reads in the order the notes were actually taken."""
        stmt = select(Note).options(selectinload(Note.understanding))
        if topic_id:
            stmt = stmt.where(Note.topic_id == topic_id)
        elif subject_id:
            stmt = stmt.join(Topic, Note.topic_id == Topic.id).where(
                Topic.subject_id == subject_id
            )
        if start is not None:
            stmt = stmt.where(Note.created_at >= start)
        if end is not None:
            stmt = stmt.where(Note.created_at < end)
        stmt = stmt.order_by(Note.created_at.asc()).limit(limit)
        return list(self.db.execute(stmt).scalars().all())

    def move_to_topic(self, note_id: str, topic_id: str) -> Note | None:
        """Re-parent a note. Does not touch `summary_stale` on either topic -
        that is the caller's job (`app.hierarchy.service.move_note`), so a
        repository stays a plain data-access layer with no cross-table
        side effects hidden inside it."""
        note = self.db.get(Note, note_id)
        if note is None:
            return None
        note.topic_id = topic_id
        self.db.flush()
        return note

    def set_assignment(
        self, note_id: str, *, topic_id: str, method: str, confidence: float, reason: str
    ) -> Note | None:
        """File a note and record how, for `app.understanding.organizer.organize`."""
        note = self.db.get(Note, note_id)
        if note is None:
            return None
        note.topic_id = topic_id
        note.topic_assignment_method = method
        note.topic_assignment_confidence = confidence
        note.topic_assignment_reason = reason
        self.db.flush()
        return note


class UnderstandingRepository:
    def __init__(self, db: Session):
        self.db = db

    def upsert(self, note_id: str, **fields) -> Understanding:
        """Replace any existing result, so re-running understanding is idempotent."""
        existing = self.db.execute(
            select(Understanding).where(Understanding.note_id == note_id)
        ).scalar_one_or_none()
        if existing is not None:
            for key, value in fields.items():
                setattr(existing, key, value)
            self.db.flush()
            return existing
        record = Understanding(note_id=note_id, **fields)
        self.db.add(record)
        self.db.flush()
        return record

    def get_for_note(self, note_id: str) -> Understanding | None:
        return self.db.execute(
            select(Understanding).where(Understanding.note_id == note_id)
        ).scalar_one_or_none()


class EntityRepository:
    def __init__(self, db: Session):
        self.db = db

    def replace_for_note(self, note_id: str, entities: list[dict]) -> list[Entity]:
        """Delete the note's entities and write the new set.

        Replacement rather than append: re-running extraction on the same note
        must not leave duplicates behind.
        """
        for stale in self.db.execute(
            select(Entity).where(Entity.note_id == note_id)
        ).scalars():
            self.db.delete(stale)
        self.db.flush()

        created: list[Entity] = []
        for payload in entities:
            entity = Entity(note_id=note_id, **payload)
            self.db.add(entity)
            created.append(entity)
        self.db.flush()
        return created

    def list_for_note(self, note_id: str, kind: str | None = None) -> list[Entity]:
        stmt = select(Entity).where(Entity.note_id == note_id)
        if kind is not None:
            stmt = stmt.where(Entity.kind == kind)
        return list(self.db.execute(stmt).scalars().all())


class SubjectRepository:
    """Idea11y Section 4.1's Frame, adapted: the top level of the hierarchy."""

    def __init__(self, db: Session):
        self.db = db

    def get(self, subject_id: str) -> Subject | None:
        stmt = (
            select(Subject)
            .where(Subject.id == subject_id)
            .options(selectinload(Subject.topics))
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_name(self, name: str) -> Subject | None:
        """Case-insensitive: "Machine Learning" and "machine learning" are one subject."""
        stmt = select(Subject).where(func.lower(Subject.name) == name.strip().lower())
        return self.db.execute(stmt).scalar_one_or_none()

    def list(self) -> list[Subject]:
        """Unfiled last, alphabetical otherwise - a screen-reader user walking
        the outline meets real subjects before the catch-all bucket."""
        stmt = (
            select(Subject)
            .order_by(Subject.is_unfiled.asc(), func.lower(Subject.name).asc())
            .options(selectinload(Subject.topics))
        )
        return list(self.db.execute(stmt).scalars().all())

    def create(self, name: str, is_unfiled: bool = False) -> Subject:
        subject = Subject(name=name.strip(), is_unfiled=is_unfiled)
        self.db.add(subject)
        self.db.flush()
        return subject

    def get_or_create(self, name: str, is_unfiled: bool = False) -> tuple[Subject, bool]:
        existing = self.get_by_name(name)
        if existing is not None:
            return existing, False
        return self.create(name, is_unfiled=is_unfiled), True

    def get_or_create_unfiled(self) -> Subject:
        stmt = select(Subject).where(Subject.is_unfiled.is_(True))
        existing = self.db.execute(stmt).scalar_one_or_none()
        if existing is not None:
            return existing
        from app.config import get_settings

        return self.create(get_settings().unfiled_subject_name, is_unfiled=True)

    def find_best_name_match(self, name: str, cutoff: float = 0.72) -> Subject | None:
        """Fuzzy name resolution for voice commands and explicit-placement
        instructions: "operating systems" should land on an existing
        "Operating Systems" subject, not spawn a near-duplicate."""
        exact = self.get_by_name(name)
        if exact is not None:
            return exact
        subjects = self.list()
        if not subjects:
            return None
        names = [s.name for s in subjects]
        best = difflib.get_close_matches(name, names, n=1, cutoff=cutoff)
        if not best:
            return None
        return next(s for s in subjects if s.name == best[0])

    def count(self) -> int:
        return self.db.execute(select(func.count(Subject.id))).scalar_one()

    def delete(self, subject_id: str) -> bool:
        subject = self.db.get(Subject, subject_id)
        if subject is None:
            return False
        self.db.delete(subject)
        return True


class TopicRepository:
    """Idea11y Section 4.1's Cluster, adapted: a Topic or Project under a Subject."""

    def __init__(self, db: Session):
        self.db = db

    def get(self, topic_id: str) -> Topic | None:
        stmt = (
            select(Topic)
            .where(Topic.id == topic_id)
            .options(selectinload(Topic.subject), selectinload(Topic.notes))
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_name(self, subject_id: str, name: str) -> Topic | None:
        stmt = select(Topic).where(
            Topic.subject_id == subject_id, func.lower(Topic.name) == name.strip().lower()
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list_for_subject(self, subject_id: str) -> list[Topic]:
        stmt = (
            select(Topic)
            .where(Topic.subject_id == subject_id)
            .order_by(func.lower(Topic.name))
        )
        return list(self.db.execute(stmt).scalars().all())

    def list_all(self) -> list[Topic]:
        stmt = select(Topic).options(
            selectinload(Topic.subject), selectinload(Topic.notes)
        )
        return list(self.db.execute(stmt).scalars().all())

    def create(self, subject_id: str, name: str, kind: str = "topic") -> Topic:
        topic = Topic(subject_id=subject_id, name=name.strip(), kind=kind)
        self.db.add(topic)
        self.db.flush()
        return topic

    def get_or_create(self, subject_id: str, name: str, kind: str = "topic") -> tuple[Topic, bool]:
        existing = self.get_by_name(subject_id, name)
        if existing is not None:
            return existing, False
        return self.create(subject_id, name, kind=kind), True

    def get_or_create_fuzzy(
        self, subject_id: str, name: str, kind: str = "topic", cutoff: float | None = None
    ) -> tuple[Topic, bool]:
        """Like `get_or_create`, but a near-miss on an existing topic in this
        subject reuses it instead of creating a near-duplicate.

        Exists because the no-LLM topic-extraction fallback
        (`app.graph.topic_extraction._fallback_extract`) has no notion that
        "Array" and "Arrays" are the same topic - each note's extraction is
        independent, so a plural or minor wording difference used to spawn a
        second topic for something already in the graph. `get_by_name` only
        ever did an exact (case-insensitive) match, so this was never caught.
        The LLM path does not need this as often (it is more consistent
        about naming), but a near-miss there is just as worth reusing.
        """
        exact = self.get_by_name(subject_id, name)
        if exact is not None:
            return exact, False

        if cutoff is None:
            from app.config import get_settings

            cutoff = get_settings().topic_similarity_threshold

        candidates = self.list_for_subject(subject_id)
        if candidates:
            names = [t.name for t in candidates]
            best = difflib.get_close_matches(name, names, n=1, cutoff=cutoff)
            if best:
                return next(t for t in candidates if t.name == best[0]), False

        return self.create(subject_id, name, kind=kind), True

    def get_or_create_unfiled(self) -> Topic:
        from app.config import get_settings

        subject = SubjectRepository(self.db).get_or_create_unfiled()
        topic, _created = self.get_or_create(subject.id, get_settings().unfiled_topic_name)
        return topic

    def find_best_name_match(self, name: str, cutoff: float = 0.72) -> Topic | None:
        """Fuzzy topic-name resolution across the whole library (not scoped to
        one subject), for "move this note to Machine Learning" and "what
        notes are under Graph Theory" - the user names a topic, not a path."""
        topics = self.list_all()
        if not topics:
            return None
        exact = next((t for t in topics if t.name.strip().lower() == name.strip().lower()), None)
        if exact is not None:
            return exact
        names = [t.name for t in topics]
        best = difflib.get_close_matches(name, names, n=1, cutoff=cutoff)
        if not best:
            return None
        return next(t for t in topics if t.name == best[0])

    def count(self) -> int:
        return self.db.execute(select(func.count(Topic.id))).scalar_one()

    def count_notes(self, topic_id: str) -> int:
        return self.db.execute(
            select(func.count(Note.id)).where(Note.topic_id == topic_id)
        ).scalar_one()

    def delete(self, topic_id: str) -> bool:
        topic = self.db.get(Topic, topic_id)
        if topic is None:
            return False
        self.db.delete(topic)
        return True


# ---------------------------------------------------------------------------
# Knowledge graph (NexaNota redesign): note<->topic links, topic-to-topic
# connections (graph edges), per-topic web resources, and a note's generated
# three-area content.
# ---------------------------------------------------------------------------


class NoteTopicRepository:
    def __init__(self, db: Session):
        self.db = db

    def set_for_note(self, note_id: str, links: list[dict]) -> list[NoteTopic]:
        """Replace a note's topic links with `links`
        (each `{"topic_id", "rank", "confidence"}`), so re-organizing a note
        (an edit, a retry) never leaves stale links behind."""
        for stale in self.db.execute(
            select(NoteTopic).where(NoteTopic.note_id == note_id)
        ).scalars():
            self.db.delete(stale)
        self.db.flush()

        created = []
        for payload in links:
            link = NoteTopic(note_id=note_id, **payload)
            self.db.add(link)
            created.append(link)
        self.db.flush()
        return created

    def list_for_note(self, note_id: str) -> list[NoteTopic]:
        stmt = (
            select(NoteTopic)
            .where(NoteTopic.note_id == note_id)
            .order_by(NoteTopic.rank.asc())
            .options(selectinload(NoteTopic.topic))
        )
        return list(self.db.execute(stmt).scalars().all())

    def list_for_topic(self, topic_id: str) -> list[NoteTopic]:
        stmt = select(NoteTopic).where(NoteTopic.topic_id == topic_id)
        return list(self.db.execute(stmt).scalars().all())


class TopicConnectionRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_for_subject(self, subject_id: str) -> list[TopicConnection]:
        stmt = (
            select(TopicConnection)
            .where(TopicConnection.subject_id == subject_id)
            .options(
                selectinload(TopicConnection.topic_a),
                selectinload(TopicConnection.topic_b),
            )
        )
        return list(self.db.execute(stmt).scalars().all())

    def exists(self, topic_a_id: str, topic_b_id: str) -> bool:
        """Order-independent: A-B and B-A are the same edge."""
        stmt = select(func.count(TopicConnection.id)).where(
            or_(
                (TopicConnection.topic_a_id == topic_a_id)
                & (TopicConnection.topic_b_id == topic_b_id),
                (TopicConnection.topic_a_id == topic_b_id)
                & (TopicConnection.topic_b_id == topic_a_id),
            )
        )
        return self.db.execute(stmt).scalar_one() > 0

    def create(
        self,
        subject_id: str,
        topic_a_id: str,
        topic_b_id: str,
        *,
        label: str = "",
        confidence: float = 0.0,
        method: str = "llm",
    ) -> TopicConnection | None:
        """No-op (returns None) if this pair, in either order, already has an
        edge or if `topic_a_id == topic_b_id` - a topic never connects to
        itself."""
        if topic_a_id == topic_b_id or self.exists(topic_a_id, topic_b_id):
            return None
        connection = TopicConnection(
            subject_id=subject_id,
            topic_a_id=topic_a_id,
            topic_b_id=topic_b_id,
            label=label,
            confidence=confidence,
            method=method,
        )
        self.db.add(connection)
        self.db.flush()
        return connection


class WebResourceRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_for_topic(self, topic_id: str) -> list[WebResource]:
        stmt = select(WebResource).where(WebResource.topic_id == topic_id)
        return list(self.db.execute(stmt).scalars().all())

    def replace_for_topic(self, topic_id: str, resources: list[dict]) -> list[WebResource]:
        for stale in self.db.execute(
            select(WebResource).where(WebResource.topic_id == topic_id)
        ).scalars():
            self.db.delete(stale)
        self.db.flush()

        created = []
        for payload in resources:
            resource = WebResource(topic_id=topic_id, **payload)
            self.db.add(resource)
            created.append(resource)
        self.db.flush()
        return created


class NoteContentRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_for_note(self, note_id: str) -> NoteContent | None:
        return self.db.execute(
            select(NoteContent).where(NoteContent.note_id == note_id)
        ).scalar_one_or_none()

    def upsert_generated(self, note_id: str, **fields) -> NoteContent:
        """Write freshly generated content.

        Never touches `edit_markdown` once `edited_by_user` is set - a
        student's edit is never silently overwritten by a later
        regeneration (NexaNota 4.3.3's Edit Area is the student's own).
        """
        existing = self.get_for_note(note_id)
        if existing is not None:
            if existing.edited_by_user:
                fields.pop("edit_markdown", None)
            for key, value in fields.items():
                setattr(existing, key, value)
            self.db.flush()
            return existing
        record = NoteContent(note_id=note_id, **fields)
        self.db.add(record)
        self.db.flush()
        return record

    def save_edit(self, note_id: str, markdown: str) -> NoteContent | None:
        content = self.get_for_note(note_id)
        if content is None:
            return None
        content.edit_markdown = markdown
        content.edited_by_user = True
        self.db.flush()
        return content
