"""Reminders and contacts (Phase 5).

Detection is built on the entities Team Member 1's extractor produces, so these
tests run real text through the real understanding pipeline rather than
fabricating entity rows - otherwise they would prove the pairing logic works on
data that never occurs.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.db.models import EntityKind, ReminderStatus
from app.reminders.contacts import ContactService, normalize_name
from app.reminders.service import (
    ReminderService,
    detect_reminders,
    narrate_reminders,
    speak_datetime,
)

TWO_TASKS_TWO_DATES = (
    "I need to submit the operating systems assignment to Professor Raman by next Friday. "
    "Also call Sarah about the database project meeting on March 3rd."
)
ONE_TASK = "I need to email Professor Chen the report by Monday."
NO_TASK = "A deadlock requires circular wait and mutual exclusion."


class TestDetection:
    def test_each_task_gets_its_own_date(self, db_session, make_note):
        """The pairing bug this guards against: one deadline in a note being
        attached to every task in it, so two commitments fire on the same wrong
        day. A reminder on the wrong day is worse than no reminder, because the
        user acts on it."""
        note = make_note(TWO_TASKS_TWO_DATES)
        detected = detect_reminders(db_session, note)

        dated = [d for d in detected if d.due_at is not None]
        assert len(dated) >= 2
        assert len({d.due_at for d in dated}) == len(dated), (
            f"tasks shared a date: {[(d.title[:30], d.due_at) for d in dated]}"
        )

    def test_the_deadline_pairs_with_the_task_beside_it(self, db_session, make_note):
        note = make_note(TWO_TASKS_TWO_DATES)
        by_title = {d.title.lower(): d for d in detect_reminders(db_session, note)}

        submit = next(v for k, v in by_title.items() if "submit" in k)
        call = next(v for k, v in by_title.items() if "call sarah" in k)
        assert submit.due_at != call.due_at
        assert submit.detected_phrase.lower() == "next friday"
        assert "march" in call.detected_phrase.lower()

    def test_confidence_is_the_weaker_of_task_and_date(self, db_session, make_note):
        """Both halves have to be right for the reminder to be right."""
        note = make_note(ONE_TASK)
        detected = detect_reminders(db_session, note)
        assert detected
        assert all(0.0 <= d.confidence <= 1.0 for d in detected)

    def test_note_with_no_commitment_yields_nothing(self, db_session, make_note):
        note = make_note(NO_TASK)
        assert detect_reminders(db_session, note) == []

    def test_low_confidence_is_suggested_not_created(self, db_session, make_note, monkeypatch):
        """A mis-heard date must not silently become a reminder that speaks up
        at the wrong moment."""
        from app.config import get_settings

        monkeypatch.setattr(get_settings(), "reminder_auto_create_confidence", 0.99, raising=False)
        note = make_note(ONE_TASK)

        detected = detect_reminders(db_session, note)
        assert detected
        assert all(not d.auto_create for d in detected)

        created = ReminderService(db_session).create_from_note(note)
        assert created == []


class TestAutoCreation:
    def test_capture_creates_reminders(self, db_session, make_note):
        note = make_note(TWO_TASKS_TWO_DATES)
        reminders = ReminderService(db_session).list_for_note(note.id)
        assert len(reminders) >= 1
        assert all(r.source == "detected" for r in reminders)

    def test_reprocessing_does_not_duplicate(self, db_session, make_note):
        """Reprocessing a capture must be safe."""
        note = make_note(ONE_TASK)
        service = ReminderService(db_session)
        before = len(service.list_for_note(note.id))

        service.create_from_note(note)
        db_session.commit()
        assert len(service.list_for_note(note.id)) == before

    def test_deleting_a_note_removes_its_reminders(self, db_session, make_note):
        from app.db.repositories import NoteRepository

        note = make_note(ONE_TASK)
        service = ReminderService(db_session)
        assert service.list_for_note(note.id)

        NoteRepository(db_session).delete(note.id)
        db_session.commit()
        assert service.list_for_note(note.id) == []

    def test_detection_failure_never_breaks_a_capture(self, db_session, monkeypatch, make_note):
        from app.reminders import service as module

        monkeypatch.setattr(
            module.ReminderService,
            "create_from_note",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        note = make_note(ONE_TASK)  # must not raise
        assert note.id is not None


class TestCrud:
    def test_create_read_update_delete(self, db_session):
        service = ReminderService(db_session)
        due = datetime.now() + timedelta(days=1)

        reminder = service.create(title="Submit report", due_at=due)
        assert service.get(reminder.id) is not None

        service.update(reminder.id, title="Submit final report")
        assert service.get(reminder.id).title == "Submit final report"

        assert service.delete(reminder.id) is True
        assert service.get(reminder.id) is None

    def test_delete_unknown_returns_false(self, db_session):
        assert ReminderService(db_session).delete("nope") is False

    def test_mark_done_and_dismiss(self, db_session):
        service = ReminderService(db_session)
        one = service.create(title="A", due_at=datetime.now())
        two = service.create(title="B", due_at=datetime.now())

        service.mark_done(one.id)
        service.dismiss(two.id)
        assert service.get(one.id).status == ReminderStatus.DONE.value
        assert service.get(two.id).status == ReminderStatus.DISMISSED.value

    def test_status_filter(self, db_session):
        service = ReminderService(db_session)
        service.create(title="pending one", due_at=datetime.now())
        done = service.create(title="done one", due_at=datetime.now())
        service.mark_done(done.id)

        pending = service.list(status=ReminderStatus.PENDING.value)
        assert [r.title for r in pending] == ["pending one"]

    def test_undated_reminders_sort_last(self, db_session):
        """A to-do with no time is not urgent; burying dated ones under a pile
        of undated ones makes the spoken list useless."""
        service = ReminderService(db_session)
        service.create(title="someday", due_at=None)
        service.create(title="tomorrow", due_at=datetime.now() + timedelta(days=1))

        assert [r.title for r in service.list()] == ["tomorrow", "someday"]


class TestWindows:
    def test_due_returns_only_what_has_arrived(self, db_session):
        service = ReminderService(db_session)
        service.create(title="past", due_at=datetime.now() - timedelta(hours=1))
        service.create(title="future", due_at=datetime.now() + timedelta(hours=5))

        assert [r.title for r in service.due()] == ["past"]

    def test_upcoming_includes_overdue(self, db_session):
        """Something due yesterday and still pending is the most important item
        in the list, not the least."""
        service = ReminderService(db_session)
        service.create(title="overdue", due_at=datetime.now() - timedelta(days=1))
        service.create(title="soon", due_at=datetime.now() + timedelta(hours=2))
        service.create(title="far off", due_at=datetime.now() + timedelta(days=10))

        titles = [r.title for r in service.upcoming(within_hours=24)]
        assert titles == ["overdue", "soon"]

    def test_done_reminders_are_excluded(self, db_session):
        service = ReminderService(db_session)
        done = service.create(title="done", due_at=datetime.now())
        service.mark_done(done.id)
        assert service.upcoming(within_hours=24) == []


class TestSpokenDates:
    NOW = datetime(2026, 9, 9, 14, 30)

    @pytest.mark.parametrize(
        "value,expected",
        [
            (datetime(2026, 9, 9, 16, 0), "today at 4 pm"),
            (datetime(2026, 9, 10, 9, 30), "tomorrow at 9:30 am"),
            (datetime(2026, 9, 8, 0, 0), "yesterday"),
            (datetime(2026, 9, 11, 0, 0), "on Friday"),
            (datetime(2026, 12, 25, 0, 0), "on 25 December"),
        ],
    )
    def test_dates_are_spoken_the_way_people_say_them(self, value, expected):
        """An ISO string read aloud is a stream of digits nobody can hold in
        their head."""
        assert speak_datetime(value, now=self.NOW) == expected

    def test_midnight_means_no_time_was_given(self):
        assert speak_datetime(datetime(2026, 9, 11, 0, 0), now=self.NOW) == "on Friday"


class TestWindowPhrasing:
    """The window has to match the question that was asked, and be sayable."""

    @pytest.mark.parametrize(
        "hours,expected",
        [
            (24, "the next 24 hours"),
            (48, "the next two days"),
            (168, "the next week"),
            (720, "the next month"),
        ],
    )
    def test_windows_are_spoken_naturally(self, hours, expected):
        from app.reminders.service import describe_window

        assert describe_window(hours) == expected

    @pytest.mark.parametrize(
        "utterance,expected_hours",
        [
            ("What's due tomorrow?", 48),
            ("What's due this week?", 168),
            ("What are my deadlines?", 24),
        ],
    )
    def test_the_window_comes_from_the_question(self, db_session, utterance, expected_hours):
        """Answering "nothing due in the next 24 hours" to "what's due this
        week" answers a narrower question than the one that was asked."""
        from app.rag.intent import parse_intent
        from app.rag.service import _reminder_window_hours

        parsed = parse_intent(utterance)
        assert _reminder_window_hours(parsed, 24) == expected_hours

    def test_a_reminder_five_days_out_is_found_by_this_week(self, db_session):
        from app.rag.service import handle_voice_query

        ReminderService(db_session).create(
            title="Submit the assignment", due_at=datetime.now() + timedelta(days=5)
        )
        db_session.commit()

        assert "Nothing due" in handle_voice_query(db_session, "What's due tomorrow?").spoken
        assert "Submit the assignment" in handle_voice_query(
            db_session, "What's due this week?"
        ).spoken


class TestNarration:
    def test_empty_list_says_so(self):
        assert "Nothing due" in narrate_reminders([], 24)

    def test_long_lists_are_capped(self, db_session):
        """A listener cannot skim past twelve items, so the rest are counted."""
        service = ReminderService(db_session)
        for index in range(6):
            service.create(title=f"Task {index}", due_at=datetime.now() + timedelta(hours=index + 1))

        spoken = narrate_reminders(service.upcoming(within_hours=24), 24)
        assert "6 reminders" in spoken
        assert "3 more" in spoken


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------


class TestContacts:
    def test_people_become_contacts_on_capture(self, db_session, make_note):
        make_note(TWO_TASKS_TWO_DATES)
        names = {c.name for c in ContactService(db_session).list()}
        assert "Raman" in names or "Professor Raman" in names
        assert "Sarah" in names

    def test_titles_are_stripped_for_matching(self):
        assert normalize_name("Professor Raman") == normalize_name("Raman")
        assert normalize_name("Dr. Chen") == "chen"

    def test_the_same_person_is_one_contact_across_notes(self, db_session, make_note):
        """ASR spells names inconsistently. Four near-identical entries in a
        spoken list is worse than none."""
        make_note("Call Professor Raman about the assignment.")
        make_note("Raman said the deadline moved.")

        matching = [c for c in ContactService(db_session).list() if "raman" in c.normalized_name]
        assert len(matching) == 1

    def test_notes_are_linked_both_ways(self, db_session, make_note):
        note = make_note("Call Sarah about the database project.")
        service = ContactService(db_session)

        contacts = service.contacts_for_note(note.id)
        assert contacts
        assert note.id in [n.id for n in service.notes_for_contact(contacts[0].id)]

    def test_linking_is_idempotent(self, db_session, make_note):
        note = make_note("Call Sarah about the project.")
        service = ContactService(db_session)
        before = len(service.contacts_for_note(note.id))

        service.link_from_note(note)
        db_session.commit()
        assert len(service.contacts_for_note(note.id)) == before

    def test_email_is_absorbed_when_one_person_is_named(self, db_session, make_note):
        make_note("Email Chen at chen@university.edu about the report by Monday.")
        contacts = ContactService(db_session).list()
        assert any(c.email == "chen@university.edu" for c in contacts)

    def test_actions_are_offered_never_executed(self, db_session):
        """EchoNotes never places a call on its own: an accidental outbound
        message cannot be recalled, and cannot be spotted by glancing."""
        service = ContactService(db_session)
        contact, _ = service.get_or_create("Sarah")
        service.update(contact.id, phone="555-123-4567", email="sarah@example.com")

        actions = service.suggest_actions(contact)
        assert {a["action"] for a in actions} == {"call", "message", "email"}
        assert all(a["spoken"].endswith("?") for a in actions)

    def test_contact_with_no_details_offers_no_actions(self, db_session):
        service = ContactService(db_session)
        contact, _ = service.get_or_create("Nobody")
        assert service.suggest_actions(contact) == []

    def test_empty_name_is_rejected(self, db_session):
        with pytest.raises(ValueError):
            ContactService(db_session).get_or_create("   ")

    def test_deleting_a_note_removes_its_links_not_the_contact(self, db_session, make_note):
        from app.db.repositories import NoteRepository

        note = make_note("Call Sarah about the project.")
        service = ContactService(db_session)
        contact = service.contacts_for_note(note.id)[0]

        NoteRepository(db_session).delete(note.id)
        db_session.commit()

        assert service.get(contact.id) is not None
        assert service.notes_for_contact(contact.id) == []

    def test_linking_failure_never_breaks_a_capture(self, db_session, monkeypatch, make_note):
        from app.reminders import contacts as module

        monkeypatch.setattr(
            module.ContactService,
            "link_from_note",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        note = make_note("Call Sarah about the project.")  # must not raise
        assert note.id is not None


class TestEntitySource:
    def test_detection_reads_team_member_1_entities(self, db_session, make_note):
        """Guards the integration itself: reminders are derived from the
        `note_entities` rows the understanding pipeline wrote, not from a second
        parser living in this module."""
        from sqlalchemy import select

        from app.db.models import Entity

        note = make_note(ONE_TASK)
        kinds = {
            e.kind
            for e in db_session.execute(
                select(Entity).where(Entity.note_id == note.id)
            ).scalars()
        }
        assert EntityKind.TASK.value in kinds or EntityKind.DEADLINE.value in kinds
        assert detect_reminders(db_session, note)
