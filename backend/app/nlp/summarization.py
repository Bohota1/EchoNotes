"""Extractive text summarization — LNT framework, Section 3.4.5.

The paper chooses extractive over abstractive and gives the procedure:

1. *"we first clean the text by removing extra white spaces, and punctuations
   except '.', lowering the case of each word"*
2. *"We do tokenization of each sentence and create the vectors of sentences by
   using the word2vec technique. Furthermore, we append it over the whole
   sentence and then take its average to have the sentence vector of fixed
   length."*
3. *"we could create the similarity matrix using cosine similarity"* (Equation 1),
   chosen *"because of its speed and usability over sparse data"*
4. *"we represent data in the form of a graph having nodes as sentences and
   edges will represent the similarities"*
5. *"we arrange the sentences as per their ranks"* — *"much similar to the Google
   page ranking system"*
6. *"we print out the first K sentences of ranking"*

Sentence scoring draws on the features the paper lists from Ferreira et al.
(2013): *"Frequency of words ..., Sentence position, Cue words in between the
sentences, Similarity for other sentences, sentence length, proper noun, and,
sentence reduction."*

One judgement the paper leaves open: it says to print the first K *of ranking*.
Selection is by rank, but the K chosen sentences are emitted in their original
order, because a summary read aloud has to follow the order the lecture was
delivered in.
"""

from __future__ import annotations

import logging
import re

import numpy as np

from app.config import get_settings

logger = logging.getLogger(__name__)

#: Phrases that mark a sentence as carrying the point — the paper's "cue words".
CUE_WORDS: frozenset[str] = frozenset(
    """
    important significant note remember key main summary conclude conclusion
    therefore thus finally result results means definition define defined
    essential crucial fundamental primary notably especially overall
    """.split()
)

_MULTI_SPACE = re.compile(r"\s+")
_KEEP_PERIOD = re.compile(r"[^\w\s.]")
_PROPER_NOUN = re.compile(r"\b[A-Z][a-z]+\b")


def clean_for_summary(text: str) -> str:
    """Step 1: strip extra whitespace and all punctuation except ".", lowercase."""
    text = _KEEP_PERIOD.sub(" ", text)
    text = _MULTI_SPACE.sub(" ", text)
    return text.strip().lower()


def cosine_similarity_matrix(vectors: np.ndarray) -> np.ndarray:
    """Equation 1: `sim(A,B) = A·B / (|A| |B|)`, pairwise over every sentence."""
    if vectors.size == 0:
        return np.zeros((0, 0), dtype=np.float32)

    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    # A zero vector (a sentence with no in-vocabulary word) would divide by
    # zero; leaving its similarity at 0 is the honest answer.
    safe = np.where(norms == 0, 1.0, norms)
    unit = vectors / safe
    similarity = unit @ unit.T
    similarity[norms.ravel() == 0, :] = 0.0
    similarity[:, norms.ravel() == 0] = 0.0
    np.fill_diagonal(similarity, 0.0)  # a sentence does not support itself
    return np.clip(similarity, 0.0, 1.0)


def build_similarity_graph(similarity: np.ndarray):
    """Step 4: nodes are sentences, edge weights are similarities."""
    import networkx as nx

    return nx.from_numpy_array(similarity)


def rank_sentences(similarity: np.ndarray) -> dict[int, float]:
    """Step 5: PageRank over the similarity graph — the paper's Google analogy."""
    import networkx as nx

    if similarity.shape[0] == 0:
        return {}
    if similarity.shape[0] == 1:
        return {0: 1.0}

    graph = build_similarity_graph(similarity)
    try:
        return nx.pagerank(graph, weight="weight")
    except nx.PowerIterationFailedConvergence:
        # Degenerate graphs (all-zero similarity) never converge. Fall back to
        # equal weighting so the feature scores alone decide the ranking.
        logger.debug("PageRank did not converge; weighting sentences equally")
        return {i: 1.0 / similarity.shape[0] for i in range(similarity.shape[0])}


def score_sentence_features(
    sentence: str,
    index: int,
    total: int,
    word_scores: dict[str, float],
    similarity_row: np.ndarray | None = None,
) -> float:
    """The Ferreira et al. (2013) feature set the paper names, combined into 0–1.

    Each feature is normalised to 0–1 and averaged, so no single one dominates.
    """
    from app.nlp.lemmatization import lemmatize_text

    lemmas = lemmatize_text(sentence)
    features: list[float] = []

    # Frequency of words: mean score of the sentence's content words.
    if lemmas and word_scores:
        features.append(
            sum(word_scores.get(lemma, 0.0) for lemma in lemmas) / len(lemmas)
        )
    else:
        features.append(0.0)

    # Sentence position: earlier sentences carry more of the point.
    features.append(1.0 - (index / total) if total else 0.0)

    # Cue words.
    lowered = sentence.lower()
    features.append(1.0 if any(cue in lowered for cue in CUE_WORDS) else 0.0)

    # Similarity to other sentences.
    if similarity_row is not None and similarity_row.size:
        features.append(float(np.clip(similarity_row.mean() * 2.0, 0.0, 1.0)))
    else:
        features.append(0.0)

    # Sentence length: mid-length sentences are the informative ones. Very short
    # ones say little; very long ones are usually digressions.
    word_count = len(sentence.split())
    if word_count < 20:
        features.append(min(word_count / 20.0, 1.0))
    else:
        features.append(max(0.0, 1.0 - (word_count - 20) / 40.0))

    # Proper nouns, skipping the sentence-initial capital.
    proper = len(_PROPER_NOUN.findall(sentence[1:])) if len(sentence) > 1 else 0
    features.append(min(proper / 3.0, 1.0))

    # Sentence reduction: the share of the sentence that survives stop-word and
    # noise-word removal, i.e. how much of it is content.
    features.append(len(lemmas) / word_count if word_count else 0.0)

    return sum(features) / len(features)


def summarize(
    text: str,
    top_k: int | None = None,
    model=None,
    return_details: bool = False,
):
    """The full §3.4.5 pipeline. Returns the summary, or (summary, details)."""
    from app.nlp.embeddings_w2v import sentence_vectors, train_word2vec
    from app.nlp.lemmatization import lemmatize_text
    from app.nlp.tokenization import sentence_tokenize
    from app.nlp.word_frequency import normalized_frequency_table

    settings = get_settings()
    sentences = sentence_tokenize(text)

    if not sentences:
        return ("", {"sentences": 0, "selected": []}) if return_details else ""
    if len(sentences) == 1:
        return (text.strip(), {"sentences": 1, "selected": [0]}) if return_details else text.strip()

    # Steps 1-2: clean, tokenize per sentence, build sentence vectors.
    tokenized = [lemmatize_text(clean_for_summary(s)) for s in sentences]

    if model is None:
        try:
            model = train_word2vec(
                tokenized, epochs=settings.word2vec_epochs
            )
        except Exception as exc:  # noqa: BLE001 - a tiny corpus can fail to train
            logger.warning("word2vec training failed (%s); ranking on features alone", exc)
            model = None

    if model is not None:
        vectors = sentence_vectors(model, tokenized)
        similarity = cosine_similarity_matrix(vectors)
    else:
        similarity = np.zeros((len(sentences), len(sentences)), dtype=np.float32)

    # Steps 4-5: graph, PageRank, plus the feature scores.
    pagerank = rank_sentences(similarity)
    word_scores = normalized_frequency_table([w for s in tokenized for w in s])

    combined: dict[int, float] = {}
    for index, sentence in enumerate(sentences):
        feature_score = score_sentence_features(
            sentence,
            index,
            len(sentences),
            word_scores,
            similarity[index] if similarity.size else None,
        )
        # PageRank values sum to 1, so they are rescaled by the sentence count
        # to sit on the same 0-1 footing as the feature score.
        graph_score = pagerank.get(index, 0.0) * len(sentences)
        combined[index] = 0.5 * graph_score + 0.5 * feature_score

    # Step 6: the first K of the ranking.
    if top_k is None:
        top_k = max(1, min(settings.summary_top_k, round(len(sentences) * settings.summary_ratio)))
    top_k = max(1, min(top_k, len(sentences)))

    ranked = sorted(combined, key=lambda i: combined[i], reverse=True)[:top_k]
    selected = sorted(ranked)  # emit in delivery order
    summary = " ".join(sentences[i] for i in selected)

    if not return_details:
        return summary

    return summary, {
        "sentences": len(sentences),
        "selected": selected,
        "scores": {i: round(combined[i], 4) for i in ranked},
        "top_k": top_k,
    }
