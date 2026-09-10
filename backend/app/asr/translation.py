"""Translation to English - LNT Sections 3.2 and 3.3.

The paper standardizes on English before any analysis: "we translate the content of the collected
data into the English language if it is not originally in English by using googletrans library."
The reason it gives (Section 5) is that the content-analysis algorithms work in a single language,
and making them multilingual would degrade performance.

Consequence: every downstream NLP module may assume English input.
"""

from __future__ import annotations


def translate_to_english(text: str, source_language: str | None = None) -> str:
    """Translate with googletrans. Returns the text unchanged when it is already English."""
    raise NotImplementedError
