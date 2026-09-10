"""The voice-query loop (Phase 4) - `app.rag.service` and `/api/v1/retrieval`.

Every branch of `handle_voice_query`, plus the HTTP surface. The invariant
asserted throughout is the one a voice loop depends on: **`spoken` is always
populated and always safe to read aloud**, including when `ok` is false. That is
the contract Team Member 2 set for `/hierarchy/command`, kept uniform across the
whole voice surface so a client never needs an error branch to know what to say.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.rag.service import handle_voice_query

OS_NOTE = (
    "Deadlock detection needs a wait for graph. A deadlock requires circular wait, "
    "hold and wait, no preemption and mutual exclusion."
)
ML_NOTE = (
    "Gradient descent minimises the loss function by stepping along the negative "
    "gradient. Machine learning models need a learning rate."
)
IDEA_NOTE = "What if we built a podcast about accessible design? A good side project."
TASK_NOTE = "I need to submit the operating systems assignment by next Friday."


@pytest.fixture
def library(db_session, make_note):
    """A small library covering every note type."""
    return {
        "os": make_note(OS_NOTE),
        "ml": make_note(ML_NOTE),
        "idea": make_note(IDEA_NOTE),
        "task": make_note(TASK_NOTE),
    }


class TestSpokenContract:
    @pytest.mark.parametrize(
        "utterance",
        [
            "What did I write about machine learning?",
            "When did I mention the assignment deadline?",
            "Summarize my notes about databases.",
            "What ideas did I have this week?",
            "What subjects do I have?",
            "What's under Machine Learning?",
            "How many notes are under Graph Theory?",
            "Take me to my Project Ideas.",
            "Move this note to Machine Learning.",
            "What's due tomorrow?",
            "",
            "asdfghjkl",
        ],
    )
    def test_every_utterance_yields_something_speakable(
        self, db_session, library, utterance
    ):
        outcome = handle_voice_query(db_session, utterance)
        assert outcome.spoken, f"no spoken response for {utterance!r}"
        assert outcome.spoken.strip() == outcome.spoken
        assert outcome.speech is not None or not outcome.ok

    def test_failures_are_speakable_not_exceptions(self, db_session):
        """An empty library must answer, not raise."""
        outcome = handle_voice_query(db_session, "What did I write about anything?")
        assert outcome.ok is False
        assert "don't have" in outcome.spoken.lower()


class TestContentQueries:
    def test_finds_the_right_note(self, db_session, library):
        outcome = handle_voice_query(db_session, "What did I write about machine learning?")
        assert outcome.ok
        assert library["ml"].id in outcome.sources

    def test_answer_cites_its_sources(self, db_session, library):
        """A user who cannot see a citation list needs provenance in the
        sentence."""
        outcome = handle_voice_query(db_session, "What did I write about deadlocks?")
        assert outcome.sources
        assert outcome.citations
        assert "From" in outcome.spoken

    def test_results_carry_the_matching_snippet(self, db_session, library):
        outcome = handle_voice_query(db_session, "What did I write about gradient descent?")
        assert outcome.results
        assert outcome.results[0].snippet
        assert outcome.results[0].matched_by

    def test_when_question_leads_with_the_date(self, db_session, library):
        outcome = handle_voice_query(db_session, "When did I mention the assignment?")
        assert outcome.ok
        assert "You mentioned that on" in outcome.spoken

    def test_summarize_uses_the_summarize_path(self, db_session, library):
        outcome = handle_voice_query(db_session, "Summarize my notes about deadlocks.")
        assert outcome.intent == "summarize"
        assert outcome.ok

    def test_what_ideas_this_week_filters_by_type_and_date(self, db_session, library):
        outcome = handle_voice_query(db_session, "What ideas did I have this week?")
        assert outcome.ok
        assert outcome.sources == [library["idea"].id]

    def test_unmatched_query_is_honest_about_it(self, db_session, library):
        """Answering from general knowledge would be the worst possible failure
        for a note-taking assistant."""
        outcome = handle_voice_query(db_session, "What did I write about quantum tunnelling?")
        assert outcome.ok is False
        assert outcome.method == "empty"
        assert outcome.confidence == 0.0
        assert outcome.sources == []

    def test_confidence_is_reported(self, db_session, library):
        outcome = handle_voice_query(db_session, "What did I write about deadlocks?")
        assert 0.0 < outcome.confidence <= 1.0


class TestNavigationCommands:
    """The four navigation examples from the brief."""

    def test_what_subjects_do_i_have(self, db_session, library):
        outcome = handle_voice_query(db_session, "What subjects do I have?")
        assert outcome.intent == "list_subjects"
        assert outcome.ok
        assert "subject" in outcome.spoken.lower()
        assert outcome.data["subjects"]

    def test_what_subjects_with_an_empty_library(self, db_session):
        outcome = handle_voice_query(db_session, "What subjects do I have?")
        assert outcome.ok
        assert "don't have any subjects" in outcome.spoken.lower()

    def test_whats_under_a_subject(self, db_session, library):
        from app.db.repositories import SubjectRepository

        subject = SubjectRepository(db_session).list()[0]
        outcome = handle_voice_query(db_session, f"What's under {subject.name}?")
        assert outcome.ok
        assert subject.name in outcome.spoken

    def test_how_many_notes_under_a_topic(self, db_session, library):
        from app.db.repositories import TopicRepository

        topic = TopicRepository(db_session).list_all()[0]
        outcome = handle_voice_query(db_session, f"How many notes are under {topic.name}?")
        assert outcome.intent == "count_notes"
        assert outcome.ok
        assert any(char.isdigit() for char in outcome.spoken)

    def test_take_me_to_a_topic_returns_a_focus_target(self, db_session, library):
        """A focus jump the user cannot see and was not told about is
        indistinguishable from the app losing their place."""
        from app.db.repositories import TopicRepository

        topic = TopicRepository(db_session).list_all()[0]
        outcome = handle_voice_query(db_session, f"Take me to my {topic.name}.")
        assert outcome.intent == "navigate"
        assert outcome.ok
        assert outcome.navigate_to == f"topic-{topic.id}"
        assert topic.name in outcome.spoken

    def test_navigate_to_something_that_does_not_exist(self, db_session, library):
        outcome = handle_voice_query(db_session, "Take me to my Kwyjibo.")
        assert outcome.ok is False
        assert outcome.navigate_to is None
        assert "couldn't find" in outcome.spoken.lower()

    def test_unknown_subject_is_reported_not_invented(self, db_session, library):
        outcome = handle_voice_query(db_session, "What's under Kwyjibo?")
        assert outcome.ok is False
        assert "don't have" in outcome.spoken.lower()


class TestOrganizeDelegation:
    def test_move_is_delegated_to_team_member_2(self, db_session, library):
        """This module must not reimplement moving; it hands the utterance to
        `app.hierarchy.commands` untouched."""
        note = library["os"]
        outcome = handle_voice_query(
            db_session, "Move this note to Machine Learning.", focused_note_id=note.id
        )
        assert outcome.intent == "move"
        assert outcome.ok
        db_session.commit()
        db_session.refresh(note)
        assert note.topic.name == "Machine Learning"

    def test_move_without_a_focused_note_asks_which_one(self, db_session, library):
        outcome = handle_voice_query(db_session, "Move this note to Machine Learning.")
        assert outcome.ok is False
        assert "which note" in outcome.spoken.lower()

    def test_moved_note_is_retrievable_at_its_new_location(self, db_session, library):
        """The reindex hook on `move_note`: search must not filter on where a
        note used to be."""
        note = library["os"]
        handle_voice_query(
            db_session, "Move this note to my Graph Theory topic.", focused_note_id=note.id
        )
        db_session.commit()

        outcome = handle_voice_query(db_session, "What did I write about deadlocks?")
        assert outcome.ok
        assert outcome.results[0].topic_name == "Graph Theory"


class TestReminderQueries:
    def test_whats_due_reads_the_reminder_list(self, db_session, library):
        outcome = handle_voice_query(db_session, "What's due this week?")
        assert outcome.intent == "reminders"
        assert outcome.ok
        assert outcome.spoken

    def test_nothing_due_says_so(self, db_session):
        outcome = handle_voice_query(db_session, "What's due tomorrow?")
        assert outcome.ok
        assert "nothing due" in outcome.spoken.lower()

    def test_due_reminder_is_announced(self, db_session):
        from app.reminders.service import ReminderService

        ReminderService(db_session).create(
            title="Submit the report", due_at=datetime.now() + timedelta(hours=3)
        )
        db_session.commit()

        outcome = handle_voice_query(db_session, "What's due tomorrow?")
        assert "Submit the report" in outcome.spoken


class TestSpeechDirectives:
    def test_answers_carry_a_speech_directive(self, db_session, library):
        outcome = handle_voice_query(db_session, "What did I write about deadlocks?")
        assert outcome.speech is not None
        assert outcome.speech.text == outcome.spoken
        assert outcome.speech.engine == "directive"

    def test_results_and_no_results_use_different_earcons(self, db_session, library):
        found = handle_voice_query(db_session, "What did I write about deadlocks?")
        missing = handle_voice_query(db_session, "What did I write about astrophysics?")
        assert found.speech.earcon != missing.speech.earcon

    def test_answers_do_not_interrupt(self, db_session, library):
        """An answer waits its turn; only errors and state changes cut in."""
        outcome = handle_voice_query(db_session, "What did I write about deadlocks?")
        assert outcome.speech.interrupt is False


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


class TestRetrievalApi:
    def test_query_endpoint_answers(self, client):
        client.post("/api/v1/understand", json={"text": OS_NOTE, "persist": True})

        response = client.post(
            "/api/v1/retrieval/query",
            json={"utterance": "What did I write about deadlocks?"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["spoken"]
        assert body["sources"]
        assert body["results"][0]["snippet"]
        assert body["speech"]["text"] == body["spoken"]

    def test_query_can_suppress_speech(self, client):
        client.post("/api/v1/understand", json={"text": OS_NOTE, "persist": True})
        response = client.post(
            "/api/v1/retrieval/query",
            json={"utterance": "What did I write about deadlocks?", "speak": False},
        )
        assert response.json()["speech"] is None

    def test_empty_utterance_is_handled_not_rejected(self, client):
        response = client.post("/api/v1/retrieval/query", json={"utterance": ""})
        assert response.status_code == 200
        assert response.json()["spoken"]

    def test_status_reports_the_index(self, client):
        client.post("/api/v1/understand", json={"text": OS_NOTE, "persist": True})
        body = client.get("/api/v1/retrieval/status").json()
        assert body["vector_store"] == "memory"
        assert body["embedding_backend"] == "hashed"
        assert body["chunk_count"] >= 1
        assert body["note_count"] >= 1

    def test_reindex_rebuilds(self, client):
        client.post("/api/v1/understand", json={"text": OS_NOTE, "persist": True})
        body = client.post("/api/v1/retrieval/reindex").json()
        assert body["notes"] >= 1
        assert body["chunks"] >= 1
        assert body["spoken"]

    def test_voice_endpoint_rejects_empty_audio(self, client):
        response = client.post(
            "/api/v1/retrieval/voice", files={"file": ("q.wav", b"", "audio/wav")}
        )
        assert response.status_code == 422

    def test_voice_endpoint_transcribes_and_answers(
        self, client, fake_transcriber, fixture_wav
    ):
        """The spoken path end to end, with Whisper faked.

        A real wav is posted rather than arbitrary bytes: the upload goes
        through Team Member 1's `UploadCaptureSource`, which inspects the
        container before handing it on.
        """
        client.post("/api/v1/understand", json={"text": OS_NOTE, "persist": True})
        fake_transcriber.text = "What did I write about deadlocks?"

        response = client.post(
            "/api/v1/retrieval/voice",
            files={"file": ("q.wav", fixture_wav.read_bytes(), "audio/wav")},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["data"]["transcribed_utterance"] == "What did I write about deadlocks?"
        assert body["spoken"]


class TestReminderApi:
    def test_crud_round_trip(self, client):
        due = (datetime.now() + timedelta(days=1)).isoformat()
        created = client.post(
            "/api/v1/reminders", json={"title": "Submit report", "due_at": due}
        )
        assert created.status_code == 201
        reminder_id = created.json()["id"]
        assert created.json()["due_spoken"]

        assert client.get(f"/api/v1/reminders/{reminder_id}").status_code == 200

        patched = client.patch(
            f"/api/v1/reminders/{reminder_id}", json={"title": "Submit final report"}
        )
        assert patched.json()["title"] == "Submit final report"

        assert client.post(f"/api/v1/reminders/{reminder_id}/done").json()["status"] == "done"
        assert client.delete(f"/api/v1/reminders/{reminder_id}").status_code == 204
        assert client.get(f"/api/v1/reminders/{reminder_id}").status_code == 404

    def test_list_is_narrated(self, client):
        client.post(
            "/api/v1/reminders",
            json={"title": "Call the department", "due_at": (datetime.now() + timedelta(hours=2)).isoformat()},
        )
        body = client.get("/api/v1/reminders").json()
        assert body["count"] == 1
        assert body["spoken"]

    def test_detected_endpoint_shows_suggestions(self, client):
        note_id = client.post(
            "/api/v1/understand", json={"text": TASK_NOTE, "persist": True}
        ).json()["note_id"]

        body = client.get(f"/api/v1/reminders/notes/{note_id}/detected").json()
        assert body
        assert "auto_create" in body[0]
        assert "confidence" in body[0]

    def test_detected_for_unknown_note_is_404(self, client):
        assert client.get("/api/v1/reminders/notes/nope/detected").status_code == 404


class TestContactApi:
    def test_contacts_appear_after_a_capture(self, client):
        client.post(
            "/api/v1/understand",
            json={"text": "Call Sarah about the database project.", "persist": True},
        )
        names = [c["name"] for c in client.get("/api/v1/contacts").json()]
        assert "Sarah" in names

    def test_detail_offers_actions_after_details_are_added(self, client):
        created = client.post(
            "/api/v1/contacts", json={"name": "Sarah", "phone": "555-123-4567"}
        )
        assert created.status_code == 201
        body = client.get(f"/api/v1/contacts/{created.json()['id']}").json()
        assert {a["action"] for a in body["actions"]} >= {"call", "message"}
        assert body["spoken"]

    def test_unknown_contact_is_404(self, client):
        assert client.get("/api/v1/contacts/nope").status_code == 404


class TestTtsApi:
    def test_speak_returns_a_directive(self, client):
        body = client.post("/api/v1/tts/speak", json={"text": "Note saved."}).json()
        assert body["text"] == "Note saved."
        assert body["engine"] == "directive"
        assert body["audio_url"] is None

    def test_voice_coding_is_off_by_default(self, client):
        """As in Idea11y: distinct voices are opt-in."""
        academic = client.post(
            "/api/v1/tts/speak", json={"text": "A note.", "note_type": "academic"}
        ).json()
        todo = client.post(
            "/api/v1/tts/speak", json={"text": "A note.", "note_type": "todo"}
        ).json()
        assert academic["voice"] == todo["voice"] == "default"

    def test_missing_audio_file_is_404(self, client):
        assert client.get("/api/v1/tts/audio/nope.wav").status_code == 404

    def test_audio_path_cannot_escape_the_output_directory(self, client):
        """The path is rebuilt from the configured directory and a bare
        filename, so a crafted name cannot walk out of it."""
        response = client.get("/api/v1/tts/audio/..%2F..%2Fconfig.py")
        assert response.status_code == 404
