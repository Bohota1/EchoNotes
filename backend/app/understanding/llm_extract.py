"""LLM fallback for classification and extraction.

Called only when the rules are not confident. Every function here returns
`None` on any failure - no key, no network, bad JSON, unexpected labels - so the
caller keeps its rule result instead of losing the note. That is the whole
contract: this module can never be the reason a capture fails.

All access goes through `app.llm.get_llm_client()`, so nothing here imports a
vendor SDK.
"""

from __future__ import annotations

import logging

from app.llm import LLMError, get_llm_client
from app.understanding.classifier import NOTE_TYPES, ClassificationResult
from app.understanding.entities import ExtractedEntity

logger = logging.getLogger(__name__)

CLASSIFY_SYSTEM = """\
You classify short voice notes into exactly one category.

academic   - lecture content, definitions, explanations, facts to revise
brainstorm - ideas, possibilities, speculation, design thinking
todo       - tasks, commitments, anything with a deadline or an owner

Reply with JSON only, no prose:
{"note_type": "academic|brainstorm|todo", "confidence": 0.0-1.0, "reason": "<8 words"}
"""

EXTRACT_SYSTEM = """\
You extract structured information from a short voice note.

Reply with JSON only, no prose:
{
  "people":      ["names of people mentioned"],
  "dates":       ["date expressions, exactly as written in the note"],
  "deadlines":   ["date expressions that something is DUE BY"],
  "tasks":       ["short imperative titles for actions the speaker committed to"],
  "key_phrases": ["2-4 word phrases describing what the note is about"]
}

Rules:
- Use only what the note actually says. Never invent a name, date or task.
- A date is a "deadline" only when something is due by it.
- Return an empty list for a field with nothing in it.
"""


def classify_with_llm(text: str) -> ClassificationResult | None:
    """Ask the LLM for a note type. Returns None if it cannot answer."""
    client = get_llm_client()
    if not client.available:
        return None

    try:
        data = client.complete_json(
            f"Classify this note:\n\n{text}", system=CLASSIFY_SYSTEM, max_tokens=200
        )
    except (LLMError, Exception) as exc:  # noqa: BLE001 - never propagate
        logger.warning("LLM classification failed, keeping rule result: %s", exc)
        return None

    if not isinstance(data, dict):
        return None

    note_type = str(data.get("note_type", "")).strip().lower()
    if note_type not in NOTE_TYPES:
        logger.warning("LLM returned unknown note_type %r", note_type)
        return None

    try:
        confidence = float(data.get("confidence", 0.7))
    except (TypeError, ValueError):
        confidence = 0.7

    return ClassificationResult(
        note_type=note_type,
        confidence=max(0.0, min(1.0, confidence)),
        method="llm",
        rationale=str(data.get("reason", "") or "classified by LLM")[:200],
    )


_LIST_FIELDS = {
    "people": "person",
    "dates": "date",
    "deadlines": "deadline",
    "tasks": "task",
    "key_phrases": "key_phrase",
}


def extract_with_llm(text: str) -> list[ExtractedEntity] | None:
    """Ask the LLM for entities. Returns None if it cannot answer.

    Spans are recovered by locating each returned value in the source text. A
    value the model paraphrased will not be found, and simply gets no span
    rather than a wrong one.
    """
    client = get_llm_client()
    if not client.available:
        return None

    try:
        data = client.complete_json(
            f"Extract from this note:\n\n{text}", system=EXTRACT_SYSTEM, max_tokens=900
        )
    except (LLMError, Exception) as exc:  # noqa: BLE001 - never propagate
        logger.warning("LLM extraction failed, keeping rule results: %s", exc)
        return None

    if not isinstance(data, dict):
        return None

    lowered = text.lower()
    entities: list[ExtractedEntity] = []

    for field, kind in _LIST_FIELDS.items():
        values = data.get(field) or []
        if not isinstance(values, list):
            continue
        for value in values:
            if not isinstance(value, str) or not value.strip():
                continue
            value = value.strip()
            position = lowered.find(value.lower())
            entities.append(
                ExtractedEntity(
                    kind=kind,
                    value=value,
                    normalized=value,
                    confidence=0.7,
                    extractor="llm",
                    span_start=position if position >= 0 else None,
                    span_end=position + len(value) if position >= 0 else None,
                )
            )

    return entities
