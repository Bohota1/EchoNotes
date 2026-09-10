"""Topic modeling with LDA - LNT Section 3.4.7.

The paper: "In the present study, we have used the Latent Dirichlet Allocation (LDA) algorithm for
performing the topic modeling." Equation 2 gives the probability of generating a document and
Equation 3 the Dirichlet distribution; alpha is the per-document topic distribution, beta the
per-topic word distribution.

The sample lecture in Section 5.1 produced 9 themes and about 55 topics, which is where the
default `LDA_NUM_TOPICS=9` comes from.
"""

from __future__ import annotations

from typing import Any


def fit_lda(documents: list[list[str]], num_topics: int = 9, max_iter: int = 20):
    """Fit LDA over lemmatized documents. Returns the fitted model and its vectorizer."""
    raise NotImplementedError


def top_terms_per_topic(model, vectorizer, top_n: int = 10) -> list[dict[str, Any]]:
    """[{"topic_id": int, "terms": [(term, weight), ...]}, ...]"""
    raise NotImplementedError


def label_topics(topics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Give each topic a human-readable label from its top terms.

    A screen reader user hears the label, never the term vector, so an unlabelled topic is
    useless in the outline.
    """
    raise NotImplementedError


def assign_topic(model, vectorizer, text: str) -> tuple[int, float]:
    """Return the dominant (topic_id, probability) for one note."""
    raise NotImplementedError
