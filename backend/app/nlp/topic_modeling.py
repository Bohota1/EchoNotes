"""Topic modelling — LNT framework, Section 3.4.7.

The paper: *"In the present study, we have used the Latent Dirichlet Allocation
(LDA) algorithm for performing the topic modeling."* Equation 2 gives the
probability of generating a document and Equation 3 the Dirichlet distribution,
where α is the per-document topic distribution and β the per-topic word
distribution.

§5.1 reports 9 major themes and around 55 topics from a 1947-word lecture, which
is where the default of 9 topics comes from.

LDA needs a *corpus*, not one document — a single text gives it nothing to
contrast. So each **sentence** is treated as a document, which is the standard
way to run LDA over a single transcript and is what lets it separate the
subjects within one lecture.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class LdaModel:
    """A fitted LDA model and the vectorizer that feeds it."""

    model: Any
    vectorizer: Any
    feature_names: list[str]
    num_topics: int


def fit_lda(
    documents: list[list[str]],
    num_topics: int | None = None,
    max_iter: int | None = None,
) -> LdaModel | None:
    """Fit LDA over lemmatized documents (one list of lemmas per document).

    Returns None when there is too little text to model — two sentences cannot
    support nine topics, and a model fitted on that is noise with a confident
    face.
    """
    from sklearn.decomposition import LatentDirichletAllocation
    from sklearn.feature_extraction.text import CountVectorizer

    settings = get_settings()
    max_iter = max_iter or settings.lda_max_iter

    joined = [" ".join(doc) for doc in documents if doc]
    if len(joined) < 2:
        logger.info("not enough documents for LDA (%d)", len(joined))
        return None

    # Never ask for more topics than the text can actually separate. One topic
    # per two sentences is the ceiling: beyond it LDA returns near-identical
    # topics, and their labels degenerate into ever-longer variations of the
    # same words ("Deadlock Use", "Deadlock Use Wait", ...).
    requested = num_topics or settings.lda_num_topics
    num_topics = max(1, min(requested, max(2, len(joined) // 2)))

    vectorizer = CountVectorizer(max_df=0.95, min_df=1, token_pattern=r"(?u)\b\w\w+\b")
    try:
        matrix = vectorizer.fit_transform(joined)
    except ValueError as exc:
        # Raised when every term was filtered out as a stop word.
        logger.info("LDA vectorization produced an empty vocabulary: %s", exc)
        return None

    if matrix.shape[1] == 0:
        return None

    model = LatentDirichletAllocation(
        n_components=num_topics,
        max_iter=max_iter,
        learning_method="batch",
        random_state=42,
    )
    model.fit(matrix)

    return LdaModel(
        model=model,
        vectorizer=vectorizer,
        feature_names=list(vectorizer.get_feature_names_out()),
        num_topics=num_topics,
    )


def top_terms_per_topic(fitted: LdaModel, top_n: int | None = None) -> list[dict[str, Any]]:
    """The highest-weighted terms of each topic."""
    top_n = top_n or get_settings().lda_top_terms

    topics: list[dict[str, Any]] = []
    for index, distribution in enumerate(fitted.model.components_):
        total = distribution.sum() or 1.0
        ranked = distribution.argsort()[: -top_n - 1 : -1]
        terms = [
            (fitted.feature_names[i], round(float(distribution[i] / total), 4))
            for i in ranked
        ]
        topics.append({"topic_id": index, "terms": terms})
    return topics


def label_topics(topics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Give each topic a readable label from its top terms.

    A listener can use "Deadlock Detection"; nobody can use a term-weight
    vector. Labels are built from the two strongest terms, and a label already
    used is extended with the next term rather than repeated.
    """
    used: set[str] = set()
    labelled: list[dict[str, Any]] = []

    for topic in topics:
        terms = [term for term, _ in topic["terms"]]
        label = " ".join(terms[:2]).title() if terms else f"Topic {topic['topic_id'] + 1}"

        position = 2
        while label.lower() in used and position < len(terms):
            label = " ".join(terms[: position + 1]).title()
            position += 1

        used.add(label.lower())
        labelled.append({**topic, "label": label})

    return labelled


def assign_topic(fitted: LdaModel, text: str) -> tuple[int, float]:
    """The dominant (topic_id, probability) for one piece of text."""
    from app.nlp.lemmatization import lemmatize_text

    lemmas = lemmatize_text(text)
    if not lemmas:
        return -1, 0.0

    distribution = fitted.model.transform(fitted.vectorizer.transform([" ".join(lemmas)]))[0]
    best = int(distribution.argmax())
    return best, round(float(distribution[best]), 4)


def model_topics(text: str, num_topics: int | None = None) -> list[dict[str, Any]]:
    """Fit LDA over the sentences of one transcript and return labelled topics."""
    from app.nlp.lemmatization import lemmatize_text
    from app.nlp.tokenization import sentence_tokenize

    documents = [lemmatize_text(s) for s in sentence_tokenize(text)]
    fitted = fit_lda(documents, num_topics=num_topics)
    if fitted is None:
        return []
    return label_topics(top_terms_per_topic(fitted))
