"""Idea11y Section 4.1 and 4.2 tests."""

import pytest


@pytest.mark.skip(reason="pending implementation")
def test_outline_has_exactly_three_levels():
    """Subject, Topic, Note. A fourth level would break heading navigation."""
    raise NotImplementedError


@pytest.mark.skip(reason="pending implementation")
def test_heading_levels_never_skip():
    """h1 then h2 then list. A skipped level misleads heading navigation."""
    raise NotImplementedError


@pytest.mark.skip(reason="pending implementation")
def test_unfiled_subject_always_exists():
    """Every note has a parent; the Unfiled subject is the fallback."""
    raise NotImplementedError


@pytest.mark.skip(reason="pending implementation")
def test_move_marks_both_topic_summaries_stale():
    """Moving a note changes what both clusters are about."""
    raise NotImplementedError


@pytest.mark.skip(reason="pending implementation")
def test_subject_boundary_outranks_semantic_similarity():
    """Idea11y's precedence: an explicit boundary beats proximity."""
    raise NotImplementedError
