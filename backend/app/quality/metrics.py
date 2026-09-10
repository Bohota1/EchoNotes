"""Quality metrics for a transcript.

Three independent measures, each normalised to 0-1 so they can be combined:

  readability               how easy the text is to read (Flesch reading ease)
  coherence                 how much consecutive sentences stay on topic
  transcription_confidence  how sure the recogniser was (supplied by the ASR stage)

All three are computed here with no external NLP dependency. That is deliberate:
these run on every capture, and a metric that needs a model download is a metric
that breaks the pipeline on a fresh machine.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from app.nlp.preprocess import split_sentences, tokenize_words

_VOWEL_GROUP_RE = re.compile(r"[aeiouy]+")
_NON_ALPHA_RE = re.compile(r"[^a-z]")

# Function words carry grammar, not topic. They are excluded from coherence and
# key-phrase work so "the" repeating everywhere does not read as topic overlap.
STOPWORDS: frozenset[str] = frozenset(
    """
    a an the and or but if then than that this these those there here
    i me my we us our you your he him his she her it its they them their
    is am are was were be been being do does did doing have has had having
    will would shall should can could may might must
    to of in on at by for with from into about over under again further
    so very just too also not no nor only own same s t don now
    what which who whom whose when where why how all any both each few more
    most other some such as up down out off because while during before after
    i'm it's don't that's we're you're
    """.split()
)


def count_syllables(word: str) -> int:
    """Approximate syllable count for one English word.

    Vowel-group counting with a silent-trailing-e correction. It is an
    approximation, but Flesch is itself an approximation and this is the
    standard heuristic; every word gets at least one syllable.
    """
    word = _NON_ALPHA_RE.sub("", word.lower())
    if not word:
        return 0
    groups = _VOWEL_GROUP_RE.findall(word)
    count = len(groups)
    if word.endswith("e") and not word.endswith(("le", "ee", "ye")) and count > 1:
        count -= 1
    return max(1, count)


def flesch_reading_ease(text: str) -> float:
    """Raw Flesch reading ease, roughly 0-100 (higher = easier).

    206.835 - 1.015 * (words/sentences) - 84.6 * (syllables/word)
    """
    sentences = split_sentences(text)
    words = tokenize_words(text)
    if not sentences or not words:
        return 0.0

    syllables = sum(count_syllables(w) for w in words)
    words_per_sentence = len(words) / len(sentences)
    syllables_per_word = syllables / len(words)
    return 206.835 - 1.015 * words_per_sentence - 84.6 * syllables_per_word


def readability(text: str) -> float:
    """Flesch reading ease squashed to 0-1."""
    return max(0.0, min(1.0, flesch_reading_ease(text) / 100.0))


def _content_terms(sentence: str) -> Counter:
    return Counter(
        w.lower()
        for w in tokenize_words(sentence)
        if w.lower() not in STOPWORDS and len(w) > 2
    )


def _cosine(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    shared = set(a) & set(b)
    if not shared:
        return 0.0
    dot = sum(a[t] * b[t] for t in shared)
    norm = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(
        sum(v * v for v in b.values())
    )
    return dot / norm if norm else 0.0


# Explicit cohesion signals. A speaker who says "also" or "because" is linking
# this sentence to the previous one even when they share no vocabulary.
_CONNECTIVES: frozenset[str] = frozenset(
    """
    also and but so then therefore thus however although though because since
    besides moreover furthermore additionally meanwhile afterwards next finally
    otherwise instead anyway plus second secondly third thirdly lastly
    """.split()
)

# Anaphors point back at something already said - the "anaphoric reference"
# half of cohesion.
_ANAPHORS: frozenset[str] = frozenset(
    """
    it its this that these those they them their he she him her his hers
    there such same one ones another
    """.split()
)


def lexical_cohesion(text: str) -> float:
    """How much each sentence shares vocabulary with the rest of the note.

    Leave-one-out: every sentence is compared against the combined terms of all
    the others, rather than only against its neighbour. Strict adjacency
    collapses to zero on the short, three-clause notes this app captures, where
    related sentences routinely share no literal words.
    """
    sentences = split_sentences(text)
    if len(sentences) < 2:
        return 1.0 if sentences else 0.0

    vectors = [_content_terms(s) for s in sentences]
    scores = []
    for index, vector in enumerate(vectors):
        rest: Counter = Counter()
        for other_index, other in enumerate(vectors):
            if other_index != index:
                rest.update(other)
        scores.append(_cosine(vector, rest))
    return sum(scores) / len(scores) if scores else 0.0


def connective_cohesion(text: str) -> float:
    """Fraction of sentence transitions carrying an explicit cohesion signal.

    Counts a transition when the following sentence uses a discourse connective
    or an anaphor, i.e. when the speaker signalled a link in words rather than
    by repeating a keyword.
    """
    sentences = split_sentences(text)
    if len(sentences) < 2:
        return 1.0 if sentences else 0.0

    linked = 0
    for sentence in sentences[1:]:
        tokens = [w.lower() for w in tokenize_words(sentence)]
        if not tokens:
            continue
        # A connective only counts as a link when it opens the sentence;
        # mid-sentence "and" joins clauses, not sentences.
        if tokens[0] in _CONNECTIVES or any(t in _ANAPHORS for t in tokens[:6]):
            linked += 1
    return linked / (len(sentences) - 1)


#: How much of coherence comes from shared vocabulary vs explicit signals.
LEXICAL_WEIGHT = 0.6
CONNECTIVE_WEIGHT = 0.4


def coherence(text: str) -> float:
    """Topical continuity of the note, 0-1.

    Blends the two ways spoken text holds together: repeated content words
    (`lexical_cohesion`) and explicit discourse signals (`connective_cohesion`).
    Using only the first scores a perfectly ordinary three-item to-do at zero.

    A single-sentence note scores 1.0 - there is nothing to drift from, and
    penalising short notes would punish exactly the quick captures this app is
    built for.
    """
    sentences = split_sentences(text)
    if not sentences:
        return 0.0
    if len(sentences) < 2:
        return 1.0

    score = (
        LEXICAL_WEIGHT * lexical_cohesion(text)
        + CONNECTIVE_WEIGHT * connective_cohesion(text)
    )
    return max(0.0, min(1.0, score))


def word_count(text: str) -> int:
    return len(tokenize_words(text))


def sentence_count(text: str) -> int:
    return len(split_sentences(text))
