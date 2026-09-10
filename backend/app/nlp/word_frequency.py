"""Word frequency - LNT Section 3.4.4.

The paper: "We use the frequency table for scoring each word that would be used while
summarization and specifying the scores. Besides, we ignore the stop words." It also notes Zipf's
law, that the Nth most frequent word occurs proportionally to 1/N, and that for thematic analysis
"we store the key in its root word form" - so build the table from lemmas, not raw tokens.
"""

from __future__ import annotations


def frequency_table(lemmas: list[str]) -> dict[str, int]:
    """Count occurrences per root word, stop words already removed."""
    raise NotImplementedError


def normalized_frequency_table(lemmas: list[str]) -> dict[str, float]:
    """Frequencies divided by the maximum, giving word scores in 0-1 for sentence scoring."""
    raise NotImplementedError


def zipf_fit(frequencies: dict[str, int]) -> dict[str, float]:
    """Rank-frequency fit against Zipf's law. Reported as a corpus statistic, per Section 3.4.4."""
    raise NotImplementedError


def word_cloud_data(frequencies: dict[str, int], top_n: int = 100) -> list[tuple[str, int]]:
    """Top-N root words for the word cloud / dictionary the paper uses in thematic analysis."""
    raise NotImplementedError
