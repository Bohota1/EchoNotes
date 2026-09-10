"""Token normalisation for retrieval (Phase 4).

Two measured problems with matching raw text, both specific to retrieval:

**Plurals.** Searching "deadlocks" against a note that says "deadlock" scored
*exactly zero* on the hashed backend - the tokens are different strings, so they
hash to different buckets and the vectors are orthogonal. People do not
reliably match their own notes' grammatical number when speaking a query, so
this is a total recall failure on an extremely common phrasing. The LNT paper
(Saini et al. 2023, Section 3.3) lists "converting plural words to singular
words" as a preprocessing step for exactly this reason; it is not implemented in
the shared `app/nlp/preprocess.py`, so it is applied here, on the retrieval path
only.

**Scope.** This normalisation is deliberately *not* pushed into
`app.nlp.preprocess` or `app.hierarchy.embeddings`. Those are Team Member 1's
and Team Member 2's, and changing what "similar" means there would silently
change topic-assignment behaviour and every threshold tuned against it. Applying
it in the retrieval provider instead means both sides of a comparison - the
indexed note and the query - normalise identically, which is the only property
matching actually requires.

The stemmer is deliberately conservative. Over-stemming collapses words that
mean different things ("bus" -> "bu"), and a false match is worse than a missed
one when the result is read aloud as though it were an answer.
"""

from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"[a-z0-9']+")

#: Words that end in 's' but are not plurals. Stripping the 's' from these
#: creates a token that matches nothing, or worse, matches something unrelated.
_NOT_PLURAL = frozenset(
    """
    is was has does goes gas bus plus this thus yes news analysis basis crisis
    thesis hypothesis series species access process address class glass pass
    less unless across always perhaps its his hers ours yours theirs status
    focus campus virus bonus census physics mathematics statistics economics
    politics ethics graphics logistics
    """.split()
)

_ES_ENDINGS = ("ses", "xes", "zes", "ches", "shes")


def singularize(token: str) -> str:
    """Best-effort English singular. Returns `token` unchanged when unsure."""
    if len(token) <= 3 or token in _NOT_PLURAL or not token.endswith("s"):
        return token

    # "policies" -> "policy", but not "series" (caught above).
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"

    # "classes" -> "class", "boxes" -> "box", "batches" -> "batch".
    for ending in _ES_ENDINGS:
        if token.endswith(ending) and len(token) > len(ending) + 1:
            return token[:-2]

    # "deadlocks" -> "deadlock". Never strip from "-ss" ("class").
    if not token.endswith("ss"):
        return token[:-1]

    return token


def normalize_tokens(text: str) -> list[str]:
    """Lower-cased, singularised content tokens."""
    return [singularize(token) for token in _TOKEN_RE.findall((text or "").lower())]


def normalize_for_matching(text: str) -> str:
    """The form both indexed notes and queries are compared in.

    Applied to both sides, so what matters is that it is applied *consistently* -
    not that it produces linguistically perfect output.
    """
    return " ".join(normalize_tokens(text))
