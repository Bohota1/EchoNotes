"""Transcript cleaning and normalisation.

Raw ASR output is one long, unpunctuated-ish, filler-laden string. Two different
consumers want two different shapes of it, so this module produces both:

`clean_transcript()` -> the **readable** form, stored as `Note.cleaned_text`.
    Whitespace, punctuation and sentence case are normalised and speech fillers
    removed, but capitalisation and punctuation are *preserved*. Entity
    extraction depends on capitalisation to find people, and anything read back
    to a user has to be readable.

`to_analysis_text()` -> the **analysis** form: lower-cased and stripped of
    punctuation, for word statistics, key phrases and scoring.

Keeping these apart matters. Lower-casing the stored transcript, as a purely
statistical pipeline would, destroys the signal the extractor needs and leaves
the user with text that reads badly.
"""

from __future__ import annotations

import re
import unicodedata

# --- character-level normalisation -----------------------------------------

_SMART_CHARS = {
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"',
    "\u2013": "-", "\u2014": "-", "\u2015": "-", "\u2212": "-",
    "\u2026": "...", "\u00a0": " ", "\u200b": "",
}

# --- speech fillers ---------------------------------------------------------
# Only unambiguous fillers. Words like "like" and "so" are left alone: they are
# filler often enough to be tempting and meaningful often enough that removing
# them corrupts real sentences.
_FILLER_WORDS = (
    "um", "umm", "uh", "uhh", "erm", "hmm", "hmmm", "mmm", "ah", "eh",
)
_FILLER_WORD_RE = re.compile(
    r"(?<![\w'])(?:%s)(?![\w'])[\s,]*" % "|".join(_FILLER_WORDS), re.IGNORECASE
)
_FILLER_PHRASE_RE = re.compile(
    r"(?<![\w'])(?:you know|i mean|sort of|kind of)\s*,\s*", re.IGNORECASE
)

_REPEATED_WORD_RE = re.compile(r"(?<![\w'])(\w+)(\s+\1)+(?![\w'])", re.IGNORECASE)
_MULTI_SPACE_RE = re.compile(r"[^\S\n]+")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,.;:!?%)\]])")
_SPACE_AFTER_OPEN_RE = re.compile(r"([(\[])\s+")
_MISSING_SPACE_RE = re.compile(r"([,;:])(?=[^\s\d])")
_REPEATED_PUNCT_RE = re.compile(r"([,.!?;:])\1{1,}")
_DANGLING_PUNCT_RE = re.compile(r"^[\s,;:.!?-]+")

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_WORD_RE = re.compile(r"[A-Za-z0-9']+")
_PUNCT_RE = re.compile(r"[^\w\s]")


def normalize_unicode(text: str) -> str:
    """NFKC-normalise and fold smart quotes, dashes and exotic spaces to ASCII."""
    text = unicodedata.normalize("NFKC", text)
    for source, target in _SMART_CHARS.items():
        text = text.replace(source, target)
    return text


def normalize_whitespace(text: str) -> str:
    """Collapse runs of spaces and blank lines, and trim each line."""
    text = _MULTI_SPACE_RE.sub(" ", text)
    text = _MULTI_NEWLINE_RE.sub("\n\n", text)
    return "\n".join(line.strip() for line in text.split("\n")).strip()


def normalize_punctuation(text: str) -> str:
    """Fix the punctuation spacing and duplication that ASR output tends to have."""
    text = _REPEATED_PUNCT_RE.sub(r"\1", text)
    text = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", text)
    text = _SPACE_AFTER_OPEN_RE.sub(r"\1", text)
    text = _MISSING_SPACE_RE.sub(r"\1 ", text)
    return text


def remove_fillers(text: str) -> str:
    """Drop unambiguous speech fillers."""
    text = _FILLER_PHRASE_RE.sub("", text)
    text = _FILLER_WORD_RE.sub("", text)
    return text


def collapse_repetitions(text: str) -> str:
    """Collapse stutters: "the the topic" -> "the topic"."""
    previous = None
    while previous != text:
        previous = text
        text = _REPEATED_WORD_RE.sub(r"\1", text)
    return text


def split_sentences(text: str) -> list[str]:
    """Split on sentence-ending punctuation, dropping empties."""
    if not text.strip():
        return []
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text.strip()) if s.strip()]


def tokenize_words(text: str) -> list[str]:
    """Word tokens, apostrophes kept so "don't" stays one token."""
    return _WORD_RE.findall(text)


def restore_sentence_case(text: str) -> str:
    """Capitalise sentence starts and the standalone pronoun "I".

    Whisper usually punctuates and capitalises already, so this is a repair pass
    rather than a rewrite: a word that is already capitalised is left alone, so
    proper nouns mid-sentence survive.
    """
    text = re.sub(r"(?<![\w'])i(?![\w'])", "I", text)

    pieces = []
    for sentence in split_sentences(text):
        sentence = _DANGLING_PUNCT_RE.sub("", sentence)
        if sentence:
            pieces.append(sentence[0].upper() + sentence[1:])
    return " ".join(pieces)


def ensure_terminal_punctuation(text: str) -> str:
    """Give the text a final full stop if it ends mid-air."""
    stripped = text.rstrip()
    if stripped and stripped[-1] not in ".!?":
        return stripped + "."
    return stripped


def clean_transcript(text: str) -> str:
    """Full readable-cleanup pass. This is what gets stored as `cleaned_text`."""
    if not text or not text.strip():
        return ""

    text = normalize_unicode(text)
    text = normalize_whitespace(text)
    text = remove_fillers(text)
    text = collapse_repetitions(text)
    text = normalize_punctuation(text)
    text = normalize_whitespace(text)
    text = restore_sentence_case(text)
    text = ensure_terminal_punctuation(text)
    return normalize_whitespace(text)


def to_analysis_text(text: str) -> str:
    """Lower-cased, punctuation-free form used for word statistics and scoring."""
    text = normalize_unicode(text).lower()
    text = _PUNCT_RE.sub(" ", text)
    return _MULTI_SPACE_RE.sub(" ", text).strip()
