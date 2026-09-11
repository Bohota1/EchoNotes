"""Start/stop microphone recording.

`MicrophoneCaptureSource` records for a fixed number of seconds and blocks until
they elapse, which is right for a hardware button wired to a timer and wrong for
a person: you cannot know in advance how long a thought takes, and a fixed
window either cuts you off or leaves you waiting in silence.

This records until told to stop. The audio arrives on a PortAudio callback
thread and is accumulated there, so `start()` and `stop()` return immediately
and the HTTP request that called them is never blocked for the length of the
recording.

**The callback takes no lock, deliberately.** It runs on PortAudio's real-time
audio thread against a hard deadline; if it blocks, PortAudio discards that
input buffer and the recording comes back with stretches of digital silence
where the speech should be - a 20-second capture yielding one sentence, with no
error anywhere. `list.append` is atomic under the GIL, which is all the
synchronisation handing blocks to `stop()` actually needs. `stop()` closes the
stream before it touches `_blocks`, so no callback can still be running by then.

One recorder per process, reached through `get_live_recorder()`. There is one
microphone, so a second concurrent recording is a conflict, not a queue.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

from app.capture.sources import (
    TARGET_CHANNELS,
    TARGET_SAMPLE_RATE,
    CapturedAudio,
    _new_capture_id,
    _output_path,
    describe_wav,
    write_pcm_wav,
)
from app.config import get_settings
from app.core.errors import AudioCaptureError

logger = logging.getLogger(__name__)


class LiveRecorder:
    """A microphone recording that runs until stopped."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stream = None
        self._blocks: list = []
        self._capture_id: str | None = None
        self._started_at: float | None = None
        self._started_wall: datetime | None = None
        self._hit_limit = False

    # --- state ----------------------------------------------------------

    @property
    def is_recording(self) -> bool:
        return self._stream is not None

    @property
    def capture_id(self) -> str | None:
        return self._capture_id

    @property
    def elapsed_seconds(self) -> float:
        if self._started_at is None:
            return 0.0
        return time.monotonic() - self._started_at

    @property
    def hit_limit(self) -> bool:
        """True when the recording stopped itself at the configured cap."""
        return self._hit_limit

    def state(self) -> dict:
        settings = get_settings()
        return {
            "recording": self.is_recording,
            "capture_id": self._capture_id,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "max_seconds": settings.max_capture_seconds,
            "hit_limit": self._hit_limit,
        }

    # --- control --------------------------------------------------------

    def start(self) -> str:
        """Begin recording. Returns the capture id."""
        if self.is_recording:
            raise AudioCaptureError("a recording is already in progress")

        try:
            import sounddevice as sd
        except Exception as exc:  # ImportError, or OSError with no PortAudio
            raise AudioCaptureError(
                f"microphone recording needs `sounddevice`: {exc}"
            ) from exc

        settings = get_settings()
        max_frames = settings.max_capture_seconds * TARGET_SAMPLE_RATE

        # Reset before the stream opens, so the callback never races this.
        self._blocks = []
        self._hit_limit = False
        frames_held = 0

        def callback(indata, _frames, _time_info, status):
            nonlocal frames_held
            # This runs on PortAudio's real-time audio thread, which has a hard
            # deadline. It must not block, and it must not acquire a lock that
            # any other thread holds - a callback that overruns its deadline
            # makes PortAudio discard the input buffer, and the recording comes
            # back with stretches of digital silence where the speech was.
            # `list.append` is atomic under the GIL, so no lock is needed to
            # hand blocks to `stop()`.
            if status:
                # Logged at warning, not debug: `input overflow` here is the
                # direct cause of dropped audio, and it is the only warning the
                # user will ever get that their recording has holes in it.
                logger.warning("input stream status: %s", status)
            if frames_held >= max_frames:
                # Stop accumulating rather than growing without bound. The
                # stream stays open so `stop()` remains the only thing that
                # ends a recording, from the caller's point of view.
                self._hit_limit = True
                return
            self._blocks.append(indata.copy())
            frames_held += len(indata)

        try:
            self._stream = sd.InputStream(
                samplerate=TARGET_SAMPLE_RATE,
                channels=TARGET_CHANNELS,
                dtype="int16",
                callback=callback,
                # A larger block and relaxed latency give the callback far more
                # headroom before PortAudio starts dropping buffers. Capture
                # here is a background task feeding a transcriber, not live
                # monitoring, so added latency costs nothing.
                blocksize=settings.capture_blocksize,
                latency="high",
            )
            self._stream.start()
        except Exception as exc:
            self._stream = None
            raise AudioCaptureError(f"could not open the microphone: {exc}") from exc

        self._capture_id = _new_capture_id()
        self._started_at = time.monotonic()
        self._started_wall = datetime.now(timezone.utc)
        logger.info("live recording %s started", self._capture_id)
        return self._capture_id

    def stop(self) -> CapturedAudio:
        """Stop recording and write the audio to disk."""
        if not self.is_recording:
            raise AudioCaptureError("no recording is in progress")

        stream, self._stream = self._stream, None
        try:
            stream.stop()
            stream.close()
        except Exception as exc:  # noqa: BLE001 - audio is already captured
            logger.warning("closing the input stream failed: %s", exc)

        with self._lock:
            blocks, self._blocks = self._blocks, []

        capture_id = self._capture_id or _new_capture_id()
        self._capture_id = None
        self._started_at = None
        started_wall = self._started_wall or datetime.now(timezone.utc)
        self._started_wall = None

        if not blocks:
            raise AudioCaptureError(
                "no audio was captured. Check that Windows is using the "
                "microphone you expect."
            )

        import numpy as np

        pcm = np.concatenate(blocks, axis=0).tobytes()
        destination = _output_path(capture_id)
        write_pcm_wav(destination, pcm)

        duration, rate, channels = describe_wav(destination)
        logger.info("live recording %s stopped: %.2fs", capture_id, duration)

        return CapturedAudio(
            capture_id=capture_id,
            path=destination,
            duration_seconds=duration,
            sample_rate=rate,
            channels=channels,
            source="microphone",
            captured_at=started_wall,
        )

    def cancel(self) -> None:
        """Stop recording and throw the audio away."""
        if not self.is_recording:
            return
        stream, self._stream = self._stream, None
        try:
            stream.stop()
            stream.close()
        except Exception:  # noqa: BLE001
            pass
        with self._lock:
            self._blocks = []
        logger.info("live recording %s cancelled", self._capture_id)
        self._capture_id = None
        self._started_at = None
        self._started_wall = None


_recorder: LiveRecorder | None = None


def get_live_recorder() -> LiveRecorder:
    global _recorder
    if _recorder is None:
        _recorder = LiveRecorder()
    return _recorder
