"""Shared fixtures."""

import pytest


@pytest.fixture
def sample_transcript() -> str:
    """A short English transcript standing in for a lecture, used across the NLP tests."""
    raise NotImplementedError


@pytest.fixture
def paper_reference_metrics() -> dict[str, float]:
    """Table 6 of Saini et al. (2023) - the sample lecture's reported quality metrics."""
    return {
        "readability": 0.8,
        "cohesion": 0.625,
        "coherence": 0.592,
        "entropy": 0.12,
        "quality_score": 0.727,
    }
