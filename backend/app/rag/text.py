"""Token normalisation for retrieval (Phase 4).

Retrieval needs both sides of a comparison - the indexed note and the query -
normalised identically, or matching silently fails. Measured: before this,
searching "deadlocks" against a note that says "deadlock" scored *exactly zero*
on the hashed backend. Different strings hash to different buckets, so the
vectors are orthogonal, and people do not reliably match their own notes'
grammatical number when speaking a query.

The singulariser itself lives in `app.nlp.preprocess` - it is LNT §3.3's
*"converting plural words to singular words"* step, and the paper puts it in
preprocessing, not in retrieval. This module reuses it rather than keeping a
second copy, so there is one definition of what a singular form is and the two
cannot drift apart.

Applied here at query and index time, **not** by changing
`app.hierarchy.embeddings`, so Team Member 2's topic assignment keeps the exact
behaviour its similarity thresholds were tuned against.
"""

from __future__ import annotations

import re

from app.nlp.preprocess import singularize

__all__ = ["singularize", "normalize_tokens", "normalize_for_matching"]

_TOKEN_RE = re.compile(r"[a-z0-9']+")


def normalize_tokens(text: str) -> list[str]:
    """Lower-cased, singularised content tokens."""
    return [singularize(token) for token in _TOKEN_RE.findall((text or "").lower())]


def normalize_for_matching(text: str) -> str:
    """The form both indexed notes and queries are compared in.

    Applied to both sides, so what matters is that it is applied *consistently* -
    not that it produces linguistically perfect output.
    """
    return " ".join(normalize_tokens(text))
