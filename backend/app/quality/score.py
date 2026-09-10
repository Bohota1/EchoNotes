"""Composite quality score.

    quality_score = w_r * readability
                  + w_c * coherence
                  + w_t * transcription_confidence

Weights come from settings and must sum to 1, so the composite is always 0-1.
Transcription confidence carries the largest default weight (0.40) because a
note the recogniser was unsure about is unreliable no matter how well it reads:
readability and coherence are computed *from* the transcript, so if the
transcript is wrong they are measuring the wrong text.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import get_settings
from app.quality import metrics


@dataclass
class QualityResult:
    readability: float
    coherence: float
    transcription_confidence: float
    quality_score: float
    word_count: int
    sentence_count: int

    def as_dict(self) -> dict[str, float | int]:
        return {
            "readability": round(self.readability, 4),
            "coherence": round(self.coherence, 4),
            "transcription_confidence": round(self.transcription_confidence, 4),
            "quality_score": round(self.quality_score, 4),
            "word_count": self.word_count,
            "sentence_count": self.sentence_count,
        }


def score_text(text: str, transcription_confidence: float = 1.0) -> QualityResult:
    """Score one note.

    `transcription_confidence` comes from the ASR stage. Text that never went
    through audio (a typed note, or POST /understand) passes 1.0, since there is
    no recognition uncertainty to account for.
    """
    settings = get_settings()

    read = metrics.readability(text)
    coh = metrics.coherence(text)
    conf = max(0.0, min(1.0, transcription_confidence))

    composite = (
        settings.quality_weight_readability * read
        + settings.quality_weight_coherence * coh
        + settings.quality_weight_transcription * conf
    )

    return QualityResult(
        readability=read,
        coherence=coh,
        transcription_confidence=conf,
        quality_score=max(0.0, min(1.0, composite)),
        word_count=metrics.word_count(text),
        sentence_count=metrics.sentence_count(text),
    )


def describe(quality_score: float) -> str:
    """Plain-language reading of the score, for anything spoken back to a user.

    A bare "0.62" tells a listener nothing.
    """
    if quality_score >= 0.75:
        return "high quality: clear, focused and confidently transcribed"
    if quality_score >= 0.55:
        return "good quality"
    if quality_score >= 0.35:
        return "mixed quality: some of this may be unclear or misheard"
    return "low quality: likely misheard or hard to follow"
