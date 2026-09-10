"""Recording and audio intake - LNT Section 3.2.

Two ways in:
  1. The browser records with MediaRecorder and uploads a blob (normal path, spacebar trigger).
  2. The server records from the local microphone (`sounddevice`) for lecture-length capture.

Either way the result is a wav file on disk that the Transcribe stage picks up. The paper records
the whole lecture first and processes it afterwards, so nothing here streams.
"""

from __future__ import annotations

from pathlib import Path


def save_uploaded_audio(data: bytes, capture_id: str, suffix: str = ".webm") -> Path:
    """Write an uploaded recording to AUDIO_RAW_DIR and return its path."""
    raise NotImplementedError


def to_wav(source: Path) -> Path:
    """Convert any uploaded container to 16 kHz mono wav, which is what SpeechRecognition wants."""
    raise NotImplementedError


def record_from_microphone(capture_id: str, max_seconds: int | None = None) -> Path:
    """Record from the server default input device until stopped. Used for long lectures."""
    raise NotImplementedError
