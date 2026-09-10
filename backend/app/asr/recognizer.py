"""Speech recognition - LNT Section 3.3.

The paper uses the `SpeechRecognition` library with the Google API, recognizing each
silence-split chunk with the language specified and appending the detected text to a file with a
"." after each chunk.

A Whisper backend sits behind the same interface for offline use; `google` is the default because
it is what the paper measured (about 92% accuracy, Section 4.2).
"""

from __future__ import annotations

import abc
from pathlib import Path


class Recognizer(abc.ABC):
    @abc.abstractmethod
    def recognize_chunk(self, chunk: Path, language: str) -> str: ...


class GoogleRecognizer(Recognizer):
    """speech_recognition.Recognizer().recognize_google(...) - the paper's own choice."""

    def recognize_chunk(self, chunk: Path, language: str) -> str:
        raise NotImplementedError


class WhisperRecognizer(Recognizer):
    """Offline fallback. Not part of the paper; label results as such in any evaluation."""

    def recognize_chunk(self, chunk: Path, language: str) -> str:
        raise NotImplementedError


def transcribe_chunks(chunks: list[Path], language: str, backend: str = "google") -> str:
    """Recognize every chunk in order and join them, appending "." after each (Section 3.3).

    A chunk that cannot be recognized is skipped rather than aborting the capture: the paper's
    framework tolerates unrecognizable audio, and for our users losing one sentence is far better
    than losing a whole lecture.
    """
    raise NotImplementedError


def get_recognizer(backend: str) -> Recognizer:
    return {"google": GoogleRecognizer, "whisper": WhisperRecognizer}[backend]()
