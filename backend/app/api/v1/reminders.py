"""Reminder endpoints - EchoNotes Feature 5."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/due")
async def due_now():
    """Reminders due right now, ready to be announced."""
    raise NotImplementedError


@router.get("/upcoming")
async def upcoming(within_hours: int = 24):
    """Answers "what is due tomorrow"."""
    raise NotImplementedError


@router.post("/{reminder_id}/done")
async def mark_done(reminder_id: str):
    raise NotImplementedError


@router.get("/contacts/{note_id}")
async def contact_actions(note_id: str):
    """Contact actions suggested by a note. Offered for confirmation, never executed here."""
    raise NotImplementedError
