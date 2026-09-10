"""Speech to text.

`Transcriber` is the interface; `FasterWhisperTranscriber` is the shipped
implementation. Everything downstream depends on `TranscriptionResult`, so a
different ASR engine can be dropped in without touching the pipeline.

Why faster-whisper: it decodes audio through bundled PyAV rather than an
external ffmpeg binary, and it reports per-segment `avg_logprob` and
`no_speech_prob`. Those two numbers are what the Phase 2 transcription
confidence metric is built from - an ASR engine that only returns a string
would leave that metric guessing.
"""

from __future__ import annotations

import abc
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path

from app.config import get_settings
from app.core.errors import TranscriptionError

logger = logging.getLogger(__name__)


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str
    avg_logprob: float | None = None
    no_speech_prob: float | None = None


@dataclass
class TranscriptionResult:
    """Everything the ASR stage knows about one recording."""

    text: str
    language: str | None = None
    language_probability: float | None = None
    duration_seconds: float | None = None
    model: str = ""
    segments: list[TranscriptSegment] = field(default_factory=list)

    @property
    def avg_logprob(self) -> float | None:
        """Duration-weighted mean log probability across segments.

        Weighted by segment length so one short, uncertain segment does not
        dominate the score of a long, clean recording.
        """
        weighted, total = 0.0, 0.0
        for segment in self.segments:
            if segment.avg_logprob is None:
                continue
            span = max(segment.end - segment.start, 1e-6)
            weighted += segment.avg_logprob * span
            total += span
        return weighted / total if total else None

    @property
    def no_speech_prob(self) -> float | None:
        """Mean probability that segments contained no speech at all."""
        values = [s.no_speech_prob for s in self.segments if s.no_speech_prob is not None]
        return sum(values) / len(values) if values else None

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


class Transcriber(abc.ABC):
    name: str = "base"

    @abc.abstractmethod
    def transcribe(self, audio_path: Path, language: str | None = None) -> TranscriptionResult:
        ...


class FasterWhisperTranscriber(Transcriber):
    """Whisper via CTranslate2.

    The model is loaded lazily and cached on the instance: loading costs a few
    seconds and several hundred MB, so it must not happen at import time or
    once per request.
    """

    name = "faster_whisper"

    def __init__(
        self,
        model_size: str | None = None,
        device: str | None = None,
        compute_type: str | None = None,
    ):
        settings = get_settings()
        self.model_size = model_size or settings.whisper_model
        self.device = device or settings.whisper_device
        self.compute_type = compute_type or settings.whisper_compute_type
        self._model = None

    def _load_model(self):
        if self._model is not None:
            return self._model
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise TranscriptionError(
                "faster-whisper is not installed; run `pip install faster-whisper`"
            ) from exc

        logger.info(
            "loading whisper model=%s device=%s compute_type=%s",
            self.model_size,
            self.device,
            self.compute_type,
        )
        self._model = WhisperModel(
            self.model_size, device=self.device, compute_type=self.compute_type
        )
        return self._model

    def transcribe(self, audio_path: Path, language: str | None = None) -> TranscriptionResult:
        if not Path(audio_path).exists():
            raise TranscriptionError(f"audio file not found: {audio_path}")

        settings = get_settings()
        model = self._load_model()

        try:
            segments_iter, info = model.transcribe(
                str(audio_path),
                language=language or settings.whisper_language,
                beam_size=settings.whisper_beam_size,
                vad_filter=settings.whisper_vad_filter,
            )
            # faster-whisper returns a generator; decoding happens on iteration.
            segments = [
                TranscriptSegment(
                    start=s.start,
                    end=s.end,
                    text=s.text.strip(),
                    avg_logprob=getattr(s, "avg_logprob", None),
                    no_speech_prob=getattr(s, "no_speech_prob", None),
                )
                for s in segments_iter
            ]
        except TranscriptionError:
            raise
        except Exception as exc:
            raise TranscriptionError(f"transcription failed: {exc}") from exc

        text = " ".join(s.text for s in segments if s.text).strip()

        return TranscriptionResult(
            text=text,
            language=getattr(info, "language", None),
            language_probability=getattr(info, "language_probability", None),
            duration_seconds=getattr(info, "duration", None),
            model=f"{self.name}:{self.model_size}",
            segments=segments,
        )


def logprob_to_confidence(avg_logprob: float | None) -> float:
    """Map a mean log probability to a 0-1 confidence.

    Whisper's avg_logprob is a per-token mean in roughly [-1.5, 0]; exponentiating
    turns it back into a probability-like value, which is what a caller wants to
    reason about. Returns 0.0 when there is nothing to score.
    """
    if avg_logprob is None:
        return 0.0
    return max(0.0, min(1.0, math.exp(avg_logprob)))


_default_transcriber: Transcriber | None = None


def get_transcriber() -> Transcriber:
    """Process-wide transcriber, so the model is loaded at most once."""
    global _default_transcriber
    if _default_transcriber is None:
        _default_transcriber = FasterWhisperTranscriber()
    return _default_transcriber


def set_transcriber(transcriber: Transcriber | None) -> None:
    """Override the shared transcriber. Tests inject a fake through this."""
    global _default_transcriber
    _default_transcriber = transcriber
