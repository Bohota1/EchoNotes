"""Retrieval endpoints - EchoNotes Feature 4 (RAG)."""

from fastapi import APIRouter, UploadFile

from app.schemas.retrieval import QueryResult, VoiceQuery

router = APIRouter()


@router.post("/query", response_model=QueryResult)
async def query(payload: VoiceQuery):
    """Resolve intent, retrieve, answer. Returns one spoken response plus the supporting notes."""
    raise NotImplementedError


@router.post("/voice", response_model=QueryResult)
async def voice_query(file: UploadFile):
    """Transcribe a spoken command, then run the same path as /query."""
    raise NotImplementedError
