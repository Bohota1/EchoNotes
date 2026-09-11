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

# --- LNT §3.3: multi-period abbreviations ----------------------------------
# Two or more single letters each followed by a period: "U.S.A.", "i.e.", "e.g."
# A lone "Dr." is deliberately not matched - see `collapse_abbreviations`.
_MULTI_PERIOD_ABBREV_RE = re.compile(r"\b(?:[A-Za-z]\.){2,}")

# --- LNT §3.3: plural -> singular -------------------------------------------
#: Words ending in "s" that are not plurals. Stripping the "s" from these
#: invents a word that was never spoken, which is worse for the frequency
#: dictionary than leaving a plural intact.
_NOT_PLURAL = frozenset(
    """
    is was has does goes gas bus plus this thus yes news analysis basis crisis
    thesis hypothesis series species access process address class glass pass
    less unless across always perhaps its his hers ours yours theirs status
    focus campus virus bonus census physics mathematics statistics economics
    politics ethics graphics logistics lens whereas
    """.split()
)

#: Endings where the plural marker is "es" rather than "s".
_ES_ENDINGS = ("ses", "xes", "zes", "ches", "shes")


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


def collapse_abbreviations(text: str) -> str:
    """LNT §3.3: *"removing periods in multi-period abbreviations"*.

    "U.S.A." becomes "USA", "i.e." becomes "ie". Without this the generic
    punctuation strip turns a single abbreviation into a run of single letters
    ("u s a"), which then pollutes the word-frequency dictionary of §3.4.4 with
    tokens that mean nothing and inflates the sentence length used for
    readability in §3.5.

    Only sequences of *two or more* single letters each followed by a period are
    collapsed, which is what "multi-period" means. A single trailing period -
    "Dr." or the end of a sentence - is left for the punctuation step, so
    sentence boundaries survive to be used by §3.4.5.
    """
    return _MULTI_PERIOD_ABBREV_RE.sub(lambda m: m.group(0).replace(".", ""), text)


def singularize(word: str) -> str:
    """LNT §3.3: *"converting plural words to singular words"*.

    A conservative rule-based singulariser. The paper names the step but not an
    implementation; this follows the ordinary English patterns and declines to
    guess anywhere they do not clearly apply, because over-stemming ("bus" ->
    "bu", "analysis" -> "analysi") corrupts the word-frequency dictionary that
    §3.4.4, §3.4.5 and §3.4.6 are all built on. A missed plural costs one split
    entry; a wrong singular invents a word that was never spoken.

    Case-insensitive on the decision, and preserves nothing: callers here are
    producing lower-cased analysis text.
    """
    lowered = word.lower()
    if len(lowered) <= 3 or lowered in _NOT_PLURAL or not lowered.endswith("s"):
        return word

    # "policies" -> "policy"; "series" is caught by _NOT_PLURAL above.
    if lowered.endswith("ies") and len(lowered) > 4:
        return word[:-3] + "y"

    # "classes" -> "class", "boxes" -> "box", "batches" -> "batch".
    for ending in _ES_ENDINGS:
        if lowered.endswith(ending) and len(lowered) > len(ending) + 1:
            return word[:-2]

    # "students" -> "student". Never strip from "-ss" ("class", "process").
    if not lowered.endswith("ss"):
        return word[:-1]

    return word


def singularize_text(text: str) -> str:
    """Apply `singularize` across every whitespace-delimited token."""
    return " ".join(singularize(token) for token in text.split())


def to_analysis_text(text: str) -> str:
    """The LNT §3.3 analysis form, in the order the paper lists the steps.

    The paper: *"we work on preprocessing of text by handling the text anomalies
    like removing extra free spaces, removing periods in multi-period
    abbreviations, removing punctuations, converting plural words to singular
    words, and converting text to lower case"*.

    All five, in that order. Lower-casing is applied before singularisation
    rather than strictly last, which produces identical output - the result is
    lower-case either way - and lets the singulariser match its word lists
    without casing them at every call.

    This is the statistical form only. `clean_transcript` deliberately does none
    of it: capitalisation is the only signal that finds people's names, and the
    text read back to a user has to remain readable.
    """
    text = normalize_unicode(text)
    text = _MULTI_SPACE_RE.sub(" ", text).strip()  # 1. extra free spaces
    text = collapse_abbreviations(text)            # 2. multi-period abbreviations
    text = _PUNCT_RE.sub(" ", text)                # 3. punctuation
    text = text.lower()                            # 5. lower case
    text = singularize_text(text)                  # 4. plural -> singular
    return _MULTI_SPACE_RE.sub(" ", text).strip()
