"""Data access. Every query lives here so services stay free of SQLAlchemy.

Covers the capture + understanding tables only. Subject/Topic repositories
belong to the hierarchy work and are not defined here.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import Entity, Note, Understanding


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
            .options(selectinload(Note.entities), selectinload(Note.understanding))
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
        from sqlalchemy import func

        return self.db.execute(select(func.count(Note.id))).scalar_one()

    def delete(self, note_id: str) -> bool:
        note = self.db.get(Note, note_id)
        if note is None:
            return False
        self.db.delete(note)
        return True


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
