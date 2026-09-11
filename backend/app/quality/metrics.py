"""Content quality metrics — LNT framework, Section 3.5, Table 2.

The paper defines exactly four metrics, and Equation 5 sums those four. Nothing
may be added here without changing what `Qi` means.

Table 2 defines them as:

* **Flesch_reading_ease** — *"the level of ease to read English text"*.
* **Cohesion** — *"the use of vocabulary and grammatical structure to make the
  connection between ideas within the text ... achieved by the appropriate use
  of Pronouns, Lexical signposts, repeating Keywords, and anaphoric nouns"*.
* **Coherence** — *"the contextual fitness of the text that contributes to
  understanding the meaning or message by promoting the thematic integrity of
  the text"*.
* **Entropy** — *"a measurement of Randomness. Lowers the chaos or randomness
  lesser is the Entropy"*.

Cohesion is implemented as the four devices Table 2 names, because the paper
names them. Coherence measures continuity of subject between adjacent sentences,
and entropy is taken over the *theme* distribution rather than the word
distribution - see each function for why.

Interpretation from §4.3, used by `describe_*` below: for lecture speech a
cohesion/coherence range of 0.5–0.75 is good, because speakers repeat
themselves; entropy is best near 0 or near 1, with 0.5 indicating *"more chaos
between themes and topics"*.
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter

logger = logging.getLogger(__name__)

_VOWEL_GROUP = re.compile(r"[aeiouy]+")
_NON_ALPHA = re.compile(r"[^a-z]")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"[A-Za-z0-9']+")

# --- Table 2 cohesion devices ----------------------------------------------

#: "Pronouns"
PRONOUNS: frozenset[str] = frozenset(
    """
    i me my mine myself you your yours yourself he him his himself she her hers
    herself it its itself we us our ours ourselves they them their theirs
    themselves
    """.split()
)

#: "anaphoric nouns" - words that point back at something already said
ANAPHORIC: frozenset[str] = frozenset(
    """
    this that these those such same one ones another former latter above
    aforementioned it they idea issue problem case point reason result
    """.split()
)

#: "Lexical signposts" - the connectives that signal how ideas relate
LEXICAL_SIGNPOSTS: frozenset[str] = frozenset(
    """
    however therefore thus hence moreover furthermore additionally besides also
    consequently accordingly meanwhile nevertheless nonetheless although though
    because since while whereas similarly likewise conversely instead finally
    first second third next then afterwards subsequently overall in-addition
    for-example for-instance in-contrast as-a-result on-the-other-hand
    """.split()
)

STOPWORDS: frozenset[str] = frozenset(
    """
    a an the and or but if then than that this these those there here
    is am are was were be been being do does did doing have has had having
    will would shall should can could may might must to of in on at by for
    with from into about over under again further so very just too also not
    no nor only own same s t don now what which who whom whose when where why
    how all any both each few more most other some such as up down out off
    because while during before after i me my we us our you your he him his
    she her it its they them their
    """.split()
)


def split_sentences(text: str) -> list[str]:
    if not text or not text.strip():
        return []
    return [s.strip() for s in _SENTENCE_SPLIT.split(text.strip()) if s.strip()]


def tokenize_words(text: str) -> list[str]:
    return _WORD.findall(text)


# --- Flesch reading ease ----------------------------------------------------


def count_syllables(word: str) -> int:
    """Approximate syllable count: vowel groups, less a silent trailing e."""
    word = _NON_ALPHA.sub("", word.lower())
    if not word:
        return 0
    count = len(_VOWEL_GROUP.findall(word))
    if word.endswith("e") and not word.endswith(("le", "ee", "ye")) and count > 1:
        count -= 1
    return max(1, count)


def flesch_reading_ease(text: str) -> float:
    """Raw Flesch reading ease, conventionally 0–100 (higher = easier).

        206.835 − 1.015 × (words / sentences) − 84.6 × (syllables / word)
    """
    sentences = split_sentences(text)
    words = tokenize_words(text)
    if not sentences or not words:
        return 0.0

    syllables = sum(count_syllables(word) for word in words)
    return (
        206.835
        - 1.015 * (len(words) / len(sentences))
        - 84.6 * (syllables / len(words))
    )


# --- Cohesion (Table 2) -----------------------------------------------------


def cohesion(text: str) -> float:
    """The four devices Table 2 names, combined into 0–1.

    Pronouns, lexical signposts, repeated keywords and anaphoric nouns each
    contribute equally: the paper lists them as alternative ways of achieving
    the same thing, so no single one is privileged.
    """
    sentences = split_sentences(text)
    words = [w.lower() for w in tokenize_words(text)]
    if not words:
        return 0.0

    # 1. Pronoun density, saturating at 15% of running words - beyond that a
    #    text is vague rather than cohesive.
    pronoun_rate = sum(1 for w in words if w in PRONOUNS) / len(words)
    pronoun_score = min(pronoun_rate / 0.15, 1.0)

    # 2. Lexical signposts, measured per sentence rather than per word.
    signposts = sum(1 for w in words if w in LEXICAL_SIGNPOSTS)
    signpost_score = min(signposts / len(sentences), 1.0) if sentences else 0.0

    # 3. Repeated keywords: the share of content words that recur. A text that
    #    never repeats a keyword is not talking about one thing.
    content = [w for w in words if w not in STOPWORDS and len(w) > 2]
    if content:
        counts = Counter(content)
        repeated = sum(count for count in counts.values() if count > 1)
        keyword_score = repeated / len(content)
    else:
        keyword_score = 0.0

    # 4. Anaphoric nouns.
    anaphor_rate = sum(1 for w in words if w in ANAPHORIC) / len(words)
    anaphor_score = min(anaphor_rate / 0.08, 1.0)

    return float(
        (pronoun_score + signpost_score + keyword_score + anaphor_score) / 4.0
    )


# --- Coherence (Table 2) ----------------------------------------------------


def coherence(text: str, model=None) -> float:
    """Thematic integrity: how much consecutive sentences stay on subject.

    Measured as the mean cosine similarity between adjacent sentences, over
    lemma count vectors.

    Word2vec vectors (§3.4.5) were the obvious choice, since the summarizer
    already builds them — but a model trained on one lecture has a few hundred
    tokens to learn from, so its vectors are close to random and adjacent
    sentences score near zero however related they are. Counting shared lemmas
    is unglamorous and actually measures what Table 2 describes. A `model` may
    still be passed to force the word2vec route.

    A single-sentence text scores 1.0: there is nothing to drift from.
    """
    import numpy as np

    sentences = split_sentences(text)
    if not sentences:
        return 0.0
    if len(sentences) == 1:
        return 1.0

    from app.nlp.lemmatization import lemmatize_text

    tokenized = [lemmatize_text(s) for s in sentences]

    if model is not None:
        try:
            from app.nlp.embeddings_w2v import sentence_vectors

            vectors = sentence_vectors(model, tokenized)
            scores = []
            for i in range(len(vectors) - 1):
                a, b = vectors[i], vectors[i + 1]
                denominator = np.linalg.norm(a) * np.linalg.norm(b)
                scores.append(float(a @ b / denominator) if denominator else 0.0)
            if scores:
                return float(np.clip(sum(scores) / len(scores), 0.0, 1.0))
        except Exception as exc:  # noqa: BLE001
            logger.debug("word2vec coherence failed (%s); using lexical vectors", exc)

    vocabulary = sorted({lemma for tokens in tokenized for lemma in tokens})
    if not vocabulary:
        return 0.0
    index = {lemma: i for i, lemma in enumerate(vocabulary)}

    matrix = np.zeros((len(tokenized), len(vocabulary)), dtype=np.float32)
    for row, tokens in enumerate(tokenized):
        for lemma in tokens:
            matrix[row, index[lemma]] += 1.0

    scores = []
    for i in range(len(tokenized) - 1):
        a, b = matrix[i], matrix[i + 1]
        denominator = np.linalg.norm(a) * np.linalg.norm(b)
        scores.append(float(a @ b / denominator) if denominator else 0.0)

    return float(np.clip(sum(scores) / len(scores), 0.0, 1.0)) if scores else 0.0


# --- Entropy (Table 2) ------------------------------------------------------


def shannon_entropy(distribution: list[float]) -> float:
    """Normalised Shannon entropy of a probability distribution, 0-1.

    Divided by `log2(k)` — the entropy of a uniform distribution over the same
    number of outcomes — so texts with different numbers of themes compare.
    """
    values = [v for v in distribution if v > 0]
    if len(values) <= 1:
        return 0.0

    total = sum(values)
    if total <= 0:
        return 0.0

    probabilities = [v / total for v in values]
    shannon = -sum(p * math.log2(p) for p in probabilities)
    maximum = math.log2(len(values))
    return float(min(shannon / maximum, 1.0)) if maximum else 0.0


def entropy(text_or_distribution) -> float:
    """Randomness of the content — Table 2, read through §4.3.

    §4.3 is specific about what the randomness is *of*: *"Entropy indicates the
    alignment of the whole content ... the scale of 0.5 is considered as more
    chaos between themes and topics."* So this is the entropy of the
    **theme distribution**, not of the word distribution.

    That distinction decides the number. A lecture that keeps returning to one
    subject has a peaked theme distribution and low entropy — which is how the
    paper's sample lecture, dominated by education, scores 0.12. Entropy over
    raw word counts instead sits near 1.0 for almost any text, because most
    words in any passage occur once, and it would report every lecture as
    maximally chaotic.

    Accepts text, an explicit list of weights, or a `{name: weight}` mapping.
    """
    if isinstance(text_or_distribution, dict):
        return shannon_entropy(list(text_or_distribution.values()))
    if isinstance(text_or_distribution, (list, tuple)):
        return shannon_entropy(list(text_or_distribution))

    text = text_or_distribution
    if not text or not text.strip():
        return 0.0

    try:
        from app.nlp.thematic import extract_themes

        themes = extract_themes(text)
        if len(themes) > 1:
            return shannon_entropy([theme["weight"] for theme in themes])
    except Exception as exc:  # noqa: BLE001
        logger.debug("thematic entropy unavailable (%s); falling back to words", exc)

    # No themes could be extracted (a one-line note). Fall back to the word
    # distribution so the metric is still defined.
    from app.nlp.lemmatization import lemmatize_text

    counts = Counter(lemmatize_text(text))
    return shannon_entropy(list(counts.values()))


# --- all four ---------------------------------------------------------------


def compute_raw_metrics(text: str, model=None) -> dict[str, float]:
    """The four Table 2 metrics before normalisation.

    Flesch is on its native 0–100 scale here; the other three are already 0–1.
    `scaling.normalize_metrics` applies Equation 4 to put them on one scale.
    """
    return {
        "flesch_reading_ease": flesch_reading_ease(text),
        "cohesion": cohesion(text),
        "coherence": coherence(text, model=model),
        "entropy": entropy(text),
    }


def word_count(text: str) -> int:
    return len(tokenize_words(text))


def sentence_count(text: str) -> int:
    return len(split_sentences(text))
