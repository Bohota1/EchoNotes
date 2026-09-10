"""Quality scoring (Phase 2)."""

from __future__ import annotations

import pytest

from app.quality.metrics import (
    coherence,
    connective_cohesion,
    count_syllables,
    flesch_reading_ease,
    lexical_cohesion,
    readability,
)
from app.quality.score import describe, score_text

FOCUSED = (
    "Deadlock happens when processes wait for each other indefinitely. "
    "It can be prevented by ordering resource requests. "
    "Deadlock detection builds a wait for graph and looks for cycles."
)
SCATTERED = "Cats sleep often. Quantum tunnelling requires barriers. My bicycle needs oil."


class TestSyllables:
    @pytest.mark.parametrize(
        "word,expected", [("the", 1), ("cat", 1), ("recovery", 4), ("assignment", 3)]
    )
    def test_counts(self, word, expected):
        assert count_syllables(word) == expected

    def test_every_word_has_at_least_one(self):
        assert count_syllables("rhythm") >= 1

    def test_non_alpha_is_zero(self):
        assert count_syllables("123") == 0


class TestReadability:
    def test_simple_text_reads_easier_than_complex(self):
        simple = readability("The cat sat on the mat. It was a good cat.")
        complex_ = readability(
            "Notwithstanding the aforementioned considerations, the "
            "implementation necessitates substantial reconceptualisation."
        )
        assert simple > complex_

    def test_normalised_to_unit_range(self):
        for text in [FOCUSED, SCATTERED, "Hi.", ""]:
            assert 0.0 <= readability(text) <= 1.0

    def test_empty_text_scores_zero(self):
        assert readability("") == 0.0
        assert flesch_reading_ease("") == 0.0


class TestCoherence:
    def test_focused_note_beats_unrelated_sentences(self):
        assert coherence(FOCUSED) > coherence(SCATTERED)

    def test_unrelated_sentences_score_near_zero(self):
        assert coherence(SCATTERED) < 0.1

    def test_single_sentence_is_coherent(self):
        # Nothing to drift from; penalising short notes would punish exactly
        # the quick captures this app exists for.
        assert coherence("Buy milk tomorrow.") == 1.0

    def test_empty_text_scores_zero(self):
        assert coherence("") == 0.0

    def test_connective_signal_counts_without_shared_words(self):
        # Purely lexical overlap scores an ordinary to-do list at zero.
        text = "I must buy milk. Also, remember the dentist."
        assert lexical_cohesion(text) == 0.0
        assert connective_cohesion(text) > 0.0
        assert coherence(text) > 0.0

    def test_in_unit_range(self):
        for text in [FOCUSED, SCATTERED, "One.", ""]:
            assert 0.0 <= coherence(text) <= 1.0


class TestCompositeScore:
    def test_components_are_reported(self, sample_text):
        result = score_text(sample_text, 0.8)
        assert result.transcription_confidence == 0.8
        assert result.word_count > 0
        assert result.sentence_count > 0

    def test_low_asr_confidence_lowers_the_score(self, sample_text):
        low = score_text(sample_text, 0.1).quality_score
        high = score_text(sample_text, 0.9).quality_score
        assert low < high

    def test_score_in_unit_range(self, sample_text):
        for confidence in (0.0, 0.5, 1.0):
            assert 0.0 <= score_text(sample_text, confidence).quality_score <= 1.0

    def test_confidence_is_clamped(self, sample_text):
        assert score_text(sample_text, 5.0).transcription_confidence == 1.0
        assert score_text(sample_text, -1.0).transcription_confidence == 0.0

    def test_weights_sum_to_one(self):
        from app.config import get_settings

        assert get_settings().weights_ok()

    def test_ideal_text_scores_one(self):
        assert score_text("Buy milk.", 1.0).quality_score == pytest.approx(1.0)

    def test_describe_is_plain_language(self):
        # A bare number tells a listener nothing.
        assert "quality" in describe(0.9).lower()
        assert describe(0.9) != describe(0.1)
