"""Content quality metrics and the quality score Qi — paper Section 3.5.

The load-bearing test here is `TestPaperTable6`: it reproduces the paper's own
reported `Qi = 0.727` from the metric values the paper prints in Table 6. If
Equation 5's implementation drifts, that test is what catches it.
"""

from __future__ import annotations

import pytest

from app.quality.metrics import (
    coherence,
    cohesion,
    compute_raw_metrics,
    count_syllables,
    entropy,
    flesch_reading_ease,
    shannon_entropy,
)
from app.quality.scaling import METRIC_RANGES, min_max, normalize_metrics
from app.quality.score import METRIC_WEIGHTS, describe, quality_score, score_text

FOCUSED = (
    "Today we will discuss deadlock in operating systems. "
    "A deadlock is defined as a state where processes are blocked because each "
    "process holds a resource and waits for another resource. "
    "Therefore, deadlock detection uses a wait for graph to find cycles. "
    "Moreover, deadlock recovery terminates those processes or preempts resources. "
    "This deadlock problem is the important point to remember."
)
SCATTERED = (
    "Cats sleep often. Quantum tunnelling requires barriers. My bicycle needs oil. "
    "The stock market closed early. Volcanoes erupt unpredictably."
)


class TestPaperTable6:
    """Reproducing the paper's reported quality score."""

    # Table 6: Readability 0.8, Cohesion 0.625, Coherence 0.592, Entropy 0.12,
    # Quality score 0.727.
    TABLE_6 = {
        "flesch_reading_ease": 0.8,
        "cohesion": 0.625,
        "coherence": 0.592,
        "entropy": 0.12,
    }

    def test_reproduces_the_reported_qi(self):
        # 0.724 from the printed values; the residual against the paper's 0.727
        # is Table 6's own rounding - readability is shown to one decimal.
        assert quality_score(self.TABLE_6) == pytest.approx(0.727, abs=0.005)

    def test_exact_with_unrounded_readability(self):
        # A true readability of 0.81 prints as "0.8" and gives 0.727 exactly.
        unrounded = dict(self.TABLE_6, flesch_reading_ease=0.81)
        assert quality_score(unrounded) == pytest.approx(0.727, abs=0.001)

    def test_a_plain_sum_would_not_be_in_range(self):
        # Equation 5 as printed is a sum of four 0-1 metrics, which reaches
        # 2.137 here - yet §4.3 says "The value of Qi lies between 0 and 1".
        # That is why the equal weighting of §3.5 is read as a mean.
        assert sum(self.TABLE_6.values()) == pytest.approx(2.137)
        assert 0.0 <= quality_score(self.TABLE_6) <= 1.0

    def test_entropy_must_be_inverted(self):
        # Table 2: "Lowers the chaos or randomness lesser is the Entropy", and
        # in Table 4 LNT wins by scoring the LOWEST entropy. Summing entropy
        # directly would reward chaos.
        low_entropy = dict(self.TABLE_6, entropy=0.1)
        high_entropy = dict(self.TABLE_6, entropy=0.9)
        assert quality_score(low_entropy) > quality_score(high_entropy)

    def test_weights_are_equal_and_sum_to_one(self):
        # §3.5: "we have assumed that each metric carries an equal weightage".
        assert len(set(METRIC_WEIGHTS.values())) == 1
        assert sum(METRIC_WEIGHTS.values()) == pytest.approx(1.0)

    def test_exactly_four_metrics(self):
        # Equation 5 has four terms. A fifth would change what Qi means.
        assert set(METRIC_WEIGHTS) == {
            "flesch_reading_ease",
            "cohesion",
            "coherence",
            "entropy",
        }


class TestEquation4:
    """Min–max normalisation."""

    def test_maps_a_known_range_onto_zero_one(self):
        assert min_max(80.0, 0.0, 100.0) == pytest.approx(0.8)
        assert min_max(0.0, 0.0, 100.0) == 0.0
        assert min_max(100.0, 0.0, 100.0) == 1.0

    def test_respects_a_custom_target_range(self):
        assert min_max(5.0, 0.0, 10.0, new_min=1.0, new_max=3.0) == pytest.approx(2.0)

    def test_clamps_out_of_range_values(self):
        # Flesch reading ease can legitimately exceed 100 or fall below 0, and a
        # metric outside 0-1 would break the bounds Qi is documented to have.
        assert min_max(130.0, 0.0, 100.0) == 1.0
        assert min_max(-20.0, 0.0, 100.0) == 0.0

    def test_zero_width_range_is_safe(self):
        assert min_max(5.0, 3.0, 3.0) == 0.0

    def test_normalises_every_metric(self):
        normalized = normalize_metrics(
            {"flesch_reading_ease": 50.0, "cohesion": 0.5, "coherence": 0.5, "entropy": 0.5}
        )
        assert normalized["flesch_reading_ease"] == pytest.approx(0.5)
        assert all(0.0 <= v <= 1.0 for v in normalized.values())

    def test_ranges_cover_all_four_metrics(self):
        assert set(METRIC_RANGES) == set(METRIC_WEIGHTS)


class TestFleschReadingEase:
    @pytest.mark.parametrize(
        "word,expected", [("the", 1), ("cat", 1), ("recovery", 4), ("deadlock", 2)]
    )
    def test_syllable_counting(self, word, expected):
        assert count_syllables(word) == expected

    def test_simple_text_reads_easier_than_complex(self):
        simple = flesch_reading_ease("The cat sat on the mat. It was a good cat.")
        complex_ = flesch_reading_ease(
            "Notwithstanding the aforementioned considerations, implementation "
            "necessitates substantial reconceptualisation."
        )
        assert simple > complex_

    def test_empty_text_scores_zero(self):
        assert flesch_reading_ease("") == 0.0


class TestCohesion:
    """Table 2: pronouns, lexical signposts, repeated keywords, anaphoric nouns."""

    def test_signposts_raise_cohesion(self):
        without = cohesion("Deadlock occurs. Detection uses a graph.")
        with_signposts = cohesion(
            "Deadlock occurs. Therefore detection uses a graph. Moreover recovery follows."
        )
        assert with_signposts > without

    def test_repeated_keywords_raise_cohesion(self):
        repeated = cohesion("Deadlock is bad. Deadlock blocks processes. Deadlock needs detection.")
        varied = cohesion("Deadlock is bad. Volcanoes erupt often. Bicycles need oil.")
        assert repeated > varied

    def test_pronouns_and_anaphora_count(self):
        assert cohesion("The process holds it. This blocks them.") > 0.0

    def test_in_unit_range(self):
        for text in [FOCUSED, SCATTERED, "Hi.", ""]:
            assert 0.0 <= cohesion(text) <= 1.0


class TestCoherence:
    def test_focused_text_beats_scattered(self):
        assert coherence(FOCUSED) > coherence(SCATTERED)

    def test_unrelated_sentences_score_near_zero(self):
        assert coherence(SCATTERED) < 0.1

    def test_single_sentence_is_coherent(self):
        # Nothing to drift from.
        assert coherence("Only one sentence.") == 1.0

    def test_empty_text(self):
        assert coherence("") == 0.0

    def test_in_unit_range(self):
        for text in [FOCUSED, SCATTERED, "One."]:
            assert 0.0 <= coherence(text) <= 1.0


class TestEntropy:
    """Table 2 read through §4.3: randomness between themes and topics."""

    def test_uniform_distribution_is_maximally_random(self):
        assert shannon_entropy([1, 1, 1, 1]) == pytest.approx(1.0)

    def test_peaked_distribution_has_low_entropy(self):
        assert shannon_entropy([100, 1, 1]) < 0.3

    def test_single_outcome_has_no_entropy(self):
        assert shannon_entropy([1]) == 0.0
        assert shannon_entropy([]) == 0.0

    def test_focused_text_is_less_chaotic_than_scattered(self):
        # §4.3: entropy measures "chaos between themes and topics".
        assert entropy(FOCUSED) < entropy(SCATTERED)

    def test_accepts_an_explicit_distribution(self):
        assert entropy({"a": 10, "b": 1}) == entropy([10, 1])

    def test_in_unit_range(self):
        for text in [FOCUSED, SCATTERED, ""]:
            assert 0.0 <= entropy(text) <= 1.0


class TestScoreText:
    def test_reports_all_four_metrics(self):
        result = score_text(FOCUSED).as_dict()
        for key in ("readability", "cohesion", "coherence", "entropy", "quality_score"):
            assert key in result

    def test_focused_text_scores_higher_than_scattered(self):
        assert score_text(FOCUSED).quality_score > score_text(SCATTERED).quality_score

    def test_qi_in_unit_range(self):
        for text in [FOCUSED, SCATTERED, "Short.", ""]:
            assert 0.0 <= score_text(text).quality_score <= 1.0

    def test_transcription_confidence_is_reported_but_not_scored(self):
        # Equation 5 has four terms and ASR confidence is not one of them, so
        # it must not move Qi.
        high = score_text(FOCUSED, transcription_confidence=1.0)
        low = score_text(FOCUSED, transcription_confidence=0.1)
        assert high.quality_score == low.quality_score
        assert low.transcription_confidence == 0.1

    def test_confidence_is_clamped(self):
        assert score_text(FOCUSED, 5.0).transcription_confidence == 1.0
        assert score_text(FOCUSED, -1.0).transcription_confidence == 0.0

    def test_raw_metrics_are_kept_alongside_normalised(self):
        result = score_text(FOCUSED)
        assert set(result.raw) == set(METRIC_RANGES)
        # Flesch is on its native scale before Equation 4 is applied.
        assert result.raw["flesch_reading_ease"] > 1.0

    def test_compute_raw_returns_exactly_the_four(self):
        assert set(compute_raw_metrics(FOCUSED)) == set(METRIC_WEIGHTS)

    def test_describe_is_plain_language(self):
        # §4.3 explains what a high and a low Qi mean; a bare number tells a
        # listener nothing.
        assert describe(0.9) != describe(0.1)
        assert "quality" in describe(0.9).lower()
