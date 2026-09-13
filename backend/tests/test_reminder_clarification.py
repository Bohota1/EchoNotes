"""Event-mention reminders and follow-up questions (app/reminders/clarify.py).

Mirrors the style of tests/test_voice_query.py's TestReminderApi: `make_note`
runs a note through the same understanding pipeline a real capture does, so
these tests see exactly what entities `handle_reminder_clarification_safe`
would see in production.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.db.models import PendingReminder
from app.reminders.clarify import handle_reminder_clarification_safe, suppress_clarification_note
from app.reminders.service import ReminderService


@pytest.fixture
def fake_recorder(monkeypatch, fixture_wav):
    """Same fake as tests/test_live_recording.py, for the /capture/stop tests
    below - kept local so this file does not depend on import order."""
    from app.capture import live
    from app.capture.sources import DummyCaptureSource
    from app.core.errors import AudioCaptureError

    class FakeRecorder:
        def __init__(self):
            self.recording = False

        def start(self):
            if self.recording:
                raise AudioCaptureError("a recording is already in progress")
            self.recording = True
            return "fake-capture"

        def stop(self):
            if not self.recording:
                raise AudioCaptureError("no recording is in progress")
            self.recording = False
            return DummyCaptureSource(fixture_wav).capture()

        def cancel(self):
            self.recording = False

        def state(self):
            return {
                "recording": self.recording,
                "capture_id": "fake-capture" if self.recording else None,
                "elapsed_seconds": 1.0 if self.recording else 0.0,
                "max_seconds": 300,
                "hit_limit": False,
            }

    recorder = FakeRecorder()
    monkeypatch.setattr(live, "get_live_recorder", lambda: recorder)
    return recorder


class TestCompleteEventMention:
    def test_date_and_time_together_creates_a_reminder_immediately(
        self, make_note, db_session
    ):
        note = make_note("I have a meeting at 3:30 am on 13 September.")
        result = handle_reminder_clarification_safe(db_session, note)
        db_session.commit()

        assert result.reminder_created
        assert result.spoken and "meeting" in result.spoken.lower()

        reminders = ReminderService(db_session).list()
        assert len(reminders) == 1
        assert reminders[0].due_at.hour == 3
        assert reminders[0].due_at.minute == 30
        assert reminders[0].due_at.month == 9
        assert reminders[0].due_at.day == 13
        assert reminders[0].title == "Meeting"

        # No dangling question left behind.
        assert db_session.execute(select(PendingReminder)).scalars().all() == []

    def test_the_word_reminder_itself_is_recognised_as_an_event_mention(
        self, make_note, db_session
    ):
        """People naturally say "I have a reminder..." for this feature, not
        just "meeting" - this must trigger the same flow, not fall through to
        an ordinary note with no follow-up question."""
        note = make_note("I have a reminder at 3:30 am on 13 September.")
        result = handle_reminder_clarification_safe(db_session, note)
        db_session.commit()

        assert result.reminder_created
        reminders = ReminderService(db_session).list()
        assert len(reminders) == 1
        assert reminders[0].title == "Reminder"


class TestTodaysDateIsNotPushedAYearAhead:
    """Regression test: dateparser resolves a bare "13 September" against
    midnight of the reference day, which is already in the past by any time
    of day after midnight - so naming *today's own date* ("I have a meeting
    ... on 13 September", said on 13 September) was silently saved a full
    year in the future instead of today, and so never showed up as due soon
    or in the reminders list."""

    def test_a_meeting_named_for_todays_own_date_is_saved_as_today(
        self, make_note, db_session
    ):
        today = datetime.now()
        note = make_note(
            f"I have a meeting on {today:%d %B} at 3:30 am."
        )
        result = handle_reminder_clarification_safe(db_session, note)
        db_session.commit()

        assert result.reminder_created, result.spoken
        reminders = ReminderService(db_session).list()
        assert len(reminders) == 1
        assert reminders[0].due_at.date() == today.date()


class TestDotSeparatedTime:
    """Regression test: "4.10 p.m." (a dot, not a colon, between hour and
    minute) was silently treated as having no time at all, so a fully
    complete meeting mention like this one wrongly asked "When is your
    meeting?" instead of saving immediately."""

    def test_a_dot_separated_time_is_recognised(self, make_note, db_session):
        note = make_note("I have a meeting on 13th September at 4.10 p.m.")
        result = handle_reminder_clarification_safe(db_session, note)
        db_session.commit()

        assert result.reminder_created, result.spoken
        reminders = ReminderService(db_session).list()
        assert len(reminders) == 1
        assert reminders[0].due_at.hour == 16
        assert reminders[0].due_at.minute == 10
        assert reminders[0].due_at.month == 9
        assert reminders[0].due_at.day == 13


class TestMissingTimeOnly:
    def test_asks_for_time_then_saves_on_the_next_note(self, make_note, db_session):
        note1 = make_note("I have a meeting tomorrow.")
        result1 = handle_reminder_clarification_safe(db_session, note1)
        db_session.commit()

        assert not result1.reminder_created
        assert result1.spoken == "When is your meeting?"
        assert ReminderService(db_session).list() == []

        note2 = make_note("3:30 am")
        result2 = handle_reminder_clarification_safe(db_session, note2)
        db_session.commit()

        assert result2.reminder_created
        reminders = ReminderService(db_session).list()
        assert len(reminders) == 1
        assert reminders[0].due_at.hour == 3
        assert reminders[0].due_at.minute == 30


class TestMissingBoth:
    def test_asks_date_first_then_time_per_spec(self, make_note, db_session):
        note1 = make_note("I have a meeting.")
        result1 = handle_reminder_clarification_safe(db_session, note1)
        db_session.commit()
        assert result1.spoken == "Which date do you have the meeting?"
        assert not result1.reminder_created

        note2 = make_note("13 September")
        result2 = handle_reminder_clarification_safe(db_session, note2)
        db_session.commit()
        assert result2.spoken == "When is your meeting?"
        assert not result2.reminder_created

        note3 = make_note("3:30 pm")
        result3 = handle_reminder_clarification_safe(db_session, note3)
        db_session.commit()
        assert result3.reminder_created

        reminders = ReminderService(db_session).list()
        assert len(reminders) == 1
        assert reminders[0].due_at.hour == 15
        assert reminders[0].due_at.minute == 30
        assert reminders[0].due_at.month == 9
        assert reminders[0].due_at.day == 13


class TestAmbiguousTimeAsksMeridiem:
    """A time with no am/pm ("3:30", "three o'clock") is not guessed at - it
    is treated like a still-missing piece of information, one more question
    ("Is it AM or PM?") rather than a coin flip that could fire the alert
    twelve hours off."""

    def test_full_walkthrough_date_then_time_then_meridiem(self, make_note, db_session):
        """Mirrors the exact walkthrough asked for: date question, time
        question, and only then - because the time answer never said am or
        pm - the meridiem question, before anything is saved."""
        note1 = make_note("I have a meeting.")
        result1 = handle_reminder_clarification_safe(db_session, note1)
        db_session.commit()
        assert result1.spoken == "Which date do you have the meeting?"
        assert not result1.reminder_created

        note2 = make_note("13 September")
        result2 = handle_reminder_clarification_safe(db_session, note2)
        db_session.commit()
        assert result2.spoken == "When is your meeting?"
        assert not result2.reminder_created

        note3 = make_note("3:30")
        result3 = handle_reminder_clarification_safe(db_session, note3)
        db_session.commit()
        assert result3.spoken == "Is it AM or PM?"
        assert not result3.reminder_created

        note4 = make_note("PM")
        result4 = handle_reminder_clarification_safe(db_session, note4)
        db_session.commit()
        assert result4.reminder_created

        reminders = ReminderService(db_session).list()
        assert len(reminders) == 1
        assert reminders[0].due_at.hour == 15
        assert reminders[0].due_at.minute == 30
        assert reminders[0].due_at.month == 9
        assert reminders[0].due_at.day == 13
        assert db_session.execute(select(PendingReminder)).scalars().all() == []

    def test_ambiguous_time_with_date_already_known_skips_straight_to_meridiem(
        self, make_note, db_session
    ):
        note1 = make_note("I have a meeting tomorrow at 3:30.")
        result1 = handle_reminder_clarification_safe(db_session, note1)
        db_session.commit()
        assert result1.spoken == "Is it AM or PM?"
        assert not result1.reminder_created

        note2 = make_note("It's in the morning.")
        result2 = handle_reminder_clarification_safe(db_session, note2)
        db_session.commit()
        assert result2.reminder_created
        reminders = ReminderService(db_session).list()
        assert reminders[0].due_at.hour == 3
        assert reminders[0].due_at.minute == 30

    def test_oclock_is_treated_as_ambiguous_not_unparseable(self, make_note, db_session):
        note1 = make_note("I have a meeting tomorrow at 3 o'clock.")
        result1 = handle_reminder_clarification_safe(db_session, note1)
        db_session.commit()
        assert result1.spoken == "Is it AM or PM?"

        note2 = make_note("In the evening.")
        result2 = handle_reminder_clarification_safe(db_session, note2)
        db_session.commit()
        assert result2.reminder_created
        reminders = ReminderService(db_session).list()
        assert reminders[0].due_at.hour == 15
        assert reminders[0].due_at.minute == 0

    def test_an_unrecognised_meridiem_answer_reasks(self, make_note, db_session):
        note1 = make_note("I have a meeting tomorrow at 3:30.")
        handle_reminder_clarification_safe(db_session, note1)
        db_session.commit()

        note2 = make_note("Not sure yet.")
        result2 = handle_reminder_clarification_safe(db_session, note2)
        db_session.commit()
        assert result2.spoken == "Sorry, I didn't catch that. Is it AM or PM?"
        assert not result2.reminder_created
        assert ReminderService(db_session).list() == []

    def test_an_explicit_24_hour_time_is_never_treated_as_ambiguous(self, make_note, db_session):
        """"15:30" can only mean 3:30 pm - there is no "15 pm" - so this must
        save immediately, exactly like the pre-existing explicit-meridiem
        behaviour, with no extra question."""
        note = make_note("I have a meeting on 13 September at 15:30.")
        result = handle_reminder_clarification_safe(db_session, note)
        db_session.commit()

        assert result.reminder_created, result.spoken
        reminders = ReminderService(db_session).list()
        assert reminders[0].due_at.hour == 15
        assert reminders[0].due_at.minute == 30


class TestUnparseableAnswerReasks:
    def test_reasks_the_same_question_when_the_answer_has_no_time(
        self, make_note, db_session
    ):
        note1 = make_note("I have a meeting tomorrow.")
        handle_reminder_clarification_safe(db_session, note1)
        db_session.commit()

        # No task cue, no date, no time - a phrase the old task/deadline
        # detector has no opinion on either, so only this module's re-ask
        # behaviour is under test here.
        note2 = make_note("The weather is quite nice.")
        result2 = handle_reminder_clarification_safe(db_session, note2)
        db_session.commit()

        assert result2.spoken == "Sorry, I didn't catch a time. When is your meeting?"
        assert not result2.reminder_created
        assert ReminderService(db_session).list() == []


class TestStaleClarificationExpires:
    def test_an_old_unanswered_question_is_dropped_and_ignored(
        self, make_note, db_session
    ):
        note1 = make_note("I have a meeting tomorrow.")
        handle_reminder_clarification_safe(db_session, note1)
        db_session.commit()

        pending = db_session.execute(select(PendingReminder)).scalars().one()
        pending.created_at = datetime.now() - timedelta(minutes=61)
        db_session.commit()

        # Not "Buy milk and eggs." - that now carries its own task entity
        # (see TestPlainTodosGetFollowUps below) and would legitimately start
        # a *new* clarification of its own, which is not what this test is
        # checking. This note has no task and no event mention, so it must
        # come back as an ordinary, untouched note either way.
        note2 = make_note("The lecture covered photosynthesis.")
        result = handle_reminder_clarification_safe(db_session, note2)
        db_session.commit()

        assert result.spoken is None
        assert db_session.execute(select(PendingReminder)).scalars().all() == []


class TestPendingReminderClockIsLocal:
    """Regression test for a timezone bug: `PendingReminder.created_at` used
    to default to UTC-aware `_utcnow()` while `_get_active_pending()`'s
    staleness check (app/reminders/clarify.py) compares it against naive
    **local** `datetime.now()`. On any machine whose local clock isn't UTC,
    that mismatch made every freshly-created row look hours old and get
    dropped as "stale" almost immediately - so the very next answer (e.g. a
    bare date, with no event-cue word for `detect_event_mention` to catch)
    found no pending row and was saved as an ordinary note instead of the
    conversation continuing. See the comment on `PendingReminder.created_at`
    in app/db/models.py.
    """

    def test_created_at_default_is_naive_local_not_utc(self, db_session):
        # A freshly inserted row's `created_at` must land on the same clock
        # `_get_active_pending` compares it against: naive local time (no
        # tzinfo), and within a few seconds of `datetime.now()` right now.
        # The UTC-aware `_utcnow` this used to default to would also have no
        # tzinfo by the time `_get_active_pending` strips it - but its clock
        # reading would be offset from local time by the machine's UTC
        # offset, which is exactly what this guards against.
        before = datetime.now()
        row = PendingReminder(title="t", stage="need_date")
        db_session.add(row)
        db_session.flush()

        assert row.created_at.tzinfo is None
        assert abs((row.created_at - before).total_seconds()) < 5

    def test_a_freshly_asked_question_is_never_treated_as_stale(
        self, make_note, db_session
    ):
        # End-to-end: ask a question, then immediately answer it. Regardless
        # of the machine's timezone, a row created moments ago must still be
        # "active" - this is the exact scenario ("I have a meeting." ->
        # "14 September") the user reported breaking.
        note1 = make_note("I have a meeting.")
        first = handle_reminder_clarification_safe(db_session, note1)
        db_session.commit()
        assert first.spoken == "Which date do you have the meeting?"

        note2 = make_note("14 September.")
        second = handle_reminder_clarification_safe(db_session, note2)
        db_session.commit()
        assert second.spoken == "When is your meeting?"


def _capture_and_clarify(db_session, make_note, text: str):
    """Run one capture through clarification the way the real capture
    endpoint does (app/api/v1/capture.py): suppress the note whenever there
    was something to say.

    The tests above this point never needed this - an event mention never
    also trips `create_reminders_safe` (the old task+date pathway), since it
    has no task verb for that pathway to find. A plain todo's task entity
    *is* something that pathway sees, so it may leave a stray, undated draft
    reminder linked to the note; only suppressing the note (as production
    always does the instant this module has something to say) cleans that
    draft up via `Note.reminders`' cascade - see `_create_reminder`'s
    `note_id` comment in app/reminders/clarify.py. Skipping suppression here
    would make a unit test see an artifact real usage never does.
    """
    note = make_note(text)
    result = handle_reminder_clarification_safe(db_session, note)
    if result.spoken is not None:
        suppress_clarification_note(db_session, note)
    db_session.commit()
    return result


class TestPlainTodosGetFollowUps:
    """A plain task with no date ("I have to submit my assignment.") used to
    sit in the Notes list forever - `detect_reminders` needs a task *and* a
    date to pair, so a bare task never became a reminder. This is the same
    follow-up machinery as an event mention, just triggered by a task entity
    instead of a cue word like "meeting", and with generic wording."""

    def test_a_bare_task_asks_date_then_time_then_saves(self, make_note, db_session):
        result1 = _capture_and_clarify(db_session, make_note, "I have to submit my assignment.")
        assert result1.spoken == "What date do you need to submit my assignment?"
        assert not result1.reminder_created

        result2 = _capture_and_clarify(db_session, make_note, "14 September")
        assert result2.spoken == "What time do you need to submit my assignment?"
        assert not result2.reminder_created

        result3 = _capture_and_clarify(db_session, make_note, "6:30 pm")
        assert result3.reminder_created
        assert result3.spoken == "Reminder set. Submit my assignment tomorrow at 6:30 pm."

        reminders = ReminderService(db_session).list()
        assert len(reminders) == 1
        assert reminders[0].title == "Submit my assignment"
        assert reminders[0].due_at.month == 9
        assert reminders[0].due_at.day == 14
        assert reminders[0].due_at.hour == 18
        assert reminders[0].due_at.minute == 30
        assert db_session.execute(select(PendingReminder)).scalars().all() == []

    def test_a_second_bare_task_with_a_different_verb_also_gets_asked(
        self, make_note, db_session
    ):
        """Not just "submit" - any task cue (`TASK_CUES`/`TASK_VERBS` in
        entities.py) with no date must get the same treatment."""
        result1 = _capture_and_clarify(db_session, make_note, "I have to pay my electricity bill.")
        assert result1.spoken == "What date do you need to pay my electricity bill?"

        result2 = _capture_and_clarify(db_session, make_note, "20 September")
        assert result2.spoken == "What time do you need to pay my electricity bill?"

        result3 = _capture_and_clarify(db_session, make_note, "5 pm")
        assert result3.reminder_created

        reminders = ReminderService(db_session).list()
        assert len(reminders) == 1
        assert reminders[0].title == "Pay my electricity bill"
        assert reminders[0].due_at.day == 20
        assert reminders[0].due_at.hour == 17

    def test_a_stray_undated_reminder_from_the_old_pathway_does_not_survive(
        self, make_note, db_session
    ):
        """`create_reminders_safe` (the old task+date pathway, run earlier in
        the capture pipeline) auto-creates an undated draft reminder for any
        confident task, date or not. Once this module decides to ask a
        follow-up question, the *capture endpoint* deletes the note (see
        `_capture_and_clarify` above) - and that draft reminder is still
        linked to the note (`note_id` is only cleared for reminders *this*
        module creates, see `_create_reminder`), so it must vanish with it
        via `Note.reminders`' cascade, never lingering alongside the
        correctly-dated reminder created once the follow-up completes."""
        _capture_and_clarify(db_session, make_note, "I have to submit my assignment.")
        # The old pathway's undated draft must be gone - the note it was
        # linked to was just suppressed.
        assert ReminderService(db_session).list() == []

        _capture_and_clarify(db_session, make_note, "14 September")
        _capture_and_clarify(db_session, make_note, "6:30 pm")

        # Exactly one reminder at the end - not the stray undated one plus
        # the correctly-dated one.
        assert len(ReminderService(db_session).list()) == 1

    def test_a_task_that_already_has_a_date_is_left_to_the_old_pathway(
        self, make_note, db_session
    ):
        """A todo that already names a date - "submit the report by Friday" -
        must not be interrupted with a question: `detect_reminders` already
        makes it a reminder immediately, same as before this feature existed."""
        note = make_note("I need to submit the report by Friday.")
        result = handle_reminder_clarification_safe(db_session, note)
        db_session.commit()

        assert result.spoken is None
        assert not result.reminder_created
        assert ReminderService(db_session).list_for_note(note.id)

    def test_a_task_with_only_a_time_is_asked_for_the_date_first(
        self, make_note, db_session
    ):
        """Mirrors the event-mention rule: date is always asked before time,
        even when the time is the half that was already given."""
        result1 = _capture_and_clarify(db_session, make_note, "I have to call the bank at 5 pm.")
        assert result1.spoken == "What date do you need to call the bank at 5 pm?"

        result2 = _capture_and_clarify(db_session, make_note, "20 September")
        assert result2.reminder_created

        reminders = ReminderService(db_session).list()
        assert len(reminders) == 1
        assert reminders[0].due_at.day == 20
        assert reminders[0].due_at.hour == 17


class TestOrdinaryNotesAreUntouched:
    def test_a_task_and_deadline_note_still_goes_through_the_old_pathway_only(
        self, make_note, db_session, sample_text
    ):
        note = make_note(sample_text)
        result = handle_reminder_clarification_safe(db_session, note)
        db_session.commit()

        # This feature has nothing to say about a note with no event mention.
        assert result.spoken is None
        assert not result.reminder_created

        # The existing task+deadline detection must still have fired for it,
        # completely unaffected by this module running afterwards.
        assert ReminderService(db_session).list_for_note(note.id)

    def test_a_note_that_merely_mentions_a_meeting_in_passing_is_not_a_reminder(
        self, make_note, db_session
    ):
        note = make_note("The meeting notes said the database project is on track.")
        result = handle_reminder_clarification_safe(db_session, note)
        db_session.commit()

        assert result.spoken is None
        assert not result.reminder_created


class TestDueSoonVoiceAlert:
    def test_a_reminder_inside_the_lead_window_is_announced_exactly_once(
        self, db_session
    ):
        service = ReminderService(db_session)
        reminder = service.create(
            title="Meeting", due_at=datetime.now() + timedelta(minutes=30)
        )
        db_session.commit()

        first = service.due_soon(lead_minutes=60)
        db_session.commit()
        assert [r.id for r in first] == [reminder.id]

        second = service.due_soon(lead_minutes=60)
        db_session.commit()
        assert second == []

    def test_a_reminder_outside_the_lead_window_is_not_yet_announced(self, db_session):
        service = ReminderService(db_session)
        service.create(title="Meeting", due_at=datetime.now() + timedelta(hours=5))
        db_session.commit()

        assert service.due_soon(lead_minutes=60) == []

    def test_an_overdue_unannounced_reminder_is_still_spoken_once(self, db_session):
        service = ReminderService(db_session)
        reminder = service.create(
            title="Meeting", due_at=datetime.now() - timedelta(minutes=5)
        )
        db_session.commit()

        due = service.due_soon(lead_minutes=60)
        db_session.commit()
        assert [r.id for r in due] == [reminder.id]


class TestCaptureEndpointWiring:
    """End to end through the actual API, exercising the exact hook points
    added in app/api/v1/capture.py (trigger and stop_recording)."""

    def test_trigger_returns_a_reminder_prompt_for_an_event_mention(
        self, client, fake_transcriber
    ):
        fake_transcriber.text = "I have a meeting at 3:30 am on 13 September."
        response = client.post("/api/v1/trigger", json={})
        assert response.status_code == 201
        body = response.json()
        assert body["reminder_prompt"]
        assert "meeting" in body["reminder_prompt"].lower()

    def test_trigger_omits_reminder_prompt_for_an_ordinary_note(
        self, client, fake_transcriber, sample_text
    ):
        fake_transcriber.text = sample_text
        response = client.post("/api/v1/trigger", json={})
        assert response.status_code == 201
        assert response.json()["reminder_prompt"] is None

    def test_stop_recording_asks_then_saves_across_two_captures(
        self, client, fake_recorder, fake_transcriber
    ):
        fake_transcriber.text = "I have a meeting tomorrow."
        client.post("/api/v1/capture/start")
        first = client.post("/api/v1/capture/stop")
        assert first.status_code == 201
        assert first.json()["reminder_prompt"] == "When is your meeting?"

        fake_transcriber.text = "3:30 am"
        client.post("/api/v1/capture/start")
        second = client.post("/api/v1/capture/stop")
        assert second.status_code == 201
        prompt = second.json()["reminder_prompt"]
        assert prompt and "meeting" in prompt.lower()

        reminders = client.get("/api/v1/reminders").json()["reminders"]
        assert any(r["title"] == "Meeting" for r in reminders)

    def test_a_complete_mention_is_never_saved_as_a_note(self, client, fake_transcriber):
        """Only the reminder should exist afterwards - not a note carrying
        the same sentence."""
        fake_transcriber.text = "I have a meeting at 3:30 am on 13 September."
        response = client.post("/api/v1/trigger", json={})
        assert response.status_code == 201
        assert response.json()["reminder_prompt"]

        assert client.get("/api/v1/notes").json() == []
        reminders = client.get("/api/v1/reminders").json()["reminders"]
        assert any(r["title"] == "Meeting" for r in reminders)

    def test_a_whole_answer_chain_leaves_no_notes_behind(self, client, fake_recorder, fake_transcriber):
        """The mention and every one of its answers - the fragments a person
        would never want cluttering their notes ("3:30", "13 September",
        "PM") - must all be gone once the reminder is saved, not just the
        ones that individually looked incomplete."""
        for text in ("I have a meeting.", "13 September", "3:30", "PM"):
            fake_transcriber.text = text
            client.post("/api/v1/capture/start")
            response = client.post("/api/v1/capture/stop")
            assert response.status_code == 201

        assert client.get("/api/v1/notes").json() == []
        reminders = client.get("/api/v1/reminders").json()["reminders"]
        assert any(r["title"] == "Meeting" for r in reminders)

    def test_an_ordinary_note_is_still_kept(self, client, fake_transcriber, sample_text):
        """Regression check: suppression must only ever fire for a note this
        module actually spoke about - everything else is saved exactly as it
        always was."""
        fake_transcriber.text = sample_text
        response = client.post("/api/v1/trigger", json={})
        assert response.status_code == 201
        assert response.json()["reminder_prompt"] is None

        assert len(client.get("/api/v1/notes").json()) == 1

    def test_a_bare_todo_asks_then_saves_through_the_real_endpoint(
        self, client, fake_recorder, fake_transcriber
    ):
        """Same walkthrough as test_stop_recording_asks_then_saves_across_two_captures
        above, but for a plain task with no event cue word at all - the exact
        gap this feature closes."""
        fake_transcriber.text = "I have to submit my assignment."
        client.post("/api/v1/capture/start")
        first = client.post("/api/v1/capture/stop")
        assert first.status_code == 201
        assert first.json()["reminder_prompt"] == "What date do you need to submit my assignment?"

        fake_transcriber.text = "14 September"
        client.post("/api/v1/capture/start")
        second = client.post("/api/v1/capture/stop")
        assert second.json()["reminder_prompt"] == "What time do you need to submit my assignment?"

        fake_transcriber.text = "6:30 pm"
        client.post("/api/v1/capture/start")
        third = client.post("/api/v1/capture/stop")
        assert third.json()["reminder_prompt"]

        # Neither the mention nor either answer left a note behind - same
        # guarantee the meeting flow already has.
        assert client.get("/api/v1/notes").json() == []
        reminders = client.get("/api/v1/reminders").json()["reminders"]
        assert any(r["title"] == "Submit my assignment" for r in reminders)
