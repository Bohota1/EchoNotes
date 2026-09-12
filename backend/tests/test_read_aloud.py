"""Reading notes back verbatim, and conversation sessions over HTTP.

Two things are asserted here that nothing else in the suite covers:

* **"Read my notes out loud" returns the notes, not a summary.** It is the one
  retrieval path that must never touch the LLM, so the test is that the stored
  wording survives intact.
* **A session is what makes a follow-up resolvable.** Without one, the second
  question is answered on its own - which is correct, and is also why the
  session has to be threaded all the way from the key press to `handle_voice_query`.
"""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.rag.conversation import get_conversation_store
from app.rag.intent import Intent, parse_intent
from app.rag.service import _collapse_repeats, handle_voice_query

DESIGN_NOTE = (
    "System design is about how the pieces of a large application fit together. "
    "You decide on the services, the data stores and how they talk to each other."
)
FAULT_NOTE = (
    "Fault tolerance is the ability of a system to keep working when one or more "
    "components fail. Redundancy and failover are the usual mechanisms."
)


@pytest.fixture
def library(db_session, make_note):
    return {
        "design": make_note(DESIGN_NOTE),
        "fault": make_note(FAULT_NOTE),
    }


class TestIntentRouting:
    """An explicit read verb is what separates the two paths. Without this,
    "what is system design" would read four notes aloud instead of answering."""

    @pytest.mark.parametrize(
        "utterance",
        [
            "Read my system design notes out loud",
            "Read out my system design notes",
            "Play back my system design notes",
            "Read my notes on system design aloud",
        ],
    )
    def test_a_read_request_is_recognised(self, utterance):
        assert parse_intent(utterance).intent == Intent.READ_ALOUD

    @pytest.mark.parametrize(
        "utterance",
        [
            "What is system design?",
            "Summarize my system design notes",
            "What did I write about system design?",
            "When did I mention system design?",
        ],
    )
    def test_a_question_is_not_a_read_request(self, utterance):
        assert parse_intent(utterance).intent != Intent.READ_ALOUD

    def test_the_subject_is_extracted(self):
        parsed = parse_intent("Read my system design notes out loud")
        assert "system design" in (parsed.target_name or parsed.query).lower()


class TestReadingAloud:
    def test_the_notes_come_back_verbatim(self, db_session, library):
        outcome = handle_voice_query(
            db_session, "Read my system design notes out loud"
        )
        assert outcome.intent == Intent.READ_ALOUD.value
        assert outcome.ok
        # The exact sentence the user recorded, not a paraphrase of it.
        assert "how the pieces of a large application fit together" in outcome.spoken
        assert outcome.data.get("verbatim") is True

    def test_several_notes_are_numbered(self, db_session, make_note):
        make_note("Caching keeps hot data close to the reader.")
        make_note("Sharding splits one large table across several machines.")
        outcome = handle_voice_query(db_session, "Read my caching notes out loud")
        assert outcome.ok
        if outcome.data.get("note_count", 0) > 1:
            assert "Note 1." in outcome.spoken

    def test_it_says_how_much_is_coming_first(self, db_session, library):
        outcome = handle_voice_query(
            db_session, "Read my system design notes out loud"
        )
        assert outcome.spoken.startswith("Reading ")

    def test_nothing_to_read_is_said_plainly(self, db_session):
        outcome = handle_voice_query(
            db_session, "Read my quantum chemistry notes out loud"
        )
        assert not outcome.ok
        assert outcome.spoken
        assert "quantum chemistry" in outcome.spoken.lower()

    def test_a_request_with_no_subject_asks_which(self, db_session, library):
        outcome = handle_voice_query(db_session, "Read my notes out loud")
        assert outcome.spoken


class TestReadingIsNotAnswering:
    def test_the_two_phrasings_take_different_paths(self, db_session, library):
        read = handle_voice_query(db_session, "Read my system design notes out loud")
        asked = handle_voice_query(db_session, "What is system design?")
        assert read.intent == Intent.READ_ALOUD.value
        assert asked.intent != Intent.READ_ALOUD.value
        assert read.data.get("verbatim") is True
        assert asked.data.get("verbatim") is not True


class TestSessionsOverHttp:
    def test_a_session_opens_and_closes(self, client):
        started = client.post("/api/v1/retrieval/session/start")
        assert started.status_code == 200
        session_id = started.json()["session_id"]
        assert session_id
        assert started.json()["spoken"]

        ended = client.post(f"/api/v1/retrieval/session/{session_id}/end")
        assert ended.status_code == 200
        assert ended.json()["turns"] == 0
        assert ended.json()["spoken"]

    def test_ending_an_unknown_session_is_not_an_error(self, client):
        response = client.post("/api/v1/retrieval/session/nosuchsession/end")
        assert response.status_code == 200
        assert response.json()["turns"] == 0

    def test_a_closed_session_is_forgotten(self, client):
        session_id = client.post("/api/v1/retrieval/session/start").json()["session_id"]
        client.post(f"/api/v1/retrieval/session/{session_id}/end")
        assert get_conversation_store().get(session_id) is None


class TestSessionsRecordTurns:
    def test_a_question_asked_in_a_session_is_remembered(self, db_session, library):
        session = get_conversation_store().start()
        try:
            handle_voice_query(
                db_session, "What is fault tolerance?", session_id=session.id
            )
            assert len(session.turns) == 1
            assert "fault tolerance" in session.turns[0].question.lower()
            assert session.turns[0].answer
        finally:
            get_conversation_store().end(session.id)

    def test_without_a_session_nothing_is_remembered(self, db_session, library):
        before = get_conversation_store().active_count()
        handle_voice_query(db_session, "What is fault tolerance?")
        assert get_conversation_store().active_count() == before

    def test_an_unknown_session_id_still_answers(self, db_session, library):
        outcome = handle_voice_query(
            db_session, "What is fault tolerance?", session_id="nosuchsession"
        )
        assert outcome.spoken

    def test_reading_aloud_is_not_recorded_as_a_turn(self, db_session, library):
        """A verbatim reading is not a question, so it must not become the
        context that the next follow-up's pronoun resolves against."""
        session = get_conversation_store().start()
        try:
            handle_voice_query(
                db_session,
                "Read my system design notes out loud",
                session_id=session.id,
            )
            assert session.is_empty
        finally:
            get_conversation_store().end(session.id)


# Two recordings of the same explanation, as they actually come back: the same
# words in the same order, differing where the recogniser heard differently.
RETAKE_EARLY = (
    "What is fault tolerance? Fault tolerance is the ability of our system to "
    "continue working even when one or more components fail. In similar words, "
    "something breaks, the system steelworks."
)
RETAKE_LATE = (
    "What is fault tolerance? Fault tolerance is the ability of a system to "
    "continue working even when one or more components fail. In simple words, "
    "something breaks, the system still works."
)


class TestCollapsingRetakes:
    """Re-recording the same explanation is normal - the user says it again
    because the first attempt was misheard. Reading every version aloud sounds
    exactly like reading one note twice, which is what it was reported as."""

    def test_a_retake_is_collapsed(self):
        kept, skipped = _collapse_repeats(
            [
                ("late", RETAKE_LATE, "2026-09-12T11:08:00"),
                ("early", RETAKE_EARLY, "2026-09-12T11:05:00"),
            ]
        )
        assert skipped == 1
        assert len(kept) == 1

    def test_the_newest_wins_even_when_it_is_shorter(self):
        """Length measures nothing about correctness. On real data, keeping the
        longest kept "the system steelworks" over a later capture that had it
        right, because the bad one was two characters longer."""
        assert len(RETAKE_EARLY) > len(RETAKE_LATE), "the premise of this test"
        kept, _ = _collapse_repeats(
            [
                ("early", RETAKE_EARLY, "2026-09-12T11:05:00"),
                ("late", RETAKE_LATE, "2026-09-12T11:08:00"),
            ]
        )
        assert [note_id for note_id, _, _ in kept] == ["late"]
        assert "still works" in kept[0][1]

    def test_distinct_notes_are_both_kept(self):
        kept, skipped = _collapse_repeats(
            [
                ("a", DESIGN_NOTE, "2026-09-12T10:00:00"),
                ("b", FAULT_NOTE, "2026-09-12T10:05:00"),
            ]
        )
        assert skipped == 0
        assert len(kept) == 2

    def test_order_follows_the_first_of_each_group(self):
        kept, _ = _collapse_repeats(
            [
                ("design", DESIGN_NOTE, "2026-09-12T10:00:00"),
                ("early", RETAKE_EARLY, "2026-09-12T10:05:00"),
                ("late", RETAKE_LATE, "2026-09-12T10:09:00"),
            ]
        )
        assert [note_id for note_id, _, _ in kept] == ["design", "late"]

    def test_a_single_note_is_left_alone(self):
        items = [("a", DESIGN_NOTE, "2026-09-12T10:00:00")]
        assert _collapse_repeats(items) == (items, 0)

    def test_it_can_be_turned_off(self, monkeypatch):
        monkeypatch.setattr(
            get_settings(), "read_aloud_collapse_repeats", False, raising=False
        )
        items = [
            ("early", RETAKE_EARLY, "2026-09-12T11:05:00"),
            ("late", RETAKE_LATE, "2026-09-12T11:08:00"),
        ]
        assert _collapse_repeats(items) == (items, 0)


class TestTheSkipIsAudible:
    """A note that silently vanishes from a verbatim reading cannot be told
    apart from one that was never saved."""

    def test_the_reading_says_what_it_skipped(self, db_session, make_note):
        make_note(RETAKE_EARLY)
        make_note(RETAKE_LATE)
        outcome = handle_voice_query(
            db_session, "Read my fault tolerance notes out loud"
        )
        assert outcome.ok
        assert outcome.data["skipped_repeats"] == 1
        assert "Skipping" in outcome.spoken

    def test_the_same_sentence_is_not_read_twice(self, db_session, make_note):
        make_note(RETAKE_EARLY)
        make_note(RETAKE_LATE)
        outcome = handle_voice_query(
            db_session, "Read my fault tolerance notes out loud"
        )
        assert outcome.spoken.count("What is fault tolerance?") == 1

    def test_sources_are_only_the_notes_that_were_read(self, db_session, make_note):
        make_note(RETAKE_EARLY)
        make_note(RETAKE_LATE)
        outcome = handle_voice_query(
            db_session, "Read my fault tolerance notes out loud"
        )
        assert len(outcome.sources) == outcome.data["note_count"]
