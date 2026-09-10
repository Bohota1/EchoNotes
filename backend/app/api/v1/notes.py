"""Note read endpoints.

Write operations on notes (create/edit/move within a hierarchy) belong to the
hierarchy work and are not defined here.

    GET /api/v1/notes            recent notes, newest first
    GET /api/v1/notes/{note_id}  one note with its transcripts and understanding
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.api.v1.serializers import capture_response, note_summary
from app.db.repositories import NoteRepository
from app.db.session import get_db
from app.schemas.capture import CaptureResponse, NoteSummary

router = APIRouter()


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
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
