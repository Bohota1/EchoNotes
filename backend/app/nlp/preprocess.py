"""Text preprocessing and cleaning - LNT Section 3.3.

The paper lists the operations exactly, and this module implements that list and nothing more:

  - remove extra free spaces
  - remove periods in multi-period abbreviations  (e.g. "u.s.a." -> "usa")
  - remove punctuation
  - convert plural words to singular
  - convert text to lower case

Order matters. Abbreviation periods must go before punctuation removal, otherwise "u.s.a." turns
into three sentence boundaries. Sentence-final periods are preserved for the summarizer
(Section 3.4.5), which needs them to split sentences.
"""

from __future__ import annotations


def remove_extra_whitespace(text: str) -> str:
    raise NotImplementedError


def collapse_abbreviation_periods(text: str) -> str:
    """"u.s.a." -> "usa". Runs before punctuation removal so abbreviations survive as one token."""
    raise NotImplementedError


def remove_punctuation(text: str, keep_sentence_periods: bool = True) -> str:
    """Strip punctuation. Sentence-final periods are kept by default, per Section 3.4.5."""
    raise NotImplementedError


def singularize(text: str) -> str:
    """Plural to singular, using `inflect`."""
    raise NotImplementedError


def clean(text: str, keep_sentence_periods: bool = True) -> str:
    """Run the paper's cleaning list in order and return the cleaned text."""
    raise NotImplementedError
