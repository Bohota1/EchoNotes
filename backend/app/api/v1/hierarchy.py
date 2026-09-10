"""Hierarchy endpoints - Idea11y Section 4.1/4.2 adapted (Phase 3), plus the
Phase 3 voice-organization command endpoint.

Phase 5's summarization endpoints live in `api/v1/summarization.py` (mounted
at `/api/v1/summary`) since the spec asks for them as a separate deliverable,
but both routers call into the same `app.hierarchy.service` /
`app.hierarchy.summarization` so there is one implementation behind both.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.v1.serializers import note_out
from app.db.session import get_db
from app.hierarchy import service as hierarchy_service
from app.schemas.hierarchy import (
    CommandRequest,
    CommandResponse,
    NoteMoveByName,
    OutlineOut,
    OverviewOut,
    SubjectCreate,
    SubjectOut,
    TopicCreate,
    TopicOut,
)
from app.schemas.note import NoteMove, NoteOut

router = APIRouter()


def _topic_out(topic) -> TopicOut:
    notes = sorted(topic.notes, key=lambda n: n.created_at, reverse=True)
    return TopicOut(
        id=topic.id,
        name=topic.name,
        kind=topic.kind,
        summary=topic.summary,
        summary_stale=topic.summary_stale,
        notes=[note_out(n) for n in notes],
    )


def _subject_out(subject) -> SubjectOut:
    topics = sorted(subject.topics, key=lambda t: t.name.lower())
    return SubjectOut(
        id=subject.id,
        name=subject.name,
        is_unfiled=subject.is_unfiled,
        topics=[_topic_out(t) for t in topics],
    )


@router.get("", response_model=OutlineOut, summary="The full hierarchy: nested JSON + narration")
def get_hierarchy(db: Session = Depends(get_db)) -> OutlineOut:
    """`GET /api/v1/hierarchy` - the Phase 3 spec's endpoint, literally.

    Identical payload to `GET /hierarchy/outline` below; both exist so the
    route matches the spec exactly while staying compatible with anything
    that calls the more specific `/outline` path.
    """
    return OutlineOut(**hierarchy_service.get_outline(db))


@router.get("/outline", response_model=OutlineOut)
def get_outline(db: Session = Depends(get_db)) -> OutlineOut:
    """The complete hierarchical outline, overview first, plus narration."""
    return OutlineOut(**hierarchy_service.get_outline(db))


@router.get("/overview", response_model=OverviewOut)
def get_overview(db: Session = Depends(get_db)) -> OverviewOut:
    """Library Overview only, for the Ctrl+Alt+O shortcut."""
    return OverviewOut(**hierarchy_service.get_overview(db))


@router.get("/subjects", response_model=list[SubjectOut])
def list_subjects(db: Session = Depends(get_db)) -> list[SubjectOut]:
    from app.db.repositories import SubjectRepository

    return [_subject_out(s) for s in SubjectRepository(db).list()]


@router.post("/subjects", response_model=SubjectOut, status_code=status.HTTP_201_CREATED)
def create_subject(payload: SubjectCreate, db: Session = Depends(get_db)) -> SubjectOut:
    subject, _created = hierarchy_service.create_subject(db, payload.name)
    db.commit()
    db.refresh(subject)
    return _subject_out(subject)


@router.get("/subjects/{subject_id}/topics", response_model=list[TopicOut])
def list_topics_under_subject(subject_id: str, db: Session = Depends(get_db)) -> list[TopicOut]:
    """"What topics are under X?" as a direct, id-addressed GET (the voice
    command with the same name goes through `POST /hierarchy/command` instead,
    since it resolves the subject by spoken name)."""
    from app.db.repositories import SubjectRepository, TopicRepository

    if SubjectRepository(db).get(subject_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no subject {subject_id}")
    return [_topic_out(t) for t in TopicRepository(db).list_for_subject(subject_id)]


@router.post("/subjects/{subject_id}/recluster")
def recluster(subject_id: str, db: Session = Depends(get_db)) -> dict:
    """Re-run clustering over a subject's notes and report what moved, so the
    client can announce it rather than let the outline silently rearrange."""
    from app.db.repositories import SubjectRepository

    if SubjectRepository(db).get(subject_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no subject {subject_id}")
    result = hierarchy_service.recluster_subject(db, subject_id)
    db.commit()
    return {"topics": result}


@router.post("/topics", response_model=TopicOut, status_code=status.HTTP_201_CREATED)
def create_topic(payload: TopicCreate, db: Session = Depends(get_db)) -> TopicOut:
    """Idea11y Section 4.2: the "New Cluster" action."""
    from app.db.repositories import SubjectRepository

    if SubjectRepository(db).get(payload.subject_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no subject {payload.subject_id}")
    topic, _created = hierarchy_service.create_topic(
        db, payload.subject_id, payload.name, payload.kind
    )
    db.commit()
    db.refresh(topic)
    return _topic_out(topic)


@router.get("/topics/{topic_id}/notes", response_model=list[NoteOut])
def list_notes_under_topic(topic_id: str, db: Session = Depends(get_db)) -> list[NoteOut]:
    """"What notes are under X?" as a direct, id-addressed GET."""
    from app.db.repositories import NoteRepository, TopicRepository

    if TopicRepository(db).get(topic_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no topic {topic_id}")
    return [note_out(n) for n in NoteRepository(db).list_by_topic(topic_id)]


@router.post("/topics/{topic_id}/summary", response_model=TopicOut)
def refresh_topic_summary(topic_id: str, db: Session = Depends(get_db)) -> TopicOut:
    """Regenerate the AI cluster summary for one topic."""
    from app.db.repositories import TopicRepository

    if TopicRepository(db).get(topic_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no topic {topic_id}")
    hierarchy_service.refresh_topic_summary(db, topic_id)
    db.commit()
    return _topic_out(TopicRepository(db).get(topic_id))


@router.post("/notes/{note_id}/move", response_model=NoteOut)
def move_note(note_id: str, payload: NoteMove, db: Session = Depends(get_db)) -> NoteOut:
    """Idea11y Section 4.2: re-file a note by target topic id (the outline's
    drop-down of current clusters)."""
    try:
        note, _topic = hierarchy_service.move_note(db, note_id, payload.target_topic_id)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    db.commit()
    db.refresh(note)
    return note_out(note)


@router.post("/notes/{note_id}/move-by-name", response_model=NoteOut)
def move_note_by_name(
    note_id: str, payload: NoteMoveByName, db: Session = Depends(get_db)
) -> NoteOut:
    """Re-file a note by spoken topic/subject name, fuzzy-matched, creating a
    new topic if nothing close enough exists - "Move this note to Machine
    Learning" from a text client, without a topic id in hand."""
    try:
        note, _topic, _subject, _created = hierarchy_service.move_note_by_name(
            db, note_id, payload.target_name
        )
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    db.commit()
    db.refresh(note)
    return note_out(note)


@router.post("/command", response_model=CommandResponse)
def run_command(payload: CommandRequest, db: Session = Depends(get_db)) -> CommandResponse:
    """Voice-based organization commands (Phase 3 spec): "move this note to
    X", "what topics are under X", "what notes are under X". Team Member 3's
    voice pipeline transcribes the utterance and calls this with the
    resulting text plus the currently-focused note id."""
    from app.hierarchy.commands import handle_command

    result = handle_command(db, payload.text, focused_note_id=payload.focused_note_id)
    if result.ok:
        db.commit()
    else:
        db.rollback()
    return CommandResponse(
        intent=result.intent, ok=result.ok, spoken=result.spoken, data=result.data
    )
