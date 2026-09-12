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

    #: What the speaker actually spoke, before any translation (Section 3.2).
    source_language: str | None = None
    #: True when the text was translated into English rather than transcribed.
    translated: bool = False
    #: How many silence-split chunks the recording produced (Section 3.3).
    chunk_count: int | None = None

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


# ---------------------------------------------------------------------------
# The LNT pipeline (paper Section 3.3)
#
#   normalise -> split on silence -> recognise each chunk -> append "." -> join
#
# The alternative is handing the whole file to Whisper at once, which is what
# `asr_pipeline = "direct"` does. Running the paper's route buys three things
# the single-shot call does not give:
#
#   * a known loudness before any threshold is applied, so one silence setting
#     works across recording levels;
#   * sentence boundaries taken from where the speaker actually paused, rather
#     than from the model's guess at punctuation - everything downstream that
#     counts sentences depends on these;
#   * a per-chunk confidence, so one mumbled passage is visible instead of
#     being averaged away across a whole lecture.
#
# It costs more wall time, because the model is invoked per chunk.
# ---------------------------------------------------------------------------

_TERMINAL_PUNCTUATION = ".!?"


def _ensure_terminal_period(text: str) -> str:
    """Append the paper's "." to a recognised chunk unless it already has one.

    Section 3.3 appends a period to every chunk, because the pause that ended
    the chunk is the sentence boundary. Whisper often punctuates already, so
    adding one unconditionally would produce ".." - the intent is one terminal
    mark, not literally one more character.
    """
    text = text.strip()
    if not text:
        return ""
    return text if text[-1] in _TERMINAL_PUNCTUATION else text + "."


def detect_language(model, audio_path: Path) -> tuple[str | None, float | None]:
    """Identify the spoken language before transcribing (Section 3.2).

    LNT is a multilanguage framework: it detects the language first so the
    recogniser can be told what to expect, and so the translation step knows
    whether it is needed at all.
    """
    try:
        _, info = model.transcribe(str(audio_path), language=None, beam_size=1)
        return getattr(info, "language", None), getattr(info, "language_probability", None)
    except Exception as exc:  # noqa: BLE001 - detection is advisory
        logger.warning("language detection failed: %s", exc)
        return None, None


#: Phrases Whisper emits when it has nothing to transcribe. It was trained on
#: subtitled video, so silence gets filled with the sign-offs that end one.
#: Matched only when the whole segment is one of them - a real note may well
#: contain the words "thank you".
_HALLUCINATED_ON_SILENCE = frozenset(
    phrase.lower()
    for phrase in (
        "Thank you.", "Thank you for watching.", "Thanks for watching.",
        "Thank you for watching!", "Thanks for watching!",
        "Please subscribe.", "Like and subscribe.",
        "You", "Bye.", "Bye-bye.", "Okay.",
        "Subtitles by the Amara.org community",
        "Transcription by ESO. Translation by -",
    )
)


def _is_speech(segment) -> bool:
    """Whether a segment is really speech, or Whisper filling a silence.

    Two signals, and the first is the honest one: Whisper reports a
    `no_speech_prob` per segment and then emits text regardless of it. Measured
    on a near-silent capture, it produced "Thank you for watching." at
    no_speech_prob 0.61 and the app stored that as the user's note.

    Dropping a real quiet sentence is a cost worth paying against that. A missed
    note is visible - the user sees nothing was saved and repeats it. An
    invented one is not: it sits in the notes looking exactly like something
    they said.
    """
    from app.config import get_settings

    text = (getattr(segment, "text", "") or "").strip()
    if not text:
        return False

    probability = getattr(segment, "no_speech_prob", None)
    if probability is not None and probability >= get_settings().whisper_no_speech_threshold:
        logger.info(
            "dropping segment %r (no_speech_prob %.2f)", text[:60], probability
        )
        return False

    if text.lower().strip(" .!?") in {
        p.strip(" .!?") for p in _HALLUCINATED_ON_SILENCE
    }:
        logger.info("dropping known silence artefact %r", text[:60])
        return False

    return True


class LNTTranscriber(Transcriber):
    """Whisper driven through the LNT framework's audio pipeline.

    The recogniser is still Whisper - the paper used the SpeechRecognition
    library against Google's API, which needs a network round trip per chunk
    and cannot run offline. The *pipeline* around it is the paper's.
    """

    name = "lnt_faster_whisper"

    def __init__(self, base: FasterWhisperTranscriber | None = None):
        self.base = base or FasterWhisperTranscriber()

    def _load_model(self):
        return self.base._load_model()

    @staticmethod
    def _prompt_for_chunk(previous_pieces: list[str]) -> str | None:
        """The vocabulary hint and recent context to prime one chunk with.

        Two separate jobs, both done through Whisper's `initial_prompt`:

        * **Vocabulary.** Whisper strongly prefers words it has been primed
          with. Without it, domain terms lose to common soundalikes - "deque"
          becomes "DQ", "linked list" becomes "lengthless".
        * **Context.** Chunking hands Whisper fragments with nothing around
          them, so a chunk containing only "like" is transcribed as the
          sentence "Like." Feeding the tail of what came before restores the
          continuity the split removed.

        Only the last couple of pieces are carried: the prompt is capped by the
        model, and a long one starts steering the transcript rather than just
        its vocabulary.
        """
        settings = get_settings()
        parts: list[str] = []

        if settings.whisper_initial_prompt:
            parts.append(settings.whisper_initial_prompt.strip())

        if settings.whisper_carry_context and previous_pieces:
            parts.append(" ".join(previous_pieces[-2:]).strip())

        prompt = " ".join(p for p in parts if p).strip()
        # Whisper counts the prompt against its context; keep it bounded.
        return prompt[-800:] if prompt else None

    def _transcribe_whole(
        self, model, audio_path: Path, normalized: Path, detected: str | None, task: str
    ) -> TranscriptionResult:
        """One pass over the whole recording, no chunking.

        Used when `WHISPER_CHUNK_AUDIO=false`. More accurate than the chunked
        path because nothing interrupts Whisper's context window, but it does
        not follow the paper's Section 3.3.
        """
        settings = get_settings()

        def run(vad: bool):
            segments, info = model.transcribe(
                str(normalized),
                language=detected if task == "transcribe" else None,
                task=task,
                beam_size=settings.whisper_beam_size,
                vad_filter=vad,
                initial_prompt=self._prompt_for_chunk([]),
            )
            segments = [s for s in segments if _is_speech(s)]
            return segments, info, " ".join(
                s.text.strip() for s in segments if s.text.strip()
            )

        segments, info, text = run(settings.whisper_vad_filter)

        if not text.strip() and settings.whisper_vad_filter:
            # Voice-activity detection decided the whole recording was silence.
            # It is tuned for long audio with real gaps, and on a short or quiet
            # note it discards the speech itself - measured: a six-second
            # capture of "So, hi." transcribed as nothing with VAD on and
            # correctly with it off.
            #
            # Retried only when VAD found nothing at all, so a normal recording
            # keeps the benefit and a quiet one is not silently lost. The cost
            # of being wrong the other way is a note the user spoke and the app
            # threw away without saying so.
            logger.info("VAD found no speech; retrying without it")
            segments, info, text = run(False)

        collected = [
            TranscriptSegment(
                start=s.start,
                end=s.end,
                text=s.text.strip(),
                avg_logprob=getattr(s, "avg_logprob", None),
                no_speech_prob=getattr(s, "no_speech_prob", None),
            )
            for s in segments
            if s.text.strip()
        ]
        logger.info("LNT pipeline: whole-file pass -> %d words", len(text.split()))

        return TranscriptionResult(
            text=_ensure_terminal_period(text),
            language="en" if task == "translate" else detected,
            language_probability=getattr(info, "language_probability", None),
            duration_seconds=getattr(info, "duration", None),
            model=f"{self.name}:{self.base.model_size}",
            segments=collected,
            source_language=detected,
        )

    def transcribe(self, audio_path: Path, language: str | None = None) -> TranscriptionResult:
        from app.audio.chunking import split_on_silence_to_files
        from app.audio.normalization import normalize

        settings = get_settings()
        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise TranscriptionError(f"audio file not found: {audio_path}")

        model = self._load_model()

        # --- 1. normalise (Section 3.3) ------------------------------------
        # Only when chunking will actually run. Normalisation exists to serve
        # chunking: it puts every recording at a known loudness so the silence
        # threshold in `app.audio.chunking` means the same thing for a quiet
        # phone recording and a loud lecture hall. With chunking off there is
        # no threshold to calibrate, and it is not free - it gains the audio,
        # attenuates anything above the median, then gains it again, which is
        # a compressor. Measured on a real capture, the same model and settings
        # gave "the system still works" on the raw audio and "the system
        # steelworks" on the normalised one, reproducibly: flattening the
        # dynamics removes what Whisper uses to separate near-homophones.
        if settings.whisper_chunk_audio:
            try:
                normalized = normalize(audio_path)
            except Exception as exc:  # noqa: BLE001
                # Losing normalisation degrades chunking; losing the capture
                # does not have to follow.
                logger.warning("normalisation failed (%s); using the raw audio", exc)
                normalized = audio_path
        else:
            normalized = audio_path

        # --- 2. detect the language (Section 3.2) --------------------------
        # A configured language wins over detection, matching WhisperTranscriber
        # above. Detection on a short clip is unreliable - a few seconds of
        # accented English can come back as Hindi at 0.37 confidence - and a
        # wrong guess is not a small error: it flips `task` to "translate"
        # below, so the note is silently rewritten instead of transcribed.
        language = language or settings.whisper_language

        detected, probability = (language, None)
        if language is None:
            detected, probability = detect_language(model, normalized)
            if probability is not None and probability < settings.language_detection_floor:
                # Too uncertain to act on. Transcribing in the detected language
                # risks nonsense; assuming English at least keeps the user's own
                # words when they were speaking it, which is the common case.
                logger.warning(
                    "language detected as %r but only %.2f confident; "
                    "transcribing as-is rather than translating",
                    detected,
                    probability,
                )
                detected = None

        # The paper standardises everything to English before analysis. Whisper
        # does that itself, so no external translation service is involved.
        task = "transcribe"
        if (
            settings.translate_to_english
            and detected
            and not detected.startswith("en")
        ):
            task = "translate"
            logger.info("source language %r; translating to English", detected)

        # --- 3. split on silence (Section 3.3) -----------------------------
        if not settings.whisper_chunk_audio:
            # Whisper reads a 30-second context window and uses the words around
            # a sound to decide what it was. Splitting at every pause takes that
            # away, so one pass over the whole recording is more accurate - at
            # the cost of departing from the paper's Section 3.3.
            logger.info("chunking disabled; recognising the whole recording in one pass")
            return self._transcribe_whole(model, audio_path, normalized, detected, task)

        try:
            chunk_paths = split_on_silence_to_files(normalized)
        except Exception as exc:  # noqa: BLE001
            logger.warning("chunking failed (%s); recognising the whole file", exc)
            chunk_paths = [normalized]

        # --- 4. recognise each chunk, append "." ---------------------------
        segments: list[TranscriptSegment] = []
        pieces: list[str] = []
        elapsed = 0.0

        for index, chunk_path in enumerate(chunk_paths):
            try:
                chunk_segments, _info = model.transcribe(
                    str(chunk_path),
                    language=detected if task == "transcribe" else None,
                    task=task,
                    beam_size=settings.whisper_beam_size,
                    vad_filter=False,  # chunking already removed the silence
                    initial_prompt=self._prompt_for_chunk(pieces),
                )
                chunk_segments = list(chunk_segments)
            except Exception as exc:  # noqa: BLE001
                # One unrecognisable chunk must not cost the whole lecture.
                logger.warning("chunk %d failed: %s", index, exc)
                continue

            text = " ".join(s.text.strip() for s in chunk_segments if s.text.strip())
            text = _ensure_terminal_period(text)

            duration = _chunk_duration_seconds(chunk_path)
            if text:
                pieces.append(text)
                logprobs = [
                    s.avg_logprob for s in chunk_segments if getattr(s, "avg_logprob", None)
                ]
                no_speech = [
                    s.no_speech_prob
                    for s in chunk_segments
                    if getattr(s, "no_speech_prob", None) is not None
                ]
                segments.append(
                    TranscriptSegment(
                        start=elapsed,
                        end=elapsed + duration,
                        text=text,
                        avg_logprob=sum(logprobs) / len(logprobs) if logprobs else None,
                        no_speech_prob=sum(no_speech) / len(no_speech) if no_speech else None,
                    )
                )
            elapsed += duration

        full_text = " ".join(pieces).strip()
        logger.info(
            "LNT pipeline: %d chunk(s) -> %d recognised, %d words",
            len(chunk_paths), len(segments), len(full_text.split()),
        )

        return TranscriptionResult(
            text=full_text,
            language="en" if task == "translate" else detected,
            language_probability=probability,
            duration_seconds=elapsed or None,
            model=f"{self.name}:{self.base.model_size}",
            segments=segments,
            source_language=detected,
            translated=task == "translate",
            chunk_count=len(chunk_paths),
        )


def _chunk_duration_seconds(path: Path) -> float:
    import wave

    try:
        with wave.open(str(path), "rb") as handle:
            return handle.getnframes() / float(handle.getframerate() or 1)
    except Exception:  # noqa: BLE001
        return 0.0


_default_transcriber: Transcriber | None = None


def get_transcriber() -> Transcriber:
    """Process-wide transcriber, so the model is loaded at most once.

    `ASR_PIPELINE` selects between the paper's route and the single-shot call.
    """
    global _default_transcriber
    if _default_transcriber is None:
        if get_settings().asr_pipeline == "direct":
            _default_transcriber = FasterWhisperTranscriber()
        else:
            _default_transcriber = LNTTranscriber()
    return _default_transcriber


def set_transcriber(transcriber: Transcriber | None) -> None:
    """Override the shared transcriber. Tests inject a fake through this."""
    global _default_transcriber
    _default_transcriber = transcriber
