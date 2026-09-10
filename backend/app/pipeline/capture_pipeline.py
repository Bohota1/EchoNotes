"""The capture pipeline.

    trigger -> capture -> transcribe -> clean -> store [-> understand -> store]

This is the single entry point for turning audio into a stored note. The API
layer calls it; so can a script, a test, or another team member's code.

Each stage is a separate module, so any of them can be replaced without
touching this file:

    capture     app.capture.sources     (AudioCaptureSource)
    transcribe  app.asr.transcriber     (Transcriber)
    clean       app.nlp.preprocess
    understand  app.understanding.service
    store       app.db.repositories
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from sqlalchemy.orm import Session

from app.asr.transcriber import (
    TranscriptionResult,
    get_transcriber,
    logprob_to_confidence,
)
from app.capture.sources import AudioCaptureSource, CapturedAudio, get_capture_source
from app.db.models import CaptureSource, Note
from app.db.repositories import NoteRepository
from app.nlp.preprocess import clean_transcript

logger = logging.getLogger(__name__)


def transcribe_audio(
    audio_path: Path, language: str | None = None
) -> TranscriptionResult:
    """Stage 2. Isolated so it can be called on its own or faked in tests."""
    return get_transcriber().transcribe(audio_path, language=language)


def persist_capture(
    db: Session,
    *,
    captured: CapturedAudio | None,
    transcription: TranscriptionResult | None,
    raw_text: str,
    cleaned_text: str,
    source: str,
) -> Note:
    """Stage 4. Write the note row."""
    repo = NoteRepository(db)
    return repo.create(
        raw_transcript=raw_text,
        cleaned_text=cleaned_text,
        source=source,
        audio_path=str(captured.path) if captured else None,
        duration_seconds=(
            transcription.duration_seconds
            if transcription and transcription.duration_seconds
            else (captured.duration_seconds if captured else None)
        ),
        asr_model=transcription.model if transcription else None,
        language=transcription.language if transcription else None,
        language_probability=transcription.language_probability if transcription else None,
        asr_avg_logprob=transcription.avg_logprob if transcription else None,
        asr_no_speech_prob=transcription.no_speech_prob if transcription else None,
        asr_segment_count=len(transcription.segments) if transcription else None,
    )


def run_capture(
    db: Session,
    *,
    source: str | AudioCaptureSource | None = None,
    language: str | None = None,
    max_seconds: int | None = None,
    run_understanding: bool = True,
) -> Note:
    """Run the whole pipeline and return the stored Note.

    The session is flushed but **not committed** - the caller owns the
    transaction, so an API request and a batch script can both use this.
    """
    started = time.perf_counter()

    # --- 1. capture -------------------------------------------------------
    capture_source = (
        source if isinstance(source, AudioCaptureSource) else get_capture_source(source)
    )
    captured = capture_source.capture(max_seconds=max_seconds)
    logger.info(
        "captured %s via %s (%.2fs)",
        captured.capture_id,
        captured.source,
        captured.duration_seconds,
    )

    # --- 2. transcribe ----------------------------------------------------
    transcription = transcribe_audio(captured.path, language=language)
    if transcription.is_empty:
        # Not an error: a trigger with no speech is a normal user mistake, and
        # the empty note plus a low confidence score says so honestly.
        logger.warning("capture %s produced an empty transcript", captured.capture_id)

    # --- 3. clean ---------------------------------------------------------
    cleaned = clean_transcript(transcription.text)

    # --- 4. store ---------------------------------------------------------
    note = persist_capture(
        db,
        captured=captured,
        transcription=transcription,
        raw_text=transcription.text,
        cleaned_text=cleaned,
        source=captured.source,
    )

    # --- 5. understand (Phase 2) -----------------------------------------
    if run_understanding and cleaned:
        _run_understanding(db, note, logprob_to_confidence(transcription.avg_logprob))

    # --- 6. organize (Phase 3, Team Member 2) ------------------------------
    # File the note into Subject -> Topic. Runs even when `run_understanding`
    # is False (understanding only adds a note_type/quality signal that
    # `organize()` does not currently require) so a transcript-only capture
    # is still filed rather than left with `topic_id=None` forever.
    if cleaned:
        _organize_note(db, note)

    logger.info(
        "capture pipeline finished note=%s in %.2fs",
        note.id,
        time.perf_counter() - started,
    )
    return note


def run_understanding_on_text(
    db: Session,
    text: str,
    *,
    persist: bool = False,
    transcription_confidence: float = 1.0,
) -> tuple[Note | None, object]:
    """Run Phase 2 on text that did not come from audio.

    Returns (note_or_None, UnderstandingResult). Used by POST /understand so the
    understanding stage is reachable without a microphone.
    """
    cleaned = clean_transcript(text)

    note: Note | None = None
    if persist:
        note = persist_capture(
            db,
            captured=None,
            transcription=None,
            raw_text=text,
            cleaned_text=cleaned,
            source=CaptureSource.TEXT.value,
        )

    from app.understanding.service import understand

    result = understand(cleaned, transcription_confidence=transcription_confidence)
    if note is not None:
        _store_understanding(db, note, result)
        if cleaned:
            _organize_note(db, note)
    return note, result


def _run_understanding(db: Session, note: Note, transcription_confidence: float) -> None:
    """Run and store Phase 2 for a note.

    Imported lazily so a transcript-only deployment never loads the
    understanding stack, and so a failure here cannot lose the transcript that
    was already written.
    """
    try:
        from app.understanding.service import understand

        result = understand(
            note.cleaned_text, transcription_confidence=transcription_confidence
        )
        _store_understanding(db, note, result)
    except Exception:
        logger.exception("understanding failed for note %s; transcript kept", note.id)


def _organize_note(db: Session, note: Note) -> None:
    """Phase 3 hand-off: file the note into Subject -> Topic
    (`app.understanding.organizer.organize`, Team Member 2's work) once the
    transcript exists. Wrapped in try/except for the same reason as
    `_run_understanding`: organization must never be the reason a capture is
    lost - a note that fails to file stays reachable via `GET /notes` with
    `topic_id=None` rather than disappearing.
    """
    try:
        from app.understanding.organizer import organize

        organize(db, note)
    except Exception:
        logger.exception("organization failed for note %s; note kept unfiled", note.id)


def _store_understanding(db: Session, note: Note, result) -> None:
    from app.db.repositories import EntityRepository, UnderstandingRepository

    UnderstandingRepository(db).upsert(
        note.id,
        note_type=result.note_type,
        note_type_confidence=result.classification.confidence,
        classification_method=result.classification.method,
        classification_rationale=result.classification.rationale,
        readability=result.quality.readability,
        coherence=result.quality.coherence,
        transcription_confidence=result.quality.transcription_confidence,
        quality_score=result.quality.quality_score,
        word_count=result.quality.word_count,
        sentence_count=result.quality.sentence_count,
    )
    EntityRepository(db).replace_for_note(
        note.id, [e.to_row() for e in result.entities]
    )
    db.refresh(note)
