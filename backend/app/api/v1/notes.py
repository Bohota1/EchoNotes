"""Note endpoints - Idea11y Section 4.2 (Design Goal 2).

The paper's requirement is that a user can add, edit, delete and move a note **from inside the
outline**, never having to leave it for a separate dialog. These endpoints are the server half of
that: one call per action, each returning enough for the client to re-render and announce.
"""

from fastapi import APIRouter

from app.schemas.note import NoteCreate, NoteInfo, NoteMove, NoteOut, NoteUpdate

router = APIRouter()


@router.post("", response_model=NoteOut)
async def create_note(payload: NoteCreate):
    """Add a note under a topic (Ctrl+Alt+N, or the Add button in each cluster)."""
    raise NotImplementedError


@router.get("/{note_id}", response_model=NoteOut)
async def get_note(note_id: str):
    raise NotImplementedError


@router.patch("/{note_id}", response_model=NoteOut)
async def update_note(note_id: str, payload: NoteUpdate):
    """Edit in place (Ctrl+Alt+E). Marks the parent topic's summary stale."""
    raise NotImplementedError


@router.post("/{note_id}/move", response_model=NoteOut)
async def move_note(note_id: str, payload: NoteMove):
    """Re-file into another topic (Ctrl+Alt+M). Marks both topics' summaries stale."""
    raise NotImplementedError


@router.delete("/{note_id}")
async def delete_note(note_id: str):
    """Delete (Ctrl+Alt+D). The client confirms first and announces where focus went."""
    raise NotImplementedError


@router.get("/{note_id}/info", response_model=NoteInfo)
async def note_info(note_id: str):
    """Note info (Ctrl+Alt+I) - Idea11y's creator-and-colour announcement, adapted."""
    raise NotImplementedError
