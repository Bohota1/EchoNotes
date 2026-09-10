"""Validation against the numbers the LNT paper reports - Sections 4.2 and 4.3.

These tests are what keep the implementation honest about "exactly like the paper". If a change
to the metrics moves Qi away from 0.727 on the reference input, either the change is wrong or the
deviation is deliberate and belongs in `docs/paper-mapping.md`.
"""

import pytest


@pytest.mark.skip(reason="pending implementation")
def test_quality_score_matches_paper(paper_reference_metrics):
    """Equation 5 over Table 6's metrics must give Qi = 0.727."""
    raise NotImplementedError


@pytest.mark.skip(reason="pending implementation")
def test_min_max_normalization_equation_4():
    """Equation 4 maps a known range onto 0-1."""
    raise NotImplementedError


@pytest.mark.skip(reason="pending implementation")
def test_theme_and_topic_density():
    """Paper's sample lecture: about one theme per 217 words and one topic per 36 words."""
    raise NotImplementedError
