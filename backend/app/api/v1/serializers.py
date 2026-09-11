"""ORM -> response-schema conversion.

Kept out of the endpoint modules so the same Note can be rendered identically
by /trigger, /notes/{id} and /understand.
"""

from __future__ import annotations

from app.asr.transcriber import logprob_to_confidence
from app.db.models import Note
from app.schemas.capture import CaptureResponse, NoteSummary, TranscriptionOut
from app.schemas.note import NoteOut
from app.schemas.understanding import (
    ClassificationOut,
    EntityOut,
    QualityOut,
    UnderstandingOut,
)


def transcription_out(note: Note) -> TranscriptionOut:
    return TranscriptionOut(
        model=note.asr_model,
        language=note.language,
        language_probability=note.language_probability,
        confidence=logprob_to_confidence(note.asr_avg_logprob),
        no_speech_probability=note.asr_no_speech_prob,
        segment_count=note.asr_segment_count,
        source_language=note.source_language,
        translated=bool(note.translated),
        chunk_count=note.chunk_count,
    )


def understanding_out(note: Note) -> UnderstandingOut | None:
    record = note.understanding
    if record is None:
        return None

    entities = [EntityOut.model_validate(e) for e in note.entities]

    def values_of(kind: str) -> list[str]:
        return [e.normalized or e.value for e in entities if e.kind == kind]

    return UnderstandingOut(
        note_id=note.id,
        note_type=record.note_type,
        classification=ClassificationOut(
            note_type=record.note_type,
            confidence=record.note_type_confidence,
            method=record.classification_method,
            rationale=record.classification_rationale,
        ),
        quality=QualityOut(
            readability=record.readability,
            coherence=record.coherence,
            transcription_confidence=record.transcription_confidence,
            quality_score=record.quality_score,
            word_count=record.word_count,
            sentence_count=record.sentence_count,
        ),
        entities=entities,
        people=values_of("person"),
        dates=values_of("date"),
        deadlines=values_of("deadline"),
        tasks=values_of("task"),
        key_phrases=values_of("key_phrase"),
        llm_used=record.classification_method != "rules"
        or any(e.extractor == "llm" for e in entities),
    )


def capture_response(note: Note) -> CaptureResponse:
    return CaptureResponse(
        note_id=note.id,
        source=note.source,
        raw_transcript=note.raw_transcript,
        cleaned_text=note.cleaned_text,
        duration_seconds=note.duration_seconds,
        audio_path=note.audio_path,
        created_at=note.created_at,
        transcription=transcription_out(note),
        understanding=understanding_out(note),
    )


def note_summary(note: Note) -> NoteSummary:
    return NoteSummary(
        note_id=note.id,
        cleaned_text=note.cleaned_text,
        source=note.source,
        note_type=note.understanding.note_type if note.understanding else None,
        quality_score=note.understanding.quality_score if note.understanding else None,
        created_at=note.created_at,
    )


# --- Phase 3: hierarchy-facing note serialization --------------------------


def note_out(note: Note) -> NoteOut:
    """A note as it appears inside the hierarchy (`TopicOut.notes`,
    `GET /hierarchy/topics/{id}/notes`, note-move responses). Distinct from
    `note_summary()` below, which backs the flat `/notes` listing and does
    not know about topics.

    `note.source` (Phase 1's `CaptureSource`) is reconciled with the Phase 3
    `NoteSource` schema by `app.hierarchy.service.note_source_label` - the one
    place that mapping lives, also used when building the outline tree.
    """
    from app.hierarchy.service import note_source_label

    return NoteOut(
        id=note.id,
        topic_id=note.topic_id or "",
        text=note.cleaned_text,
        note_type=(note.understanding.note_type if note.understanding else "academic"),
        source=note_source_label(note.source),
        created_at=note.created_at,
        updated_at=note.updated_at,
        quality_score=note.understanding.quality_score if note.understanding else None,
    )
