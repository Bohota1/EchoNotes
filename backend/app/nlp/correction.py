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
from collections.abc import Sequence
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
- fill in words you think the recogniser missed: an incomplete phrase stays incomplete
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


def _words_changed(original: str, corrected: str) -> int:
    """How many of the original's words the correction did not keep.

    Counted rather than measured as a ratio, because a ratio says nothing
    useful about short text: repairing "Various system design" to "What is
    system design" keeps two words of three, which is a 57% similarity and a
    33% length change - both of which look catastrophic and neither of which
    describes what happened, namely that one word was fixed.

    Word count, unlike a proportion, means the same thing at every length.
    """
    original_words = original.split()
    matcher = difflib.SequenceMatcher(None, original_words, corrected.split())
    kept = sum(block.size for block in matcher.get_matching_blocks())
    return max(len(original_words) - kept, 0)


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

    # One rule, in words rather than proportions: how many of the original's
    # words did this not keep? A repair swaps a few; a rewrite replaces most.
    #
    # The allowance is the larger of a small absolute number and a proportion,
    # so it is meaningful at both ends. A three-word question may have two
    # words fixed; a hundred-word note may have twenty-five. Neither may be
    # replaced wholesale.
    changed = _words_changed(original, corrected)
    allowed = max(
        settings.transcript_correction_max_word_drift,
        int(original_words * settings.transcript_correction_max_length_drift),
    )
    if changed > allowed:
        return False, f"{changed} of {original_words} words changed (max {allowed})"

    # Length is bounded separately, so a "correction" cannot bolt on a new
    # sentence while leaving the original intact.
    added = abs(corrected_words - original_words)
    if added > allowed:
        return False, f"length changed by {added} words (max {allowed})"

    return True, ""


def correct_transcript(
    text: str, *, kind: str = "note", unclear: Sequence[str] | None = None
) -> CorrectionResult:
    """Ask the LLM to repair recognition errors. Never raises.

    `kind` is "note" or "question". A question uses a much lower length
    threshold and is told it is a question, because a four-word query is normal
    and a mishearing in it sends the search after the wrong thing.

    `unclear` is the passages the recogniser was least sure of (see
    `TranscriptionResult.unclear_passages`). They tell the model where to
    look; they do not loosen what it is allowed to change. For a question,
    an empty list means the recogniser was sure of every word, and the
    question is left exactly as heard.
    """
    settings = get_settings()
    original = (text or "").strip()

    if not settings.llm_correct_transcript:
        return CorrectionResult(text=text, changed=False, method="skipped",
                                reason="disabled")
    if not original:
        return CorrectionResult(text=text, changed=False, method="skipped",
                                reason="empty transcript")
    min_words = (
        settings.transcript_correction_min_words_question
        if kind == "question"
        else settings.transcript_correction_min_words
    )
    if len(original.split()) < min_words:
        # Too short for the surrounding meaning to disambiguate anything, and
        # a short note is where an over-eager rewrite does proportionally the
        # most damage.
        return CorrectionResult(text=text, changed=False, method="skipped",
                                reason="too short to correct safely")

    if kind == "question" and unclear is not None and not any(
        p and p.strip() for p in unclear
    ):
        # The recogniser was sure of every word. A question is short, so there
        # is no surrounding meaning to overrule a confident hearing with, and
        # correcting anyway only invites the model to improve it - measured on
        # confident transcripts: "notes related to English" became "notes
        # related to linked list", and "Read the whole note" became "What is
        # the whole note?". `unclear=None` means the caller has no confidence
        # data at all, and keeps the previous behaviour.
        return CorrectionResult(text=text, changed=False, method="skipped",
                                reason="recogniser was confident")

    from app.llm import get_llm_client

    client = get_llm_client()
    if not client.available:
        return CorrectionResult(text=text, changed=False, method="skipped",
                                reason="no LLM configured")

    # The vocabulary hint that primes Whisper is just as useful here: it tells
    # the model which domain the mishearings will come from.
    hint = ""
    # The vocabulary hint describes lectures. A question is about whatever the
    # user's notes happen to hold, and handed a list of computer-science terms
    # the model swaps a word it cannot place for one of them - measured: "notes
    # related to English" became "notes related to linked list".
    if settings.whisper_initial_prompt and kind != "question":
        hint = f"Context: {settings.whisper_initial_prompt}\n\n"

    if kind == "question":
        # Knowing it is a question does most of the work. "Various system
        # design" is a plausible phrase but an implausible question, and only a
        # model told to expect a question will prefer "What is system design".
        # Without this the model tidies the phrase instead of repairing it.
        hint += (
            "The text is a short spoken question the user asked about their own "
            "notes, not a lecture note. It should read as a question. Recogniser "
            'errors at the start of a question are common: "Various" or "Word is" '
            'for "What is", "Do I" for "Does", and similar. A request such as '
            '"Read my notes" or "Read the whole note" is not a question: leave it '
            "a request.\n\n"
        )

    passages = [p.strip() for p in (unclear or []) if p and p.strip()]
    if passages:
        # Named rather than left for the model to find. Told nothing, it reads
        # the whole note with equal suspicion, and the words it "fixes" are as
        # likely to be ones that were heard correctly.
        listed = "\n".join(
            f'- "{p}"' for p in passages[: settings.transcript_correction_max_unclear]
        )
        hint += (
            "The recogniser was least confident in these passages, so a misheard "
            "word is most likely inside them. Check each word there against the "
            "meaning of the sentence around it:\n" + listed + "\n\n"
        )

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


def correct_transcript_safe(
    text: str, *, kind: str = "note", unclear: Sequence[str] | None = None
) -> str:
    """Just the text, for callers that do not care why. Never raises."""
    try:
        return correct_transcript(text, kind=kind, unclear=unclear).text
    except Exception:
        logger.exception("transcript correction failed; keeping the transcript as-is")
        return text
