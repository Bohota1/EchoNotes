"""Content quality metrics - LNT Section 3.5, Table 2.

The paper defines four metrics and nothing else. Do not add metrics here: the quality score in
Equation 5 is the sum of exactly these four, each weighted equally, and adding a fifth changes
the score's meaning.

  Flesch_reading_ease  the level of ease with which English text can be read
  Cohesion             use of vocabulary and grammatical structure to connect ideas within the
                       text - achieved through pronouns, lexical signposts, repeated keywords and
                       anaphoric nouns
  Coherence            contextual fitness of the text, promoting its thematic integrity
  Entropy              a measurement of randomness; less chaos means lower entropy

Interpretation the paper gives (Section 4.3): a cohesion/coherence scale of 0.5-0.75 is good for
spoken lectures, because speakers repeat themselves; entropy is preferred near 0 or near 1, with
0.5 indicating chaos between themes and topics.
"""

from __future__ import annotations


def flesch_reading_ease(text: str) -> float:
    """Raw Flesch reading ease (roughly 0-100). Normalized later by `scaling.min_max`."""
    raise NotImplementedError


def cohesion(sentences: list[str]) -> float:
    """Connection between ideas: pronouns, lexical signposts, repeated keywords, anaphoric nouns.

    Computed as mean lexical overlap between adjacent sentences plus the density of the cohesive
    devices the paper names.
    """
    raise NotImplementedError


def coherence(sentence_vectors) -> float:
    """Thematic integrity: mean cosine similarity between consecutive sentence vectors.

    Reuses the sentence vectors already built for summarization (Section 3.4.5) rather than
    recomputing them.
    """
    raise NotImplementedError


def entropy(frequencies: dict[str, int]) -> float:
    """Shannon entropy of the word distribution, in bits. Lower means less randomness."""
    raise NotImplementedError


def compute_all(text: str, sentences: list[str], sentence_vectors, frequencies) -> dict[str, float]:
    """Return the four raw metric values before normalization."""
    raise NotImplementedError
