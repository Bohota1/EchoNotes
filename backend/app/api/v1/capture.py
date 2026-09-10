"""Capture endpoints - EchoNotes Feature 1.

POST /capture/audio  is the spacebar path: the browser uploads what it recorded while Space was
held, and the LNT pipeline runs on it.
"""

from fastapi import APIRouter, UploadFile

from app.schemas.capture import CaptureResult, CaptureStatus

router = APIRouter()


@router.post("/audio", response_model=CaptureResult)
async def capture_audio(file: UploadFile, language: str | None = None):
    """Run a recording through Transcribe -> Understand -> Organize -> Store -> Respond."""
    raise NotImplementedError


@router.get("/{capture_id}/status", response_model=CaptureStatus)
async def capture_status(capture_id: str):
    """Progress for a long capture, so the UI can announce it instead of going silent."""
    raise NotImplementedError


@router.post("/{capture_id}/cancel")
async def cancel_capture(capture_id: str):
    """Discard a capture in flight (Escape while recording)."""
    raise NotImplementedError
