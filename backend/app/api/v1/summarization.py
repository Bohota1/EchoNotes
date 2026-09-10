"""Phase 5 - Summarization endpoints: by Subject, Project (a kind of Topic),
Topic and time range.

Reuses Topic summaries where possible (`app.hierarchy.cluster_summary`) and
adds the roll-up summarizer for larger collections
(`app.hierarchy.summarization`). Mounted at `/api/v1/summary`.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.hierarchy import summarization
from app.schemas.summarization import SummaryOut

router = APIRouter()


def _as_out(rollup: summarization.RollupSummary) -> SummaryOut:
    return SummaryOut(
        scope=rollup.scope,
        scope_id=rollup.scope_id,
        scope_name=rollup.scope_name,
        note_count=rollup.note_count,
        summary=rollup.summary,
        spoken=rollup.spoken,
        method=rollup.method,
    )


@router.get("/subjects/{subject_id}", response_model=SummaryOut)
def summarize_subject(subject_id: str, db: Session = Depends(get_db)) -> SummaryOut:
    """Subject -> Topics -> topic summaries -> subject-level roll-up."""
    try:
        result = summarization.summarize_subject(db, subject_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    db.commit()
    return _as_out(result)


@router.get("/topics/{topic_id}", response_model=SummaryOut)
def summarize_topic(
    topic_id: str, refresh: bool = False, db: Session = Depends(get_db)
) -> SummaryOut:
    """The topic's own AI-generated summary (Idea11y Section 4.1). Pass
    `?refresh=true` to force regeneration even if it is not marked stale."""
    try:
        result = summarization.summarize_topic(db, topic_id, force_refresh=refresh)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    db.commit()
    return _as_out(result)


@router.get("/range", response_model=SummaryOut)
def summarize_range(
    start: datetime | None = Query(default=None, description="ISO-8601. Omit for open-ended."),
    end: datetime | None = Query(default=None, description="ISO-8601. Omit for open-ended."),
    subject_id: str | None = Query(default=None),
    topic_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> SummaryOut:
    """Roll-up summary of every note captured in `[start, end)`, optionally
    scoped to one Subject or Topic. Omit both `start` and `end` to summarize
    the whole library across all time."""
    result = summarization.summarize_range(
        db, start=start, end=end, subject_id=subject_id, topic_id=topic_id
    )
    db.commit()
    return _as_out(result)
