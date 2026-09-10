"""Reminder scheduling and delivery - EchoNotes Feature 5."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def create_reminder(note_id: str, title: str, due_at: datetime) -> str:
    """Persist a reminder and return its id."""
    raise NotImplementedError


def due_reminders(now: datetime | None = None) -> list[dict[str, Any]]:
    """Reminders now due, for the client to announce."""
    raise NotImplementedError


def upcoming(within_hours: int = 24) -> list[dict[str, Any]]:
    """Answers "what is due tomorrow", the REMIND intent."""
    raise NotImplementedError


def mark_done(reminder_id: str) -> None:
    raise NotImplementedError
