"""Data access. Every query lives here so the services stay free of SQLAlchemy."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session


class SubjectRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_or_create(self, name: str) -> Any: ...
    def unfiled(self) -> Any: ...
    def list_all(self) -> list[Any]: ...


class TopicRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, subject_id: str, name: str, kind: str = "topic") -> Any: ...
    def list_for_subject(self, subject_id: str) -> list[Any]: ...
    def set_summary(self, topic_id: str, summary: str) -> None: ...
    def mark_stale(self, topic_id: str) -> None: ...


class NoteRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **fields) -> Any: ...
    def get(self, note_id: str) -> Any: ...
    def update_text(self, note_id: str, text: str) -> Any: ...
    def move(self, note_id: str, topic_id: str) -> Any: ...
    def delete(self, note_id: str) -> None: ...
    def list_for_topic(self, topic_id: str) -> list[Any]: ...


class HierarchyRepository:
    """Loads the whole tree in one pass for the outline endpoint.

    The outline is requested on nearly every interaction, so it must not fan out into a query per
    topic.
    """

    def __init__(self, db: Session):
        self.db = db

    def load_hierarchy(self) -> Any: ...


class AnalysisRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, note_id: str, **metrics) -> Any: ...
    def get_for_note(self, note_id: str) -> Any: ...


class ReminderRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **fields) -> Any: ...
    def due(self, now) -> list[Any]: ...
    def upcoming(self, within_hours: int) -> list[Any]: ...
