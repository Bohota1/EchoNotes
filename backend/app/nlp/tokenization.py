"""Tokenization — LNT framework, Section 3.4.1.

The paper is explicit about the choice: *"In our proposed methodology, we have
employed the White space tokenization method with space as a delimiter. We
create a dictionary of the words along with their frequency and length of
words."* Stop words and noise words are then removed or ignored.

Whitespace tokenization is used here even though NLTK offers better tokenizers,
because the paper names it and the word-frequency scoring in §3.4.4 and the
summarizer in §3.4.5 are calibrated against its output. Substituting a smarter
tokenizer would silently change every score downstream.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

#: Speech fillers. The paper cites Li et al. (2018) on "noise words" without
#: enumerating them; for lecture transcripts the noise is disfluency.
NOISE_WORDS: frozenset[str] = frozenset(
    """
    um umm uh uhh uhm erm er hmm hmmm mmm mm ah aah eh oh okay ok
    yeah yep nope hey well like just actually basically literally
    """.split()
)

_PUNCT_STRIP = ".,;:!?\"'()[]{}<>—–-"


@dataclass
class TokenEntry:
    """One entry of the paper's word dictionary: the word, its frequency, its length."""

    word: str
    frequency: int
    length: int


def whitespace_tokenize(text: str) -> list[str]:
    """Split on whitespace, with space as the delimiter (§3.4.1)."""
    if not text:
        return []
    return [token for token in text.split() if token]


def strip_punctuation(tokens: list[str]) -> list[str]:
    """Trim edge punctuation so "word," and "word" are the same token."""
    cleaned = [token.strip(_PUNCT_STRIP) for token in tokens]
    return [token for token in cleaned if token]


def sentence_tokenize(text: str) -> list[str]:
    """Split into sentences.

    The periods that make this work were appended one-per-chunk by the audio
    stage (§3.3), so a sentence here corresponds to a pause the speaker made.
    """
    if not text or not text.strip():
        return []
    try:
        from nltk.tokenize import sent_tokenize as nltk_sent_tokenize

        return [s.strip() for s in nltk_sent_tokenize(text) if s.strip()]
    except Exception as exc:  # noqa: BLE001 - punkt data may be absent
        logger.debug("NLTK sentence tokenizer unavailable (%s); splitting on .!?", exc)
        return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]


def get_stopwords() -> frozenset[str]:
    """English stop words (§3.4.1, Othman et al. 2015)."""
    try:
        from nltk.corpus import stopwords

        return frozenset(stopwords.words("english"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("NLTK stopwords unavailable (%s); using a minimal list", exc)
        return frozenset(
            """
            a an the and or but if then than that this these those there here
            is am are was were be been being do does did to of in on at by for
            with from into about as it its i you he she they we
            """.split()
        )


def remove_stopwords(tokens: list[str]) -> list[str]:
    stops = get_stopwords()
    return [token for token in tokens if token.lower() not in stops]


def remove_noise_words(tokens: list[str]) -> list[str]:
    """Drop fillers, and single characters that survive recognition errors."""
    return [
        token
        for token in tokens
        if token.lower() not in NOISE_WORDS and len(token) > 1
    ]


def tokenize(
    text: str,
    *,
    drop_stopwords: bool = True,
    drop_noise: bool = True,
    lowercase: bool = True,
) -> list[str]:
    """The §3.4.1 pipeline: whitespace split → strip punctuation → filter."""
    tokens = strip_punctuation(whitespace_tokenize(text))
    if lowercase:
        tokens = [token.lower() for token in tokens]
    if drop_noise:
        tokens = remove_noise_words(tokens)
    if drop_stopwords:
        tokens = remove_stopwords(tokens)
    return tokens


def build_word_dictionary(text: str, **kwargs) -> dict[str, TokenEntry]:
    """The paper's "dictionary of the words along with their frequency and length".

    Feeds the formative summarization and the topic modelling, as §3.4.1 says.
    """
    entries: dict[str, TokenEntry] = {}
    for token in tokenize(text, **kwargs):
        existing = entries.get(token)
        if existing is None:
            entries[token] = TokenEntry(word=token, frequency=1, length=len(token))
        else:
            existing.frequency += 1
    return entries
