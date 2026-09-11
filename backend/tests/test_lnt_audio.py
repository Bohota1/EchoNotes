"""The LNT framework's audio pipeline (paper Sections 3.2 and 3.3).

Covers normalisation, silence-based chunking, and the sentence-boundary rule
that the rest of the analysis depends on. Synthetic audio is generated in-test,
so none of this needs a fixture file or a Whisper model.
"""

from __future__ import annotations

import pytest

pydub = pytest.importorskip("pydub")

from pydub import AudioSegment  # noqa: E402
from pydub.generators import Sine  # noqa: E402

from app.asr.language import (  # noqa: E402
    is_english,
    language_name,
    needs_translation,
)
from app.asr.transcriber import _ensure_terminal_period  # noqa: E402
from app.audio.chunking import split_segment_on_silence  # noqa: E402
from app.audio.normalization import (  # noqa: E402
    attenuate_outlier_peaks,
    match_target_amplitude,
    normalize_segment,
)


def tone(ms: int, dbfs: float = -20.0, freq: int = 440) -> AudioSegment:
    return Sine(freq).to_audio_segment(duration=ms).apply_gain(
        dbfs - Sine(freq).to_audio_segment(duration=ms).dBFS
    )


def silence(ms: int) -> AudioSegment:
    return AudioSegment.silent(duration=ms)


class TestNormalisation:
    def test_quiet_audio_is_brought_up(self):
        quiet = tone(500, dbfs=-40)
        assert match_target_amplitude(quiet, -20.0).dBFS == pytest.approx(-20.0, abs=0.5)

    def test_loud_audio_is_brought_down(self):
        loud = tone(500, dbfs=-5)
        assert match_target_amplitude(loud, -20.0).dBFS == pytest.approx(-20.0, abs=0.5)

    def test_silence_is_left_alone(self):
        # dBFS is -inf; no finite gain makes silence louder.
        result = match_target_amplitude(silence(300), -20.0)
        assert result.dBFS == float("-inf")

    def test_outlier_burst_is_attenuated(self):
        # A burst far above the speech level - the paper's applause case.
        speech = tone(1000, dbfs=-25)
        burst = tone(200, dbfs=-3, freq=900)
        combined = speech + burst + speech

        before = combined.max_dBFS
        after = attenuate_outlier_peaks(combined).max_dBFS
        assert after < before

    def test_steady_audio_is_not_attenuated(self):
        steady = tone(2000, dbfs=-20)
        assert attenuate_outlier_peaks(steady).max_dBFS == pytest.approx(
            steady.max_dBFS, abs=0.5
        )

    def test_full_normalisation_hits_the_target(self):
        segment = tone(800, dbfs=-35) + tone(200, dbfs=-4) + tone(800, dbfs=-35)
        assert normalize_segment(segment, -20.0).dBFS == pytest.approx(-20.0, abs=1.5)


class TestChunking:
    def test_splits_on_a_pause(self):
        audio = tone(600) + silence(700) + tone(600)
        assert len(split_segment_on_silence(audio, min_silence_len_ms=400)) == 2

    def test_does_not_split_without_a_pause(self):
        assert len(split_segment_on_silence(tone(1500))) == 1

    def test_short_pause_does_not_split(self):
        audio = tone(600) + silence(120) + tone(600)
        assert len(split_segment_on_silence(audio, min_silence_len_ms=400)) == 1

    def test_continuous_audio_is_never_lost(self):
        # split_on_silence returns nothing when it finds no silence; the audio
        # has to survive that rather than vanish.
        chunks = split_segment_on_silence(tone(900), silence_thresh_dbfs=-80)
        assert chunks and len(chunks[0]) > 0

    def test_slivers_are_dropped(self):
        audio = tone(600) + silence(700) + tone(40) + silence(700) + tone(600)
        chunks = split_segment_on_silence(audio, min_silence_len_ms=400)
        assert all(len(c) >= 200 for c in chunks)

    def test_over_long_chunks_are_split(self):
        from app.config import get_settings

        cap = get_settings().max_chunk_ms
        chunks = split_segment_on_silence(tone(cap + 4000))
        assert len(chunks) > 1
        assert all(len(c) <= cap + 1 for c in chunks)

    def test_threshold_adapts_to_recording_level(self):
        # The same content at two levels must chunk the same way; a fixed
        # absolute threshold would split one and not the other.
        pattern = tone(600) + silence(700) + tone(600)
        loud = split_segment_on_silence(pattern.apply_gain(10))
        quiet = split_segment_on_silence(pattern.apply_gain(-15))
        assert len(loud) == len(quiet) == 2


class TestSentenceBoundaries:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("hello world", "hello world."),
            ("Already done.", "Already done."),
            ("What now?", "What now?"),
            ("Stop!", "Stop!"),
            ("  spaced  ", "spaced."),
            ("", ""),
        ],
    )
    def test_each_chunk_ends_one_sentence(self, text, expected):
        # Section 3.3 appends "." per chunk, because the pause that ended the
        # chunk is the sentence boundary. Everything downstream that counts
        # sentences depends on it - but the intent is one terminal mark, not
        # literally one more character, so "done." must not become "done..".
        assert _ensure_terminal_period(text) == expected


class TestLanguageHandling:
    def test_english_needs_no_translation(self):
        assert is_english("en")
        assert not needs_translation("en")

    @pytest.mark.parametrize("code", ["hi", "bn", "ta", "gu"])
    def test_other_languages_are_translated(self, code):
        assert needs_translation(code)

    def test_unknown_language_is_not_translated(self):
        # Translating text that may already be English risks mangling it.
        assert not needs_translation(None)

    def test_names_are_human_readable(self):
        assert language_name("hi") == "Hindi"
        assert language_name(None) == "unknown"
