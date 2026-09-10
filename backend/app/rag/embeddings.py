"""Sentence embeddings - shared by retrieval and by hierarchy clustering.

One model serves both so a note's position in the hierarchy and its retrievability are computed
from the same representation. Changing the model invalidates both the Chroma index and the stored
clusters.
"""

from __future__ import annotations

import numpy as np


def get_model():
    """Load and cache the sentence-transformers model named by EMBEDDING_MODEL."""
    raise NotImplementedError


def embed(texts: list[str]) -> np.ndarray:
    raise NotImplementedError


def embed_one(text: str) -> np.ndarray:
    raise NotImplementedError
