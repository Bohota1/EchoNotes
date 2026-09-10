"""Text-to-speech (Phase 4).

Two backends behind one interface, selected by `TTS_ENGINE`:

  ``directive`` (default) - returns a structured `SpeechDirective` that the
              browser speaks with the Web Speech API. No dependency, no
              synthesis latency, and - the reason it is the default - it speaks
              in the voice and at the speech rate the user has already
              configured for themselves. Experienced screen reader users run
              their synthesiser at rates that sound absurd to everyone else;
              overriding that with a server-side voice makes an accessible app
              worse, not better.

  ``pyttsx3`` - additionally synthesises a wav on the server and returns a file
              reference alongside the directive. For headless demos, CLI use and
              anything that needs an audio artefact to point at. Optional
              dependency; if it is missing the engine degrades to a directive
              rather than failing the request.

Both return the same `SpeechDirective`, so a caller never branches on which
backend is configured - `audio_url` is simply `None` when nothing was
synthesised.
"""

from __future__ import annotations

import abc
import hashlib
import logging
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

from app.config import get_settings
from app.tts.voice_profiles import VoiceProfile, voice_for

logger = logging.getLogger(__name__)


@dataclass
class SpeechDirective:
    """Everything the client needs to speak one response."""

    text: str
    voice: str = "default"
    rate: int = 180
    pitch: float = 1.0
    #: True for errors and state changes that should cut off whatever is being
    #: read; False for answers, which wait their turn.
    interrupt: bool = False
    #: Non-speech cue played alongside, if any (see `app.tts.earcons`).
    earcon: str | None = None
    #: Set only when a backend actually synthesised audio.
    audio_url: str | None = None
    audio_path: str | None = None
    engine: str = "directive"

    def to_dict(self) -> dict:
        return asdict(self)


class TTSEngine(abc.ABC):
    name: str = "base"

    @abc.abstractmethod
    def speak(
        self,
        text: str,
        *,
        note_type: str | None = None,
        interrupt: bool = False,
        earcon: str | None = None,
    ) -> SpeechDirective: ...

    def _directive(
        self,
        text: str,
        note_type: str | None,
        interrupt: bool,
        earcon: str | None,
    ) -> SpeechDirective:
        settings = get_settings()
        profile: VoiceProfile = voice_for(note_type, settings.tts_voice_coding)
        return SpeechDirective(
            text=text,
            voice=profile.voice,
            rate=profile.rate or settings.tts_rate,
            pitch=profile.pitch,
            interrupt=interrupt,
            earcon=earcon,
            engine=self.name,
        )


class DirectiveTTSEngine(TTSEngine):
    """Speech instructions only. The browser does the speaking."""

    name = "directive"

    def speak(self, text, *, note_type=None, interrupt=False, earcon=None):
        return self._directive(text, note_type, interrupt, earcon)


class Pyttsx3TTSEngine(TTSEngine):
    """Server-side synthesis to a wav file.

    A fresh engine is created per call rather than kept as a long-lived
    instance: pyttsx3 drives platform speech APIs (SAPI5 on Windows) that are
    not reliably reusable across threads, and a FastAPI worker is threaded.
    """

    name = "pyttsx3"

    def speak(self, text, *, note_type=None, interrupt=False, earcon=None):
        directive = self._directive(text, note_type, interrupt, earcon)
        path = self._synthesize(text, directive.rate)
        if path is not None:
            directive.audio_path = str(path)
            directive.audio_url = f"/api/v1/tts/audio/{path.name}"
        return directive

    def _synthesize(self, text: str, rate: int) -> Path | None:
        if not text.strip():
            return None

        settings = get_settings()
        output_dir = settings.tts_output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        # Content-addressed: the same sentence at the same rate is synthesised
        # once. Voice responses repeat a lot ("Note saved", "I don't have any
        # notes about that"), and re-synthesising them is pure latency.
        digest = hashlib.blake2b(
            f"{rate}:{text}".encode("utf-8"), digest_size=8
        ).hexdigest()
        path = output_dir / f"{digest}.wav"
        if path.exists():
            return path

        try:
            import pyttsx3

            engine = pyttsx3.init()
            engine.setProperty("rate", rate)
            engine.save_to_file(text, str(path))
            engine.runAndWait()
            engine.stop()
        except Exception:
            logger.exception("pyttsx3 synthesis failed; returning a directive only")
            return None

        return path if path.exists() else None


def _build_engine() -> TTSEngine:
    settings = get_settings()
    engine_name = (settings.tts_engine or "directive").strip().lower()

    if engine_name == "pyttsx3":
        try:
            import pyttsx3  # noqa: F401
        except ImportError:
            logger.warning(
                "TTS_ENGINE=pyttsx3 but pyttsx3 is not installed; "
                "returning speech directives instead. `pip install pyttsx3` to enable."
            )
            return DirectiveTTSEngine()
        return Pyttsx3TTSEngine()

    if engine_name != "directive":
        logger.warning("unknown TTS_ENGINE %r, using directives", engine_name)
    return DirectiveTTSEngine()


@lru_cache
def get_tts_engine() -> TTSEngine:
    return _build_engine()


def reset_tts_engine_cache() -> None:
    """Drop the cached engine. Tests use this after changing settings."""
    get_tts_engine.cache_clear()


def speak(
    text: str,
    *,
    note_type: str | None = None,
    interrupt: bool = False,
    earcon: str | None = None,
) -> SpeechDirective:
    """Convenience wrapper over the configured engine."""
    return get_tts_engine().speak(
        text, note_type=note_type, interrupt=interrupt, earcon=earcon
    )
