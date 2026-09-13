"""Reminders (Phase 5).

Detection is **built on Team Member 1's extraction, not repeated**. Their
`app/understanding/entities.py` already finds tasks, dates and deadlines from a
transcript, normalises relative dates against the capture time, and stores each
with a confidence and a character span. Re-parsing "next Friday" here would give
the project two date parsers that could disagree with each other - which is the
one thing a reminder system must never do. This module reads the `note_entities`
rows their pipeline wrote and decides which of them deserve a reminder.

**Pairing.** A reminder needs a *what* and a *when*, and a note supplies them as
separate entities. Tasks and deadlines are paired by proximity in the text -
the deadline nearest a task's span is the one that belongs to it - which handles
the common "submit the report by Friday, and call Sarah on Monday" case that a
naive first-task-first-date pairing gets backwards.

**Confidence gates auto-creation.** Below
`REMINDER_AUTO_CREATE_CONFIDENCE` a detection is returned as a *suggestion* and
not written. A reminder the user did not intend is worse than a missed one: they
cannot see the list to notice it, and it will speak up at the wrong moment.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import (
    Entity,
    EntityKind,
    Note,
    Reminder,
    ReminderAlert,
    ReminderSource,
    ReminderStatus,
)

logger = logging.getLogger(__name__)


@dataclass
class DetectedReminder:
    """A candidate reminder, before the confidence gate decides its fate."""

    title: str
    due_at: datetime | None
    confidence: float
    detected_phrase: str
    auto_create: bool


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def _parse_normalized(value: str | None) -> datetime | None:
    """Read the ISO-8601 value Team Member 1's extractor stored."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        # A date-only value ("2026-09-11") parses; anything else is a phrase the
        # extractor could not normalise, and a reminder with no time is better
        # than one at a guessed time.
        logger.debug("unparseable normalized date %r", value)
        return None


#: How much closer a plain date must be than a deadline to win the pairing.
#: A deadline ("by Friday") is a stronger commitment signal than a bare date
#: ("on March 3rd"), so it is preferred - but only as a tiebreaker. Treating it
#: as absolute precedence attaches the one deadline in a note to every task in
#: it, including tasks that had a date of their own sitting right beside them.
_DEADLINE_BONUS_CHARS = 40.0


def _midpoint(entity: Entity) -> float | None:
    if entity.span_start is None:
        return None
    return (entity.span_start + (entity.span_end or entity.span_start)) / 2


def _pair_distance(task: Entity, candidate: Entity) -> float:
    """Text distance between a task and a candidate date, deadline-adjusted."""
    task_mid = _midpoint(task)
    candidate_mid = _midpoint(candidate)
    if task_mid is None or candidate_mid is None:
        # No spans to compare. Usable, but always the last resort.
        return 10_000.0
    distance = abs(candidate_mid - task_mid)
    if candidate.kind == EntityKind.DEADLINE.value:
        distance -= _DEADLINE_BONUS_CHARS
    return distance


def _pair_tasks_with_dates(
    tasks: list[Entity], dated: list[Entity]
) -> dict[str, Entity]:
    """Assign each task at most one date, and each date to at most one task.

    Greedy over every (task, date) pair sorted by adjusted distance. One-to-one
    matters: a note with two tasks and two dates should produce two reminders on
    two different days, which is exactly what a shared-date assignment gets
    wrong - and a reminder that fires on the wrong day is worse than one that
    never fires, because the user acts on it.
    """
    pairs = sorted(
        (
            (_pair_distance(task, candidate), task.id, candidate.id)
            for task in tasks
            for candidate in dated
        ),
        key=lambda item: item[0],
    )

    by_id = {entity.id: entity for entity in dated}
    assigned: dict[str, Entity] = {}
    taken_dates: set[str] = set()

    for _distance, task_id, candidate_id in pairs:
        if task_id in assigned or candidate_id in taken_dates:
            continue
        assigned[task_id] = by_id[candidate_id]
        taken_dates.add(candidate_id)

    return assigned


def detect_reminders(db: Session, note: Note) -> list[DetectedReminder]:
    """Which reminders this note implies, given what was already extracted."""
    settings = get_settings()

    entities = list(
        db.execute(select(Entity).where(Entity.note_id == note.id)).scalars().all()
    )
    tasks = [e for e in entities if e.kind == EntityKind.TASK.value]
    dated = [
        e
        for e in entities
        if e.kind in (EntityKind.DEADLINE.value, EntityKind.DATE.value)
        and _parse_normalized(e.normalized) is not None
    ]
    deadlines = [e for e in dated if e.kind == EntityKind.DEADLINE.value]

    detected: list[DetectedReminder] = []
    paired = _pair_tasks_with_dates(tasks, dated)
    used_date_ids: set[str] = {entity.id for entity in paired.values()}

    for task in tasks:
        match = paired.get(task.id)
        due_at = _parse_normalized(match.normalized) if match else None
        confidence = task.confidence
        phrase = match.value if match else ""
        if match is not None:
            # Both halves have to be right for the reminder to be right.
            confidence = min(task.confidence, match.confidence)

        detected.append(
            DetectedReminder(
                title=_clean_title(task.value),
                due_at=due_at,
                confidence=round(confidence, 3),
                detected_phrase=phrase,
                auto_create=confidence >= settings.reminder_auto_create_confidence,
            )
        )

    # A deadline with no task attached still deserves a reminder - "the report
    # is due Friday" names a commitment without an imperative verb.
    for entity in deadlines:
        if entity.id in used_date_ids:
            continue
        due_at = _parse_normalized(entity.normalized)
        if due_at is None:
            continue
        detected.append(
            DetectedReminder(
                title=_title_from_context(note, entity),
                due_at=due_at,
                confidence=round(entity.confidence, 3),
                detected_phrase=entity.value,
                auto_create=entity.confidence >= settings.reminder_auto_create_confidence,
            )
        )

    return detected


def _clean_title(text: str) -> str:
    """Turn an extracted task phrase into a short spoken title."""
    title = " ".join((text or "").split())
    title = title.rstrip(".!?,;: ")
    if title:
        title = title[0].upper() + title[1:]
    return title[:200]


def _title_from_context(note: Note, entity: Entity) -> str:
    """Name a reminder from the sentence its deadline appeared in."""
    text = note.cleaned_text or note.raw_transcript or ""
    if entity.span_start is None or not text:
        return _clean_title(entity.value or "Reminder")

    start = text.rfind(".", 0, entity.span_start) + 1
    end = text.find(".", entity.span_start)
    sentence = text[start : end if end != -1 else len(text)]
    return _clean_title(sentence) or _clean_title(entity.value or "Reminder")


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


class ReminderService:
    """Reminder CRUD plus detection. Flushes, never commits - the caller owns
    the transaction, matching the convention Team Member 1 set in
    `capture_pipeline.persist_capture`."""

    def __init__(self, db: Session):
        self.db = db

    # --- create ---------------------------------------------------------

    def create(
        self,
        *,
        title: str,
        due_at: datetime | None = None,
        note_id: str | None = None,
        source: str = ReminderSource.MANUAL.value,
        confidence: float = 1.0,
        detected_phrase: str | None = None,
    ) -> Reminder:
        reminder = Reminder(
            note_id=note_id,
            title=title,
            due_at=due_at,
            status=ReminderStatus.PENDING.value,
            source=source,
            confidence=confidence,
            detected_phrase=detected_phrase,
        )
        self.db.add(reminder)
        self.db.flush()
        return reminder

    def create_from_note(self, note: Note) -> list[Reminder]:
        """Detect and persist the confident reminders in a note.

        Idempotent: re-running on the same note does not duplicate reminders,
        so reprocessing a capture is safe.
        """
        created: list[Reminder] = []
        existing = {
            (r.title, r.due_at) for r in self.list_for_note(note.id)
        }

        for candidate in detect_reminders(self.db, note):
            if not candidate.auto_create:
                logger.info(
                    "reminder suggestion (not created, confidence %.2f): %r",
                    candidate.confidence,
                    candidate.title,
                )
                continue
            if (candidate.title, candidate.due_at) in existing:
                continue
            created.append(
                self.create(
                    title=candidate.title,
                    due_at=candidate.due_at,
                    note_id=note.id,
                    source=ReminderSource.DETECTED.value,
                    confidence=candidate.confidence,
                    detected_phrase=candidate.detected_phrase,
                )
            )
            existing.add((candidate.title, candidate.due_at))

        if created:
            logger.info("created %d reminder(s) from note %s", len(created), note.id)
        return created

    # --- read -----------------------------------------------------------

    def get(self, reminder_id: str) -> Reminder | None:
        return self.db.get(Reminder, reminder_id)

    def list(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Reminder]:
        statement = select(Reminder)
        if status:
            statement = statement.where(Reminder.status == status)
        # Undated reminders sort last: a to-do with no time is not urgent, and
        # burying dated ones underneath them makes the list useless.
        statement = statement.order_by(
            Reminder.due_at.is_(None), Reminder.due_at.asc(), Reminder.created_at.desc()
        )
        statement = statement.limit(limit).offset(offset)
        return list(self.db.execute(statement).scalars().all())

    def list_for_note(self, note_id: str) -> list[Reminder]:
        statement = select(Reminder).where(Reminder.note_id == note_id)
        return list(self.db.execute(statement).scalars().all())

    def due(self, now: datetime | None = None) -> list[Reminder]:
        """Pending reminders whose time has arrived."""
        now = now or datetime.now()
        statement = (
            select(Reminder)
            .where(Reminder.status == ReminderStatus.PENDING.value)
            .where(Reminder.due_at.is_not(None))
            .where(Reminder.due_at <= now)
            .order_by(Reminder.due_at.asc())
        )
        return list(self.db.execute(statement).scalars().all())

    def upcoming(self, within_hours: int = 24, now: datetime | None = None) -> list[Reminder]:
        """Pending reminders falling due inside the window.

        Overdue ones are included: something that was due yesterday and is still
        pending is the most important thing in the list, not the least.
        """
        now = now or datetime.now()
        horizon = now + timedelta(hours=within_hours)
        statement = (
            select(Reminder)
            .where(Reminder.status == ReminderStatus.PENDING.value)
            .where(Reminder.due_at.is_not(None))
            .where(Reminder.due_at <= horizon)
            .order_by(Reminder.due_at.asc())
        )
        return list(self.db.execute(statement).scalars().all())

    def due_soon(self, lead_minutes: int = 60, now: datetime | None = None) -> list[Reminder]:
        """Pending reminders due within `lead_minutes` that have not yet been
        announced, marking them announced as a side effect.

        For the one-hour-before voice alert (blind users cannot glance at a
        screen to notice a reminder is coming up, so the app has to say it).
        Overdue-but-unannounced reminders are included too, same reasoning as
        `upcoming()`: a missed alert (the app was closed at the time) should
        still be spoken once, not silently skipped.

        Marking happens here, not by the caller, so two near-simultaneous
        polls can never both announce the same reminder: this call is the
        single place that decides "has this been said yet", and it decides it
        atomically with recording that it now has.
        """
        now = now or datetime.now()
        horizon = now + timedelta(minutes=lead_minutes)
        already_alerted = set(
            self.db.execute(select(ReminderAlert.reminder_id)).scalars().all()
        )

        statement = (
            select(Reminder)
            .where(Reminder.status == ReminderStatus.PENDING.value)
            .where(Reminder.due_at.is_not(None))
            .where(Reminder.due_at <= horizon)
            .order_by(Reminder.due_at.asc())
        )
        due_soon = [
            r for r in self.db.execute(statement).scalars().all() if r.id not in already_alerted
        ]

        for reminder in due_soon:
            self.db.add(ReminderAlert(reminder_id=reminder.id, alerted_at=now))
        if due_soon:
            self.db.flush()

        return due_soon

    # --- update / delete -------------------------------------------------

    def update(
        self,
        reminder_id: str,
        *,
        title: str | None = None,
        due_at: datetime | None = None,
        status: str | None = None,
    ) -> Reminder | None:
        reminder = self.get(reminder_id)
        if reminder is None:
            return None
        if title is not None:
            reminder.title = title
        if due_at is not None:
            reminder.due_at = due_at
        if status is not None:
            reminder.status = status
        self.db.flush()
        return reminder

    def mark_done(self, reminder_id: str) -> Reminder | None:
        return self.update(reminder_id, status=ReminderStatus.DONE.value)

    def dismiss(self, reminder_id: str) -> Reminder | None:
        return self.update(reminder_id, status=ReminderStatus.DISMISSED.value)

    def delete(self, reminder_id: str) -> bool:
        reminder = self.get(reminder_id)
        if reminder is None:
            return False
        self.db.delete(reminder)
        self.db.flush()
        return True

    # --- serialisation ---------------------------------------------------

    def to_dict(self, reminder: Reminder) -> dict[str, Any]:
        return {
            "id": reminder.id,
            "note_id": reminder.note_id,
            "title": reminder.title,
            "due_at": reminder.due_at.isoformat() if reminder.due_at else None,
            "due_spoken": speak_datetime(reminder.due_at) if reminder.due_at else None,
            "status": reminder.status,
            "source": reminder.source,
            "confidence": reminder.confidence,
            "detected_phrase": reminder.detected_phrase,
            "created_at": reminder.created_at.isoformat() if reminder.created_at else None,
        }


def create_reminders_safe(db: Session, note: Note) -> list[Reminder]:
    """Detection that never raises, for the capture pipeline.

    Same contract as understanding and organization: a note is never lost
    because something downstream of it failed.
    """
    try:
        return ReminderService(db).create_from_note(note)
    except Exception:
        logger.exception("reminder detection failed for note %s; note kept", note.id)
        return []


# ---------------------------------------------------------------------------
# Speaking dates and reminder lists
# ---------------------------------------------------------------------------


def speak_datetime(value: datetime, now: datetime | None = None) -> str:
    """Say a date the way a person would.

    "tomorrow at four" rather than "2026-09-12T16:00:00". An ISO string read by
    a screen reader is a stream of digits nobody can hold in their head.
    """
    now = now or datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    that_day = value.replace(hour=0, minute=0, second=0, microsecond=0)
    delta_days = (that_day - today).days

    if delta_days == 0:
        day = "today"
    elif delta_days == 1:
        day = "tomorrow"
    elif delta_days == -1:
        day = "yesterday"
    elif 1 < delta_days < 7:
        day = f"on {value:%A}"
    elif -7 < delta_days < -1:
        day = f"last {value:%A}"
    else:
        day = f"on {value.day} {value:%B}"

    # Midnight almost always means "no time was given", not "at 00:00".
    if value.hour == 0 and value.minute == 0:
        return day

    hour = value.hour % 12 or 12
    meridiem = "am" if value.hour < 12 else "pm"
    if value.minute:
        return f"{day} at {hour}:{value.minute:02d} {meridiem}"
    return f"{day} at {hour} {meridiem}"


def describe_window(hours: int) -> str:
    """Say a lookahead window the way a person would.

    "in the next 168 hours" is arithmetically correct and useless to listen to.
    """
    if hours <= 1:
        return "the next hour"
    if hours < 24:
        return f"the next {hours} hours"
    if hours == 24:
        return "the next 24 hours"
    if hours == 48:
        return "the next two days"
    days = hours // 24
    if days == 7:
        return "the next week"
    if days < 7:
        return f"the next {days} days"
    if days in (30, 31):
        return "the next month"
    if days >= 365:
        return "the next year"
    weeks = days // 7
    if weeks == 1:
        return "the next week"
    return f"the next {weeks} weeks"


def narrate_reminders(
    reminders: list[Reminder], within_hours: int, now: datetime | None = None
) -> str:
    """One spoken sentence for a reminder list.

    Capped at three read aloud. A listener cannot skim past a list of twelve, so
    the rest are counted rather than enumerated.
    """
    now = now or datetime.now()
    window = describe_window(within_hours)

    if not reminders:
        return f"Nothing due in {window}."

    spoken_items = [
        f"{r.title}, {speak_datetime(r.due_at, now)}" if r.due_at else r.title
        for r in reminders[:3]
    ]
    count = len(reminders)
    lead = f"You have {count} reminder{'s' if count != 1 else ''} in {window}. "
    body = ". ".join(spoken_items)
    if count > 3:
        body += f". And {count - 3} more"
    return f"{lead}{body}."
