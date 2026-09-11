"""Language detection — LNT framework, Section 3.2.

LNT is a *multilanguage* framework: the lecture may be delivered in any of
several languages, and the framework identifies which before doing anything
else. The paper targets seven Indian regional languages alongside English.

Detection happens on the audio (Whisper reports the spoken language directly),
not on the transcript. Detecting from text would mean transcribing first, which
is the thing that needs the language.

`detect_text_language` exists for the case where only text is available — a
typed note, or a transcript being reprocessed.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: The paper's target languages, ISO-639-1 to a display name. Whisper supports
#: all of them plus many more; this table is what the UI reads.
SUPPORTED_LANGUAGES: dict[str, str] = {
    "en": "English",
    "hi": "Hindi",
    "bn": "Bengali",
    "pa": "Punjabi",
    "ta": "Tamil",
    "te": "Telugu",
    "mr": "Marathi",
    "gu": "Gujarati",
    "ur": "Urdu",
    "kn": "Kannada",
    "ml": "Malayalam",
}


def language_name(code: str | None) -> str:
    """Human-readable name for a language code, for anything spoken to a user."""
    if not code:
        return "unknown"
    return SUPPORTED_LANGUAGES.get(code.split("-")[0].lower(), code)


def is_english(code: str | None) -> bool:
    return bool(code) and code.split("-")[0].lower() == "en"


def needs_translation(code: str | None) -> bool:
    """Whether Section 3.2's standardise-to-English step applies.

    An unknown language is treated as *not* needing translation: translating
    text that may already be English risks mangling it, and the recogniser
    reporting nothing is itself a sign not to take further automated action.
    """
    if not code:
        return False
    return not is_english(code)


def detect_text_language(text: str) -> str | None:
    """Best-effort language of a piece of text.

    Uses `langdetect` when it is installed. It is optional, because the audio
    path never needs it — Whisper reports the language from the audio itself.
    """
    if not text or not text.strip():
        return None
    try:
        from langdetect import detect
    except ImportError:
        logger.debug("langdetect not installed; text language left undetected")
        return None
    try:
        return detect(text)
    except Exception as exc:  # noqa: BLE001 - langdetect raises its own errors
        logger.debug("text language detection failed: %s", exc)
        return None
