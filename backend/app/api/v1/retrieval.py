"""Voice query and retrieval endpoints (Phase 4, Team Member 3).

    POST /api/v1/retrieval/query      answer a transcribed utterance
    POST /api/v1/retrieval/voice      upload audio, transcribe, then answer
    POST /api/v1/retrieval/ask/start  open the mic to record a question
    POST /api/v1/retrieval/ask/stop   stop, transcribe and answer it
    POST /api/v1/retrieval/reindex    rebuild the vector index from SQLite
    GET  /api/v1/retrieval/status     what the index currently holds

`/ask/start` and `/ask/stop` are the spoken half of the two-button interface:
Space records a note, Enter asks a question, and nothing else is needed to
operate the app without sight. They share the one microphone with
`/capture/start`, so the two cannot run at once.

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

from app.core.errors import AudioCaptureError
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


@router.post("/session/start", summary="Open a conversation session")
def session_start():
    """Shift opens one. Inside it, follow-ups resolve against what was already
    asked, so "how does it relate to system design" finds the right notes."""
    from app.rag.conversation import get_conversation_store

    session = get_conversation_store().start()
    return {
        "session_id": session.id,
        "spoken": "Conversation started. Press Enter to ask a question.",
    }


@router.post("/session/{session_id}/end", summary="End a conversation session")
def session_end(session_id: str):
    from app.rag.conversation import get_conversation_store

    session = get_conversation_store().end(session_id)
    turns = len(session.turns) if session else 0
    return {
        "session_id": session_id,
        "turns": turns,
        "spoken": (
            f"Conversation ended after {turns} question{'s' if turns != 1 else ''}."
            if turns
            else "Conversation ended."
        ),
    }


@router.post(
    "/ask/start",
    summary="Start recording a spoken question",
)
def ask_start():
    """Open the microphone to record a question.

    Deliberately the same `LiveRecorder` singleton that `/capture/start` uses:
    there is one microphone, so recording a question while a note is being
    recorded is a conflict, not something to queue. Whichever started first
    keeps the microphone and the second call is refused.
    """
    from app.capture.live import get_live_recorder

    recorder = get_live_recorder()
    try:
        recorder.start()
    except AudioCaptureError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc

    return {
        "recording": True,
        "spoken": "Listening for your question.",
        "capture_id": recorder.capture_id,
    }


@router.post(
    "/ask/stop",
    response_model=VoiceQueryResponse,
    summary="Stop recording, transcribe the question, and answer it",
)
def ask_stop(
    focused_note_id: str | None = None,
    session_id: str | None = None,
    db: Session = Depends(get_db),
):
    """The spoken half of the two-button loop: audio in, spoken answer out.

    Transcription goes through exactly the same stack a captured note uses, so
    a question benefits from the same model, the same forced language and the
    same vocabulary priming - a question misheard as "system designs" finds
    nothing, so this matters as much here as it does for the note itself.
    """
    from app.capture.live import get_live_recorder
    from app.nlp.correction import correct_transcript_safe
    from app.pipeline.capture_pipeline import transcribe_audio

    recorder = get_live_recorder()
    try:
        captured = recorder.stop()
    except AudioCaptureError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc

    try:
        transcription = transcribe_audio(captured.path)
    except Exception as exc:
        logger.exception("could not transcribe the spoken question")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"could not transcribe the question: {exc}",
        ) from exc

    question = correct_transcript_safe(
        transcription.text, kind="question", unclear=transcription.unclear_passages()
    ).strip()

    if not question:
        # Silence, or speech the recogniser could not make out. Said plainly
        # rather than returned as an error: the user cannot see a status code.
        outcome = VoiceQueryOutcome(
            intent="unknown",
            ok=False,
            spoken="I didn't catch a question. Press Enter and try again.",
        )
        return _to_response(outcome, include_speech=True)

    outcome = handle_voice_query(
        db, question, focused_note_id=focused_note_id, session_id=session_id
    )
    db.commit()

    response = _to_response(outcome, include_speech=True)
    # What the system heard, so a user who was misheard can tell why the answer
    # is odd - and so the UI can show it alongside the answer.
    response.data = {**response.data, "question": question}
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
