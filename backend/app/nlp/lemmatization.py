"""Lemmatization - LNT Section 3.4.2.

The paper: "we are using WordNetLemmatizer from nltk library that uses the inbuilt Morphy
function to return the output of word based on WordNet."

Lemmatization, not stemming: the paper is explicit that it considers part of speech and context
rather than chopping suffixes, and the thematic analysis stores keys in root-word form.
"""

from __future__ import annotations


def lemmatize_token(token: str, pos: str = "n") -> str:
    """Single token through NLTK WordNetLemmatizer / Morphy."""
    raise NotImplementedError


def lemmatize(tokens: list[str], use_pos_tags: bool = True) -> list[str]:
    """Lemmatize a token list.

    With `use_pos_tags`, POS-tag first and map Penn tags to WordNet tags, which is what makes the
    lemmatizer handle verbs correctly ("running" -> "run" rather than "running").
    """
    raise NotImplementedError
