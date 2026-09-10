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
