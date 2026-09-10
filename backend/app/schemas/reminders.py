"""Reminder and contact schemas (Phase 5)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ReminderCreate(BaseModel):
    title: str
    due_at: datetime | None = None
    note_id: str | None = None


class ReminderUpdate(BaseModel):
    title: str | None = None
    due_at: datetime | None = None
    status: str | None = Field(default=None, description="pending | done | dismissed")


class ReminderOut(BaseModel):
    id: str
    note_id: str | None = None
    title: str
    due_at: str | None = None
    due_spoken: str | None = Field(
        default=None, description='The due date as a person would say it: "tomorrow at 4 pm"'
    )
    status: str
    source: str = Field(description='"detected" from a note, or "manual"')
    confidence: float = 0.0
    detected_phrase: str | None = Field(
        default=None, description='The wording the date came from, e.g. "next Friday"'
    )
    created_at: str | None = None


class ReminderListOut(BaseModel):
    reminders: list[ReminderOut]
    count: int
    spoken: str = Field(description="The list narrated in one sentence")


class DetectedReminderOut(BaseModel):
    """A candidate found in a note. Below the confidence floor it is offered
    rather than created - see `app/reminders/service.py`."""

    title: str
    due_at: str | None = None
    due_spoken: str | None = None
    confidence: float
    detected_phrase: str = ""
    auto_create: bool


class ContactCreate(BaseModel):
    name: str
    email: str | None = None
    phone: str | None = None


class ContactUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None


class ContactOut(BaseModel):
    id: str
    name: str
    normalized_name: str
    email: str | None = None
    phone: str | None = None
    mention_count: int = 0
    created_at: str | None = None


class ContactActionOut(BaseModel):
    action: str = Field(description="call | message | email")
    target: str
    spoken: str = Field(description="The confirmation to speak before doing anything")


class ContactDetailOut(BaseModel):
    contact: ContactOut
    actions: list[ContactActionOut] = Field(
        default_factory=list,
        description="Offered for confirmation. EchoNotes never executes these itself.",
    )
    note_ids: list[str] = []
    spoken: str = ""
