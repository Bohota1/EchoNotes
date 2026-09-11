"""Min–max normalisation — LNT framework, Section 3.5, Equation 4.

*"While analyzing the calculated metrics, it is observed that each metric has
values on a different scale and carries distinct ranges. To measure the value of
the quality score (Qi), we need to remove heterogeneity among these metrics. For
this purpose, we have applied the min–max normalization."*

    V' = (V − min(a)) / (max(a) − min(a)) × (new_max(a) − new_min(a)) + new_min(A)

with the target range 0–1. *"we have assumed that each metric carries an equal
weightage."*
"""

from __future__ import annotations

#: The observed range of each metric, used as min(a) / max(a) in Equation 4.
#:
#: Equation 4 needs a population min and max, but a single lecture has none of
#: its own. These are the conventional ranges of each measure: Flesch reading
#: ease is defined on 0-100, and the other three are constructed on 0-1 by the
#: functions in `metrics.py`. Any reported score is only reproducible alongside
#: the ranges it was computed with, so they live here rather than inline.
METRIC_RANGES: dict[str, tuple[float, float]] = {
    "flesch_reading_ease": (0.0, 100.0),
    "cohesion": (0.0, 1.0),
    "coherence": (0.0, 1.0),
    "entropy": (0.0, 1.0),
}


def min_max(
    value: float,
    min_a: float,
    max_a: float,
    new_min: float = 0.0,
    new_max: float = 1.0,
) -> float:
    """Equation 4, clamped to the target range.

    A value outside [min_a, max_a] is clamped rather than allowed to leave the
    scale: Flesch reading ease can legitimately exceed 100 or fall below 0, and
    a metric outside 0-1 would break the bounds `Qi` is documented to have.
    """
    span = max_a - min_a
    if span == 0:
        return new_min
    scaled = (value - min_a) / span * (new_max - new_min) + new_min
    return max(new_min, min(new_max, scaled))


def normalize_metrics(raw: dict[str, float]) -> dict[str, float]:
    """Apply Equation 4 to every metric, using METRIC_RANGES."""
    normalized: dict[str, float] = {}
    for name, value in raw.items():
        low, high = METRIC_RANGES.get(name, (0.0, 1.0))
        normalized[name] = min_max(value, low, high)
    return normalized
