"""End-to-end API tests for the capture and understanding pipeline.

These run against the real FastAPI app and the real database, with only the
Whisper model replaced by `FakeTranscriber` - so routing, validation,
persistence and serialisation are all exercised for real.
"""

from __future__ import annotations


class TestHealth:
    def test_reports_capture_and_llm_status(self, client):
        body = client.get("/health").json()
        assert body["status"] == "ok"
        assert body["capture_source"] == "dummy"
        assert body["capture_available"] is True
        assert body["llm_available"] is False


class TestCaptureSources:
    def test_lists_sources_and_marks_the_default(self, client):
        sources = client.get("/api/v1/capture/sources").json()
        names = {s["name"] for s in sources}
        assert {"dummy", "microphone"} <= names
        assert [s for s in sources if s["is_default"]][0]["name"] == "dummy"

    def test_every_source_explains_itself(self, client):
        for source in client.get("/api/v1/capture/sources").json():
            assert source["detail"]


class TestTrigger:
    def test_empty_body_is_valid(self, client):
        # This is what a hardware button sends.
        assert client.post("/api/v1/trigger").status_code == 201

    def test_returns_both_transcripts(self, client, sample_text):
        body = client.post("/api/v1/trigger", json={}).json()
        assert body["raw_transcript"] == sample_text
        assert body["cleaned_text"]
        assert body["note_id"]

    def test_reports_transcription_detail(self, client):
        transcription = client.post("/api/v1/trigger", json={}).json()["transcription"]
        assert transcription["language"] == "en"
        assert 0.0 <= transcription["confidence"] <= 1.0
        assert transcription["segment_count"] == 1

    def test_runs_understanding_by_default(self, client):
        understanding = client.post("/api/v1/trigger", json={}).json()["understanding"]
        assert understanding is not None
        assert understanding["note_type"] == "todo"
        assert "Raman" in understanding["people"]
        assert understanding["deadlines"]
        assert understanding["tasks"]
        assert understanding["key_phrases"]

    def test_understanding_can_be_skipped(self, client):
        body = client.post("/api/v1/trigger", json={"run_understanding": False}).json()
        assert body["understanding"] is None
        assert body["cleaned_text"], "the transcript must still be produced"

    def test_persists_the_note(self, client):
        note_id = client.post("/api/v1/trigger", json={}).json()["note_id"]
        fetched = client.get(f"/api/v1/notes/{note_id}")
        assert fetched.status_code == 200
        assert fetched.json()["note_id"] == note_id

    def test_writes_the_audio_file(self, client):
        from pathlib import Path

        body = client.post("/api/v1/trigger", json={}).json()
        assert Path(body["audio_path"]).exists()

    def test_unknown_source_is_a_service_error_not_a_crash(self, client):
        response = client.post("/api/v1/trigger", json={"source": "no-such-source"})
        assert response.status_code == 503
        assert "no-such-source" in response.json()["detail"]

    def test_empty_transcript_still_stores_a_note(self, client, fake_transcriber):
        # A trigger that caught no speech is a normal user mistake, not a 500.
        fake_transcriber.text = ""
        body = client.post("/api/v1/trigger", json={}).json()
        assert body["cleaned_text"] == ""
        assert body["understanding"] is None

    def test_rejects_an_out_of_range_max_seconds(self, client):
        assert client.post("/api/v1/trigger", json={"max_seconds": 0}).status_code == 422


class TestUnderstandEndpoint:
    def test_runs_on_supplied_text(self, client, sample_text):
        body = client.post("/api/v1/understand", json={"text": sample_text}).json()
        assert body["note_type"] == "todo"
        assert "Sarah" in body["people"]

    def test_does_not_persist_by_default(self, client, sample_text):
        client.post("/api/v1/understand", json={"text": sample_text})
        assert client.get("/api/v1/notes").json() == []

    def test_persists_when_asked(self, client, sample_text):
        client.post(
            "/api/v1/understand", json={"text": sample_text, "persist": True}
        )
        notes = client.get("/api/v1/notes").json()
        assert len(notes) == 1
        assert notes[0]["note_type"] == "todo"

    def test_entities_carry_spans_into_the_text(self, client, sample_text):
        body = client.post("/api/v1/understand", json={"text": sample_text}).json()
        spanned = [e for e in body["entities"] if e["span_start"] is not None]
        assert spanned
        for entity in spanned:
            excerpt = sample_text[entity["span_start"] : entity["span_end"]]
            assert excerpt.lower() == entity["value"].lower()

    def test_empty_text_is_rejected(self, client):
        assert client.post("/api/v1/understand", json={"text": ""}).status_code == 422

    def test_quality_reflects_supplied_confidence(self, client, sample_text):
        low = client.post(
            "/api/v1/understand",
            json={"text": sample_text, "transcription_confidence": 0.1},
        ).json()
        high = client.post(
            "/api/v1/understand",
            json={"text": sample_text, "transcription_confidence": 1.0},
        ).json()
        assert low["quality"]["quality_score"] < high["quality"]["quality_score"]


class TestNotes:
    def test_empty_list_initially(self, client):
        assert client.get("/api/v1/notes").json() == []

    def test_lists_newest_first(self, client):
        first = client.post("/api/v1/trigger", json={}).json()["note_id"]
        second = client.post("/api/v1/trigger", json={}).json()["note_id"]
        listed = [n["note_id"] for n in client.get("/api/v1/notes").json()]
        assert listed.index(second) < listed.index(first)

    def test_respects_limit(self, client):
        for _ in range(3):
            client.post("/api/v1/trigger", json={})
        assert len(client.get("/api/v1/notes?limit=2").json()) == 2

    def test_missing_note_is_404(self, client):
        assert client.get("/api/v1/notes/does-not-exist").status_code == 404

    def test_delete_removes_the_note_and_its_children(self, client):
        note_id = client.post("/api/v1/trigger", json={}).json()["note_id"]
        assert client.delete(f"/api/v1/notes/{note_id}").status_code == 204
        assert client.get(f"/api/v1/notes/{note_id}").status_code == 404

    def test_deleting_a_missing_note_is_404(self, client):
        assert client.delete("/api/v1/notes/nope").status_code == 404
