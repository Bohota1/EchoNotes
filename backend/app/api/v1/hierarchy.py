"""Outline endpoints - Idea11y Section 4.1.

GET /hierarchy/outline is the endpoint the whole UI is built around: it returns the overview and
the full Subject/Topic/Note tree with heading levels attached.
"""

from fastapi import APIRouter

from app.schemas.hierarchy import OutlineOut, OverviewOut, TopicCreate, TopicOut

router = APIRouter()


@router.get("/outline", response_model=OutlineOut)
async def get_outline():
    """The complete hierarchical outline, overview first."""
    raise NotImplementedError


@router.get("/overview", response_model=OverviewOut)
async def get_overview():
    """Library Overview only, for the Ctrl+Alt+O shortcut."""
    raise NotImplementedError


@router.post("/topics", response_model=TopicOut)
async def create_topic(payload: TopicCreate):
    """Idea11y Section 4.2: the "New Cluster" action."""
    raise NotImplementedError


@router.post("/topics/{topic_id}/summary", response_model=TopicOut)
async def refresh_topic_summary(topic_id: str):
    """Regenerate the AI cluster summary for one topic."""
    raise NotImplementedError


@router.post("/subjects/{subject_id}/recluster")
async def recluster(subject_id: str):
    """Re-run DBSCAN over a subject's notes and report what moved, so it can be announced."""
    raise NotImplementedError
