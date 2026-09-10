"""HTTP-level tests for the Phase 3 endpoints, mounted under
`/api/v1/hierarchy` - `GET /hierarchy` (the spec's literal endpoint), the
outline/overview, subject/topic CRUD, note moves, and the voice-command
dispatcher. Runs against the real app and a temporary SQLite file via the
`client` fixture (`conftest.py`), same as `test_api.py` does for Phase 1/2.
"""

from __future__ import annotations


def _capture_note(client, text: str) -> str:
    response = client.post("/api/v1/understand", json={"text": text, "persist": True})
    assert response.status_code == 200
    return response.json()["note_id"]


def test_get_hierarchy_matches_the_spec_endpoint(client):
    """`GET /api/v1/hierarchy` - literally what the Phase 3 spec asks for."""
    response = client.get("/api/v1/hierarchy")
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"overview", "subjects", "narration"}
    assert body["overview"]["subject_count"] == 0
    assert "narration" in body and isinstance(body["narration"], str)


def test_outline_and_hierarchy_return_identical_payloads(client):
    _capture_note(client, "Buy milk. File this under Groceries.")
    a = client.get("/api/v1/hierarchy").json()
    b = client.get("/api/v1/hierarchy/outline").json()
    assert a == b


def test_capture_files_a_note_automatically(client):
    note_id = _capture_note(client, "Buy milk and eggs. File this under Groceries.")

    outline = client.get("/api/v1/hierarchy").json()
    names = [s["name"] for s in outline["subjects"]]
    assert "Groceries" in names

    groceries = next(s for s in outline["subjects"] if s["name"] == "Groceries")
    all_note_ids = {n["id"] for t in groceries["topics"] for n in t["notes"]}
    assert note_id in all_note_ids


def test_narration_is_present_and_nonempty_with_content(client):
    _capture_note(client, "Buy milk. File this under Groceries.")
    outline = client.get("/api/v1/hierarchy").json()
    assert "1 subject" in outline["narration"]
    assert "Under Groceries" in outline["narration"]


def test_create_subject_and_topic(client):
    response = client.post("/api/v1/hierarchy/subjects", json={"name": "Thesis"})
    assert response.status_code == 201
    subject = response.json()
    assert subject["name"] == "Thesis"

    response = client.post(
        "/api/v1/hierarchy/topics",
        json={"subject_id": subject["id"], "name": "Chapter 3", "kind": "project"},
    )
    assert response.status_code == 201
    topic = response.json()
    assert topic["kind"] == "project"
    assert topic["notes"] == []


def test_create_topic_under_unknown_subject_is_404(client):
    response = client.post(
        "/api/v1/hierarchy/topics", json={"subject_id": "nope", "name": "X"}
    )
    assert response.status_code == 404


def test_list_topics_under_subject_and_notes_under_topic(client):
    note_id = _capture_note(client, "Buy milk. File this under Groceries.")
    outline = client.get("/api/v1/hierarchy").json()
    subject = outline["subjects"][0]
    topic = subject["topics"][0]

    response = client.get(f"/api/v1/hierarchy/subjects/{subject['id']}/topics")
    assert response.status_code == 200
    assert any(t["id"] == topic["id"] for t in response.json())

    response = client.get(f"/api/v1/hierarchy/topics/{topic['id']}/notes")
    assert response.status_code == 200
    assert any(n["id"] == note_id for n in response.json())


def test_move_note_by_id(client):
    note_id = _capture_note(client, "Buy milk. File this under Groceries.")
    response = client.post("/api/v1/hierarchy/subjects", json={"name": "Errands"})
    subject_id = response.json()["id"]
    response = client.post(
        "/api/v1/hierarchy/topics", json={"subject_id": subject_id, "name": "Shopping"}
    )
    topic_id = response.json()["id"]

    response = client.post(
        f"/api/v1/hierarchy/notes/{note_id}/move", json={"target_topic_id": topic_id}
    )
    assert response.status_code == 200
    assert response.json()["topic_id"] == topic_id


def test_move_note_by_name_creates_topic_when_nothing_matches(client):
    note_id = _capture_note(client, "Buy milk. File this under Groceries.")
    response = client.post(
        f"/api/v1/hierarchy/notes/{note_id}/move-by-name",
        json={"target_name": "Machine Learning"},
    )
    assert response.status_code == 200
    body = response.json()
    outline = client.get("/api/v1/hierarchy").json()
    ml_subject = next(s for s in outline["subjects"] if s["name"] == "Machine Learning")
    assert any(n["id"] == note_id for t in ml_subject["topics"] for n in t["notes"])
    assert body["topic_id"]


def test_move_unknown_note_is_404(client):
    response = client.post(
        "/api/v1/hierarchy/notes/does-not-exist/move", json={"target_topic_id": "also-nope"}
    )
    assert response.status_code == 404


def test_refresh_topic_summary(client):
    _capture_note(client, "Buy milk and eggs and bread. File this under Groceries.")
    outline = client.get("/api/v1/hierarchy").json()
    topic = outline["subjects"][0]["topics"][0]
    assert topic["summary_stale"] is True

    response = client.post(f"/api/v1/hierarchy/topics/{topic['id']}/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["summary_stale"] is False
    assert body["summary"] != ""


def test_recluster_subject(client):
    _capture_note(client, "Buy milk. File this under Groceries.")
    outline = client.get("/api/v1/hierarchy").json()
    subject_id = outline["subjects"][0]["id"]

    response = client.post(f"/api/v1/hierarchy/subjects/{subject_id}/recluster")
    assert response.status_code == 200
    assert "topics" in response.json()


def test_recluster_unknown_subject_is_404(client):
    response = client.post("/api/v1/hierarchy/subjects/does-not-exist/recluster")
    assert response.status_code == 404


# --- Voice-based organization commands (Phase 3 spec) ------------------------


def test_command_move_this_note_to(client):
    note_id = _capture_note(client, "Buy milk. File this under Groceries.")
    response = client.post(
        "/api/v1/hierarchy/command",
        json={"text": "Move this note to Machine Learning.", "focused_note_id": note_id},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "move"
    assert body["ok"] is True
    assert body["data"]["topic_name"] == "Machine Learning"


def test_command_move_without_focused_note_fails_gracefully(client):
    response = client.post(
        "/api/v1/hierarchy/command", json={"text": "Move this note to Machine Learning."}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["intent"] == "move"


def test_command_what_topics_are_under(client):
    _capture_note(client, "Buy milk. File this under Groceries.")
    response = client.post(
        "/api/v1/hierarchy/command", json={"text": "What topics are under Groceries?"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "topics_under"
    assert body["ok"] is True
    assert "Groceries" in body["data"]["topics"]


def test_command_what_notes_are_under(client):
    _capture_note(client, "Buy milk. File this under Groceries.")
    response = client.post(
        "/api/v1/hierarchy/command", json={"text": "What notes are under Groceries?"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "notes_under"
    assert len(body["data"]["notes"]) == 1


def test_command_unrecognized(client):
    response = client.post(
        "/api/v1/hierarchy/command", json={"text": "Please make me a sandwich."}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "unrecognized"
    assert body["ok"] is False


def test_command_unknown_subject_reports_failure_not_error(client):
    response = client.post(
        "/api/v1/hierarchy/command",
        json={"text": "What topics are under Quantum Cryptography?"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert "spoken" in body
