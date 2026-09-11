"""Thematic analysis — LNT framework, Sections 3.4.6 and 4.1.

Section 4.1 names the techniques: *"this framework works on the processed input
to extract the notable themes from the lecture using hapaxes, collocation, and
bigrams techniques."*

* **Hapaxes** — words occurring exactly once. Rare terms carry high information;
  a word a lecturer says once is often the name of a specific concept.
* **Collocations** — word pairs appearing together far more often than chance,
  scored by pointwise mutual information. "mutual exclusion" is a collocation;
  "the process" is not.
* **Bigrams** — the most frequent adjacent pairs, which catch the terms a
  lecture keeps returning to.

Table 5 shows the output shape: a handful of **themes**, each containing several
**topics**.

The paper produced that grouping with MeaningCloud, a commercial Excel add-in
that maps terms onto a general-knowledge taxonomy (Education, Economy, Law ...).
That is not reachable from a service and needs a subscription, so the grouping
here is derived from the text itself: candidate terms are clustered by shared
head words, and each cluster is named after its strongest member. The extraction
techniques are the paper's; the taxonomy is not, so themes are named after what
the lecture actually says rather than mapped onto external categories.
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)


def hapaxes(lemmas: list[str]) -> list[str]:
    """Words occurring exactly once (§4.1, NLTK `FreqDist.hapaxes`)."""
    if not lemmas:
        return []
    try:
        from nltk import FreqDist

        return list(FreqDist(lemmas).hapaxes())
    except Exception as exc:  # noqa: BLE001
        logger.debug("NLTK FreqDist unavailable (%s); counting directly", exc)
        counts = Counter(lemmas)
        return [word for word, count in counts.items() if count == 1]


def collocations(
    tokens: list[str], num: int | None = None, window_size: int | None = None
) -> list[tuple[str, str]]:
    """Word pairs co-occurring more than chance would predict, by PMI (§4.1)."""
    settings = get_settings()
    num = num or settings.thematic_top_n
    window_size = window_size or settings.collocation_window

    if len(tokens) < 2:
        return []
    try:
        from nltk.collocations import BigramAssocMeasures, BigramCollocationFinder

        finder = BigramCollocationFinder.from_words(tokens, window_size=window_size)
        # In a long text a pair seen once is rarity, not association, so require
        # two. Most captures here are a few sentences, where almost every real
        # phrase occurs once - filtering those out returns nothing at all.
        finder.apply_freq_filter(2 if len(tokens) > 200 else 1)

        # Likelihood ratio rather than PMI. PMI is maximised by pairs that occur
        # exactly once, so on a short transcript it ranks accidental adjacencies
        # ("define state", "cycle moreover") above the real terms. Likelihood
        # ratio does not have that bias at low counts.
        return list(finder.nbest(BigramAssocMeasures().likelihood_ratio, num))
    except Exception as exc:  # noqa: BLE001
        logger.debug("NLTK collocations unavailable (%s)", exc)
        return []


def bigrams(tokens: list[str], top_n: int | None = None) -> list[tuple[tuple[str, str], int]]:
    """Most frequent adjacent word pairs (§4.1)."""
    top_n = top_n or get_settings().thematic_top_n
    if len(tokens) < 2:
        return []
    pairs = Counter(zip(tokens, tokens[1:], strict=False))
    return pairs.most_common(top_n)


def _candidate_terms(lemmas: list[str]) -> dict[str, float]:
    """Score candidate topic terms from all three techniques.

    Scores are driven by **how often a term occurs**, with a bonus for being a
    multi-word phrase and a further bonus for being a statistical collocation.

    Frequency has to lead. Scoring every adjacent pair a flat amount lets a
    transcript's many one-off bigrams outweigh the word the lecture is actually
    about - fifty junk pairs at 1.3 each bury one real subject mentioned five
    times.
    """
    scores: dict[str, float] = defaultdict(float)
    frequencies = Counter(lemmas)
    once = set(hapaxes(lemmas))

    # Multi-word phrases, weighted by how often they recur.
    for (first, second), count in bigrams(lemmas):
        if first in once and second in once and count < 2:
            # Two words each said once, adjacent once: an accident, not a term.
            continue
        scores[f"{first} {second}"] += count * 1.5

    # A statistical collocation is stronger evidence of a real term.
    for first, second in collocations(lemmas):
        scores[f"{first} {second}"] += 1.0

    # Single words, weighted by frequency. Hapaxes score low: rare terms carry
    # information, but a word said once rarely names the lecture's subject.
    for lemma, count in frequencies.items():
        if len(lemma) <= 3:
            continue
        scores[lemma] += 0.3 if lemma in once else float(count)

    return dict(scores)


def _group_into_themes(
    scored: dict[str, float], max_themes: int, max_topics: int | None = None
) -> list[dict[str, Any]]:
    """Cluster candidate terms into themes by shared words.

    Multi-word terms sharing a word belong to the same theme: "deadlock
    detection" and "deadlock recovery" are two topics under one theme. Each
    cluster is named after its highest-scoring member.
    """
    ordered = sorted(scored.items(), key=lambda kv: kv[1], reverse=True)

    themes: list[dict[str, Any]] = []
    claimed: set[str] = set()

    for term, score in ordered:
        if term in claimed:
            continue
        words = set(term.split())

        for theme in themes:
            if words & theme["_words"]:
                theme["topics"].append(term)
                theme["_words"] |= words
                theme["weight"] += score
                claimed.add(term)
                break
        else:
            if len(themes) >= max_themes:
                continue
            themes.append(
                {
                    "theme": term.title(),
                    "topics": [term],
                    "weight": score,
                    "_words": words,
                }
            )
            claimed.add(term)

    total = sum(theme["weight"] for theme in themes) or 1.0
    for theme in themes:
        theme.pop("_words", None)
        theme["weight"] = round(theme["weight"] / total, 4)

    themes = sorted(themes, key=lambda t: t["weight"], reverse=True)

    # Spread the topic budget over the themes, heaviest first, so a short note
    # does not report more topics than it has content for.
    if max_topics is not None:
        remaining = max_topics
        for theme in themes:
            share = max(1, round(remaining * theme["weight"])) if remaining > 0 else 1
            theme["topics"] = theme["topics"][: max(1, min(share, remaining or 1))]
            remaining = max(0, remaining - len(theme["topics"]))

    return themes


#: The density the paper reports for its sample lecture (§5.1): 1947 words gave
#: 9 themes and about 55 topics, i.e. one theme per ~217 words and one topic per
#: ~36 words.
WORDS_PER_THEME = 217
WORDS_PER_TOPIC = 36


def extract_themes(
    text: str,
    lemmas: list[str] | None = None,
    max_themes: int | None = None,
    max_topics: int | None = None,
) -> list[dict[str, Any]]:
    """Themes and their topics — the structure of the paper's Table 5.

    How many of each is derived from the length of the text, using the density
    §5.1 reports. Without that, a fifty-word note is carved into nine themes and
    fifty topics: every adjacent word pair becomes a "topic", and the density
    figures come out two orders of magnitude away from the paper's.

    Returns `[{"theme": str, "topics": [str, ...], "weight": float}, ...]`.
    """
    from app.nlp.lemmatization import lemmatize_text

    if lemmas is None:
        lemmas = lemmatize_text(text)
    if not lemmas:
        return []

    word_count = len(text.split()) or len(lemmas)
    ceiling = get_settings().lda_num_topics

    if max_themes is None:
        max_themes = max(1, min(ceiling, round(word_count / WORDS_PER_THEME) or 1))
    if max_topics is None:
        max_topics = max(len(range(max_themes)), round(word_count / WORDS_PER_TOPIC))
        max_topics = max(max_themes, max_topics)

    return _group_into_themes(_candidate_terms(lemmas), max_themes, max_topics)


def theme_density(themes: list[dict[str, Any]], word_count: int) -> dict[str, float]:
    """Words per theme and words per topic.

    §5.1 reports *"one theme for every 217 words and a topic for every 36
    words"* for the sample lecture, and uses it as a sanity check on the
    analysis. The same figures are reported here for comparison.
    """
    topic_count = sum(len(theme["topics"]) for theme in themes)
    return {
        "themes": len(themes),
        "topics": topic_count,
        "words": word_count,
        "words_per_theme": round(word_count / len(themes), 2) if themes else 0.0,
        "words_per_topic": round(word_count / topic_count, 2) if topic_count else 0.0,
    }
