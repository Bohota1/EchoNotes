"""The understanding stage.

`understand()` is the public entry point for Phase 2. Given cleaned text it
returns everything the rest of the system needs to know about a note:

    result.note_type      academic | brainstorm | todo
    result.entities       every extraction, with character spans
    result.people         convenience views over `entities`
    result.dates
    result.deadlines
    result.tasks
    result.key_phrases
    result.quality        readability, coherence, ASR confidence, composite

Call it directly:

    from app.understanding.service import understand
    result = understand(cleaned_text, transcription_confidence=0.82)

Or over HTTP: POST /api/v1/understand {"text": "..."}.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from app.config import get_settings
from app.quality.score import QualityResult, score_text
from app.understanding.classifier import ClassificationResult, classify
from app.understanding.entities import ExtractedEntity, extract_all

logger = logging.getLogger(__name__)

#: Kinds that count as "the extractor found something real".
_SUBSTANTIVE_KINDS = ("person", "date", "deadline", "task")


@dataclass
class UnderstandingResult:
    note_type: str
    classification: ClassificationResult
    quality: QualityResult
    entities: list[ExtractedEntity] = field(default_factory=list)
    llm_used: bool = False

    def values_of(self, kind: str) -> list[str]:
        return [e.normalized or e.value for e in self.entities if e.kind == kind]

    @property
    def people(self) -> list[str]:
        return self.values_of("person")

    @property
    def dates(self) -> list[str]:
        return self.values_of("date")

    @property
    def deadlines(self) -> list[str]:
        return self.values_of("deadline")

    @property
    def tasks(self) -> list[str]:
        return self.values_of("task")

    @property
    def key_phrases(self) -> list[str]:
        return self.values_of("key_phrase")

    def to_dict(self) -> dict:
        return {
            "note_type": self.note_type,
            "classification": {
                "note_type": self.classification.note_type,
                "confidence": self.classification.confidence,
                "method": self.classification.method,
                "rationale": self.classification.rationale,
            },
            "quality": self.quality.as_dict(),
            "entities": [e.to_row() for e in self.entities],
            "people": self.people,
            "dates": self.dates,
            "deadlines": self.deadlines,
            "tasks": self.tasks,
            "key_phrases": self.key_phrases,
            "llm_used": self.llm_used,
        }

    def to_schema(self):
        """Convert to the API response model."""
        from app.schemas.understanding import (
            ClassificationOut,
            EntityOut,
            QualityOut,
            UnderstandingOut,
        )

        return UnderstandingOut(
            note_type=self.note_type,
            classification=ClassificationOut(
                note_type=self.classification.note_type,
                confidence=self.classification.confidence,
                method=self.classification.method,
                rationale=self.classification.rationale,
            ),
            quality=QualityOut(**self.quality.as_dict()),
            entities=[EntityOut(**e.to_row()) for e in self.entities],
            people=self.people,
            dates=self.dates,
            deadlines=self.deadlines,
            tasks=self.tasks,
            key_phrases=self.key_phrases,
            llm_used=self.llm_used,
        )


def _extraction_is_weak(entities: list[ExtractedEntity]) -> bool:
    """Decide whether the rule extractor found too little to be trusted.

    Weak means it found no people, dates, deadlines or tasks at all, or the ones
    it found are all low confidence. Key phrases do not count: those come from
    word statistics and are present for almost any text, so counting them would
    hide a total extraction failure.
    """
    substantive = [e for e in entities if e.kind in _SUBSTANTIVE_KINDS]
    if not substantive:
        return True
    return max(e.confidence for e in substantive) < get_settings().extraction_confidence_floor


def _merge_entities(
    primary: list[ExtractedEntity], secondary: list[ExtractedEntity]
) -> list[ExtractedEntity]:
    """Combine two entity lists, keeping the higher-confidence copy of each."""
    merged: dict[tuple[str, str], ExtractedEntity] = {e.key(): e for e in primary}
    for entity in secondary:
        existing = merged.get(entity.key())
        if existing is None or entity.confidence > existing.confidence:
            merged[entity.key()] = entity
    return sorted(
        merged.values(), key=lambda e: (e.kind, -e.confidence, e.span_start or 0)
    )


def _empty_result(transcription_confidence: float) -> UnderstandingResult:
    return UnderstandingResult(
        note_type="academic",
        classification=ClassificationResult(
            note_type="academic",
            confidence=0.0,
            method="rules",
            rationale="empty note",
        ),
        quality=score_text("", transcription_confidence),
        entities=[],
        llm_used=False,
    )


def understand(
    text: str,
    *,
    transcription_confidence: float = 1.0,
    reference: datetime | None = None,
    allow_llm: bool = True,
) -> UnderstandingResult:
    """Run extraction, classification and quality scoring over a note.

    `reference` is the capture time, used to resolve relative dates such as
    "next Friday". It defaults to now, which is only right for a note processed
    as it is captured - pass the real capture time when reprocessing old audio.

    Never raises for ordinary input: empty text returns an empty result with a
    zero quality score rather than an error, because a trigger that caught no
    speech is a normal event, not a failure.
    """
    if not text or not text.strip():
        return _empty_result(transcription_confidence)

    settings = get_settings()

    # --- extraction -------------------------------------------------------
    entities = extract_all(
        text, reference=reference, key_phrase_limit=settings.key_phrase_limit
    )
    llm_used = False

    if allow_llm and _extraction_is_weak(entities):
        from app.understanding.llm_extract import extract_with_llm

        llm_entities = extract_with_llm(text)
        if llm_entities:
            logger.info("extraction escalated to LLM (%d entities)", len(llm_entities))
            entities = _merge_entities(entities, llm_entities)
            llm_used = True

    # --- classification ---------------------------------------------------
    classification = classify(
        text,
        task_count=sum(1 for e in entities if e.kind == "task"),
        deadline_count=sum(1 for e in entities if e.kind == "deadline"),
        allow_llm=allow_llm,
    )
    if classification.method == "llm":
        llm_used = True

    # --- quality ----------------------------------------------------------
    quality = score_text(text, transcription_confidence)

    return UnderstandingResult(
        note_type=classification.note_type,
        classification=classification,
        quality=quality,
        entities=entities,
        llm_used=llm_used,
    )
