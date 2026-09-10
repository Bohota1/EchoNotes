"""Embedding providers for retrieval (Phase 4).

One interface, two backends, selected by `EMBEDDING_BACKEND`:

  ``hashed``  (default) - Team Member 2's dependency-free hashed bag-of-words
              vectorizer, reused directly from `app.hierarchy.embeddings` rather
              than reimplemented here. Zero install, zero download, deterministic
              across restarts, and it keeps the whole project's "runs offline
              with no API key" property intact.

  ``sentence-transformers`` - a real semantic model (default
              ``all-MiniLM-L6-v2``). Opt-in, because it pulls in torch.

**Know what the default cannot do.** The hashed backend matches shared
vocabulary, not meaning. A query for "machine learning" will *not* retrieve a
note that only ever says "neural nets and gradient descent" - there is no token
overlap, so the cosine similarity is 0. That is a real recall limit, and it is
why `app.rag.retriever` also runs a lexical pass and why the answerer is honest
when nothing was retrieved. Switch `EMBEDDING_BACKEND=sentence-transformers`
for semantic recall.

The interface is deliberately narrow - `embed_one`, `embed_many`, `dimension`,
`name` - so a third backend (an embeddings API, say) is a new subclass and a
factory line, with nothing else in the codebase touched.
"""

from __future__ import annotations

import abc
import logging
from functools import lru_cache

from app.config import get_settings

logger = logging.getLogger(__name__)


class EmbeddingProvider(abc.ABC):
    """Turns text into a vector. Implementations must be deterministic for a
    given text, because stored vectors and query vectors have to be comparable
    across process restarts."""

    #: Short identifier, recorded alongside indexed vectors. Changing backends
    #: invalidates an existing index, and this is how that is detected.
    name: str = "base"

    #: True when similarity is token overlap rather than meaning. The retriever
    #: uses this to decide whether a nonzero cosine with no shared vocabulary is
    #: evidence (it is not, for a hashed backend - it is a hash collision).
    is_lexical: bool = False

    @property
    @abc.abstractmethod
    def dimension(self) -> int:
        """Length of the vectors this provider returns."""

    @abc.abstractmethod
    def embed_many(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch. Batching matters for the model-based backends."""

    def embed_one(self, text: str) -> list[float]:
        return self.embed_many([text])[0]


class HashedEmbeddingProvider(EmbeddingProvider):
    """Delegates to `app.hierarchy.embeddings` - Team Member 2's vectorizer.

    Reused rather than copied on purpose. Topic assignment and retrieval then
    agree about what "similar" means, and when the team swaps in a real model
    there is one function to change, not two implementations to keep in step.
    """

    name = "hashed"
    is_lexical = True

    def __init__(self, dim: int | None = None):
        self._dim = dim or get_settings().hierarchy_embedding_dim

    @property
    def dimension(self) -> int:
        return self._dim

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        from app.hierarchy.embeddings import embed_text

        from app.rag.text import normalize_for_matching

        # Normalise before hashing so "deadlocks" and "deadlock" land in the
        # same bucket. Measured: without this they score exactly 0.0 against
        # each other. Applied here rather than inside `embed_text` so Team
        # Member 2's topic assignment keeps the exact behaviour it was tuned
        # against - see `app/rag/text.py`.
        return [
            embed_text(normalize_for_matching(text), dim=self._dim).tolist()
            for text in texts
        ]


class SentenceTransformerEmbeddingProvider(EmbeddingProvider):
    """Real semantic embeddings. Optional dependency.

    The model loads lazily on first use, not in `__init__`, so importing this
    module never costs a model load and the factory can fall back cleanly when
    the package is absent.
    """

    name = "sentence-transformers"
    is_lexical = False

    def __init__(self, model_name: str):
        self.model_name = model_name
        self._model = None
        self._dimension: int | None = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            logger.info("loading embedding model %s", self.model_name)
            self._model = SentenceTransformer(self.model_name)
            self._dimension = int(self._model.get_sentence_embedding_dimension())
        return self._model

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            self._load()
        return int(self._dimension or 0)

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        model = self._load()
        vectors = model.encode(
            texts, normalize_embeddings=True, show_progress_bar=False
        )
        return [list(map(float, v)) for v in vectors]


def _build_provider() -> EmbeddingProvider:
    settings = get_settings()
    backend = (settings.embedding_backend or "hashed").strip().lower()

    if backend in {"sentence-transformers", "sentence_transformers", "st"}:
        try:
            import sentence_transformers  # noqa: F401
        except ImportError:
            # Not fatal. An unavailable optional dependency should degrade the
            # quality of retrieval, never take the service down.
            logger.warning(
                "EMBEDDING_BACKEND=%s but sentence-transformers is not installed; "
                "falling back to the hashed backend. Install it with "
                "`pip install sentence-transformers` for semantic retrieval.",
                backend,
            )
            return HashedEmbeddingProvider()
        return SentenceTransformerEmbeddingProvider(settings.embedding_model)

    if backend != "hashed":
        logger.warning("unknown EMBEDDING_BACKEND %r, using hashed", backend)
    return HashedEmbeddingProvider()


@lru_cache
def get_embedding_provider() -> EmbeddingProvider:
    """The configured provider. Cached so a model loads at most once."""
    return _build_provider()


def reset_embedding_provider_cache() -> None:
    """Drop the cached provider. Tests use this after changing settings."""
    get_embedding_provider.cache_clear()
