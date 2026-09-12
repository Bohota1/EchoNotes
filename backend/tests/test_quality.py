"""Obsolete: an older, pre-LNT-paper quality-scoring API (readability(),
lexical_cohesion(), connective_cohesion()) that app/quality/metrics.py no
longer has - it was rewritten against the LNT framework's Section 3.5/Table 2
(flesch_reading_ease, a single combined cohesion(), coherence(), entropy()).

tests/test_lnt_quality.py is the current, passing test file for that module -
41 tests, including a check against the paper's own Table 6 numbers. This file
is a stale duplicate left over from before the rewrite.

Safe to delete outright. Left as a skip stub rather than actually deleted only
because the file bridge to this machine could not run a delete/move command
when this cleanup was done (device_bash was down).
"""

import pytest

pytest.skip(
    "obsolete: superseded by tests/test_lnt_quality.py after app/quality/metrics.py "
    "was rewritten against the LNT paper's Table 2",
    allow_module_level=True,
)
