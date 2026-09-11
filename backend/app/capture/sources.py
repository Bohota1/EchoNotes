"""Audio capture sources.

`AudioCaptureSource` is the seam between "something asked for audio" and "where
the audio actually comes from". The pipeline only ever sees this interface, so
swapping a laptop microphone for a GPIO button wired to a mic is a matter of
registering another implementation - no pipeline change.

Implementations shipped here:

    DummyCaptureSource      replays a fixture file; needs no hardware, so the
                            whole pipeline is runnable and testable on a machine
                            with no microphone and in CI
    MicrophoneCaptureSource records from the host default input device
    UploadCaptureSource     wraps bytes the caller already has

A future GPIOCaptureSource / SerialCaptureSource implements the same two methods
and is registered in `SOURCES` below. See `app/capture/trigger.py` for the
button half of that story.
"""

from __future__ import annotations

import abc
import logging
import uuid
import wave
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.config import get_settings
from app.core.errors import AudioCaptureError

logger = logging.getLogger(__name__)

# What the ASR stage expects. Whisper resamples internally, but writing 16 kHz
# mono here keeps fixtures small and makes every source produce identical files.
TARGET_SAMPLE_RATE = 16_000
TARGET_CHANNELS = 1
TARGET_SAMPLE_WIDTH = 2  # bytes, i.e. 16-bit PCM


@dataclass
class CapturedAudio:
    """One recording, on disk and described."""

    capture_id: str
    path: Path
    duration_seconds: float
    sample_rate: int
    channels: int
    source: str
    captured_at: datetime


class AudioCaptureSource(abc.ABC):
    """Anything that can hand the pipeline a recording."""

    name: str = "base"

    @abc.abstractmethod
    def capture(self, max_seconds: int | None = None) -> CapturedAudio:
        """Acquire audio and return it as a wav file on disk."""

    def is_available(self) -> tuple[bool, str]:
        """(usable, reason). Lets /trigger explain a problem instead of failing."""
        return True, "ready"


def _new_capture_id() -> str:
    return uuid.uuid4().hex[:12]


def _output_path(capture_id: str) -> Path:
    settings = get_settings()
    settings.audio_raw_dir.mkdir(parents=True, exist_ok=True)
    return settings.audio_raw_dir / f"{capture_id}.wav"


def describe_wav(path: Path) -> tuple[float, int, int]:
    """(duration_seconds, sample_rate, channels) read from the wav header."""
    try:
        with wave.open(str(path), "rb") as handle:
            frames = handle.getnframes()
            rate = handle.getframerate() or TARGET_SAMPLE_RATE
            channels = handle.getnchannels()
            return frames / float(rate), rate, channels
    except wave.Error as exc:
        raise AudioCaptureError(f"{path} is not a readable wav file: {exc}") from exc


def write_pcm_wav(path: Path, pcm: bytes, sample_rate: int = TARGET_SAMPLE_RATE) -> None:
    """Write raw 16-bit mono PCM as a wav file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(TARGET_CHANNELS)
        handle.setsampwidth(TARGET_SAMPLE_WIDTH)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm)


class DummyCaptureSource(AudioCaptureSource):
    """Replays a fixture wav as though it had just been recorded.

    This is the default source. It means `POST /trigger` exercises the entire
    pipeline - transcribe, clean, understand, store - on a machine with no
    microphone, and it makes the pipeline tests deterministic.
    """

    name = "dummy"

    def __init__(self, fixture_path: Path | None = None):
        self.fixture_path = Path(fixture_path or get_settings().dummy_audio_path)

    def is_available(self) -> tuple[bool, str]:
        if not self.fixture_path.exists():
            return False, (
                f"fixture audio not found at {self.fixture_path}. "
                "Run `python scripts/make_fixture_audio.py` or set DUMMY_AUDIO_PATH."
            )
        return True, f"replaying {self.fixture_path.name}"

    def capture(self, max_seconds: int | None = None) -> CapturedAudio:
        usable, reason = self.is_available()
        if not usable:
            raise AudioCaptureError(reason)

        capture_id = _new_capture_id()
        destination = _output_path(capture_id)
        destination.write_bytes(self.fixture_path.read_bytes())

        duration, rate, channels = describe_wav(destination)
        logger.info("dummy capture %s (%.2fs) from %s", capture_id, duration, self.fixture_path)
        return CapturedAudio(
            capture_id=capture_id,
            path=destination,
            duration_seconds=duration,
            sample_rate=rate,
            channels=channels,
            source=self.name,
            captured_at=datetime.now(timezone.utc),
        )


class MicrophoneCaptureSource(AudioCaptureSource):
    """Records from the host's default input device.

    `sounddevice` is imported lazily and is an optional dependency: a machine
    that only ever uses the dummy source does not need PortAudio installed.
    """

    name = "microphone"

    def __init__(self, seconds: int | None = None):
        self.seconds = seconds

    def is_available(self) -> tuple[bool, str]:
        try:
            import sounddevice  # noqa: F401
        except Exception as exc:  # ImportError, or OSError when PortAudio is missing
            return False, f"microphone capture needs `sounddevice`: {exc}"
        return True, "ready"

    def capture(self, max_seconds: int | None = None) -> CapturedAudio:
        usable, reason = self.is_available()
        if not usable:
            raise AudioCaptureError(reason)

        import sounddevice as sd

        settings = get_settings()
        seconds = max_seconds or self.seconds or settings.default_capture_seconds
        # Never record longer than the hard cap, however the caller asked.
        seconds = max(1, min(int(seconds), settings.max_capture_seconds))
        frames = int(seconds * TARGET_SAMPLE_RATE)

        logger.info("recording %ss from the default input device", seconds)
        recording = sd.rec(
            frames,
            samplerate=TARGET_SAMPLE_RATE,
            channels=TARGET_CHANNELS,
            dtype="int16",
        )
        sd.wait()

        capture_id = _new_capture_id()
        destination = _output_path(capture_id)
        write_pcm_wav(destination, recording.tobytes())

        duration, rate, channels = describe_wav(destination)
        return CapturedAudio(
            capture_id=capture_id,
            path=destination,
            duration_seconds=duration,
            sample_rate=rate,
            channels=channels,
            source=self.name,
            captured_at=datetime.now(timezone.utc),
        )


class UploadCaptureSource(AudioCaptureSource):
    """Wraps audio the caller already holds, e.g. a browser upload."""

    name = "upload"

    def __init__(self, data: bytes, suffix: str = ".wav"):
        self.data = data
        self.suffix = suffix

    def capture(self, max_seconds: int | None = None) -> CapturedAudio:
        if not self.data:
            raise AudioCaptureError("no audio data was supplied")

        capture_id = _new_capture_id()
        settings = get_settings()
        settings.audio_raw_dir.mkdir(parents=True, exist_ok=True)
        destination = settings.audio_raw_dir / f"{capture_id}{self.suffix}"
        destination.write_bytes(self.data)

        # Only wav can be described from its header without decoding; anything
        # else is left at zero and the ASR stage reports the real duration.
        if self.suffix == ".wav":
            duration, rate, channels = describe_wav(destination)
        else:
            duration, rate, channels = 0.0, TARGET_SAMPLE_RATE, TARGET_CHANNELS

        return CapturedAudio(
            capture_id=capture_id,
            path=destination,
            duration_seconds=duration,
            sample_rate=rate,
            channels=channels,
            source=self.name,
            captured_at=datetime.now(timezone.utc),
        )


#: Registry. A hardware source is added here and selected with CAPTURE_SOURCE.
SOURCES: dict[str, type[AudioCaptureSource]] = {
    DummyCaptureSource.name: DummyCaptureSource,
    MicrophoneCaptureSource.name: MicrophoneCaptureSource,
}


def register_source(source_class: type[AudioCaptureSource]) -> None:
    """Add a capture source at runtime.

    This is the extension point for hardware: a GPIO or serial source can be
    registered from its own module without editing this file.
    """
    SOURCES[source_class.name] = source_class


def get_capture_source(name: str | None = None) -> AudioCaptureSource:
    """Build the configured capture source."""
    resolved = name or get_settings().capture_source
    try:
        return SOURCES[resolved]()
    except KeyError:
        raise AudioCaptureError(
            f"unknown capture source {resolved!r}; known: {', '.join(sorted(SOURCES))}"
        ) from None


class PreRecordedSource(AudioCaptureSource):
    """Hands the pipeline audio that has already been recorded.

    Lets a start/stop recording (`app.capture.live`) or an upload go through the
    identical `run_capture` path as a triggered one, instead of duplicating the
    transcribe → understand → store stages for each way audio can arrive.
    """

    name = "pre-recorded"

    def __init__(self, captured: CapturedAudio):
        self.captured = captured

    def capture(self, max_seconds: int | None = None) -> CapturedAudio:
        return self.captured
