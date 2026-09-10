"""Reminder endpoints (Phase 5, Team Member 3).

    GET    /api/v1/reminders             list, optionally filtered by status
    POST   /api/v1/reminders             create one directly
    GET    /api/v1/reminders/due         what is due now
    GET    /api/v1/reminders/upcoming    what is due within a window
    GET    /api/v1/reminders/{id}        one reminder
    PATCH  /api/v1/reminders/{id}        edit title, due date or status
    POST   /api/v1/reminders/{id}/done   mark done
    POST   /api/v1/reminders/{id}/dismiss
    DELETE /api/v1/reminders/{id}
    GET    /api/v1/reminders/notes/{note_id}/detected   what a note implies

The list endpoints return a narrated `spoken` field alongside the data, because
the primary client reads them aloud rather than rendering a table.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_db
from app.reminders.service import (
    ReminderService,
    detect_reminders,
    narrate_reminders,
    speak_datetime,
)
from app.schemas.reminders import (
    DetectedReminderOut,
    ReminderCreate,
    ReminderListOut,
    ReminderOut,
    ReminderUpdate,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _out(service: ReminderService, reminder) -> ReminderOut:
    return ReminderOut(**service.to_dict(reminder))


def _list_response(service: ReminderService, reminders, within_hours: int) -> ReminderListOut:
    return ReminderListOut(
        reminders=[_out(service, r) for r in reminders],
        count=len(reminders),
        spoken=narrate_reminders(reminders, within_hours),
    )


@router.get("", response_model=ReminderListOut, summary="List reminders")
def list_reminders(
    status_filter: str | None = Query(
        default=None, alias="status", description="pending | done | dismissed"
    ),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    service = ReminderService(db)
    reminders = service.list(status=status_filter, limit=limit, offset=offset)
    return _list_response(service, reminders, get_settings().reminder_lookahead_hours)


@router.post(
    "",
    response_model=ReminderOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a reminder",
)
def create_reminder(payload: ReminderCreate, db: Session = Depends(get_db)):
    service = ReminderService(db)
    reminder = service.create(
        title=payload.title, due_at=payload.due_at, note_id=payload.note_id
    )
    db.commit()
    return _out(service, reminder)


@router.get("/due", response_model=ReminderListOut, summary="Reminders due now")
def due_now(db: Session = Depends(get_db)):
    service = ReminderService(db)
    return _list_response(service, service.due(), get_settings().reminder_lookahead_hours)


@router.get(
    "/upcoming", response_model=ReminderListOut, summary="Reminders due within a window"
)
def upcoming(
    within_hours: int = Query(default=24, ge=1, le=24 * 90),
    db: Session = Depends(get_db),
):
    service = ReminderService(db)
    return _list_response(service, service.upcoming(within_hours=within_hours), within_hours)


@router.get(
    "/notes/{note_id}/detected",
    response_model=list[DetectedReminderOut],
    summary="What reminders a note implies",
)
def detected_for_note(note_id: str, db: Session = Depends(get_db)):
    """Every candidate found in a note, including the low-confidence ones that
    were *not* auto-created - so a user can review and confirm them."""
    from app.db.repositories import NoteRepository

    note = NoteRepository(db).get(note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="note not found")

    return [
        DetectedReminderOut(
            title=candidate.title,
            due_at=candidate.due_at.isoformat() if candidate.due_at else None,
            due_spoken=speak_datetime(candidate.due_at) if candidate.due_at else None,
            confidence=candidate.confidence,
            detected_phrase=candidate.detected_phrase,
            auto_create=candidate.auto_create,
        )
        for candidate in detect_reminders(db, note)
    ]


@router.get("/{reminder_id}", response_model=ReminderOut, summary="One reminder")
def get_reminder(reminder_id: str, db: Session = Depends(get_db)):
    service = ReminderService(db)
    reminder = service.get(reminder_id)
    if reminder is None:
        raise HTTPException(status_code=404, detail="reminder not found")
    return _out(service, reminder)


@router.patch("/{reminder_id}", response_model=ReminderOut, summary="Edit a reminder")
def update_reminder(
    reminder_id: str, payload: ReminderUpdate, db: Session = Depends(get_db)
):
    service = ReminderService(db)
    reminder = service.update(
        reminder_id, title=payload.title, due_at=payload.due_at, status=payload.status
    )
    if reminder is None:
        raise HTTPException(status_code=404, detail="reminder not found")
    db.commit()
    return _out(service, reminder)


@router.post("/{reminder_id}/done", response_model=ReminderOut, summary="Mark done")
def mark_done(reminder_id: str, db: Session = Depends(get_db)):
    service = ReminderService(db)
    reminder = service.mark_done(reminder_id)
    if reminder is None:
        raise HTTPException(status_code=404, detail="reminder not found")
    db.commit()
    return _out(service, reminder)


@router.post("/{reminder_id}/dismiss", response_model=ReminderOut, summary="Dismiss")
def dismiss(reminder_id: str, db: Session = Depends(get_db)):
    service = ReminderService(db)
    reminder = service.dismiss(reminder_id)
    if reminder is None:
        raise HTTPException(status_code=404, detail="reminder not found")
    db.commit()
    return _out(service, reminder)


@router.delete(
    "/{reminder_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete"
)
def delete_reminder(reminder_id: str, db: Session = Depends(get_db)):
    if not ReminderService(db).delete(reminder_id):
        raise HTTPException(status_code=404, detail="reminder not found")
    db.commit()
