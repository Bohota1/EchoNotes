"""Analysis endpoints - LNT Sections 3.4 and 3.5.

These expose the paper's qualitative content analysis: summary, themes, LDA topics, and the four
quality metrics with the score Qi.
"""

from fastapi import APIRouter

from app.schemas.analysis import AnalysisOut, QualityOut

router = APIRouter()


@router.get("/notes/{note_id}", response_model=AnalysisOut)
async def note_analysis(note_id: str):
    """Full LNT analysis for one capture."""
    raise NotImplementedError


@router.get("/notes/{note_id}/quality", response_model=QualityOut)
async def note_quality(note_id: str):
    """Readability, cohesion, coherence, entropy and Qi, with a spoken description."""
    raise NotImplementedError


@router.get("/subjects/{subject_id}/summary")
async def subject_summary(subject_id: str):
    """AI summarization by subject - EchoNotes Feature 6."""
    raise NotImplementedError


@router.get("/summary/period")
async def period_summary(start: str, end: str, subject_id: str | None = None):
    """AI summarization by time period - EchoNotes Feature 6 ("summarize this week")."""
    raise NotImplementedError
