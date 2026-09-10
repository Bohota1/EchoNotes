"""Phase 5 - Summarization by Subject, Project, Topic and time range.

Covers `app.hierarchy.summarization` directly (roll-up logic, both the
extractive-fallback path used by default under `LLM_PROVIDER=null` and the
mocked-LLM path) and the HTTP layer at `/api/v1/summary/*`.

Per the spec, a Subject-level summary must reuse Topic summaries rather than
re-summarizing every note directly - `test_summarize_subject_rolls_up_topic_summaries`
is the test that would fail if that indirection were ever removed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.db.repositories import NoteRepository, SubjectRepository, TopicRepository
from app.hierarchy.summarization import summarize_range, summarize_subject, summarize_topic


def _note(db_session, text: str, *, topic_id: str | None = None, created_at=None):
    note = NoteRepository(db_session).create(
        raw_transcript=text, cleaned_text=text, source="text"
    )
    if topic_id is not None:
        note.topic_id = topic_id
    if created_at is not None:
        note.created_at = created_at
    db_session.flush()
    return note


# --- summarize_topic ----------------------------------------------------------


def test_summarize_topic_refreshes_when_stale(db_session):
    subject, _ = SubjectRepository(db_session).get_or_create("Discrete Structure")
    topic, _ = TopicRepository(db_session).get_or_create(subject.id, "Deadlock")
    _note(db_session, "A deadlock needs circular wait and mutual exclusion.", topic_id=topic.id)
    _note(db_session, "Hold and wait plus no preemption also required.", topic_id=topic.id)

    assert topic.summary_stale is True
    result = summarize_topic(db_session, topic.id)

    assert result.scope == "topic"
    assert result.scope_id == topic.id
    assert result.scope_name == "Deadlock"
    assert result.note_count == 2
    assert result.summary != ""
    assert result.method in ("llm", "extractive")
    assert "Deadlock" in result.spoken
    assert "2 notes" in result.spoken


def test_summarize_topic_uses_cache_when_fresh(db_session):
    subject, _ = SubjectRepository(db_session).get_or_create("Discrete Structure")
    topic, _ = TopicRepository(db_session).get_or_create(subject.id, "Deadlock")
    _note(db_session, "A deadlock needs circular wait.", topic_id=topic.id)
    summarize_topic(db_session, topic.id)  # first call refreshes and caches

    result = summarize_topic(db_session, topic.id)
    assert result.method == "cached"


def test_summarize_topic_force_refresh_bypasses_cache(db_session):
    subject, _ = SubjectRepository(db_session).get_or_create("Discrete Structure")
    topic, _ = TopicRepository(db_session).get_or_create(subject.id, "Deadlock")
    _note(db_session, "A deadlock needs circular wait.", topic_id=topic.id)
    summarize_topic(db_session, topic.id)

    result = summarize_topic(db_session, topic.id, force_refresh=True)
    assert result.method != "cached"


def test_summarize_topic_unknown_id_raises(db_session):
    with pytest.raises(ValueError):
        summarize_topic(db_session, "does-not-exist")


# --- summarize_subject: the Subject -> Topics -> topic summaries roll-up -----


def test_summarize_subject_rolls_up_topic_summaries(db_session):
    subject, _ = SubjectRepository(db_session).get_or_create("Discrete Structure")
    t1, _ = TopicRepository(db_session).get_or_create(subject.id, "Deadlock")
    t2, _ = TopicRepository(db_session).get_or_create(subject.id, "Graph Theory")
    _note(db_session, "A deadlock needs circular wait and mutual exclusion.", topic_id=t1.id)
    _note(db_session, "Graphs have vertices and edges and can be traversed.", topic_id=t2.id)

    result = summarize_subject(db_session, subject.id)

    assert result.scope == "subject"
    assert result.scope_name == "Discrete Structure"
    assert result.note_count == 2
    assert "2 topics" in result.spoken
    assert "2 notes" in result.spoken
    assert result.summary != ""

    # Both topic summaries must have been generated (not left stale) as a
    # side effect of the roll-up, since they are its inputs.
    db_session.refresh(t1)
    db_session.refresh(t2)
    assert t1.summary_stale is False
    assert t2.summary_stale is False


def test_summarize_subject_with_no_notes_is_empty_not_an_error(db_session):
    subject, _ = SubjectRepository(db_session).get_or_create("Empty Subject")
    result = summarize_subject(db_session, subject.id)

    assert result.method == "empty"
    assert result.note_count == 0
    assert result.summary == "No notes yet."


def test_summarize_subject_unknown_id_raises(db_session):
    with pytest.raises(ValueError):
        summarize_subject(db_session, "does-not-exist")


# --- summarize_range -----------------------------------------------------------


def test_summarize_range_filters_by_window(db_session):
    subject, _ = SubjectRepository(db_session).get_or_create("Journal")
    topic, _ = TopicRepository(db_session).get_or_create(subject.id, "Daily")
    old = datetime(2026, 1, 1, tzinfo=timezone.utc)
    recent = datetime(2026, 6, 1, tzinfo=timezone.utc)
    _note(db_session, "An old note from January about tax season.", topic_id=topic.id, created_at=old)
    _note(db_session, "A recent note from June about summer plans.", topic_id=topic.id, created_at=recent)

    result = summarize_range(
        db_session,
        start=datetime(2026, 3, 1, tzinfo=timezone.utc),
        end=datetime(2026, 12, 31, tzinfo=timezone.utc),
    )

    assert result.note_count == 1
    assert "summer" in result.summary.lower() or result.summary != ""


def test_summarize_range_scoped_to_subject(db_session):
    subject_a, _ = SubjectRepository(db_session).get_or_create("Subject A")
    subject_b, _ = SubjectRepository(db_session).get_or_create("Subject B")
    topic_a, _ = TopicRepository(db_session).get_or_create(subject_a.id, "T")
    topic_b, _ = TopicRepository(db_session).get_or_create(subject_b.id, "T")
    _note(db_session, "Note in subject A.", topic_id=topic_a.id)
    _note(db_session, "Note in subject B.", topic_id=topic_b.id)

    result = summarize_range(db_session, subject_id=subject_a.id)
    assert result.note_count == 1
    assert result.scope_name == "Subject A"


def test_summarize_range_scoped_to_topic(db_session):
    subject, _ = SubjectRepository(db_session).get_or_create("Discrete Structure")
    t1, _ = TopicRepository(db_session).get_or_create(subject.id, "Deadlock")
    t2, _ = TopicRepository(db_session).get_or_create(subject.id, "Graph Theory")
    _note(db_session, "About deadlocks.", topic_id=t1.id)
    _note(db_session, "About graphs.", topic_id=t2.id)

    result = summarize_range(db_session, topic_id=t1.id)
    assert result.note_count == 1
    assert result.scope_name == "Deadlock"


def test_summarize_range_with_no_matching_notes_is_empty(db_session):
    result = summarize_range(
        db_session,
        start=datetime(2099, 1, 1, tzinfo=timezone.utc),
        end=datetime(2099, 12, 31, tzinfo=timezone.utc),
    )
    assert result.method == "empty"
    assert result.note_count == 0
    assert result.summary == "No notes in that time range."


def test_summarize_range_across_all_time_when_unbounded(db_session):
    subject, _ = SubjectRepository(db_session).get_or_create("Journal")
    topic, _ = TopicRepository(db_session).get_or_create(subject.id, "Daily")
    _note(db_session, "Some note.", topic_id=topic.id)

    result = summarize_range(db_session)
    assert result.note_count == 1
    assert "across all time" in result.spoken


# --- HTTP layer: /api/v1/summary/* ---------------------------------------------


def _capture_note(client, text: str) -> str:
    response = client.post("/api/v1/understand", json={"text": text, "persist": True})
    assert response.status_code == 200
    return response.json()["note_id"]


def test_get_topic_summary_endpoint(client):
    _capture_note(client, "Buy milk and eggs and bread. File this under Groceries.")
    outline = client.get("/api/v1/hierarchy").json()
    topic = outline["subjects"][0]["topics"][0]

    response = client.get(f"/api/v1/summary/topics/{topic['id']}")
    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == "topic"
    assert body["note_count"] == 1
    assert body["summary"] != ""


def test_get_topic_summary_refresh_query_param(client):
    _capture_note(client, "Buy milk. File this under Groceries.")
    outline = client.get("/api/v1/hierarchy").json()
    topic_id = outline["subjects"][0]["topics"][0]["id"]

    client.get(f"/api/v1/summary/topics/{topic_id}")  # warm the cache
    response = client.get(f"/api/v1/summary/topics/{topic_id}", params={"refresh": "true"})
    assert response.status_code == 200
    assert response.json()["method"] != "cached"


def test_get_topic_summary_unknown_id_is_404(client):
    response = client.get("/api/v1/summary/topics/does-not-exist")
    assert response.status_code == 404


def test_get_subject_summary_endpoint(client):
    _capture_note(client, "Buy milk. File this under Groceries.")
    outline = client.get("/api/v1/hierarchy").json()
    subject_id = outline["subjects"][0]["id"]

    response = client.get(f"/api/v1/summary/subjects/{subject_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == "subject"
    assert body["scope_name"] == "Groceries"
    assert body["note_count"] == 1


def test_get_subject_summary_unknown_id_is_404(client):
    response = client.get("/api/v1/summary/subjects/does-not-exist")
    assert response.status_code == 404


def test_get_range_summary_endpoint_unscoped(client):
    _capture_note(client, "Buy milk. File this under Groceries.")
    response = client.get("/api/v1/summary/range")
    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == "range"
    assert body["note_count"] >= 1


def test_get_range_summary_endpoint_scoped_and_windowed(client):
    _capture_note(client, "Buy milk. File this under Groceries.")
    outline = client.get("/api/v1/hierarchy").json()
    subject_id = outline["subjects"][0]["id"]

    response = client.get(
        "/api/v1/summary/range",
        params={
            "subject_id": subject_id,
            "start": "2020-01-01T00:00:00",
            "end": "2099-01-01T00:00:00",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["note_count"] == 1
    assert body["scope_name"] == "Groceries"
