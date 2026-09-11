"""Quality score Qi — LNT framework, Section 3.5, Equation 5.

    QualityScore(Qi) = Flesch_reading_ease + Cohesion + Coherence + Entropy

Two things have to be reconciled to make that equation produce the paper's own
reported number, and both are stated by the paper itself.

**1. Entropy is inverted.** Table 2 says *"Lowers the chaos or randomness lesser
is the Entropy"*, and in Table 4 the LNT framework wins on entropy by scoring
the *lowest* value (0.15 against the experts' 0.18–0.26) while §4.2 describes
*"the higher values of the quality measures"* as the sign of its supremacy. So
low entropy is good, and it enters the sum as `1 − entropy`.

**2. The sum is averaged.** §4.3 states *"The value of Qi lies between 0 and
1"*, and §3.5 that *"each metric carries an equal weightage"*. Four normalised
metrics summed reach 4, so equal weighting means dividing by four.

Checked against Table 6 (readability 0.8, cohesion 0.625, coherence 0.592,
entropy 0.12, Qi 0.727):

    raw sum            0.8 + 0.625 + 0.592 + 0.12          = 2.137   (not 0-1)
    mean, no inversion 2.137 / 4                           = 0.534   (≠ 0.727)
    mean, inverted     (0.8 + 0.625 + 0.592 + 0.88) / 4    = 0.724   (≈ 0.727)

The residual 0.003 is the table's own rounding: Table 6 prints readability to
one decimal, and a true 0.81 gives exactly 0.727.
`tests/test_lnt_quality.py` pins this.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.quality import metrics
from app.quality.scaling import normalize_metrics

#: Equal weightage (§3.5): four metrics, one quarter each.
METRIC_WEIGHTS: dict[str, float] = {
    "flesch_reading_ease": 0.25,
    "cohesion": 0.25,
    "coherence": 0.25,
    "entropy": 0.25,
}


@dataclass
class QualityResult:
    """The four Table 2 metrics, normalised, plus Qi."""

    readability: float
    cohesion: float
    coherence: float
    entropy: float
    quality_score: float
    word_count: int = 0
    sentence_count: int = 0
    #: ASR confidence for this capture. Reported alongside, deliberately NOT a
    #: term of Equation 5 - the paper's Qi has exactly four metrics.
    transcription_confidence: float = 1.0
    raw: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "readability": round(self.readability, 4),
            "cohesion": round(self.cohesion, 4),
            "coherence": round(self.coherence, 4),
            "entropy": round(self.entropy, 4),
            "quality_score": round(self.quality_score, 4),
            "word_count": self.word_count,
            "sentence_count": self.sentence_count,
            "transcription_confidence": round(self.transcription_confidence, 4),
        }


def quality_score(normalized: dict[str, float]) -> float:
    """Equation 5 over already-normalised metrics.

    Expects the keys of `METRIC_WEIGHTS`; `entropy` is inverted here, for the
    reason in the module docstring.
    """
    contributions = {
        "flesch_reading_ease": normalized.get("flesch_reading_ease", 0.0),
        "cohesion": normalized.get("cohesion", 0.0),
        "coherence": normalized.get("coherence", 0.0),
        "entropy": 1.0 - normalized.get("entropy", 0.0),
    }
    total = sum(
        METRIC_WEIGHTS[name] * value for name, value in contributions.items()
    )
    return max(0.0, min(1.0, total))


def score_text(
    text: str,
    transcription_confidence: float = 1.0,
    model=None,
) -> QualityResult:
    """Compute the four metrics, normalise them (Eq. 4), and score Qi (Eq. 5)."""
    raw = metrics.compute_raw_metrics(text, model=model)
    normalized = normalize_metrics(raw)

    return QualityResult(
        readability=normalized["flesch_reading_ease"],
        cohesion=normalized["cohesion"],
        coherence=normalized["coherence"],
        entropy=normalized["entropy"],
        quality_score=quality_score(normalized),
        word_count=metrics.word_count(text),
        sentence_count=metrics.sentence_count(text),
        transcription_confidence=max(0.0, min(1.0, transcription_confidence)),
        raw=raw,
    )


def describe(score: float) -> str:
    """Plain-language reading of Qi, for anything spoken back to a user.

    §4.3: a Qi near 1 means *"less chaos, but more readability, clarity, and
    thematic integrity"*; near 0 means *"the text is more random, which means
    less information is present"*.
    """
    if score >= 0.75:
        return "high quality: readable, clear and thematically consistent"
    if score >= 0.55:
        return "good quality"
    if score >= 0.35:
        return "mixed quality: some of this may be unclear or wandering"
    return "low quality: random or hard to follow, with little information"
