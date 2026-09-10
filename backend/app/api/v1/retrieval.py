"""Voice query and retrieval endpoints (Phase 4, Team Member 3).

    POST /api/v1/retrieval/query    answer a transcribed utterance
    POST /api/v1/retrieval/voice    upload audio, transcribe, then answer
    POST /api/v1/retrieval/reindex  rebuild the vector index from SQLite
    GET  /api/v1/retrieval/status   what the index currently holds

`/query` is the endpoint the whole voice loop runs on. It handles content
questions, hierarchy questions, navigation, organization commands and reminder
questions - one entry point, because they all arrive through one microphone and
the caller cannot know in advance which one an utterance will turn out to be.

Every response carries a `spoken` string that is safe to read aloud even when
`ok` is false, so a client never needs a separate error path to know what to
say.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.rag.indexer import index_stats, reindex_all
from app.rag.service import VoiceQueryOutcome, handle_voice_query
from app.schemas.retrieval import (
    IndexStatusOut,
    ReindexResponse,
    RetrievedNoteOut,
    SpeechOut,
    VoiceQueryRequest,
    VoiceQueryResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _to_response(outcome: VoiceQueryOutcome, include_speech: bool) -> VoiceQueryResponse:
    return VoiceQueryResponse(
        intent=outcome.intent,
        ok=outcome.ok,
        spoken=outcome.spoken,
        answer=outcome.answer_text,
        sources=outcome.sources,
        citations=outcome.citations,
        results=[
            RetrievedNoteOut(
                note_id=note.note_id,
                text=note.text,
                snippet=note.snippet,
                score=round(note.score, 4),
                subject_id=note.subject_id,
                subject_name=note.subject_name,
                topic_id=note.topic_id,
                topic_name=note.topic_name,
                note_type=note.note_type,
                source=note.source,
                created_at=note.created_at,
                matched_by=note.matched_by,
            )
            for note in outcome.results
        ],
        confidence=outcome.confidence,
        method=outcome.method,
        filter_description=outcome.filter_description,
        navigate_to=outcome.navigate_to,
        data=outcome.data,
        speech=(
            SpeechOut(**outcome.speech.to_dict())
            if include_speech and outcome.speech is not None
            else None
        ),
    )


@router.post(
    "/query",
    response_model=VoiceQueryResponse,
    summary="Answer a transcribed voice query",
)
def query(payload: VoiceQueryRequest, db: Session = Depends(get_db)):
    """Resolve intent, retrieve, answer, and return something ready to speak."""
    outcome = handle_voice_query(
        db,
        payload.utterance,
        focused_note_id=payload.focused_note_id,
        top_k=payload.top_k,
    )
    db.commit()  # organization commands can write; reads are unaffected
    return _to_response(outcome, payload.speak)


@router.post(
    "/voice",
    response_model=VoiceQueryResponse,
    summary="Upload spoken audio, transcribe it, and answer",
)
async def voice_query(
    file: UploadFile = File(...),
    focused_note_id: str | None = None,
    db: Session = Depends(get_db),
):
    """The full spoken path: audio in, spoken answer out.

    Transcription reuses Team Member 1's capture and ASR stack rather than
    opening a second audio path into the system.
    """
    from app.capture.sources import UploadCaptureSource
    from app.pipeline.capture_pipeline import transcribe_audio

    data = await file.read()
    if not data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="empty audio upload",
        )

    suffix = "." + (file.filename or "query.wav").rsplit(".", 1)[-1]
    try:
        captured = UploadCaptureSource(data, suffix=suffix).capture()
        transcription = transcribe_audio(captured.path)
    except Exception as exc:
        logger.exception("voice query transcription failed")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"could not transcribe the audio: {exc}",
        ) from exc

    utterance = (transcription.text or "").strip()
    if not utterance:
        outcome = VoiceQueryOutcome(
            intent="unknown",
            ok=False,
            spoken="I didn't hear anything. Try again.",
        )
        return _to_response(outcome, include_speech=True)

    outcome = handle_voice_query(db, utterance, focused_note_id=focused_note_id)
    db.commit()
    response = _to_response(outcome, include_speech=True)
    response.data = {**response.data, "transcribed_utterance": utterance}
    return response


@router.post(
    "/reindex",
    response_model=ReindexResponse,
    summary="Rebuild the vector index from SQLite",
)
def reindex(db: Session = Depends(get_db)):
    """Rebuild every vector from the notes table.

    Required after changing `EMBEDDING_BACKEND`: vectors from two different
    models are not comparable, and a half-migrated index returns confident
    nonsense instead of failing loudly.
    """
    result = reindex_all(db)
    return ReindexResponse(
        notes=result["notes"],
        chunks=result["chunks"],
        backend=result["backend"],
        spoken=(
            f"Reindexed {result['notes']} note{'s' if result['notes'] != 1 else ''} "
            f"into {result['chunks']} searchable chunk"
            f"{'s' if result['chunks'] != 1 else ''}."
        ),
    )


@router.get("/status", response_model=IndexStatusOut, summary="Vector index status")
def status_(db: Session = Depends(get_db)):
    from app.db.repositories import NoteRepository

    stats = index_stats()
    return IndexStatusOut(
        vector_store=stats["vector_store"],
        embedding_backend=stats["embedding_backend"],
        chunk_count=stats["chunk_count"],
        note_count=NoteRepository(db).count(),
    )
