"""Speech to text through Groq's hosted Whisper large-v3.

The local recogniser (`LNTTranscriber`, Whisper "small" on the CPU) cannot
decode a quiet or quickly spoken stretch however it is configured. Measured on
a 40-second note, scored against what was actually said (53 words):

    local small, every setting tried            19-22 wrong
    Groq large-v3                               17 wrong, ~1s instead of ~11s
    Groq large-v3 on loudness-evened audio      14 wrong

and on three cleaner recordings large-v3 got 2 of 31 wrong, where the local
model had stored "our system", "given by" and "steelworks".

It is not exact, and nothing measured was. On that note even large-v3 heard
"evaluate skills, understand opinions, or make a decision" as "evaluate skills,
and discuss opinions". What remains depends on the recording itself, and on the
LLM correction step for words that are merely misheard - it cannot, and must
not, put back words that never reached the transcript.

## Trade-offs, and what happens when they bite

The audio leaves the machine, so this is opt-in: `ASR_BACKEND=groq`. It needs a
network connection and a key, it is rate-limited on the free tier, and uploads
are capped at 25 MB. When any of that fails, the recording is transcribed
locally instead (`ASR_FALLBACK_TO_LOCAL`). A slower, less accurate note beats a
lost one, and the stored `asr_model` says which recogniser produced it.

The upload is FLAC when ffmpeg is available: lossless, so the model hears exactly
the same audio, at about half the size, which doubles how long a recording fits
under the cap.

The same no-speech filter as the local path applies. Large-v3 still fills
silence with invented sentences, and an invented note is worse than a missing
one.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from app.asr.transcriber import (
    Transcriber,
    TranscriptionResult,
    TranscriptSegment,
    _ensure_terminal_period,
    _is_speech,
)
from app.config import get_settings
from app.core.errors import TranscriptionError

logger = logging.getLogger(__name__)

#: Groq's upload cap for audio transcription.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

_TEMP_PREFIX = "echonotes-asr-"


def _nothing() -> None:
    return None


def _field(obj, name: str, default=None):
    """Read a response field wherever the SDK put it.

    Groq's SDK types declare only `text`; `segments`, `duration` and `language`
    arrive as extra fields in `model_extra`, and an SDK upgrade may promote any
    of them to real attributes. Plain dicts are accepted too.
    """
    if isinstance(obj, dict):
        return obj.get(name, default)
    value = getattr(obj, name, None)
    if value is not None:
        return value
    extra = getattr(obj, "model_extra", None) or {}
    return extra.get(name, default)


class GroqTranscriber(Transcriber):
    """Whisper large-v3 on Groq, with the local model as the fallback."""

    name = "groq"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        client=None,
        fallback: Transcriber | None = None,
    ):
        settings = get_settings()
        self.api_key = settings.groq_api_key if api_key is None else api_key
        self.model_name = model or settings.groq_asr_model
        self._client = client
        self._fallback = fallback

    # --- public -----------------------------------------------------------

    def transcribe(self, audio_path: Path, language: str | None = None) -> TranscriptionResult:
        audio_path = Path(audio_path)
        if not audio_path.exists():
            # Not a Groq problem, and the local model cannot fix it either.
            raise TranscriptionError(f"audio file not found: {audio_path}")

        try:
            return self._transcribe_remote(audio_path, language)
        except Exception as exc:  # noqa: BLE001 - every failure has the same answer
            if not get_settings().asr_fallback_to_local:
                if isinstance(exc, TranscriptionError):
                    raise
                raise TranscriptionError(f"Groq transcription failed: {exc}") from exc
            logger.warning(
                "Groq transcription failed (%s); transcribing locally instead", exc
            )
            return self._local().transcribe(audio_path, language=language)

    # --- internals --------------------------------------------------------

    def _local(self) -> Transcriber:
        if self._fallback is None:
            from app.asr.transcriber import FasterWhisperTranscriber, LNTTranscriber

            self._fallback = (
                FasterWhisperTranscriber()
                if get_settings().asr_pipeline == "direct"
                else LNTTranscriber()
            )
        return self._fallback

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not self.api_key:
            raise TranscriptionError("GROQ_API_KEY is not set")
        try:
            import groq
        except ImportError as exc:
            raise TranscriptionError("the `groq` package is not installed") from exc
        self._client = groq.Groq(
            api_key=self.api_key, timeout=get_settings().groq_asr_timeout_seconds
        )
        return self._client

    def _transcribe_remote(self, audio_path: Path, language: str | None) -> TranscriptionResult:
        settings = get_settings()
        client = self._get_client()

        upload, cleanup = self._prepare_upload(audio_path)
        try:
            payload = upload.read_bytes()
        finally:
            cleanup()

        if len(payload) > MAX_UPLOAD_BYTES:
            raise TranscriptionError(
                f"recording is {len(payload) / 1_048_576:.1f} MB, over Groq's "
                f"{MAX_UPLOAD_BYTES // 1_048_576} MB upload limit"
            )

        language = language or settings.whisper_language
        request = {
            "file": (upload.name, payload),
            "model": self.model_name,
            # Segments carry avg_logprob and no_speech_prob: the silence filter
            # needs the second, and the correction step's unclear-passage hint
            # needs the first.
            "response_format": "verbose_json",
            # Deterministic: the same recording should give the same note.
            "temperature": 0.0,
        }
        if language:
            request["language"] = language
        if settings.groq_asr_use_prompt and settings.whisper_initial_prompt:
            request["prompt"] = settings.whisper_initial_prompt

        response = client.audio.transcriptions.create(**request)
        return self._to_result(response, language)

    def _to_result(self, response, language: str | None) -> TranscriptionResult:
        segments = [
            TranscriptSegment(
                start=float(_field(s, "start", 0.0) or 0.0),
                end=float(_field(s, "end", 0.0) or 0.0),
                text=str(_field(s, "text", "") or "").strip(),
                avg_logprob=_field(s, "avg_logprob"),
                no_speech_prob=_field(s, "no_speech_prob"),
            )
            for s in (_field(response, "segments") or [])
        ]

        if not segments:
            # No per-segment data, so there is no no_speech_prob to read. Keep
            # the text as one segment rather than drop a whole note over a
            # missing field; the known-hallucination check still applies.
            text = str(_field(response, "text", "") or "").strip()
            duration = float(_field(response, "duration", 0.0) or 0.0)
            segments = [TranscriptSegment(start=0.0, end=duration, text=text)] if text else []

        kept = [s for s in segments if _is_speech(s)]
        text = " ".join(s.text for s in kept if s.text).strip()
        detected = language or _field(response, "language")

        logger.info("Groq %s: %d segment(s), %d words", self.model_name, len(kept), len(text.split()))

        return TranscriptionResult(
            text=_ensure_terminal_period(text) if text else "",
            language=detected,
            duration_seconds=_field(response, "duration"),
            model=f"{self.name}:{self.model_name}",
            segments=kept,
            source_language=detected,
        )

    def _prepare_upload(self, audio_path: Path) -> tuple[Path, Callable[[], None]]:
        """Loudness-even the recording and encode it as FLAC, when ffmpeg exists.

        Returns the file to upload and a function that removes it. Any failure
        here uploads the recording as it was captured: preparation improves a
        transcript, and must never be the reason there is none.
        """
        settings = get_settings()
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            if settings.groq_asr_loudnorm:
                logger.info(
                    "ffmpeg not found; uploading the recording without loudness normalisation"
                )
            return audio_path, _nothing

        handle, name = tempfile.mkstemp(suffix=".flac", prefix=_TEMP_PREFIX)
        os.close(handle)
        target = Path(name)

        command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(audio_path)]
        if settings.groq_asr_loudnorm:
            command += ["-af", settings.groq_asr_loudnorm_filter]
        command += ["-ar", "16000", "-ac", "1", str(target)]

        try:
            subprocess.run(command, check=True, capture_output=True, timeout=120)
        except (subprocess.SubprocessError, OSError) as exc:
            target.unlink(missing_ok=True)
            logger.warning(
                "could not prepare the recording with ffmpeg (%s); uploading it as recorded", exc
            )
            return audio_path, _nothing

        return target, lambda: target.unlink(missing_ok=True)
