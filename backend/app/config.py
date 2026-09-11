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
    # How long a live recording runs when the caller does not say. This is the
    # actual recording length, not a ceiling - `max_capture_seconds` below is
    # the ceiling. They were the same setting once, which meant every
    # microphone capture blocked for five minutes.
    default_capture_seconds: int = 15
    max_capture_seconds: int = 300
    # Frames PortAudio hands the capture callback at a time. Larger blocks give
    # the callback more headroom before input is dropped; 0 lets PortAudio
    # choose, which on Windows can be small enough to drop audio under load.
    capture_blocksize: int = 4096

    # ---- LNT audio pipeline (paper Section 3.3) ----
    # Loudness every recording is normalised to before chunking.
    audio_target_dbfs: float = -20.0
    audio_processed_dir: Path = BASE_DIR / "data" / "audio_processed"
    # Silence threshold. The offset is taken relative to the recording's own
    # loudness, which is what makes one setting work across recording levels;
    # `silence_thresh_dbfs` is the absolute fallback.
    silence_thresh_offset_db: float = -16.0
    silence_thresh_dbfs: int = -40
    min_silence_len_ms: int = 400
    chunk_keep_silence_ms: int = 200
    # Chunks outside this range are split or dropped.
    min_chunk_ms: int = 250
    max_chunk_ms: int = 30_000

    # ---- Speech to text (Phase 1) ----
    asr_backend: str = "faster_whisper"
    whisper_model: str = "base"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    whisper_language: str | None = None  # None -> auto-detect
    whisper_beam_size: int = 5
    whisper_vad_filter: bool = True
    # Below this confidence a detected language is treated as unknown rather
    # than acted on. Detection on a few seconds of accented speech is noisy,
    # and a wrong guess flips transcription into translation, which rewrites
    # the note instead of recording it.
    language_detection_floor: float = 0.60

    # Vocabulary hint passed to Whisper. Whisper strongly prefers words it has
    # been primed with, which is the fix for domain terms it otherwise mangles
    # ("deque" -> "DQ", "linked list" -> "lengthless"). Keep it short: a long
    # prompt starts to bias the transcript rather than just its vocabulary.
    whisper_initial_prompt: str = ""

    # Carry the tail of the previous chunk forward as context. The paper's
    # Section 3.3 chunking splits on silence and recognises each chunk alone,
    # which suited an API that had no cross-clip context anyway. Whisper does
    # have context and depends on it, so a chunk containing only "like" is
    # transcribed as the sentence "Like." Passing recent text forward restores
    # what the split removed.
    whisper_carry_context: bool = True

    # Whether to chunk at all before recognising. True follows the paper.
    # False sends the whole recording to Whisper in one pass, which is more
    # accurate because nothing interrupts its context window - at the cost of
    # departing from Section 3.3.
    whisper_chunk_audio: bool = True
    # Which transcription pipeline to run:
    #   lnt    - the paper's Section 3.3 route: normalise -> split on silence ->
    #            recognise each chunk -> append "." -> join
    #   direct - hand the whole file to Whisper in one go
    asr_pipeline: str = "lnt"
    # The paper standardises every language to English before analysis
    # (Section 3.2). Whisper does this itself with its translate task, so no
    # external translation service is involved.
    translate_to_english: bool = True

    # ---- LNT NLP tasks (paper Section 3.4) ----
    # 3.4.3 Word2Vec: "cbow" or "skipgram" (the paper implements both)
    word2vec_algorithm: str = "cbow"
    word2vec_vector_size: int = 100
    word2vec_window: int = 5
    word2vec_min_count: int = 1
    word2vec_epochs: int = 30
    # 3.4.5 Summarization: the paper prints "the first K sentences of ranking".
    summary_top_k: int = 5
    # Fraction of sentences to keep when K is not given explicitly.
    summary_ratio: float = 0.35
    # 3.4.6 Thematic analysis: hapaxes, collocations, bigrams
    thematic_top_n: int = 20
    collocation_window: int = 2
    # 3.4.7 Topic modelling with LDA
    lda_num_topics: int = 9
    lda_max_iter: int = 20
    lda_top_terms: int = 10

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
