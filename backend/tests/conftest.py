"""Shared test fixtures.

Two rules make this suite fast and hermetic:

  * No Whisper. `FakeTranscriber` returns fixed text, so tests never download a
    model or decode audio. The real transcriber is covered separately by
    `test_transcriber.py`, which is skipped unless faster-whisper is installed.
  * No shared state. Each test session gets its own SQLite file and its own
    silent fixture wav, both in tmp, and tables are cleared between tests.
"""

from __future__ import annotations

import os
import tempfile
import wave
from pathlib import Path

import pytest

# Environment must be set before anything imports app.config, which caches
# settings on first use.
_TMP = Path(tempfile.mkdtemp(prefix="echonotes-tests-"))
_FIXTURE_WAV = _TMP / "silent.wav"

os.environ["DATABASE_URL"] = f"sqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["AUDIO_RAW_DIR"] = str(_TMP / "audio_raw")
os.environ["TRANSCRIPT_DIR"] = str(_TMP / "transcripts")
os.environ["CAPTURE_SOURCE"] = "dummy"
os.environ["DUMMY_AUDIO_PATH"] = str(_FIXTURE_WAV)
os.environ["LLM_PROVIDER"] = "null"
os.environ["ANTHROPIC_API_KEY"] = ""
# Speech to text stays local and offline. A developer's .env may set
# ASR_BACKEND=groq with a real key, and without these any test reaching the
# default transcriber would upload audio to Groq.
os.environ["ASR_BACKEND"] = "faster_whisper"
os.environ["GROQ_API_KEY"] = ""

# Phase 4 (Team Member 3). The in-memory vector store keeps the suite fast and
# hermetic: no Chroma client to build (~1s), nothing written to disk, no state
# leaking between tests. The real ChromaDB backend is exercised directly by
# tests/test_rag_retrieval.py, which constructs it against a tmp path.
os.environ["VECTOR_STORE"] = "memory"
os.environ["EMBEDDING_BACKEND"] = "hashed"
os.environ["CHROMA_DIR"] = str(_TMP / "chroma")
os.environ["TTS_ENGINE"] = "directive"
os.environ["TTS_OUTPUT_DIR"] = str(_TMP / "tts")


def _write_silent_wav(path: Path, seconds: float = 1.0, rate: int = 16_000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * int(seconds * rate))


_write_silent_wav(_FIXTURE_WAV)


SAMPLE_TRANSCRIPT = (
    "Reminder to myself. I need to submit the operating systems assignment "
    "to Professor Raman by next Friday. Also, call Sarah about the database "
    "project meeting on March 3rd. The key topic is deadlock detection and recovery."
)


@pytest.fixture(scope="session")
def tmp_root() -> Path:
    return _TMP


@pytest.fixture(scope="session")
def fixture_wav() -> Path:
    return _FIXTURE_WAV


class FakeTranscriber:
    """Stand-in for Whisper. Returns whatever it was constructed with."""

    name = "fake"

    def __init__(self, text: str = SAMPLE_TRANSCRIPT, avg_logprob: float = -0.27):
        self.text = text
        self.avg_logprob = avg_logprob
        self.calls: list[Path] = []

    def transcribe(self, audio_path, language=None):
        from app.asr.transcriber import TranscriptionResult, TranscriptSegment

        self.calls.append(Path(audio_path))
        segments = [
            TranscriptSegment(
                start=0.0,
                end=5.0,
                text=self.text,
                avg_logprob=self.avg_logprob,
                no_speech_prob=0.01,
            )
        ]
        return TranscriptionResult(
            text=self.text,
            language="en",
            language_probability=0.99,
            duration_seconds=5.0,
            model="fake:test",
            segments=segments if self.text else [],
        )


@pytest.fixture
def fake_transcriber():
    """Install a fake transcriber for the duration of one test."""
    from app.asr.transcriber import set_transcriber

    transcriber = FakeTranscriber()
    set_transcriber(transcriber)
    yield transcriber
    set_transcriber(None)


@pytest.fixture(autouse=True)
def clean_database():
    """Start every test with empty tables and an empty vector index.

    The vector store is a process-level cached singleton, so unlike the
    database it is not reset by clearing tables - a note indexed by one test
    would still be retrievable in the next one.
    """
    from app.db.models import Base
    from app.db.session import engine, init_db
    from app.rag.vector_store import get_vector_store

    init_db()
    get_vector_store().clear()
    yield
    with engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            connection.exec_driver_sql(f"DELETE FROM {table.name}")
    get_vector_store().clear()


@pytest.fixture
def make_note(db_session):
    """Create a stored, understood, organized, indexed note from text.

    Runs the same `run_understanding_on_text` path the /understand endpoint
    uses, so a test note goes through every stage a real one does - including
    Team Member 2's topic assignment and Team Member 3's indexing.
    """
    from app.pipeline.capture_pipeline import run_understanding_on_text

    def _make(text: str):
        note, _result = run_understanding_on_text(db_session, text, persist=True)
        db_session.commit()
        return note

    return _make


@pytest.fixture
def db_session():
    from app.db.session import SessionLocal

    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def client(fake_transcriber):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def sample_text() -> str:
    return SAMPLE_TRANSCRIPT
