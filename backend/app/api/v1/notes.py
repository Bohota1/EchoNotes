"""Note read endpoints.

Write operations on notes (create/edit/move within a hierarchy) belong to the
hierarchy work and are not defined here.

    GET /api/v1/notes            recent notes, newest first
    GET /api/v1/notes/{note_id}  one note with its transcripts and understanding
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v1.serializers import capture_response, note_summary
from app.db.repositories import NoteContentRepository, NoteRepository
from app.db.session import get_db
from app.schemas.capture import CaptureResponse, NoteSummary

router = APIRouter()


class NoteContentOut(BaseModel):
    """A note's 3-area content (NexaNota 4.3.3)."""

    note_id: str
    definition: str
    example_analysis: str
    summary: str
    edit_markdown: str
    edited_by_user: bool
    method: str


class EditMarkdown(BaseModel):
    markdown: str


class ReplaySegmentOut(BaseModel):
    start: float
    end: float
    text: str
    label: str


@router.get("", response_model=list[NoteSummary], summary="List notes")
def list_notes(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[NoteSummary]:
    return [note_summary(n) for n in NoteRepository(db).list(limit=limit, offset=offset)]


@router.get("/{note_id}", response_model=CaptureResponse, summary="Get one note")
def get_note(note_id: str, db: Session = Depends(get_db)) -> CaptureResponse:
    note = NoteRepository(db).get(note_id)
    if note is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"no note with id {note_id}"
        )
    return capture_response(note)


@router.delete(
    "/{note_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_note(note_id: str, db: Session = Depends(get_db)) -> Response:
    if not NoteRepository(db).delete(note_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"no note with id {note_id}"
        )
    # Phase 4 (Team Member 3): drop the note's vectors too. SQLite is
    # authoritative, so an orphaned vector would surface a note that no longer
    # exists - the retriever skips those defensively, but leaving them behind
    # would grow the index forever.
    from app.rag.indexer import remove_note

    remove_note(note_id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{note_id}/content", response_model=NoteContentOut, summary="The 3-area note content")
def get_note_content(note_id: str, db: Session = Depends(get_db)) -> NoteContentOut:
    """Note-Taking Area, Link Area (see `/api/v1/graph/topics/{id}/web-resources`
    for a topic's links) and Edit Area (NexaNota 4.3.3, D2)."""
    note = NoteRepository(db).get(note_id)
    if note is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no note with id {note_id}")
    content = NoteContentRepository(db).get_for_note(note_id)
    if content is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"note {note_id} has no generated content yet"
        )
    return NoteContentOut(
        note_id=note_id,
        definition=content.definition,
        example_analysis=content.example_analysis,
        summary=content.summary,
        edit_markdown=content.edit_markdown,
        edited_by_user=content.edited_by_user,
        method=content.method,
    )


@router.patch("/{note_id}/content", response_model=NoteContentOut, summary="Save the Edit Area")
def edit_note_content(
    note_id: str, payload: EditMarkdown, db: Session = Depends(get_db)
) -> NoteContentOut:
    """The Edit Area (NexaNota 4.3.3): the student's own markdown. Once
    saved here, later regeneration never overwrites it (see
    `NoteContentRepository.upsert_generated`)."""
    content = NoteContentRepository(db).save_edit(note_id, payload.markdown)
    if content is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"note {note_id} has no generated content yet"
        )
    db.commit()
    return NoteContentOut(
        note_id=note_id,
        definition=content.definition,
        example_analysis=content.example_analysis,
        summary=content.summary,
        edit_markdown=content.edit_markdown,
        edited_by_user=content.edited_by_user,
        method=content.method,
    )


@router.get(
    "/{note_id}/replay",
    response_model=list[ReplaySegmentOut],
    summary="Timestamped transcript replay",
)
def get_note_replay(note_id: str, db: Session = Depends(get_db)) -> list[ReplaySegmentOut]:
    """The note's segments with their timing and classification label
    (NexaNota 4.3.1). See `app/graph/replay.py` for how EchoNotes' one-note
    unit maps onto the paper's whole-lecture replay."""
    from app.graph.replay import build_replay

    note = NoteRepository(db).get(note_id)
    if note is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no note with id {note_id}")
    return [
        ReplaySegmentOut(start=s.start, end=s.end, text=s.text, label=s.label)
        for s in build_replay(note)
    ]
