"""Lecture replay - NexaNota Section 4.3.1: "The replayed lecture was
presented as a series of transcribed text, accompanied by the corresponding
timeline and relevant classification labels for each note reference."

NexaNota replays a 30-45 minute lecture video. EchoNotes' unit is one short
voice capture, so this replays *that capture's* segments (its ASR
segment-by-segment transcript, persisted as `Note.asr_segments_json` - see
`app/pipeline/capture_pipeline.py`) rather than a whole course - the
faithful equivalent of "timestamped transcript with labels" at this app's
scale. See the redesign plan, section 6.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from app.db.models import Note


@dataclass(frozen=True)
class ReplaySegment:
    start: float
    end: float
    text: str
    label: str


def build_replay(note: Note) -> list[ReplaySegment]:
    """The note's segments, each tagged with a classification label.

    EchoNotes classifies a whole note, not each segment individually, so
    every segment carries the note's own `note_type` as its label - the
    closest honest equivalent to NexaNota's per-reference label without
    inventing per-segment classification this project does not do.
    """
    try:
        raw = json.loads(note.asr_segments_json or "[]")
    except (TypeError, ValueError):
        raw = []

    label = note.understanding.note_type if note.understanding else "unclassified"

    segments = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        segments.append(
            ReplaySegment(
                start=float(item.get("start", 0.0) or 0.0),
                end=float(item.get("end", 0.0) or 0.0),
                text=text,
                label=label,
            )
        )

    if not segments and (note.cleaned_text or "").strip():
        # No segment timing (e.g. a typed note) - one untimed "segment" so
        # replay still has something to show rather than an empty list.
        segments.append(
            ReplaySegment(start=0.0, end=note.duration_seconds or 0.0, text=note.cleaned_text, label=label)
        )

    return segments
