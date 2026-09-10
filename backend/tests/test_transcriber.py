"""The real Whisper transcriber.

Marked `slow` and skipped when faster-whisper is not installed. The first run
downloads the model, so the rest of the suite uses `FakeTranscriber` instead.

    pytest -m slow          run these
    pytest -m "not slow"    skip them
"""

from __future__ import annotations

import pytest

from app.asr.transcriber import (
    TranscriptionResult,
    TranscriptSegment,
    logprob_to_confidence,
)

faster_whisper = pytest.importorskip("faster_whisper")

FIXTURE = "data/fixtures/sample_capture.wav"


class TestConfidenceMapping:
    """Pure functions - fast, no model needed."""

    def test_high_logprob_maps_to_high_confidence(self):
        assert logprob_to_confidence(-0.1) > 0.85

    def test_low_logprob_maps_to_low_confidence(self):
        assert logprob_to_confidence(-2.0) < 0.2

    def test_missing_logprob_is_zero(self):
        assert logprob_to_confidence(None) == 0.0

    @pytest.mark.parametrize("value", [-10.0, -1.0, 0.0, 5.0])
    def test_always_in_unit_range(self, value):
        assert 0.0 <= logprob_to_confidence(value) <= 1.0


class TestResultAggregation:
    def test_avg_logprob_is_weighted_by_segment_length(self):
        # A short uncertain segment must not outweigh a long clean one.
        result = TranscriptionResult(
            text="x",
            segments=[
                TranscriptSegment(0.0, 10.0, "long", avg_logprob=-0.1),
                TranscriptSegment(10.0, 10.5, "short", avg_logprob=-2.0),
            ],
        )
        assert result.avg_logprob == pytest.approx(-0.19, abs=0.02)

    def test_no_segments_gives_no_logprob(self):
        assert TranscriptionResult(text="").avg_logprob is None

    def test_is_empty_detects_blank_text(self):
        assert TranscriptionResult(text="   ").is_empty
        assert not TranscriptionResult(text="hi").is_empty


@pytest.mark.slow
class TestRealTranscription:
    def test_transcribes_the_fixture(self):
        from pathlib import Path

        from app.asr.transcriber import FasterWhisperTranscriber

        audio = Path(FIXTURE)
        if not audio.exists():
            pytest.skip("run scripts/make_fixture_audio.py first")

        result = FasterWhisperTranscriber().transcribe(audio)
        assert not result.is_empty
        assert result.language == "en"
        assert result.segments
        assert "assignment" in result.text.lower()

    def test_missing_file_raises(self):
        from pathlib import Path

        from app.asr.transcriber import FasterWhisperTranscriber
        from app.core.errors import TranscriptionError

        with pytest.raises(TranscriptionError):
            FasterWhisperTranscriber().transcribe(Path("no-such-audio.wav"))
