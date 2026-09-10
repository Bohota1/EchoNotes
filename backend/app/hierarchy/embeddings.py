"""Lightweight, dependency-free text embeddings for hierarchy work.

Phase 3 needs *some* vector representation of note and topic text to compare
similarity for topic assignment ("compare with existing topics using
embeddings and/or LLM reasoning" - Team Member 2 spec). `app/rag/embeddings.py`
is owned by the retrieval work (Team Member 3, still unimplemented as of this
writing) and loading a real sentence-embedding model
(`sentence-transformers`) is a new, fairly heavy dependency that has not been
approved - see `requirements.txt`, which lists it commented out under "owned
by other team members", and the project's own instruction to ask before
adding a major dependency.

So this module ships a small, deterministic, hash-based bag-of-words vector:
each (non-stopword) token is hashed into one of `dim` buckets, the bucket is
incremented by its term frequency, and the resulting vector is L2-normalised
so a dot product is a cosine similarity. This is **not** a semantic
embedding - "cat" and "kitten" do not end up close together - but it is
enough to tell whether two pieces of text share vocabulary, which is exactly
what topic assignment on short personal voice notes needs day to day, and it
costs nothing to run and nothing to install.

**This is a placeholder, not a design decision.** If/when the team approves
`sentence-transformers` (or an API embedding model), swap the body of
`embed_text()` for a real model call - every caller in `app/hierarchy` and
`app/understanding/organizer.py` goes through this one function and
`cosine_similarity`, so nothing else has to change. See
`docs/hierarchy-handoff.md`, "Open items".
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

import numpy as np

from app.config import get_settings

_TOKEN_RE = re.compile(r"[a-z0-9]+")

#: A deliberately small English stopword list. Filtering these out keeps a
#: short note ("I need to submit the assignment") from being dominated by
#: function words that carry no topical signal.
_STOPWORDS = frozenset(
    """
    a an the this that these those is are was were be been being
    i you he she it we they me him her us them my your his its our their
    to of in on at for with by from as and or but if then so than
    do does did done have has had having will would can could should shall
    not no nor
    """.split()
)


def _tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS and len(t) > 1]


def _bucket(token: str, dim: int) -> int:
    """Deterministic hash, independent of `PYTHONHASHSEED`.

    Python's built-in `hash()` is randomised per process for strings, which
    would make embeddings incomparable across a service restart mid-way
    through a user's library. blake2b is fast, stable, and needs no extra
    dependency.
    """
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=4).digest()
    return int.from_bytes(digest, "big") % dim


def embed_text(text: str, dim: int | None = None) -> np.ndarray:
    """Hashed bag-of-words vector for one piece of text, L2-normalised.

    Returns an all-zero vector for empty or entirely-stopword text; callers
    must treat that as "no signal", not "similar to everything" -
    `cosine_similarity` special-cases zero vectors for exactly this reason.
    """
    dim = dim or get_settings().hierarchy_embedding_dim
    vector = np.zeros(dim, dtype=np.float64)
    for token in _tokenize(text or ""):
        vector[_bucket(token, dim)] += 1.0
    norm = np.linalg.norm(vector)
    if norm > 0:
        vector /= norm
    return vector


def embed_many(texts: Iterable[str], dim: int | None = None) -> np.ndarray:
    """Stack `embed_text` over several texts. Shape `(n, dim)`."""
    dim = dim or get_settings().hierarchy_embedding_dim
    rows = [embed_text(t, dim=dim) for t in texts]
    if not rows:
        return np.zeros((0, dim), dtype=np.float64)
    return np.vstack(rows)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two vectors, safe against zero vectors and
    against vectors that were not pre-normalised."""
    if a is None or b is None or not np.any(a) or not np.any(b):
        return 0.0
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def most_similar(
    query: np.ndarray, candidates: list[tuple[str, np.ndarray]]
) -> tuple[str, float] | None:
    """Best `(id, score)` pair from `[(id, embedding), ...]`, or `None` if empty."""
    best_id: str | None = None
    best_score = -1.0
    for candidate_id, embedding in candidates:
        score = cosine_similarity(query, embedding)
        if score > best_score:
            best_id, best_score = candidate_id, score
    if best_id is None:
        return None
    return best_id, best_score
