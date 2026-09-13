"""Event-mention reminders with follow-up questions (Phase 5 addition).

`app/reminders/service.py` turns a *task* paired with a *date* into a
reminder ("submit the report by Friday"). It deliberately does not handle a
plain event mention like "I have a meeting at 3:30 am on 13 September": there
is no task verb and no deadline cue, so `detect_reminders` never looks at it
- see that module's docstring. This module is the separate, additive pathway
for exactly that phrasing:

    "I have a meeting at 3:30 am on 13 September"
        -> date and an unambiguous time are known -> reminder saved
           immediately.

    "I have a meeting tomorrow"
        -> date known, time missing -> asks "When is your meeting?" -> the
           next note's answer supplies the time -> reminder saved (or, if
           that answer's time has no am/pm, one more question first - see
           below).

    "I have a meeting"
        -> neither known -> asks "Which date do you have the meeting?"
           (date first, per spec) -> then "When is your meeting?" -> saved.

    "I have a meeting at 3:30"
        -> a time was given, but nothing said whether it is 3:30 in the
           morning or the evening ("3:30 pm" or "15:30" would need no
           follow-up; a bare "3:30" or "three o'clock" does - see
           `entities.time_is_ambiguous`). Whichever of date/time is still
           missing is asked for first as above, and once both are in hand,
           "Is it AM or PM?" is asked before anything is saved - a guess that
           fires a reminder twelve hours off is worse than one more question.

Same architectural rule as `reminders/service.py`: **never re-implement
date/time parsing here.** Every date or time this module uses was already
extracted and normalised by `app/understanding/entities.py` and is read back
from the `note_entities` rows the capture pipeline already wrote (or, for a
one-off answer like "3:30 am", the rows written for that answer's own note).
Reading a plain "am"/"pm"/"morning"/"evening" reply to this module's own
question is the one exception - that is not a date or a time expression on
its own, so entities.py has no reason to know about it; it belongs here.

State lives in a new `PendingReminder` table (see `app/db/models.py`) so this
whole feature is additive: nothing here changes what `detect_reminders`,
`ReminderService`, or the capture pipeline already do for every other note.
`PendingReminder.stage` also carries the "still needs a meridiem after this"
bit rather than a new column, so an existing user's database (already
carrying this table from before the am/pm question existed) never needs
altering - see the stage list on `_handle_pending_answer`.

None of this belongs in the Notes list. An event mention and every answer it
takes to complete it ("5:20 p.m.", "13th September", "PM") are one side of a
question the app itself asked - not something the user sat down to write.
The capture endpoint (`app/api/v1/capture.py`) calls `suppress_clarification_note`
below to delete the note the moment `handle_reminder_clarification_safe`
reports it had something to say (a question, or "Reminder set..."); only a
capture this module has no opinion on (`ClarificationResult(spoken=None)`)
is kept as an ordinary note.

**Plain todos get the identical treatment, not just event mentions.** "I have
to submit my assignment." has a task (Team Member 1's `entities.py` already
extracted it) but no date, so `detect_reminders` in `app/reminders/service.py`
never fires - it needs a task *and* a date to pair - and the note used to sit
in the Notes list forever with no way to become a reminder. `detect_task_mention`
below reads that same task entity, and when the note has no date at all, this
module drives the exact same date -> time -> (meridiem if ambiguous) -> save
state machine used for an event mention, just with generic wording ("What
date do you need to submit my assignment?" instead of "Which date do you have
the meeting?"). A todo that already has a date - "submit my assignment by
Friday" - is left alone: `detect_reminders` already turns that into a
reminder immediately, same as before this was added, and asking a redundant
question there would just be annoying. The two flows share one `PendingReminder`
row and one TTL/staleness check; which wording a row uses is recorded by
prefixing its `stage` with "todo_" (see `_kind_and_stage` below) rather than a
new column, for the same reason `stage` already doubles up for the meridiem
sub-states - `init_db()` never alters an existing table's columns.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Entity, Note, PendingReminder, ReminderSource
from app.reminders.service import ReminderService, speak_datetime
from app.understanding.entities import time_is_ambiguous

logger = logging.getLogger(__name__)

# Conservative on purpose: this only fires on a clear first-person mention of
# having an event, not on any note that happens to contain the word
# "meeting" ("the meeting notes say..." should not become a reminder).
# "reminder"/"event" are here too because that is how people actually ask
# for this feature ("I have a reminder at 5:30") - without it, "I have a
# reminder..." fell through to an ordinary note with no follow-up question
# at all, since nothing recognised it as an event mention to begin with.
_EVENT_CUES = (
    "meeting", "appointment", "interview", "exam", "class", "lecture",
    "session", "call", "checkup", "check-up", "consultation", "reminder",
    "event",
)
_EVENT_MENTION_RE = re.compile(
    r"\b(?:i\s+have(?:\s+got)?|i['’]ve\s+got|i\s+got|there(?:['’]s|\s+is)|my)\s+"
    r"(?:a|an|the)?\s*(?P<event>%s)\b" % "|".join(_EVENT_CUES),
    re.IGNORECASE,
)


@dataclass
class ClarificationResult:
    """What happened to one captured note, for the caller to speak."""

    #: What to say, or None when this note had nothing to do with a
    #: clarification (no event mention, and no pending question to answer).
    spoken: str | None
    #: True once a Reminder was actually created.
    reminder_created: bool = False


def _title_for_event(word: str) -> str:
    return word[:1].upper() + word[1:].lower()


def detect_event_mention(text: str) -> str | None:
    """Return a spoken-style title ("Meeting") if `text` mentions having an
    event, else None."""
    match = _EVENT_MENTION_RE.search(text or "")
    if not match:
        return None
    return _title_for_event(match.group("event"))


def detect_task_mention(db: Session, note_id: str) -> str | None:
    """Return a spoken-style title ("Submit my assignment") for this note's
    task entity, if it has one, else None.

    Reuses Team Member 1's task extraction (`app/understanding/entities.py`,
    already stored as `note_entities` rows) instead of re-detecting task
    phrasing here - the same rule this module already follows for dates and
    times, see the module docstring. The task's own phrase ("submit my
    assignment") is always a verb phrase (every `TASK_CUES` entry in
    entities.py is followed directly by one), which is what lets
    `_ask_date`/`_ask_time` below turn it into a natural question ("What date
    do you need to submit my assignment?").
    """
    for entity in _entities_for_note(db, note_id):
        if entity.kind == "task" and entity.value:
            return _title_for_event(entity.value)
    return None


def _entities_for_note(db: Session, note_id: str) -> list[Entity]:
    return list(db.execute(select(Entity).where(Entity.note_id == note_id)).scalars().all())


def _resolved_date_from_note(db: Session, note_id: str) -> tuple[str | None, str]:
    """The first resolvable date/deadline entity's ISO date and source phrase."""
    for entity in _entities_for_note(db, note_id):
        if entity.kind in ("date", "deadline") and entity.normalized:
            try:
                datetime.fromisoformat(entity.normalized)
            except ValueError:
                continue
            return entity.normalized[:10], entity.value
    return None, ""


def _resolved_time_from_note(db: Session, note_id: str) -> tuple[str | None, str]:
    """The first resolvable time entity's ISO time and source phrase."""
    for entity in _entities_for_note(db, note_id):
        if entity.kind == "time" and entity.normalized:
            return entity.normalized, entity.value
    return None, ""


def _combine(date_iso: str | None, time_iso: str | None) -> datetime | None:
    if not date_iso or not time_iso:
        return None
    try:
        return datetime.fromisoformat(f"{date_iso}T{time_iso}")
    except ValueError:
        return None


#: Prefixes a todo row's `stage` ("need_date" -> "todo_need_date") so one
#: `PendingReminder` table serves both flows without a new column - see the
#: module docstring's "Plain todos" paragraph.
_TODO_STAGE_PREFIX = "todo_"


def _stage_name(base: str, kind: str) -> str:
    return f"{_TODO_STAGE_PREFIX}{base}" if kind == "todo" else base


def _kind_and_stage(stage: str) -> tuple[str, str]:
    """Split a possibly-prefixed `stage` back into ("event"|"todo", base)."""
    if stage.startswith(_TODO_STAGE_PREFIX):
        return "todo", stage[len(_TODO_STAGE_PREFIX) :]
    return "event", stage


def _ask_time(kind: str, title: str) -> str:
    if kind == "todo":
        return f"What time do you need to {title.lower()}?"
    return "When is your meeting?"


def _ask_date(kind: str, title: str) -> str:
    if kind == "todo":
        return f"What date do you need to {title.lower()}?"
    return "Which date do you have the meeting?"


def _ask_meridiem() -> str:
    return "Is it AM or PM?"


#: A reply to `_ask_meridiem()`. Accepts the plain word too ("morning",
#: "evening"), so the user is not forced to say the letters "AM"/"PM"
#: exactly - natural speech-to-text is more likely to produce the word.
_MERIDIEM_ANSWER_RE = re.compile(
    r"\b(a\.?m\.?|p\.?m\.?|morning|afternoon|evening|night)\b", re.IGNORECASE
)


def _parse_meridiem_answer(text: str) -> str | None:
    """Read a reply to "Is it AM or PM?" as "am", "pm", or None (unrecognised,
    so the question should be asked again)."""
    match = _MERIDIEM_ANSWER_RE.search(text or "")
    if not match:
        return None
    word = match.group(1).lower().replace(".", "")
    if word in ("am", "morning"):
        return "am"
    if word in ("pm", "afternoon", "evening", "night"):
        return "pm"
    return None


def _apply_meridiem(time_iso: str, meridiem: str) -> str:
    """Turn a placeholder time from `time_is_ambiguous` into a real one, the
    same 12-hour-clock arithmetic `entities.normalize_time` already uses for
    an explicit "3 pm"."""
    hour = int(time_iso[:2])
    minute = time_iso[3:5]
    if meridiem == "pm" and hour != 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0
    return f"{hour:02d}:{minute}:00"


def _get_active_pending(db: Session) -> PendingReminder | None:
    """The one live clarification, if any and not stale.

    A stale row (older than `reminder_clarification_ttl_minutes`) is dropped
    silently - the user has moved on, and treating a much later, unrelated
    note as the answer to a forgotten question would create a wrong
    reminder, which is worse than creating none.
    """
    pending = db.execute(
        select(PendingReminder).order_by(PendingReminder.created_at.desc())
    ).scalars().first()
    if pending is None:
        return None

    ttl = get_settings().reminder_clarification_ttl_minutes
    if datetime.now() - pending.created_at.replace(tzinfo=None) > timedelta(minutes=ttl):
        db.delete(pending)
        db.flush()
        return None
    return pending


def _create_reminder(
    db: Session, *, title: str, date_iso: str, time_iso: str, kind: str = "event"
) -> ClarificationResult:
    due_at = _combine(date_iso, time_iso)
    if due_at is None:
        # Should not happen given the callers below, but a reminder is never
        # worth creating with a guessed time.
        return ClarificationResult(spoken=None)

    service = ReminderService(db)
    service.create(
        title=title,
        due_at=due_at,
        # No note_id: the note that carried this mention (or its last
        # answer) is deleted right after this call returns - see
        # `suppress_clarification_note` below - and `Note.reminders` cascades
        # "all, delete-orphan", so a reminder linked to that note would be
        # deleted right along with it. Leaving it note-less is what lets the
        # note disappear while the reminder it produced stays. It also means
        # a stray, undated reminder `create_reminders_safe` (the old
        # task+date pathway) may already have linked to this same note gets
        # cascade-deleted for free when that note is suppressed, instead of
        # sitting alongside the dated one this call just created.
        note_id=None,
        source=ReminderSource.DETECTED.value,
        confidence=0.9,
        detected_phrase=title,
    )

    if kind == "todo":
        # `title` is already a verb phrase ("Submit my assignment"), so it
        # reads naturally on its own - "You have a submit my assignment..."
        # (the event phrasing below) would not.
        spoken = f"Reminder set. {title} {speak_datetime(due_at)}."
    else:
        article = "an" if title[:1].lower() in "aeiou" else "a"
        spoken = f"Reminder set. You have {article} {title.lower()} {speak_datetime(due_at)}."
    return ClarificationResult(spoken=spoken, reminder_created=True)


def _finalize_pending(
    db: Session, pending: PendingReminder, *, date_iso: str, time_iso: str
) -> ClarificationResult:
    kind, _stage = _kind_and_stage(pending.stage)
    result = _create_reminder(
        db, title=pending.title, date_iso=date_iso, time_iso=time_iso, kind=kind
    )
    db.delete(pending)
    db.flush()
    return result


def _handle_pending_answer(db: Session, pending: PendingReminder, note: Note) -> ClarificationResult:
    # Stages, in the order a fully-blank "I have a meeting" (or "todo_" +
    # the same names, for a plain task with no date - see the module
    # docstring's "Plain todos" paragraph) walks through them - each asks
    # only for what is still actually missing. Date is always asked before
    # time, per spec:
    #   need_date                date is missing (time may or may not be known)
    #   need_time                time is missing; the known date is already
    #                            settled, so nothing more to ask after it
    #   need_date_then_meridiem  a time is already known but ambiguous, and
    #                            the date is missing - once the date answer
    #                            comes in, only "AM or PM?" is left
    #   need_meridiem            only the AM/PM question is left
    kind, stage = _kind_and_stage(pending.stage)
    title = pending.title

    if stage == "need_date":
        date_iso, _phrase = _resolved_date_from_note(db, note.id)
        if date_iso is None:
            return ClarificationResult(
                spoken=f"Sorry, I didn't catch a date. {_ask_date(kind, title)}"
            )

        if pending.time_iso:
            # A time was already known (and unambiguous - an ambiguous one
            # would have parked this row in need_date_then_meridiem instead)
            # when this stage started, so the date is all that was missing.
            return _finalize_pending(db, pending, date_iso=date_iso, time_iso=pending.time_iso)

        pending.date_iso = date_iso
        pending.note_id = note.id
        pending.stage = _stage_name("need_time", kind)
        db.flush()
        return ClarificationResult(spoken=_ask_time(kind, title))

    if stage == "need_time":
        time_iso, time_phrase = _resolved_time_from_note(db, note.id)
        if time_iso is None:
            return ClarificationResult(
                spoken=f"Sorry, I didn't catch a time. {_ask_time(kind, title)}"
            )

        if time_is_ambiguous(time_phrase):
            pending.time_iso = time_iso
            pending.note_id = note.id
            pending.stage = _stage_name("need_meridiem", kind)
            db.flush()
            return ClarificationResult(spoken=_ask_meridiem())

        # The date is always already known by the time this stage runs -
        # either it came with the original mention, or need_date just set it.
        return _finalize_pending(db, pending, date_iso=pending.date_iso or "", time_iso=time_iso)

    if stage == "need_date_then_meridiem":
        date_iso, _phrase = _resolved_date_from_note(db, note.id)
        if date_iso is None:
            return ClarificationResult(
                spoken=f"Sorry, I didn't catch a date. {_ask_date(kind, title)}"
            )
        pending.date_iso = date_iso
        pending.note_id = note.id
        pending.stage = _stage_name("need_meridiem", kind)
        db.flush()
        return ClarificationResult(spoken=_ask_meridiem())

    if stage == "need_meridiem":
        meridiem = _parse_meridiem_answer(note.cleaned_text or note.raw_transcript or "")
        if meridiem is None:
            return ClarificationResult(spoken=f"Sorry, I didn't catch that. {_ask_meridiem()}")
        resolved_time_iso = _apply_meridiem(pending.time_iso or "00:00:00", meridiem)
        return _finalize_pending(
            db, pending, date_iso=pending.date_iso or "", time_iso=resolved_time_iso
        )

    # Unknown stage: defensive only, never expected.
    db.delete(pending)
    db.flush()
    return ClarificationResult(spoken=None)


def _handle_new_mention(
    db: Session, note: Note, title: str, kind: str = "event"
) -> ClarificationResult:
    date_iso, _date_phrase = _resolved_date_from_note(db, note.id)
    time_iso, time_phrase = _resolved_time_from_note(db, note.id)
    ambiguous = time_iso is not None and time_is_ambiguous(time_phrase)

    if date_iso and time_iso and not ambiguous:
        return _create_reminder(db, title=title, date_iso=date_iso, time_iso=time_iso, kind=kind)

    if date_iso and time_iso and ambiguous:
        db.add(
            PendingReminder(
                title=title,
                date_iso=date_iso,
                time_iso=time_iso,
                stage=_stage_name("need_meridiem", kind),
                note_id=note.id,
            )
        )
        db.flush()
        return ClarificationResult(spoken=_ask_meridiem())

    if time_iso and not date_iso:
        # The date is what's missing here - always asked before time - but
        # an already-known, still-ambiguous time means one more question
        # (AM or PM?) is still owed once that date comes in.
        db.add(
            PendingReminder(
                title=title,
                date_iso=None,
                time_iso=time_iso,
                stage=_stage_name(
                    "need_date_then_meridiem" if ambiguous else "need_date", kind
                ),
                note_id=note.id,
            )
        )
        db.flush()
        return ClarificationResult(spoken=_ask_date(kind, title))

    if date_iso and not time_iso:
        db.add(
            PendingReminder(
                title=title,
                date_iso=date_iso,
                time_iso=None,
                stage=_stage_name("need_time", kind),
                note_id=note.id,
            )
        )
        db.flush()
        return ClarificationResult(spoken=_ask_time(kind, title))

    # Neither known: date first, per spec.
    db.add(
        PendingReminder(
            title=title,
            date_iso=None,
            time_iso=None,
            stage=_stage_name("need_date", kind),
            note_id=note.id,
        )
    )
    db.flush()
    return ClarificationResult(spoken=_ask_date(kind, title))


def handle_reminder_clarification(db: Session, note: Note) -> ClarificationResult:
    """Advance the event-mention reminder state machine for one captured note.

    Called after a note's entities are already stored (so date/time entities
    for `note` itself can be read back), before the caller commits. Returns
    what to say, if anything - the caller decides how to speak it.
    """
    pending = _get_active_pending(db)
    if pending is not None:
        return _handle_pending_answer(db, pending, note)

    title = detect_event_mention(note.cleaned_text or note.raw_transcript or "")
    if title is not None:
        return _handle_new_mention(db, note, title, kind="event")

    task_title = detect_task_mention(db, note.id)
    if task_title is not None:
        date_iso, _phrase = _resolved_date_from_note(db, note.id)
        if date_iso is None:
            # No date at all - `detect_reminders` (app/reminders/service.py)
            # cannot make a reminder from a task with nothing to pair it to,
            # so this note would otherwise sit in the Notes list forever.
            # Same follow-up machinery as an event mention, generic wording.
            return _handle_new_mention(db, note, task_title, kind="todo")
        # Already has a date: `create_reminders_safe` (called earlier in the
        # capture pipeline, before this function runs) already turned this
        # into a reminder. Nothing more for this pathway to do - asking a
        # redundant question here would just be annoying.
        return ClarificationResult(spoken=None)

    return ClarificationResult(spoken=None)


def handle_reminder_clarification_safe(db: Session, note: Note) -> ClarificationResult:
    """Same contract as `create_reminders_safe`: never raises, never loses a
    note. A capture that already succeeded must not fail because this,
    additive, feature hit an edge case."""
    try:
        return handle_reminder_clarification(db, note)
    except Exception:
        logger.exception("reminder clarification failed for note %s; note kept", note.id)
        return ClarificationResult(spoken=None)


def suppress_clarification_note(db: Session, note: Note) -> None:
    """Delete `note` after a `ClarificationResult` with `spoken is not None`.

    This module's whole job is to keep an event mention ("I have a
    meeting...") and its follow-up answers ("5:20 p.m.", "13th September",
    "PM") out of the ordinary Notes list - they are not notes, they are one
    side of a question-and-answer exchange whose only real output is a
    Reminder (or, mid-exchange, the next spoken question). Call this from the
    capture endpoint right after `handle_reminder_clarification_safe` returns
    a non-None `spoken`, and build the `CaptureResponse` *before* calling
    it - `note`'s ORM attributes are unusable once its row is gone.

    Never called for a `ClarificationResult(spoken=None)`: that is this
    module's way of saying "this note was none of my business", and an
    ordinary note is always kept.

    Safe to call unconditionally once that check has passed: `_create_reminder`
    above never links a reminder to a note, so this can never cascade-delete
    the very reminder the note's mention or answer just produced. It *can*
    (via `Note.reminders`' "all, delete-orphan" cascade) delete a stray,
    undated reminder `create_reminders_safe` linked to this same note earlier
    in the same request - see the note_id comment on `_create_reminder`
    above - which is the intended cleanup, not a bug.
    """
    from app.db.repositories import NoteRepository
    from app.rag.indexer import remove_note

    if NoteRepository(db).delete(note.id):
        remove_note(note.id)
