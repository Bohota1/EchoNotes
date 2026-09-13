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
from app.reminders.clarify import (
    handle_reminder_clarification_safe,
    suppress_clarification_note,
)
from app.schemas.capture import (
    CaptureResponse,
    CaptureSourceOut,
    RecordingState,
    TriggerRequest,
)
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

    # Additive: does not touch anything `run_capture` already stored. Reads
    # the entities that step just wrote, and asks the one question or saves
    # the one reminder an "I have a meeting..." note implies - see
    # app/reminders/clarify.py.
    clarification = handle_reminder_clarification_safe(db, note)

    if clarification.spoken is not None:
        # This capture was the clarification machinery talking to itself (an
        # event mention, or an answer to one of its own questions) - build
        # the response first, since `note`'s ORM attributes are unusable the
        # moment its row is gone, then remove it so it never shows up as a
        # stray fragment in the Notes list.
        response = capture_response(note, reminder_prompt=clarification.spoken)
        suppress_clarification_note(db, note)
        db.commit()
        return response

    db.commit()
    db.refresh(note)
    return capture_response(note, reminder_prompt=clarification.spoken)


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


# ---------------------------------------------------------------------------
# Live recording: start, stop, cancel.
#
# `/trigger` records for a fixed number of seconds and blocks until they pass,
# which suits a hardware button but not a person - nobody knows in advance how
# long a thought will take. These three let the user end the recording.
# ---------------------------------------------------------------------------
def _recording_state_out(recorder) -> RecordingState:
    state = recorder.state()
    if state["recording"]:
        spoken = f"Recording, {int(state['elapsed_seconds'])} seconds."
        if state["hit_limit"]:
            spoken = "Recording length limit reached. Press stop."
    else:
        spoken = "Not recording."
    return RecordingState(**state, spoken=spoken)


@router.post(
    "/capture/start",
    response_model=RecordingState,
    summary="Start recording until stopped",
)
def start_recording() -> RecordingState:
    """Open the microphone and record until `/capture/stop` is called."""
    from app.capture.live import get_live_recorder

    recorder = get_live_recorder()
    try:
        recorder.start()
    except AudioCaptureError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    return _recording_state_out(recorder)


@router.get(
    "/capture/state",
    response_model=RecordingState,
    summary="Whether a recording is running",
)
def recording_state() -> RecordingState:
    from app.capture.live import get_live_recorder

    return _recording_state_out(get_live_recorder())


@router.post(
    "/capture/stop",
    response_model=CaptureResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Stop recording and process what was captured",
)
def stop_recording(
    run_understanding: bool = True,
    language: str | None = None,
    db: Session = Depends(get_db),
) -> CaptureResponse:
    """Close the microphone, then run the same pipeline a trigger would.

    The recorded audio is wrapped in a `PreRecordedSource`, so transcription,
    understanding, storage and filing are the identical code path - there is no
    second implementation to keep in step.
    """
    from app.capture.live import get_live_recorder
    from app.capture.sources import PreRecordedSource

    recorder = get_live_recorder()
    try:
        captured = recorder.stop()
    except AudioCaptureError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc

    try:
        note = run_capture(
            db,
            source=PreRecordedSource(captured),
            language=language,
            run_understanding=run_understanding,
        )
    except TranscriptionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    clarification = handle_reminder_clarification_safe(db, note)

    if clarification.spoken is not None:
        response = capture_response(note, reminder_prompt=clarification.spoken)
        suppress_clarification_note(db, note)
        db.commit()
        return response

    db.commit()
    db.refresh(note)
    return capture_response(note, reminder_prompt=clarification.spoken)


@router.post(
    "/capture/cancel",
    response_model=RecordingState,
    summary="Stop recording and discard the audio",
)
def cancel_recording() -> RecordingState:
    """Throw away the recording in progress. Nothing is transcribed or stored."""
    from app.capture.live import get_live_recorder

    recorder = get_live_recorder()
    recorder.cancel()
    return _recording_state_out(recorder)
