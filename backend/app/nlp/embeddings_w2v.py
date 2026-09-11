"""Word2Vec — LNT framework, Section 3.4.3.

The paper describes both architectures of its Figure 4:

* **CBOW** — *"we predict the target center word from the context ... we do the
  one-hot encoding of all the words in the context and feed it into the model
  with a hidden layer of size equal to the context, and expect the outcome to be
  in the form of the probability distribution. For this, we have used softmax
  function."*
* **Continuous skip-gram** — *"we have to predict the context concerning the
  words ... we feed the input of the center word in the form of a one-hot
  encoded vector."*

Both are available; `WORD2VEC_ALGORITHM` selects one. In gensim that is `sg=0`
for CBOW and `sg=1` for skip-gram, and the softmax the paper describes is
`hs=1` (hierarchical softmax) rather than gensim's default negative sampling.

The vectors exist to serve §3.4.5, which builds a sentence vector by averaging
the word vectors of the sentence.

The paper also notes: *"we can always use pre-trained models to fulfill our
purpose."* A single lecture is a very small corpus to train on, so vectors
learned here describe that lecture rather than the language at large — which is
what the similarity matrix in §3.4.5 actually needs.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from app.config import get_settings

logger = logging.getLogger(__name__)


def train_word2vec(
    sentences: list[list[str]],
    algorithm: str | None = None,
    vector_size: int | None = None,
    window: int | None = None,
    min_count: int | None = None,
    epochs: int = 30,
):
    """Train a Word2Vec model over tokenized sentences.

    `algorithm` is "cbow" or "skipgram" (paper §3.4.3).
    """
    from gensim.models import Word2Vec

    settings = get_settings()
    algorithm = (algorithm or settings.word2vec_algorithm).lower()
    if algorithm not in ("cbow", "skipgram"):
        raise ValueError(f"unknown word2vec algorithm {algorithm!r}")

    usable = [s for s in sentences if s]
    if not usable:
        raise ValueError("no tokenized sentences to train on")

    model = Word2Vec(
        sentences=usable,
        vector_size=vector_size or settings.word2vec_vector_size,
        window=window or settings.word2vec_window,
        min_count=min_count if min_count is not None else settings.word2vec_min_count,
        sg=1 if algorithm == "skipgram" else 0,
        hs=1,  # hierarchical softmax - the paper's "softmax function"
        negative=0,
        epochs=epochs,
        workers=1,  # deterministic; a lecture-sized corpus does not need more
        seed=42,
    )
    logger.info(
        "word2vec (%s) trained: %d words, %d dimensions",
        algorithm, len(model.wv), model.wv.vector_size,
    )
    return model


def sentence_vector(model, tokens: list[str]) -> np.ndarray:
    """Average the word vectors of a sentence into one fixed-length vector.

    §3.4.5: *"we append it over the whole sentence and then take its average to
    have the sentence vector of fixed length."*

    Tokens absent from the vocabulary are skipped; a sentence with no known
    token yields a zero vector, which the cosine similarity treats as similar to
    nothing.
    """
    size = model.wv.vector_size
    known = [model.wv[token] for token in tokens if token in model.wv]
    if not known:
        return np.zeros(size, dtype=np.float32)
    return np.mean(known, axis=0)


def sentence_vectors(model, tokenized_sentences: list[list[str]]) -> np.ndarray:
    """Stack one vector per sentence, ready for the §3.4.5 similarity matrix."""
    if not tokenized_sentences:
        return np.zeros((0, model.wv.vector_size), dtype=np.float32)
    return np.vstack([sentence_vector(model, tokens) for tokens in tokenized_sentences])


def save_model(model, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    model.save(str(path))
    return path


def load_model(path: Path):
    from gensim.models import Word2Vec

    return Word2Vec.load(str(path))
