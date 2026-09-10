"""Word2Vec - LNT Section 3.4.3.

The paper describes both architectures shown in its Figure 4:

  - **CBOW**: predict the centre word from its context. Context words are one-hot encoded and fed
    through a hidden layer the size of the context; the output is a probability distribution
    produced by softmax and compared with the actual value, and the weights are updated from the
    loss.
  - **Continuous skip-gram**: predict the context from the centre word. The centre word goes in
    as a one-hot vector and a vector of context words comes out.

Both are supported; `WORD2VEC_ALGORITHM` selects one. These vectors feed the extractive
summarizer in Section 3.4.5, which averages the word vectors of a sentence into a sentence vector.
"""

from __future__ import annotations

from pathlib import Path


def train_word2vec(
    sentences: list[list[str]],
    algorithm: str = "cbow",
    vector_size: int = 100,
    window: int = 5,
    min_count: int = 1,
):
    """Train gensim Word2Vec. `algorithm="cbow"` sets sg=0, `"skipgram"` sets sg=1."""
    raise NotImplementedError


def sentence_vector(model, tokens: list[str]):
    """Average the word vectors of a sentence into one fixed-length vector (Section 3.4.5).

    Tokens absent from the vocabulary are skipped; an empty sentence yields a zero vector.
    """
    raise NotImplementedError


def save_model(model, path: Path) -> Path:
    raise NotImplementedError


def load_model(path: Path):
    raise NotImplementedError
