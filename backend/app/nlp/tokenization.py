"""Tokenization - LNT Section 3.4.1.

The paper is specific: "In our proposed methodology, we have employed the White space
tokenization method with space as a delimiter. We create a dictionary of the words along with
their frequency and length of words." Stop words and noise words are then removed.

Do not substitute a smarter tokenizer here. The paper names whitespace tokenization, and the
summarizer and topic model are calibrated against its output.
"""

from __future__ import annotations


def whitespace_tokenize(text: str) -> list[str]:
    """Split on whitespace, the paper's delimiter."""
    raise NotImplementedError


def sentence_tokenize(text: str) -> list[str]:
    """Split into sentences on the periods appended per audio chunk (Section 3.3)."""
    raise NotImplementedError


def remove_stopwords(tokens: list[str]) -> list[str]:
    """Drop NLTK English stop words (Section 3.4.1)."""
    raise NotImplementedError


def remove_noise_words(tokens: list[str]) -> list[str]:
    """Drop filler and disfluency tokens: um, uh, hmm, and single stray characters.

    Speech transcripts carry far more of these than written text, which is why the paper
    separates noise words from stop words.
    """
    raise NotImplementedError


def build_token_dictionary(tokens: list[str]) -> dict[str, dict[str, int]]:
    """Return {token: {"frequency": n, "length": len(token)}} - the paper's word dictionary."""
    raise NotImplementedError
