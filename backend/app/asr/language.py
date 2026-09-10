"""Language detection - LNT Section 3.2.

LNT is a multilanguage framework: the input may be in any of several languages. Detecting it lets
the recognizer be told which language to expect, and tells `translation.py` whether a translation
step is needed at all.
"""

from __future__ import annotations

#: The paper targets seven Indian regional languages plus English. BCP-47 tags for the recognizer.
SUPPORTED_LANGUAGES: dict[str, str] = {
    "en": "en-US",
    "hi": "hi-IN",
    "bn": "bn-IN",
    "pa": "pa-IN",
    "ta": "ta-IN",
    "te": "te-IN",
    "mr": "mr-IN",
    "gu": "gu-IN",
}


def detect_language(text: str) -> str:
    """Return an ISO-639-1 code for already-transcribed text, using `langdetect`."""
    raise NotImplementedError


def to_recognizer_tag(language_code: str) -> str:
    """Map "hi" to "hi-IN" for the recognizer; fall back to the configured default."""
    raise NotImplementedError
