"""Standardising to English — LNT framework, Sections 3.2 and 3.3.

The paper translates every non-English lecture into English before any analysis
runs, and says why in Section 5: the content-analysis algorithms work in a
single language, and making them multilingual would degrade them. Everything
downstream — cleaning, entity extraction, classification, scoring — therefore
assumes English.

**How this differs from the paper.** The paper calls `googletrans`, which sends
the transcript to Google Translate. Here the translation happens inside Whisper
instead, via its `translate` task (`app.asr.transcriber.LNTTranscriber`), which:

* does it in one pass instead of transcribe-then-translate, so nothing is lost
  twice;
* needs no network and no third-party service, which matters for lecture and
  personal audio;
* avoids `googletrans`, an unofficial scraper of a private endpoint that breaks
  whenever Google changes it.

The outcome the paper specifies — English text for every input language — is
unchanged. This module holds the text-level fallback for the case where a
transcript already exists and only text can be translated.
"""

from __future__ import annotations

import logging

from app.asr.language import is_english, needs_translation

logger = logging.getLogger(__name__)


def translate_text_to_english(text: str, source_language: str | None = None) -> str:
    """Translate an existing transcript into English.

    Not used by the audio path — `LNTTranscriber` translates during recognition.
    This covers text that arrives already transcribed.

    Returns the text unchanged when it is already English, when no translator is
    available, or when translation fails. Returning the original is the right
    failure mode: a note in the wrong language is still readable, whereas a
    half-translated or empty one is not.
    """
    if not text or not text.strip():
        return text
    if source_language and is_english(source_language):
        return text
    if source_language and not needs_translation(source_language):
        return text

    client = _get_llm_translator()
    if client is None:
        logger.info("no translator available; leaving the text in its source language")
        return text

    try:
        response = client.complete(
            "Translate the following into English. Reply with the translation "
            f"only, no preamble and no explanation:\n\n{text}",
            max_tokens=2000,
        )
        translated = response.text.strip()
        return translated or text
    except Exception as exc:  # noqa: BLE001 - never lose the note over this
        logger.warning("translation failed, keeping the original text: %s", exc)
        return text


def _get_llm_translator():
    """The configured LLM, when one is available, else None."""
    from app.llm import get_llm_client

    client = get_llm_client()
    return client if client.available else None
