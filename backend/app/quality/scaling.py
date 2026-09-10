"""Min-max normalization - LNT Section 3.5, Equation 4.

The four quality metrics are on different scales and ranges, so the paper removes that
heterogeneity before summing them:

    v' = (v - min(a)) / (max(a) - min(a)) * (new_max - new_min) + new_min

with the target range 0-1. The paper assumes each metric carries **equal weight**, stating
explicitly that it had no objective for evaluating their relative weightage.
"""

from __future__ import annotations

#: Observed ranges used to project a single document onto 0-1. A single lecture has no
#: min and max of its own, so these come from the corpus and must be recorded with any
#: reported score for it to be reproducible.
METRIC_RANGES: dict[str, tuple[float, float]] = {
    "readability": (0.0, 100.0),  # Flesch reading ease
    "cohesion": (0.0, 1.0),
    "coherence": (0.0, 1.0),
    "entropy": (0.0, 1.0),        # against log2(vocabulary size)
}


def min_max(value: float, min_a: float, max_a: float, new_min: float = 0.0, new_max: float = 1.0) -> float:
    """Equation 4."""
    raise NotImplementedError


def normalize_metrics(raw: dict[str, float]) -> dict[str, float]:
    """Project every raw metric onto 0-1 using METRIC_RANGES."""
    raise NotImplementedError
