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
    # Fixed-length fallback used only by `MicrophoneCaptureSource.capture()`
    # (a single record-for-N-seconds capture, e.g. a hardware trigger button)
    # when no caller-supplied length is given. The Start/Stop flow the frontend
    # actually uses (`app/capture/live.py`) ignores this entirely.
    default_capture_seconds: int = 10
    # `sounddevice.InputStream(blocksize=...)`: frames per audio callback. Was
    # never defined even though `live.py` already read it, so every live
    # (Start/Stop) recording failed with "'Settings' object has no attribute
    # 'capture_blocksize'" before the stream could even open. 8000 frames is
    # 0.5s at the 16 kHz capture rate - large enough to give the callback the
    # headroom described in `live.py`'s docstring without adding noticeable
    # start/stop latency.
    capture_blocksize: int = 8000

    # ---- LNT audio pipeline (Phase 1, paper Section 3.3) ----
    # Normalisation target and the silence-based chunking `app/audio/chunking.py`
    # and `app/audio/normalization.py` need. This block was missing entirely
    # (both modules already read `get_settings().<name>` for every value here,
    # so without it every real call - and every `tests/test_lnt_audio.py`
    # chunking test - raised AttributeError; fixed alongside the NexaNota
    # redesign since it surfaced while verifying that work, not because it is
    # part of it).
    #
    # Where a normalised recording and its silence-based chunks are written.
    audio_processed_dir: Path = BASE_DIR / "data" / "audio_processed"
    # Loudness `normalize_segment`/`normalize` bring a recording to (dBFS).
    audio_target_dbfs: float = -20.0
    # A pause must be at least this long to count as a chunk boundary.
    min_silence_len_ms: int = 400
    # How much of the surrounding silence to keep on each side of a chunk, so
    # a word right at the edge of a pause is not clipped.
    chunk_keep_silence_ms: int = 150
    # The default silence cut-off is relative: `segment.dBFS + this offset`,
    # so the same recording chunks the same way whether it is a quiet phone
    # capture or a loud lecture hall (see `split_segment_on_silence`,
    # `relative_threshold`). -16 dB below the recording's own average is the
    # standard pydub silence-detection heuristic.
    silence_thresh_offset_db: float = -16.0
    # Absolute fallback threshold, used only when a relative one cannot be
    # computed (a fully-silent segment, whose dBFS is -inf).
    silence_thresh_dbfs: int = -40
    # A speaker who never pauses produces one very long chunk; anything past
    # this is cut at its quietest point instead of left as one slow-to-transcribe
    # blob (`_enforce_max_length`).
    max_chunk_ms: int = 60_000
    # Fragments shorter than this (a breath, a click) are dropped rather than
    # sent to the recogniser as their own "sentence".
    min_chunk_ms: int = 200

    # ---- LNT NLP tasks (Phase 1, paper Section 3.4) ----
    # Same story as the audio-pipeline block above: `app/nlp/embeddings_w2v.py`,
    # `app/nlp/thematic.py` and `app/nlp/topic_modeling.py` already read every
    # value below through `get_settings()`; this section was simply never
    # added, so real calls (and most of `tests/test_lnt_nlp.py`) raised
    # AttributeError. Added alongside the NexaNota redesign since it surfaced
    # while verifying that work, not because it is part of it.
    #
    # Word2Vec (3.4.3). "cbow" or "skipgram" - both are always available by
    # name; this only picks the one used when a caller does not choose.
    word2vec_algorithm: str = "cbow"
    word2vec_vector_size: int = 100
    word2vec_window: int = 5
    # A single lecture is a very small corpus (see embeddings_w2v.py's module
    # docstring) - gensim's own default of 5 would drop nearly every word in
    # a short capture, so every word that appears at all counts.
    word2vec_min_count: int = 1
    word2vec_epochs: int = 30
    # Collocations/bigrams (3.4.6, 4.1): how many pairs to return, and the
    # window `BigramCollocationFinder` looks across for a pairing.
    thematic_top_n: int = 10
    collocation_window: int = 2
    # LDA (3.4.7). Section 5.1's sample lecture: 1947 words -> 9 themes, ~55
    # topics - 9 is where the topic-count default comes from.
    lda_num_topics: int = 9
    lda_max_iter: int = 50
    lda_top_terms: int = 10

    # ---- Speech to text (Phase 1) ----
    asr_backend: str = "faster_whisper"
    whisper_model: str = "base"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    whisper_language: str | None = None  # None -> auto-detect
    whisper_beam_size: int = 5
    whisper_vad_filter: bool = True

    # `app/asr/transcriber.py::get_transcriber()` already read every setting
    # below to choose and run a transcriber, but none of them were ever
    # defined here - so the very first real transcription (dummy or
    # microphone; the test suite injects a fake transcriber and never hits
    # this) raised AttributeError on `get_settings().asr_pipeline` before a
    # single word was recognised, surfacing to the user as a bare Internal
    # Server Error. Left out of the earlier settings pass because this file
    # is the "don't touch speech-to-text" zone - these are declarations the
    # code already depends on, not a logic change.
    #
    # "direct" hands Whisper the whole recording in one call. Anything else
    # (the default) runs the paper's own route in `LNTTranscriber`: normalise
    # -> split on silence -> recognise each chunk -> join - see the module
    # comment above `LNTTranscriber` for why that costs more time but is worth
    # it (known loudness, real sentence boundaries, per-chunk confidence).
    asr_pipeline: str = "lnt"
    # Only used by the "lnt" pipeline, and only when `whisper_language` is not
    # set, so detection actually runs. Below this confidence, a detected
    # language is discarded and the audio is transcribed as-is rather than
    # risking a wrong-language guess silently flipping `task` to "translate".
    language_detection_floor: float = 0.5
    # Whisper already standardises non-English speech to English when asked;
    # off by default so a note keeps the language it was actually spoken in
    # unless this is deliberately turned on.
    translate_to_english: bool = False
    # The paper's Section 3.3 silence-based chunking (see `LNTTranscriber`).
    # False falls back to one whole-file pass, which reads better as prose but
    # loses the per-chunk confidence and real sentence boundaries.
    whisper_chunk_audio: bool = True
    # Domain vocabulary Whisper is primed with on every chunk (e.g. course
    # jargon it would otherwise mishear as a common soundalike - "deque" as
    # "DQ"). Empty by default: this is a per-deployment hint, not something
    # with a sensible universal value.
    whisper_initial_prompt: str | None = None
    # Carries the tail of the previous chunk's text into the next chunk's
    # prompt, so a fragment like "like" is not transcribed as the standalone
    # sentence "Like." - see `LNTTranscriber._prompt_for_chunk`.
    whisper_carry_context: bool = True

    # ---- LLM abstraction (Phase 2) ----
    # The pipeline works with no key at all: rules run first and the LLM is
    # consulted only when a rule result is below its confidence floor.
    # `groq` is the free option - no credit card, a free key from
    # console.groq.com (see GROQ_API_KEY below).
    llm_provider: str = "anthropic"  # anthropic | groq | null
    llm_model: str = "claude-opus-5"
    llm_max_tokens: int = 1024
    llm_timeout_seconds: float = 30.0
    anthropic_api_key: str = ""
    groq_api_key: str = ""

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
        if self.llm_provider == "groq":
            return bool(self.groq_api_key)
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
