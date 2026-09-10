"""Thematic analysis - LNT Section 3.4.6 and Section 4.1.

Thematic analysis is the paper's qualitative analysis of the text. Section 4.1 names the
techniques used to extract the notable themes: **hapaxes, collocations and bigrams**.

Table 5 shows the shape of the result: a small set of themes (Education, Economy, Institutes,
Law, Linguistics, Media, Politics, Technology, Sociology) each containing many topics. The paper
used MeaningCloud for theme labelling; here the labelling step is pluggable, so it can run
against MeaningCloud or an LLM while the hapax / collocation / bigram extraction stays as
described.
"""

from __future__ import annotations

from typing import Any


def hapaxes(lemmas: list[str]) -> list[str]:
    """Words occurring exactly once (NLTK FreqDist.hapaxes) - rare, high-information terms."""
    raise NotImplementedError


def collocations(tokens: list[str], num: int = 20, window_size: int = 2) -> list[tuple[str, str]]:
    """Word pairs occurring together more often than chance, by PMI."""
    raise NotImplementedError


def bigrams(tokens: list[str], top_n: int = 30) -> list[tuple[tuple[str, str], int]]:
    """Most frequent adjacent word pairs."""
    raise NotImplementedError


def extract_themes(text: str, lemmas: list[str]) -> list[dict[str, Any]]:
    """Combine hapaxes, collocations and bigrams into themes with their member topics.

    Returns [{"theme": str, "topics": [str, ...], "weight": float}, ...], the structure of Table 5.
    """
    raise NotImplementedError


def theme_density(themes: list[dict[str, Any]], word_count: int) -> dict[str, float]:
    """Words per theme and words per topic.

    The paper reports one theme per 217 words and one topic per 36 words for its sample lecture,
    and uses these as a sanity check on the analysis.
    """
    raise NotImplementedError
