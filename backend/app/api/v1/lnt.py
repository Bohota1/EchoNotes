"""LNT qualitative content analysis endpoints — paper Sections 3.4 and 3.5.

    GET  /api/v1/lnt/notes/{note_id}   the stored analysis for one capture
    POST /api/v1/lnt/analyze           run the analysis over supplied text
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.repositories import LntAnalysisRepository, NoteRepository
from app.db.session import get_db

router = APIRouter()


class AnalyzeRequest(BaseModel):
    text: str = Field(min_length=1)
    top_k: int | None = Field(default=None, ge=1, le=50, description="Summary length in sentences")
    num_topics: int | None = Field(default=None, ge=1, le=50)
    transcription_confidence: float = Field(default=1.0, ge=0.0, le=1.0)


@router.post("/analyze", summary="Run the LNT analysis over text")
def analyze_text(payload: AnalyzeRequest) -> dict:
    """Summary, themes, LDA topics, word frequencies and the quality score Qi."""
    from app.nlp.analysis import analyze

    result = analyze(
        payload.text,
        transcription_confidence=payload.transcription_confidence,
        top_k=payload.top_k,
        num_topics=payload.num_topics,
    )
    return result.to_dict()


@router.get("/notes/{note_id}", summary="Stored LNT analysis for a note")
def note_analysis(note_id: str, db: Session = Depends(get_db)) -> dict:
    note = NoteRepository(db).get(note_id)
    if note is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"no note with id {note_id}"
        )

    stored = LntAnalysisRepository(db).get_for_note(note_id)
    if stored is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="this note has no LNT analysis; it may predate the analysis stage",
        )

    understanding = note.understanding
    stored["quality"] = (
        {
            "readability": understanding.readability,
            "cohesion": understanding.cohesion,
            "coherence": understanding.coherence,
            "entropy": understanding.entropy,
            "quality_score": understanding.quality_score,
            "transcription_confidence": understanding.transcription_confidence,
        }
        if understanding
        else {}
    )
    stored["note_id"] = note_id
    return stored
