"""Lemmatization — LNT framework, Section 3.4.2.

The paper: *"Specifically, we are using WordNetLemmatizer from nltk library that
uses the inbuilt Morphy function to return the output of word based on
WordNet."*

Lemmatization, not stemming — the paper draws the distinction explicitly:
*"Unlike stemming, lemmatization not only considers the present word and removes
the suffix or postfix but also deals with the proper usage of nouns and verbs.
It also examines the context in which the word is used."*

Honouring "the proper usage of nouns and verbs" means supplying a part of speech.
`WordNetLemmatizer` defaults to noun, which leaves every verb untouched
("running" stays "running"); POS-tagging first is what makes it reach "run".
"""

from __future__ import annotations

import logging
from functools import lru_cache

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _lemmatizer():
    from nltk.stem import WordNetLemmatizer

    return WordNetLemmatizer()


def penn_to_wordnet(penn_tag: str) -> str:
    """Map a Penn Treebank POS tag to the WordNet tag Morphy expects."""
    from nltk.corpus import wordnet

    if penn_tag.startswith("J"):
        return wordnet.ADJ
    if penn_tag.startswith("V"):
        return wordnet.VERB
    if penn_tag.startswith("R"):
        return wordnet.ADV
    return wordnet.NOUN


def lemmatize_token(token: str, pos: str = "n") -> str:
    """Single token through WordNetLemmatizer / Morphy."""
    if not token:
        return token
    try:
        return _lemmatizer().lemmatize(token.lower(), pos)
    except Exception as exc:  # noqa: BLE001 - wordnet data may be absent
        logger.debug("lemmatization unavailable (%s); returning the token", exc)
        return token.lower()


def lemmatize(tokens: list[str], use_pos_tags: bool = True) -> list[str]:
    """Lemmatize a token list, POS-tagging first so verbs are handled properly."""
    if not tokens:
        return []

    if not use_pos_tags:
        return [lemmatize_token(token) for token in tokens]

    try:
        from nltk import pos_tag

        tagged = pos_tag(tokens)
    except Exception as exc:  # noqa: BLE001 - tagger data may be absent
        logger.debug("POS tagging unavailable (%s); lemmatizing as nouns", exc)
        return [lemmatize_token(token) for token in tokens]

    return [lemmatize_token(token, penn_to_wordnet(tag)) for token, tag in tagged]


def lemmatize_text(text: str, **tokenize_kwargs) -> list[str]:
    """Tokenize (§3.4.1) then lemmatize (§3.4.2)."""
    from app.nlp.tokenization import tokenize

    return lemmatize(tokenize(text, **tokenize_kwargs))
