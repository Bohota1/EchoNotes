"""Application settings.

Anything tunable lives here so behaviour can change through `.env` rather than
through code edits. Settings are grouped by the pipeline stage they affect.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ---- Core ----
    echonotes_env: str = "development"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    cors_origins: str = "http://localhost:5173"

    # ---- Storage ----
    database_url: str = f"sqlite:///{(BASE_DIR / 'data' / 'echonotes.db').as_posix()}"
    audio_raw_dir: Path = BASE_DIR / "data" / "audio_raw"
    transcript_dir: Path = BASE_DIR / "data" / "transcripts"

    # ---- Capture (Phase 1) ----
    # Which AudioCaptureSource the /trigger endpoint uses.
    #   dummy      - replays a fixture file, needs no hardware (default)
    #   microphone - records from the host microphone, needs `sounddevice`
    #   upload     - audio supplied by the caller
    capture_source: str = "dummy"
    dummy_audio_path: Path = BASE_DIR / "data" / "fixtures" / "sample_capture.wav"
    max_capture_seconds: int = 300

    # ---- Speech to text (Phase 1) ----
    asr_backend: str = "faster_whisper"
    whisper_model: str = "base"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    whisper_language: str | None = None  # None -> auto-detect
    whisper_beam_size: int = 5
    whisper_vad_filter: bool = True

    # ---- LLM abstraction (Phase 2) ----
    # The pipeline works with no key at all: rules run first and the LLM is
    # consulted only when a rule result is below its confidence floor.
    llm_provider: str = "anthropic"  # anthropic | null
    llm_model: str = "claude-opus-5"
    llm_max_tokens: int = 1024
    llm_timeout_seconds: float = 30.0
    anthropic_api_key: str = ""

    # ---- Understanding (Phase 2) ----
    # Below these confidences the rule result is treated as unreliable and the
    # LLM fallback is asked instead.
    classification_confidence_floor: float = 0.55
    extraction_confidence_floor: float = 0.50
    key_phrase_limit: int = 10

    # ---- Quality scoring (Phase 2) ----
    # Composite weights. Must sum to 1.0; validated at import by `weights_ok`.
    quality_weight_readability: float = 0.30
    quality_weight_coherence: float = 0.30
    quality_weight_transcription: float = 0.40

    # ---- Hierarchy (Phase 3 - Subject/Topic/Note, Idea11y DG1 adapted) ----
    unfiled_subject_name: str = "Unfiled"
    unfiled_topic_name: str = "Unfiled"
    default_subject_name: str = "General"
    # Cosine-similarity bar an existing Topic/Subject must clear for a new
    # note to be filed there instead of creating a new one.
    topic_similarity_threshold: float = 0.72
    subject_similarity_threshold: float = 0.55
    # Dimensionality of the dependency-free hashed bag-of-words vector used
    # for topic-assignment similarity. See `app/hierarchy/embeddings.py`.
    hierarchy_embedding_dim: int = 256
    # DBSCAN-over-embeddings weights for the optional batch "recluster a
    # subject" action (`app/hierarchy/clustering.py`) - Idea11y's gestalt
    # precedence (bounded region > colour > proximity) re-expressed as
    # (subject > note type > semantic proximity).
    cluster_weight_note_type: float = 0.3
    cluster_weight_subject: float = 0.6
    cluster_eps: float = 0.45
    cluster_min_samples: int = 2
    # AI-generated summary lengths (words), Idea11y Section 4.1 + Phase 5.
    topic_summary_max_words: int = 12
    rollup_summary_max_words: int = 60
    range_summary_max_words: int = 80

    # ---- Retrieval / RAG (Phase 4, Team Member 3) ----
    # Embeddings. "hashed" reuses Team Member 2's dependency-free hashed
    # bag-of-words vectorizer (app/hierarchy/embeddings.py) so the project keeps
    # working with no downloads and no API key. "sentence-transformers" is the
    # opt-in semantic backend - it is NOT a hard requirement; see
    # requirements.txt. Switching backends invalidates the index: run
    # POST /retrieval/reindex afterwards, because vectors from two different
    # models are not comparable.
    embedding_backend: str = "hashed"  # hashed | sentence-transformers
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    # Vector store. "chroma" persists under chroma_dir; "memory" is brute-force
    # numpy with no persistence (what the test suite uses).
    vector_store: str = "chroma"  # chroma | memory
    chroma_dir: Path = BASE_DIR / "data" / "chroma"

    # Chunking. A short voice note is one chunk; a lecture is windowed, because
    # one vector over 2000 words averages away the specifics that make a note
    # findable.
    rag_chunk_chars: int = 900
    rag_chunk_overlap: int = 120

    # Retrieval. `rag_vector_weight` splits the hybrid score between the vector
    # and lexical passes; `rag_min_score` drops weak matches so an unrelated
    # note never becomes a citation.
    rag_top_k: int = 5
    rag_min_score: float = 0.08
    rag_vector_weight: float = 0.65
    rag_chunk_overfetch: int = 3
    rag_lexical_scan_limit: int = 300

    # Answer generation.
    rag_context_max_chars: int = 6000
    rag_answer_max_words: int = 45
    rag_summary_max_words: int = 90
    rag_answer_max_tokens: int = 600

    # ---- Text to speech (Phase 4, Team Member 3) ----
    # "directive" returns structured speech instructions for the browser's Web
    # Speech API - the default, because it uses the blind user's own configured
    # voice and speech rate. "pyttsx3" additionally synthesises a wav server-side
    # and returns a file reference, for headless demos.
    tts_engine: str = "directive"  # directive | pyttsx3
    tts_output_dir: Path = BASE_DIR / "data" / "tts"
    tts_rate: int = 180
    tts_voice_coding: str = "consistent"  # consistent | by_type

    # ---- Reminders & contacts (Phase 5, Team Member 3) ----
    # A deadline entity below this confidence is surfaced as a suggestion rather
    # than auto-created, so a mis-heard date never silently becomes a reminder.
    reminder_auto_create_confidence: float = 0.60
    reminder_lookahead_hours: int = 24
    contact_match_cutoff: float = 0.82

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def llm_configured(self) -> bool:
        """True when a real LLM provider can actually be reached."""
        if self.llm_provider == "anthropic":
            return bool(self.anthropic_api_key)
        return False

    def weights_ok(self) -> bool:
        total = (
            self.quality_weight_readability
            + self.quality_weight_coherence
            + self.quality_weight_transcription
        )
        return abs(total - 1.0) < 1e-6


@lru_cache
def get_settings() -> Settings:
    return Settings()
