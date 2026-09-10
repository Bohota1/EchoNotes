"""Capture endpoints (Phase 1) and the understanding utility endpoint (Phase 2).

    POST /api/v1/trigger          fire the capture pipeline
    GET  /api/v1/capture/sources  which capture sources exist and are usable
    POST /api/v1/understand       run Phase 2 on text, no audio needed
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.v1.serializers import capture_response, understanding_out
from app.capture.sources import SOURCES, get_capture_source
from app.config import get_settings
from app.core.errors import AudioCaptureError, TranscriptionError
from app.db.session import get_db
from app.pipeline.capture_pipeline import run_capture, run_understanding_on_text
from app.schemas.capture import CaptureResponse, CaptureSourceOut, TriggerRequest
from app.schemas.understanding import UnderstandingOut, UnderstandRequest

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/trigger",
    response_model=CaptureResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Trigger a voice capture",
)
def trigger(
    payload: TriggerRequest | None = None,
    db: Session = Depends(get_db),
) -> CaptureResponse:
    """Capture audio, transcribe it, clean it, understand it, store it.

    An empty body is valid: the configured capture source is used and the
    language is auto-detected. This is the endpoint a hardware button maps to.
    """
    request = payload or TriggerRequest()

    try:
        note = run_capture(
            db,
            source=request.source,
            language=request.language,
            max_seconds=request.max_seconds,
            run_understanding=request.run_understanding,
        )
    except AudioCaptureError as exc:
        # The capture device is unusable - a configuration problem, not a bug.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except TranscriptionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    db.commit()
    db.refresh(note)
    return capture_response(note)


@router.get(
    "/capture/sources",
    response_model=list[CaptureSourceOut],
    summary="List capture sources",
)
def list_sources() -> list[CaptureSourceOut]:
    """Report every registered source and whether it can run right now.

    Lets a client find out that the microphone is unavailable before firing a
    trigger that would fail.
    """
    default = get_settings().capture_source
    out: list[CaptureSourceOut] = []
    for name in sorted(SOURCES):
        try:
            available, detail = get_capture_source(name).is_available()
        except Exception as exc:
            available, detail = False, str(exc)
        out.append(
            CaptureSourceOut(
                name=name, available=available, detail=detail, is_default=name == default
            )
        )
    return out


@router.post(
    "/understand",
    response_model=UnderstandingOut,
    summary="Run understanding on text",
)
def understand_text(
    payload: UnderstandRequest,
    db: Session = Depends(get_db),
) -> UnderstandingOut:
    """Phase 2 over supplied text, bypassing audio capture.

    Set `persist: true` to also store it as a note.
    """
    note, result = run_understanding_on_text(
        db,
        payload.text,
        persist=payload.persist,
        transcription_confidence=(
            payload.transcription_confidence
            if payload.transcription_confidence is not None
            else 1.0
        ),
    )
    db.commit()

    if note is not None:
        db.refresh(note)
        rendered = understanding_out(note)
        if rendered is not None:
            return rendered
    return result.to_schema()
