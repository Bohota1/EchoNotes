"""Groq's hosted Whisper - `app.asr.groq_transcriber`.

No network anywhere: the Groq client is faked. What these pin is everything
around the call - the request that goes out, the silence filter on what comes
back, and above all that **a failure never loses the note**: no key, no
network, a rate limit or an oversized recording all fall back to the local
model.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.asr import groq_transcriber
from app.asr import transcriber as transcriber_module
from app.asr.groq_transcriber import GroqTranscriber
from app.asr.transcriber import TranscriptionResult, TranscriptSegment
from app.config import get_settings
from app.core.errors import TranscriptionError
from tests.conftest import FakeTranscriber

REAL_WHICH = shutil.which


def seg(text, start=0.0, end=2.0, lp=-0.3, nsp=0.01):
    return {"start": start, "end": end, "text": text, "avg_logprob": lp, "no_speech_prob": nsp}


def response(*segments, text=None, duration=5.0):
    body = {"duration": duration, "language": "en", "segments": list(segments)}
    body["text"] = text if text is not None else " ".join(s["text"] for s in segments)
    return body


class FakeGroq:
    """Stands in for `groq.Groq`: records every request, returns or raises."""

    def __init__(self, reply=None, error=None):
        self.reply = reply
        self.error = error
        self.calls: list[dict] = []
        self.audio = SimpleNamespace(transcriptions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.reply


@pytest.fixture(autouse=True)
def no_ffmpeg(monkeypatch):
    """Tests run without ffmpeg unless they ask for it, so they pass anywhere."""
    monkeypatch.setattr(shutil, "which", lambda name: None)


class TestTranscript:
    def test_segments_become_the_transcript(self, fixture_wav):
        client = FakeGroq(response(
            seg("An interview is a formal conversation", 0, 4),
            seg("between an interviewer and an interviewee", 4, 8),
        ))
        result = GroqTranscriber(api_key="k", client=client).transcribe(fixture_wav)
        assert result.text.startswith(
            "An interview is a formal conversation between an interviewer and an interviewee"
        )
        assert result.text.endswith(".")
        assert result.model == "groq:whisper-large-v3"
        assert [s.avg_logprob for s in result.segments] == [-0.3, -0.3]

    def test_the_request_asks_for_segments_deterministically(self, fixture_wav):
        client = FakeGroq(response(seg("hello there")))
        GroqTranscriber(api_key="k", client=client).transcribe(fixture_wav)
        request = client.calls[0]
        assert request["model"] == "whisper-large-v3"
        assert request["response_format"] == "verbose_json"
        assert request["temperature"] == 0.0
        assert request["language"] == "en"

    def test_the_vocabulary_prompt_is_off_by_default(self, fixture_wav):
        """Measured: it steered large-v3 more than it helped (18 wrong vs 17)."""
        client = FakeGroq(response(seg("hello there")))
        GroqTranscriber(api_key="k", client=client).transcribe(fixture_wav)
        assert "prompt" not in client.calls[0]

    def test_the_vocabulary_prompt_can_be_turned_on(self, fixture_wav, monkeypatch):
        monkeypatch.setattr(get_settings(), "groq_asr_use_prompt", True, raising=False)
        client = FakeGroq(response(seg("hello there")))
        GroqTranscriber(api_key="k", client=client).transcribe(fixture_wav)
        assert client.calls[0]["prompt"] == get_settings().whisper_initial_prompt

    def test_without_ffmpeg_the_recording_is_uploaded_as_captured(self, fixture_wav):
        client = FakeGroq(response(seg("hello there")))
        GroqTranscriber(api_key="k", client=client).transcribe(fixture_wav)
        _, payload = client.calls[0]["file"]
        assert payload == Path(fixture_wav).read_bytes()

    def test_a_reply_without_segments_still_gives_text(self, fixture_wav):
        client = FakeGroq({"text": "just the text", "duration": 3.0})
        result = GroqTranscriber(api_key="k", client=client).transcribe(fixture_wav)
        assert "just the text" in result.text
        assert len(result.segments) == 1


class TestSilenceFilter:
    """Large-v3 invents sentences in silence too."""

    def test_segments_whisper_calls_silence_are_dropped(self, fixture_wav):
        client = FakeGroq(response(
            seg("real words here", nsp=0.01),
            seg("something invented", nsp=0.9),
        ))
        result = GroqTranscriber(api_key="k", client=client).transcribe(fixture_wav)
        assert "real words here" in result.text
        assert "invented" not in result.text

    def test_known_silence_artefacts_are_dropped(self, fixture_wav):
        client = FakeGroq(response(
            seg("real words here", nsp=0.01),
            seg("Thank you for watching.", nsp=0.02),
        ))
        result = GroqTranscriber(api_key="k", client=client).transcribe(fixture_wav)
        assert "watching" not in result.text.lower()


class TestNeverLosesTheNote:
    def test_an_api_failure_falls_back_to_the_local_model(self, fixture_wav):
        local = FakeTranscriber(text="spoken locally")
        client = FakeGroq(error=RuntimeError("503 service unavailable"))
        result = GroqTranscriber(api_key="k", client=client, fallback=local).transcribe(fixture_wav)
        assert result.text == "spoken locally"
        assert local.calls, "the local model was never asked"

    def test_no_key_falls_back_without_calling_groq(self, fixture_wav):
        local = FakeTranscriber(text="spoken locally")
        result = GroqTranscriber(api_key="", fallback=local).transcribe(fixture_wav)
        assert result.text == "spoken locally"

    def test_a_recording_over_the_upload_limit_falls_back(self, fixture_wav, monkeypatch):
        monkeypatch.setattr(groq_transcriber, "MAX_UPLOAD_BYTES", 10)
        local = FakeTranscriber(text="spoken locally")
        client = FakeGroq(response(seg("never sent")))
        result = GroqTranscriber(api_key="k", client=client, fallback=local).transcribe(fixture_wav)
        assert result.text == "spoken locally"
        assert client.calls == [], "an oversized recording was uploaded anyway"

    def test_with_fallback_off_a_failure_is_raised(self, fixture_wav, monkeypatch):
        monkeypatch.setattr(get_settings(), "asr_fallback_to_local", False, raising=False)
        client = FakeGroq(error=RuntimeError("rate limited"))
        with pytest.raises(TranscriptionError):
            GroqTranscriber(api_key="k", client=client).transcribe(fixture_wav)

    def test_a_missing_file_is_an_error_not_a_fallback(self, tmp_path):
        local = FakeTranscriber(text="spoken locally")
        with pytest.raises(TranscriptionError):
            GroqTranscriber(api_key="k", client=FakeGroq(), fallback=local).transcribe(
                tmp_path / "nope.wav"
            )
        assert local.calls == []


class TestPreparingTheUpload:
    @pytest.mark.skipif(REAL_WHICH("ffmpeg") is None, reason="ffmpeg is not installed")
    def test_with_ffmpeg_the_upload_is_flac_and_the_temp_file_is_removed(
        self, fixture_wav, monkeypatch
    ):
        monkeypatch.setattr(shutil, "which", REAL_WHICH)
        temp = Path(tempfile.gettempdir())
        before = set(temp.glob("echonotes-asr-*"))

        client = FakeGroq(response(seg("hello there")))
        GroqTranscriber(api_key="k", client=client).transcribe(fixture_wav)

        name, payload = client.calls[0]["file"]
        assert name.endswith(".flac")
        assert payload[:4] == b"fLaC"
        assert set(temp.glob("echonotes-asr-*")) == before, "temporary upload left behind"

    def test_an_ffmpeg_failure_uploads_the_recording_as_captured(self, fixture_wav, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda name: "ffmpeg")

        def broken(*args, **kwargs):
            raise subprocess.CalledProcessError(1, "ffmpeg")

        monkeypatch.setattr(subprocess, "run", broken)
        client = FakeGroq(response(seg("hello there")))
        GroqTranscriber(api_key="k", client=client).transcribe(fixture_wav)
        _, payload = client.calls[0]["file"]
        assert payload == Path(fixture_wav).read_bytes()


class TestChoosingTheRecogniser:
    @pytest.fixture(autouse=True)
    def fresh_default(self):
        transcriber_module.set_transcriber(None)
        yield
        transcriber_module.set_transcriber(None)

    def test_asr_backend_groq_selects_groq(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "asr_backend", "groq", raising=False)
        assert isinstance(transcriber_module.get_transcriber(), GroqTranscriber)

    def test_the_default_stays_local(self, monkeypatch):
        """Nobody's audio goes to a cloud service without choosing it."""
        monkeypatch.setattr(get_settings(), "asr_backend", "faster_whisper", raising=False)
        assert not isinstance(transcriber_module.get_transcriber(), GroqTranscriber)


class TestUnclearPassages:
    def test_only_low_confidence_segments_are_unclear(self):
        result = TranscriptionResult(
            text="clear part murky part no score",
            segments=[
                TranscriptSegment(0, 1, "clear part", avg_logprob=-0.34),
                TranscriptSegment(1, 2, "murky part", avg_logprob=-0.78),
                TranscriptSegment(2, 3, "no score"),
            ],
        )
        assert result.unclear_passages(-0.5) == ["murky part"]

    def test_the_default_floor_comes_from_settings(self):
        result = TranscriptionResult(
            text="x",
            segments=[TranscriptSegment(0, 1, "murky part", avg_logprob=-0.78)],
        )
        assert result.unclear_passages() == ["murky part"]
