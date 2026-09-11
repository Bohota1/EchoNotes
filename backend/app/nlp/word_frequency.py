"""Word frequency — LNT framework, Section 3.4.4.

The paper: *"It is the count of particular tokens (or words) occurring in the
document ... We use the frequency table for scoring each word that would be used
while summarization and specifying the scores. Besides, we ignore the stop
words. The Word frequency and word cloud (or dictionary) are significant while
performing thematic analysis as we store the key in its root word form. The
unique word with different meanings is given as the key and the count is stored
as the value."*

So: keys are **lemmas**, not surface forms, and stop words are excluded. Zipf's
law is cited as the expected shape of the distribution — *"the number of
occurrences of the Nth most frequently occurring word is proportional to 1/N"* —
and is reported here as a corpus statistic.
"""

from __future__ import annotations

import math
from collections import Counter


def frequency_table(lemmas: list[str]) -> dict[str, int]:
    """Count occurrences per root word (§3.4.4)."""
    return dict(Counter(lemmas))


def normalized_frequency_table(lemmas: list[str]) -> dict[str, float]:
    """Frequencies divided by the maximum, giving word scores in 0–1.

    This is the per-word score the summarizer in §3.4.5 uses when ranking
    sentences by *"Frequency of words"*.
    """
    counts = frequency_table(lemmas)
    if not counts:
        return {}
    highest = max(counts.values())
    return {word: count / highest for word, count in counts.items()}


def frequency_from_text(text: str) -> dict[str, int]:
    """Tokenize (§3.4.1) → lemmatize (§3.4.2) → count (§3.4.4)."""
    from app.nlp.lemmatization import lemmatize_text

    return frequency_table(lemmatize_text(text))


def word_cloud_data(frequencies: dict[str, int], top_n: int = 100) -> list[tuple[str, int]]:
    """The paper's "word cloud (or dictionary)": the most frequent root words."""
    return Counter(frequencies).most_common(top_n)


def zipf_fit(frequencies: dict[str, int]) -> dict[str, float]:
    """How closely the distribution follows Zipf's law.

    Zipf predicts `frequency ≈ C / rank`. Fitting `log(frequency)` against
    `log(rank)` by least squares gives a slope that should sit near −1, plus an
    R² for how well the text obeys the law. Reported as a corpus statistic, as
    the paper does; nothing downstream depends on it.
    """
    counts = sorted(frequencies.values(), reverse=True)
    if len(counts) < 3:
        return {"slope": 0.0, "r_squared": 0.0, "vocabulary": len(counts)}

    log_rank = [math.log(rank) for rank in range(1, len(counts) + 1)]
    log_freq = [math.log(count) for count in counts]
    n = len(counts)

    mean_x = sum(log_rank) / n
    mean_y = sum(log_freq) / n
    covariance = sum(
        (x - mean_x) * (y - mean_y)
        for x, y in zip(log_rank, log_freq, strict=True)
    )
    variance_x = sum((x - mean_x) ** 2 for x in log_rank)
    if variance_x == 0:
        return {"slope": 0.0, "r_squared": 0.0, "vocabulary": n}

    slope = covariance / variance_x
    intercept = mean_y - slope * mean_x

    total_ss = sum((y - mean_y) ** 2 for y in log_freq)
    residual_ss = sum(
        (y - (slope * x + intercept)) ** 2
        for x, y in zip(log_rank, log_freq, strict=True)
    )
    r_squared = 1.0 - residual_ss / total_ss if total_ss else 0.0

    return {
        "slope": round(slope, 4),
        "r_squared": round(r_squared, 4),
        "vocabulary": n,
    }
