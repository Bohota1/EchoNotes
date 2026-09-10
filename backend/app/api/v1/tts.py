"""Text-to-speech endpoints (Phase 4, Team Member 3).

    POST /api/v1/tts/speak             turn text into a speech directive
    GET  /api/v1/tts/audio/{filename}  fetch audio a server-side engine produced

`/speak` exists so a client can voice arbitrary text - an announcement, a
re-read of a note - through the same voice-coding rules the rest of the system
uses, rather than inventing its own.

`/audio` only serves files under `TTS_OUTPUT_DIR` and only by bare filename;
the path is rebuilt from the directory rather than taken from the request, so a
crafted name cannot walk out of it.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.config import get_settings
from app.schemas.retrieval import SpeechOut
from app.tts.engine import speak

router = APIRouter()


class SpeakRequest(BaseModel):
    text: str
    note_type: str | None = None
    interrupt: bool = False
    earcon: str | None = None


@router.post("/speak", response_model=SpeechOut, summary="Speak arbitrary text")
def speak_text(payload: SpeakRequest):
    directive = speak(
        payload.text,
        note_type=payload.note_type,
        interrupt=payload.interrupt,
        earcon=payload.earcon,
    )
    return SpeechOut(**directive.to_dict())


@router.get("/audio/{filename}", summary="Fetch synthesised audio")
def get_audio(filename: str):
    settings = get_settings()
    # Rebuild the path from the configured directory and the bare name only.
    safe_name = Path(filename).name
    path = settings.tts_output_dir / safe_name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="audio not found")
    return FileResponse(path, media_type="audio/wav", filename=safe_name)
