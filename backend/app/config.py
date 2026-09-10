"""Application settings.

Every LNT tunable named in the paper is exposed here so an experiment can be reproduced by
changing configuration rather than code. Defaults match the values reported in
Saini et al. (2023) where the paper states one.
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
    database_url: str = "sqlite:///./data/echonotes.db"
    chroma_dir: Path = BASE_DIR / "data" / "chroma"
    audio_raw_dir: Path = BASE_DIR / "data" / "audio_raw"
    audio_processed_dir: Path = BASE_DIR / "data" / "audio_processed"
    transcript_dir: Path = BASE_DIR / "data" / "transcripts"
    image_dir: Path = BASE_DIR / "data" / "images"

    # ---- LNT Section 3.3: audio normalization + silence chunking ----
    audio_target_dbfs: float = -20.0
    silence_thresh_dbfs: int = -40
    min_silence_len_ms: int = 500
    chunk_keep_silence_ms: int = 250

    # ---- LNT Section 3.2: ASR + translation to English ----
    asr_backend: str = "google"
    asr_default_language: str = "en-US"
    translate_to: str = "en"

    # ---- LNT Section 3.4: NLP ----
    word2vec_algorithm: str = "cbow"  # cbow | skipgram, paper Section 3.4.3
    word2vec_vector_size: int = 100
    word2vec_window: int = 5
    word2vec_min_count: int = 1
    summary_top_k: int = 10  # first K ranked sentences, paper Section 3.4.5
    lda_num_topics: int = 9  # paper's sample lecture produced 9 themes
    lda_max_iter: int = 20

    # ---- LLM ----
    llm_provider: str = "anthropic"
    llm_model: str = "claude-sonnet-5"
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # ---- Retrieval ----
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    # ---- Clustering weights, Idea11y Section 4.1 adapted ----
    cluster_eps: float = 0.45
    cluster_min_samples: int = 2
    cluster_weight_note_type: float = 0.3
    cluster_weight_subject: float = 0.6

    # ---- OCR ----
    ocr_engine: str = "tesseract"
    tesseract_cmd: str = ""

    # ---- Accessibility ----
    capture_trigger: str = "spacebar"
    tts_engine: str = "web_speech"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
