"""Hearing a spoken question right - recorder, correction, and saying it back.

Three failures from one real session, where the same question had to be asked
three times:

* **The recording cut off the last word.** Stopping closed the stream at once,
  discarding the half-filled audio block, and "interview" came back as
  "English".
* **Correction changed confident questions.** "notes related to English" became
  "notes related to linked list"; "Read the whole note" became "What is the
  whole note?", which would answer instead of read.
* **A mishearing was indistinguishable from an empty result.** The question
  heard was only on screen, which the user cannot see.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from app.api.v1 import retrieval
from app.asr.transcriber import TranscriptionResult, TranscriptSegment
from app.config import get_settings
from app.rag.intent import Intent
from app.rag.service import VoiceQueryOutcome
from app.tts.engine import speak


def heard(text: str, logprob: float = -0.2) -> TranscriptionResult:
    """A transcription of `text` the recogniser scored at `logprob`."""
    return TranscriptionResult(
        text=text,
        segments=[TranscriptSegment(0.0, 2.0, text, avg_logprob=logprob, no_speech_prob=0.01)],
    )


def outcome(ok: bool = True, method: str = "llm", spoken: str = "An answer.") -> VoiceQueryOutcome:
    return VoiceQueryOutcome(
        intent="ask", ok=ok, spoken=spoken, method=method, speech=speak(spoken)
    )


# ---------------------------------------------------------------------------
# the recorder
# ---------------------------------------------------------------------------


class TestTheRecordingKeepsTheLastWord:
    @pytest.fixture
    def fake_mic(self, monkeypatch):
        """A stand-in for `sounddevice` that records what the recorder does."""
        from app.capture import live

        events: list = []

        class FakeStream:
            last = None

            def __init__(self, *, callback, **_kwargs):
                self.callback = callback
                FakeStream.last = self

            def start(self):
                events.append("start")

            def stop(self):
                events.append("stop")

            def close(self):
                events.append("close")

        monkeypatch.setitem(sys.modules, "sounddevice", SimpleNamespace(InputStream=FakeStream))
        monkeypatch.setattr(live.time, "sleep", lambda seconds: events.append(("sleep", seconds)))
        return SimpleNamespace(events=events, stream=lambda: FakeStream.last)

    def _record_a_block(self, fake_mic):
        from app.capture.live import LiveRecorder

        recorder = LiveRecorder()
        recorder.start()
        block = np.full((1600, 1), 1000, dtype=np.int16)
        fake_mic.stream().callback(block, len(block), None, None)
        return recorder

    def test_stop_keeps_listening_before_it_closes_the_stream(self, fake_mic):
        recorder = self._record_a_block(fake_mic)
        captured = recorder.stop()

        tail = get_settings().capture_stop_tail_seconds
        assert tail > 0.5, "the tail must outlast one half-second audio block"
        assert ("sleep", tail) in fake_mic.events
        assert fake_mic.events.index(("sleep", tail)) < fake_mic.events.index("stop")
        assert Path(captured.path).exists()

    def test_the_tail_can_be_turned_off(self, fake_mic, monkeypatch):
        monkeypatch.setattr(get_settings(), "capture_stop_tail_seconds", 0.0, raising=False)
        recorder = self._record_a_block(fake_mic)
        recorder.stop()
        assert not [e for e in fake_mic.events if isinstance(e, tuple)]

    def test_the_recorder_is_usable_again_after_stopping(self, fake_mic):
        recorder = self._record_a_block(fake_mic)
        recorder.stop()
        assert not recorder.is_recording
        recorder.start()
        assert recorder.is_recording


# ---------------------------------------------------------------------------
# correction must not change what was asked
# ---------------------------------------------------------------------------


class TestCorrectionNeverChangesTheRequest:
    def test_a_request_turned_into_a_question_is_discarded(self, monkeypatch):
        monkeypatch.setattr(
            "app.nlp.correction.correct_transcript_safe",
            lambda text, **kwargs: "What is the whole note?",
        )
        assert retrieval._heard_question(heard("Read the whole note.", -0.54)) == (
            "Read the whole note."
        )

    def test_a_repair_that_keeps_the_request_is_used(self, monkeypatch):
        monkeypatch.setattr(
            "app.nlp.correction.correct_transcript_safe",
            lambda text, **kwargs: "What is system design?",
        )
        assert retrieval._heard_question(heard("Various system design?", -0.7)) == (
            "What is system design?"
        )

    def test_a_confident_hearing_tells_correction_nothing_was_unclear(self, monkeypatch):
        seen = {}

        def record(text, **kwargs):
            seen.update(kwargs)
            return text

        monkeypatch.setattr("app.nlp.correction.correct_transcript_safe", record)
        retrieval._heard_question(heard("Do I have any notes related to interview?", -0.19))
        assert seen["unclear"] == []


# ---------------------------------------------------------------------------
# saying what was heard
# ---------------------------------------------------------------------------


class TestSayingWhatWasHeard:
    QUESTION = "Do I have any notes related to English?"

    def test_nothing_found_says_what_was_heard(self):
        reply = outcome(ok=True, method="empty", spoken="I don't have any notes about English.")
        retrieval._say_what_was_heard(reply, self.QUESTION, heard(self.QUESTION))
        assert reply.spoken == (
            "I heard: Do I have any notes related to English. "
            "I don't have any notes about English."
        )
        assert reply.speech.text == reply.spoken, "the spoken directive was not updated"

    def test_a_request_not_understood_says_what_was_heard(self):
        reply = outcome(ok=False, method="", spoken="I didn't catch that.")
        retrieval._say_what_was_heard(reply, "asdf", heard("asdf"))
        assert reply.spoken.startswith("I heard: asdf.")

    def test_an_unsure_hearing_says_what_was_heard_even_with_an_answer(self):
        reply = outcome()
        retrieval._say_what_was_heard(reply, self.QUESTION, heard(self.QUESTION, logprob=-0.9))
        assert reply.spoken.startswith("I heard:")

    def test_a_confident_answer_is_not_prefixed(self):
        reply = outcome()
        retrieval._say_what_was_heard(reply, self.QUESTION, heard(self.QUESTION, logprob=-0.2))
        assert reply.spoken == "An answer."


class TestOverHttp:
    @pytest.fixture
    def mic(self, monkeypatch, fixture_wav):
        from app.capture import live
        from app.capture.sources import DummyCaptureSource

        recorder = SimpleNamespace(capture_id="fake")
        recorder.start = lambda: "fake"
        recorder.stop = lambda: DummyCaptureSource(fixture_wav).capture()
        monkeypatch.setattr(live, "get_live_recorder", lambda: recorder)
        return recorder

    def ask(self, client, fake_transcriber, text):
        fake_transcriber.text = text
        assert client.post("/api/v1/retrieval/ask/start").status_code == 200
        response = client.post("/api/v1/retrieval/ask/stop")
        assert response.status_code == 200, response.text
        return response.json()

    def test_nothing_found_is_said_with_the_question_heard(self, client, fake_transcriber, mic):
        body = self.ask(client, fake_transcriber, "Do I have any notes related to English?")
        assert body["spoken"].startswith("I heard: Do I have any notes related to English.")
        assert "about Do I have" not in body["spoken"]

    def test_found_notes_are_answered_without_the_prefix(
        self, client, fake_transcriber, mic, make_note
    ):
        make_note(
            "An interview is a formal conversation used to evaluate a candidate's "
            "skills, knowledge and suitability for the organization."
        )
        body = self.ask(client, fake_transcriber, "Do I have any notes related to interview?")
        assert body["intent"] == Intent.SEARCH.value
        assert not body["spoken"].startswith("I heard")


# ---------------------------------------------------------------------------
# the empty answer
# ---------------------------------------------------------------------------


class TestTheEmptyAnswer:
    def test_a_whole_sentence_is_not_read_back_as_a_topic(self):
        from app.rag.answerer import _empty_answer

        result = SimpleNamespace(query="Do I have any notes related to English", filter_description="")
        assert "Do I have" not in _empty_answer(Intent.ASK, result).spoken

    def test_a_topic_is_read_back(self):
        from app.rag.answerer import _empty_answer

        result = SimpleNamespace(query="English", filter_description="")
        assert _empty_answer(Intent.ASK, result).spoken == "I don't have any notes about English."


# ---------------------------------------------------------------------------
# a question is handled like a note, plus context
# ---------------------------------------------------------------------------


class TestQuestionsAreHandledLikeNotes:
    def test_a_question_gets_the_same_correction_as_a_note(self, monkeypatch):
        seen = {}

        def record(text, **kwargs):
            seen.update(kwargs)
            return text

        monkeypatch.setattr("app.nlp.correction.correct_transcript_safe", record)
        retrieval._heard_question(heard("Do I have any notes related to interview?", -0.7))
        assert seen.get("kind", "note") == "note", "a question-specific rewrite is still used"


class TestQuestionsGetContext:
    @pytest.fixture
    def mic(self, monkeypatch, fixture_wav):
        from app.capture import live
        from app.capture.sources import DummyCaptureSource

        recorder = SimpleNamespace(capture_id="fake")
        recorder.start = lambda: "fake"
        recorder.stop = lambda: DummyCaptureSource(fixture_wav).capture()
        monkeypatch.setattr(live, "get_live_recorder", lambda: recorder)
        return recorder

    def test_a_spoken_question_is_transcribed_with_the_question_prompt(
        self, client, fake_transcriber, mic
    ):
        fake_transcriber.text = "Do I have any notes related to interview?"
        client.post("/api/v1/retrieval/ask/start")
        assert client.post("/api/v1/retrieval/ask/stop").status_code == 200
        assert fake_transcriber.prompts[-1] == get_settings().question_asr_prompt

    def test_a_note_is_transcribed_without_it(self, client, fake_transcriber):
        """A note carries its own context; priming it with question phrasing
        would only steer a lecture toward "Do I have notes on"."""
        assert client.post("/api/v1/trigger", json={}).status_code in (200, 201)
        assert fake_transcriber.prompts[-1] is None

    def test_the_local_whole_file_path_uses_the_prompt(self, tmp_path):
        from app.asr.transcriber import LNTTranscriber

        sent = []

        class FakeModel:
            def transcribe(self, path, **kwargs):
                sent.append(kwargs.get("initial_prompt"))
                segment = SimpleNamespace(start=0.0, end=1.0, text="hello there",
                                          avg_logprob=-0.2, no_speech_prob=0.01)
                return [segment], SimpleNamespace(language_probability=1.0, duration=1.0)

        audio = tmp_path / "q.wav"
        audio.write_bytes(b"")
        LNTTranscriber()._transcribe_whole(
            FakeModel(), audio, audio, "en", "transcribe", prompt="Questions about my notes."
        )
        assert sent == ["Questions about my notes."]
