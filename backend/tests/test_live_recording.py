"""Live (start/stop) recording endpoints.

The microphone itself is faked, so these run on a machine with no audio
hardware and in CI.
"""

from __future__ import annotations

import pytest

from app.core.errors import AudioCaptureError


@pytest.fixture
def fake_recorder(monkeypatch, fixture_wav):
    """Replace the live recorder with one that returns the fixture wav."""
    from app.capture import live
    from app.capture.sources import DummyCaptureSource

    class FakeRecorder:
        def __init__(self):
            self.recording = False
            self.cancelled = False

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
            self.cancelled = True

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


class TestRecordingState:
    def test_idle_by_default(self, client, fake_recorder):
        body = client.get("/api/v1/capture/state").json()
        assert body["recording"] is False
        assert body["spoken"] == "Not recording."

    def test_reports_recording_after_start(self, client, fake_recorder):
        client.post("/api/v1/capture/start")
        body = client.get("/api/v1/capture/state").json()
        assert body["recording"] is True
        # The state has to be sayable, not only visible.
        assert "Recording" in body["spoken"]


class TestStartStop:
    def test_start_then_stop_creates_a_note(self, client, fake_recorder):
        assert client.post("/api/v1/capture/start").json()["recording"] is True

        response = client.post("/api/v1/capture/stop")
        assert response.status_code == 201
        body = response.json()
        assert body["note_id"]
        assert body["cleaned_text"]

    def test_stopped_note_is_stored(self, client, fake_recorder):
        client.post("/api/v1/capture/start")
        note_id = client.post("/api/v1/capture/stop").json()["note_id"]
        assert client.get(f"/api/v1/notes/{note_id}").status_code == 200

    def test_stop_runs_understanding(self, client, fake_recorder):
        client.post("/api/v1/capture/start")
        body = client.post("/api/v1/capture/stop").json()
        assert body["understanding"] is not None

    def test_second_start_conflicts(self, client, fake_recorder):
        # There is one microphone, so a concurrent recording is a conflict,
        # not something to queue.
        client.post("/api/v1/capture/start")
        assert client.post("/api/v1/capture/start").status_code == 503

    def test_stop_without_start_is_a_conflict(self, client, fake_recorder):
        assert client.post("/api/v1/capture/stop").status_code == 409

    def test_can_record_again_after_stopping(self, client, fake_recorder):
        client.post("/api/v1/capture/start")
        client.post("/api/v1/capture/stop")
        assert client.post("/api/v1/capture/start").status_code == 200


class TestCancel:
    def test_cancel_discards_without_storing(self, client, fake_recorder):
        client.post("/api/v1/capture/start")
        body = client.post("/api/v1/capture/cancel").json()

        assert body["recording"] is False
        assert fake_recorder.cancelled
        assert client.get("/api/v1/notes").json() == []

    def test_cancel_when_idle_is_harmless(self, client, fake_recorder):
        assert client.post("/api/v1/capture/cancel").status_code == 200

    def test_can_record_after_cancelling(self, client, fake_recorder):
        client.post("/api/v1/capture/start")
        client.post("/api/v1/capture/cancel")
        assert client.post("/api/v1/capture/start").status_code == 200
