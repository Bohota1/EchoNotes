"""Understanding schemas (Phase 2).

`UnderstandingOut` is the contract other team members consume. It is produced
by `app.understanding.service.understand()` and is also what is stored.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class NoteTypeOut(str, Enum):
    ACADEMIC = "academic"
    BRAINSTORM = "brainstorm"
    TODO = "todo"


class EntityKindOut(str, Enum):
    PERSON = "person"
    DATE = "date"
    DEADLINE = "deadline"
    TASK = "task"
    KEY_PHRASE = "key_phrase"


class EntityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    kind: EntityKindOut
    value: str = Field(description="The phrase as it appears in the text")
    normalized: str | None = Field(
        default=None,
        description="Canonical form: ISO-8601 for dates, cleaned title for tasks",
    )
    confidence: float = 0.0
    extractor: str = Field(default="rules", description="rules | llm")
    span_start: int | None = None
    span_end: int | None = None


class ClassificationOut(BaseModel):
    note_type: NoteTypeOut
    confidence: float
    method: str = Field(description="rules | llm | rules+llm")
    rationale: str | None = None


class QualityOut(BaseModel):
    """Composite quality score and its three components, each 0-1."""

    readability: float = Field(description="Reading ease, normalised to 0-1")
    coherence: float = Field(description="Sentence-to-sentence topic continuity")
    transcription_confidence: float = Field(description="ASR confidence for this audio")
    quality_score: float = Field(description="Weighted composite, 0-1")
    word_count: int = 0
    sentence_count: int = 0


class UnderstandingOut(BaseModel):
    """The full Phase 2 result for one note.

    `entities` holds every extraction; `people` / `dates` / `deadlines` /
    `tasks` / `key_phrases` are convenience views over the same data so callers
    do not each have to filter by kind.
    """

    note_id: str | None = None
    note_type: NoteTypeOut
    classification: ClassificationOut
    quality: QualityOut
    entities: list[EntityOut] = []

    people: list[str] = []
    dates: list[str] = []
    deadlines: list[str] = []
    tasks: list[str] = []
    key_phrases: list[str] = []

    llm_used: bool = False


class UnderstandRequest(BaseModel):
    """Body for POST /understand - run Phase 2 on arbitrary text.

    Provided so other team members can exercise the understanding stage without
    going through audio capture.
    """

    text: str = Field(min_length=1)
    persist: bool = Field(
        default=False, description="Store the text as a new note with its result"
    )
    transcription_confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="ASR confidence when known. Text-only input assumes 1.0.",
    )
