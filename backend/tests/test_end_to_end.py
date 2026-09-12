"""End-to-end integration (Phase 6).

One test walks the complete system in the order the brief specifies:

    Trigger -> Record -> Transcribe -> Understand -> Classify -> Organize
            -> Store -> Index -> Retrieve -> Respond

It runs against the real app, the real database and the real HTTP surface, with
only Whisper faked (`FakeTranscriber`, from `conftest.py`) so no model is
downloaded and no microphone is needed. Everything else - classification,
topic assignment, indexing, retrieval, answering, reminders, contacts, TTS - is
the shipping code path.

The point of an end-to-end test here is not coverage; the unit suites have that.
It is to catch the failures that only appear at the seams between three people's
work: a note that is stored but never indexed, a topic assigned but not
denormalised into the index, a reminder detected but never surfaced.
"""

from __future__ import annotations

import pytest

LECTURE_NOTE = (
    "Today's operating systems lecture covered deadlock detection. "
    "A deadlock requires circular wait, hold and wait, no preemption and mutual exclusion. "
    "The wait for graph is how we detect one at runtime."
)
TASK_NOTE = (
    "I need to submit the operating systems assignment to Professor Raman by next Friday. "
    "Also call Sarah about the database project meeting on March 3rd."
)
IDEA_NOTE = (
    "What if we made the lecture recordings searchable by voice? "
    "That could be a good final year project."
)


@pytest.fixture
def populated(client):
    """Capture three notes of three different types through the real API."""
    notes = {}
    for key, text in (
        ("lecture", LECTURE_NOTE),
        ("task", TASK_NOTE),
        ("idea", IDEA_NOTE),
    ):
        response = client.post("/api/v1/understand", json={"text": text, "persist": True})
        assert response.status_code == 200, response.text
        notes[key] = response.json()
    return notes


class TestFullLoop:
    def test_the_whole_pipeline_from_trigger_to_spoken_answer(self, client):
        """Trigger -> ... -> Respond, in one test, through HTTP only."""

        # --- Trigger / Record / Transcribe -------------------------------
        # An empty body is what a hardware button sends.
        captured = client.post("/api/v1/trigger", json={})
        assert captured.status_code == 201, captured.text
        note = captured.json()
        note_id = note["note_id"]
        assert note["raw_transcript"]
        assert note["cleaned_text"]

        # --- Understand / Classify ---------------------------------------
        understanding = note["understanding"]
        assert understanding["note_type"] in {"academic", "brainstorm", "todo"}
        assert understanding["quality"]["quality_score"] >= 0.0
        assert understanding["people"], "expected a person to be extracted"

        # --- Organize -------------------------------------------------------
        # NOTE (NexaNota redesign): this used to check placement in the old
        # Subject/Topic tree via GET /api/v1/hierarchy, which is no longer
        # mounted (see app/api/v1/router.py). The graph-based replacement is
        # GET /api/v1/graph/subjects + GET /api/v1/graph/subjects/{id} - not
        # asserted here yet; see tests/test_end_to_end.py history for the
        # removed check.

        # --- Index --------------------------------------------------------
        index = client.get("/api/v1/retrieval/status").json()
        assert index["chunk_count"] >= 1, "note was stored but never indexed"
        assert index["note_count"] >= 1

        # --- Retrieve / Respond -------------------------------------------
        answer = client.post(
            "/api/v1/retrieval/query",
            json={"utterance": "What did I write about the assignment?"},
        ).json()
        assert answer["ok"] is True
        assert note_id in answer["sources"], "the captured note was not retrievable"
        assert answer["spoken"]
        assert answer["speech"]["text"] == answer["spoken"]
        assert answer["citations"]

        # --- Derived: reminders and contacts -------------------------------
        reminders = client.get("/api/v1/reminders").json()
        assert reminders["count"] >= 1, "a to-do capture produced no reminder"
        assert reminders["spoken"]

        contacts = client.get("/api/v1/contacts").json()
        assert contacts, "a note naming people produced no contacts"


class TestSpecQueries:
    """The four Phase 4 query examples from the brief, end to end."""

    def test_what_did_i_write_about(self, client, populated):
        answer = client.post(
            "/api/v1/retrieval/query",
            json={"utterance": "What did I write about deadlock detection?"},
        ).json()
        assert answer["ok"]
        assert populated["lecture"]["note_id"] in answer["sources"]

    def test_when_did_i_mention(self, client, populated):
        answer = client.post(
            "/api/v1/retrieval/query",
            json={"utterance": "When did I mention the assignment deadline?"},
        ).json()
        assert answer["ok"]
        assert "You mentioned that on" in answer["spoken"]

    def test_summarize_my_notes_about(self, client, populated):
        answer = client.post(
            "/api/v1/retrieval/query",
            json={"utterance": "Summarize my notes about deadlocks."},
        ).json()
        assert answer["intent"] == "summarize"
        assert answer["ok"]
        assert answer["spoken"]

    def test_what_ideas_did_i_have_this_week(self, client, populated):
        answer = client.post(
            "/api/v1/retrieval/query",
            json={"utterance": "What ideas did I have this week?"},
        ).json()
        assert answer["ok"]
        assert answer["sources"] == [populated["idea"]["note_id"]]


class TestSpecNavigation:
    """The navigation examples from the brief, end to end.

    NexaNota redesign: `test_whats_under_a_subject`, `test_how_many_notes_under_a_topic`
    and `test_take_me_to_a_topic` were removed - they asserted against
    GET /api/v1/hierarchy/subjects, which is no longer mounted (that data now
    lives at GET /api/v1/graph/subjects and GET /api/v1/graph/topics/{id}/notes).
    """

    def test_what_subjects_do_i_have(self, client, populated):
        answer = client.post(
            "/api/v1/retrieval/query", json={"utterance": "What subjects do I have?"}
        ).json()
        assert answer["ok"]
        assert answer["data"]["subjects"]


class TestCrossPhaseConsistency:
    """The seams between the three team members' work."""

    def test_every_stored_note_is_indexed(self, client, populated):
        notes = client.get("/api/v1/notes").json()  # a list
        index = client.get("/api/v1/retrieval/status").json()
        assert index["chunk_count"] >= len(notes)

    # NexaNota redesign: `test_moving_a_note_updates_both_hierarchy_and_index`
    # was removed - it asserted against the now-unmounted
    # POST /api/v1/hierarchy/notes/{id}/move-by-name. The voice-command path
    # to the same underlying move (`app.hierarchy.service.move_note_by_name`)
    # is still live and still covered by `test_voice_move_command_round_trips`
    # below.

    def test_deleting_a_note_removes_it_everywhere(self, client, populated):
        note_id = populated["lecture"]["note_id"]
        assert client.delete(f"/api/v1/notes/{note_id}").status_code == 204

        answer = client.post(
            "/api/v1/retrieval/query",
            json={"utterance": "What did I write about deadlock detection?"},
        ).json()
        assert note_id not in answer["sources"]

    def test_voice_move_command_round_trips(self, client, populated):
        """A spoken organization command goes through Team Member 3's intent
        router, Team Member 2's command handler, and back out as speech."""
        note_id = populated["idea"]["note_id"]

        answer = client.post(
            "/api/v1/retrieval/query",
            json={
                "utterance": "Move this note to my Final Year Project topic.",
                "focused_note_id": note_id,
            },
        ).json()
        assert answer["intent"] == "move"
        assert answer["ok"]
        assert answer["spoken"]
        # NexaNota redesign: this used to also confirm placement via
        # topic_of() / GET /api/v1/hierarchy (removed, no longer mounted).

    def test_reindex_restores_search_after_index_loss(self, client, populated):
        """The recovery path: SQLite is authoritative, so a lost index is
        always rebuildable."""
        from app.rag.vector_store import get_vector_store

        get_vector_store().clear()
        assert client.get("/api/v1/retrieval/status").json()["chunk_count"] == 0

        rebuilt = client.post("/api/v1/retrieval/reindex").json()
        assert rebuilt["notes"] == 3
        assert rebuilt["chunks"] >= 3

        answer = client.post(
            "/api/v1/retrieval/query",
            json={"utterance": "What did I write about deadlock detection?"},
        ).json()
        assert answer["ok"]

    def test_health_reports_the_whole_system(self, client):
        body = client.get("/health").json()
        assert body["status"] in {"ok", "degraded"}
        assert "llm_available" in body


class TestDegradedModes:
    """The system runs with no API key by default, and both teammates kept it
    that way. These assert the whole loop still works in that configuration -
    which is what the test suite runs in."""

    def test_answers_are_produced_without_an_llm(self, client, populated):
        answer = client.post(
            "/api/v1/retrieval/query",
            json={"utterance": "What did I write about deadlock detection?"},
        ).json()
        assert answer["method"] == "extractive"
        assert answer["ok"]
        assert answer["sources"]

    def test_nothing_is_invented_when_nothing_matches(self, client, populated):
        """The single most important property of the whole feature."""
        answer = client.post(
            "/api/v1/retrieval/query",
            json={"utterance": "What did I write about medieval pottery?"},
        ).json()
        assert answer["ok"] is False
        assert answer["method"] == "empty"
        assert answer["sources"] == []
        assert answer["confidence"] == 0.0
