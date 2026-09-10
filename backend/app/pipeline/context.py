"""The object carried through the eight stages of the interaction loop.

One `PipelineContext` per capture. Each stage reads what earlier stages wrote and adds its own
fields, so a failed run can be inspected to see exactly how far it got.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class PipelineContext:
    # --- Trigger / Record ---
    capture_id: str
    source: str = "voice"  # voice | ocr | manual
    started_at: datetime = field(default_factory=datetime.utcnow)
    raw_audio_path: Path | None = None
    image_path: Path | None = None

    # --- Transcribe (LNT Section 3.2, 3.3) ---
    normalized_audio_path: Path | None = None
    chunk_paths: list[Path] = field(default_factory=list)
    detected_language: str | None = None
    raw_transcript: str = ""
    english_transcript: str = ""

    # --- Understand (LNT Section 3.4, 3.5 + Feature 2) ---
    cleaned_text: str = ""
    tokens: list[str] = field(default_factory=list)
    lemmas: list[str] = field(default_factory=list)
    word_frequencies: dict[str, int] = field(default_factory=dict)
    summary: str = ""
    themes: list[dict[str, Any]] = field(default_factory=list)
    lda_topics: list[dict[str, Any]] = field(default_factory=list)
    quality: dict[str, float] = field(default_factory=dict)
    note_type: str | None = None  # academic | brainstorm | todo
    entities: list[dict[str, Any]] = field(default_factory=list)

    # --- Organize (Idea11y Section 4.1) ---
    subject_id: str | None = None
    topic_id: str | None = None
    cluster_summary: str = ""

    # --- Store ---
    note_id: str | None = None

    # --- Respond ---
    announcement: str = ""
    earcon: str | None = None

    # --- Diagnostics ---
    stage_timings: dict[str, float] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
