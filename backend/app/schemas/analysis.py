"""LNT analysis schemas - paper Sections 3.4 and 3.5."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ThemeOut(BaseModel):
    """A theme and its topics - the shape of the paper's Table 5."""

    theme: str
    topics: list[str]
    weight: float


class LdaTopicOut(BaseModel):
    topic_id: int
    label: str
    terms: list[tuple[str, float]]


class QualityOut(BaseModel):
    """Table 2 metrics, normalized 0-1, plus Qi from Equation 5."""

    readability: float = Field(description="Flesch reading ease, normalized")
    cohesion: float
    coherence: float
    entropy: float
    quality_score: float = Field(description="Qi, Equation 5")
    spoken: str


class AnalysisOut(BaseModel):
    note_id: str
    word_count: int
    summary: str
    themes: list[ThemeOut]
    lda_topics: list[LdaTopicOut]
    quality: QualityOut
    words_per_theme: float
    words_per_topic: float
