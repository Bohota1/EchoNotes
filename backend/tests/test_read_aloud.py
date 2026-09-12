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

from app.rag.conversation import get_conversation_store
from app.rag.intent import Intent, parse_intent
from app.rag.service import handle_voice_query

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
