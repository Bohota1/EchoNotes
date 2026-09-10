"""Quality score Qi - LNT Section 3.5, Equation 5.

    Quality Score (Qi) = Flesch_reading_ease + Cohesion + Coherence + Entropy

with each term already min-max normalized to 0-1 and equally weighted. Qi itself lies in 0-1:
close to 1 means high readability, thematic integrity and clarity with little chaos; close to 0
means the text is random and carries little information.

Paper reference point (Table 6, sample lecture): readability 0.8, cohesion 0.625, coherence
0.592, entropy 0.12, **Qi = 0.727**. `tests/test_quality_validation.py` checks the implementation
reproduces that from the same inputs.
"""

from __future__ import annotations

#: Equal weights, per Section 3.5.
METRIC_WEIGHTS: dict[str, float] = {
    "readability": 0.25,
    "cohesion": 0.25,
    "coherence": 0.25,
    "entropy": 0.25,
}


def quality_score(normalized: dict[str, float]) -> float:
    """Equation 5, scaled back into 0-1 by the equal weights above."""
    raise NotImplementedError


def describe(qi: float) -> str:
    """One spoken sentence describing the score.

    Users hear this, so it says what the number means rather than reading the number alone.
    """
    raise NotImplementedError
