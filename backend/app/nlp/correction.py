"""LLM review of a raw transcript.

Whisper is an acoustic model with a shallow language prior. It decides between
candidates on what the audio sounds like and whether the result is plausible
English - it does not reason about meaning. So a near-homophone that is a real
word wins whenever the acoustic evidence is thin: measured on a real capture,
"the system still works" came back as "the system steelworks", and "in simpler
words" as "in similar words".

An LLM does reason about meaning. Given a sentence about fault tolerance it
knows a steel factory is not what was said. This module hands the transcript to
the configured LLM and asks it to repair *only* that class of error.

**The hard part is not fixing errors, it is not inventing them.** A model asked
to improve a transcript will happily rewrite clumsy speech into better prose,
and then the note is no longer what the user said. Three things guard against
that:

1. The prompt forbids rewording, reordering, summarising and adding.
2. `raw_transcript` is stored untouched on the note, so the original is always
   recoverable and the two can be compared.
3. `_is_plausible_correction` rejects a result that changed too much to be a
   transcription fix. A correction that rewrites half the note is a rewrite,
   whatever the prompt said.

Never raises and never blocks a capture: with no LLM configured, or on any
failure, the transcript passes through untouched.
"""

from __future__ import annotations

import difflib
import logging
from dataclasses import dataclass

from app.config import get_settings

logger = logging.getLogger(__name__)

SYSTEM = """\
You repair speech-recognition errors in a transcript. The audio was a spoken \
lecture note.

Fix ONLY what the recogniser clearly got wrong:
- near-homophones that do not fit the meaning ("steelworks" -> "still works", \
"in similar words" -> "in simpler words", "lengthless" -> "linked list")
- technical terms it misheard as ordinary words
- obviously wrong word boundaries

You must NOT:
- reword, rephrase or improve anything that is merely clumsy
- reorder, summarise, shorten or expand
- add any information that is not already there
- fix grammar the speaker actually used
- change punctuation, hyphenation or capitalisation for style
- use typographic characters: plain ASCII only, never curly quotes, en dashes \
or non-breaking hyphens
- change names, numbers or dates unless the surrounding words make the \
mishearing certain

A word the recogniser heard correctly is correct, even if you would have \
written it differently. If nothing in the text is clearly a mishearing, return \
it completely unchanged, character for character.

Return ONLY the corrected transcript. No preamble, no commentary, no quotes."""

PROMPT = """\
{hint}Transcript:
{text}"""


@dataclass
class CorrectionResult:
    """The corrected text plus why it is or is not different."""

    text: str
    changed: bool
    method: str  # "llm" | "unchanged" | "skipped" | "rejected"
    reason: str = ""

    @property
    def applied(self) -> bool:
        return self.method == "llm" and self.changed


#: Typographic characters an LLM reaches for unprompted, and the plain
#: equivalents. A transcript is spoken words: it has no typography to get right,
#: and exotic codepoints break on a Windows console (measured) and in anything
#: that assumes ASCII. Mapped back rather than trusted to the prompt, because a
#: prompt is a request and this is a guarantee.
_TYPOGRAPHIC = {
    "‐": "-", "‑": "-", "‒": "-", "–": "-",
    "—": "-", "―": "-", "−": "-",
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "…": "...", " ": " ", " ": " ", "​": "",
}


def _to_plain_ascii_punctuation(text: str) -> str:
    """Undo typographic substitutions the model made on its own."""
    for fancy, plain in _TYPOGRAPHIC.items():
        text = text.replace(fancy, plain)
    return text


def _similarity(a: str, b: str) -> float:
    """How much of the original survives, 0-1."""
    return difflib.SequenceMatcher(None, a.split(), b.split()).ratio()


def _is_plausible_correction(original: str, corrected: str) -> tuple[bool, str]:
    """Reject a 'correction' that is really a rewrite.

    A transcription fix swaps a handful of words. Anything that changes the
    length substantially, or leaves little of the original intact, is the model
    improving the prose rather than repairing a mishearing - which is the one
    thing this must never do silently.
    """
    settings = get_settings()

    if not corrected.strip():
        return False, "empty result"

    original_words = len(original.split())
    corrected_words = len(corrected.split())
    if original_words == 0:
        return False, "nothing to correct"

    drift = abs(corrected_words - original_words) / original_words
    if drift > settings.transcript_correction_max_length_drift:
        return False, f"length changed by {drift:.0%}"

    similarity = _similarity(original, corrected)
    if similarity < settings.transcript_correction_min_similarity:
        return False, f"only {similarity:.0%} of the wording survived"

    return True, ""


def correct_transcript(text: str) -> CorrectionResult:
    """Ask the LLM to repair recognition errors. Never raises."""
    settings = get_settings()
    original = (text or "").strip()

    if not settings.llm_correct_transcript:
        return CorrectionResult(text=text, changed=False, method="skipped",
                                reason="disabled")
    if not original:
        return CorrectionResult(text=text, changed=False, method="skipped",
                                reason="empty transcript")
    if len(original.split()) < settings.transcript_correction_min_words:
        # Too short for the surrounding meaning to disambiguate anything, and
        # a short note is where an over-eager rewrite does proportionally the
        # most damage.
        return CorrectionResult(text=text, changed=False, method="skipped",
                                reason="too short to correct safely")

    from app.llm import get_llm_client

    client = get_llm_client()
    if not client.available:
        return CorrectionResult(text=text, changed=False, method="skipped",
                                reason="no LLM configured")

    # The vocabulary hint that primes Whisper is just as useful here: it tells
    # the model which domain the mishearings will come from.
    hint = ""
    if settings.whisper_initial_prompt:
        hint = f"Context: {settings.whisper_initial_prompt}\n\n"

    try:
        response = client.complete(
            PROMPT.format(hint=hint, text=original),
            system=SYSTEM,
            max_tokens=settings.transcript_correction_max_tokens,
        )
    except Exception:
        logger.exception("transcript correction failed; keeping the transcript as-is")
        return CorrectionResult(text=text, changed=False, method="skipped",
                                reason="llm error")

    corrected = _to_plain_ascii_punctuation((response.text or "").strip().strip('"'))
    if not corrected or corrected == original:
        return CorrectionResult(text=text, changed=False, method="unchanged")

    ok, why = _is_plausible_correction(original, corrected)
    if not ok:
        logger.warning("rejected transcript correction: %s", why)
        return CorrectionResult(text=text, changed=False, method="rejected", reason=why)

    logger.info(
        "corrected transcript (%d -> %d words, %.0f%% unchanged)",
        len(original.split()),
        len(corrected.split()),
        _similarity(original, corrected) * 100,
    )
    return CorrectionResult(text=corrected, changed=True, method="llm")


def correct_transcript_safe(text: str) -> str:
    """Just the text, for callers that do not care why. Never raises."""
    try:
        return correct_transcript(text).text
    except Exception:
        logger.exception("transcript correction failed; keeping the transcript as-is")
        return text
