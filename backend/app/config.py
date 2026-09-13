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
    # How long a live recording keeps listening after it is told to stop, before
    # the stream closes. Audio arrives in whole blocks of `capture_blocksize`
    # frames - half a second at the default - and closing the stream discards
    # the block still being filled, which is the end of whatever was said as
    # Enter was pressed. Measured: of the last 25 recordings, the two that ended
    # mid-sound were both questions, and one lost enough of "interview" to come
    # back as "English". Must be longer than one block.
    capture_stop_tail_seconds: float = 0.7

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
    # Which recogniser runs. "faster_whisper" is local (the model below);
    # "groq" sends the recording to Groq's hosted Whisper large-v3 using
    # GROQ_API_KEY - see app/asr/groq_transcriber.py.
    #
    # Measured on a 40-second note with a quiet stretch, scored against what
    # was actually said (53 words): local "small" got 19-22 wrong under every
    # setting tried; Groq large-v3 got 17 wrong, and 14 on loudness-evened
    # audio, in about 1 second instead of 11. On three cleaner recordings it
    # got 2 of 31 wrong where "small" had stored "our system", "given by" and
    # "steelworks". The trade: the audio leaves the machine, and it needs a
    # network connection (see asr_fallback_to_local).
    #
    # Local stays the default so nobody's audio goes to a cloud service
    # without choosing it: set ASR_BACKEND=groq to opt in.
    asr_backend: str = "faster_whisper"  # faster_whisper | groq
    groq_asr_model: str = "whisper-large-v3"
    # Evens out loudness before upload (ffmpeg's EBU R128 loudnorm). Measured
    # with Groq: 17 -> 14 words wrong on a recording with a quiet stretch, and
    # identical output on three recordings without one. A heavier dynamic
    # normaliser (dynaudnorm) made the same recording worse (20). This is a
    # gentler filter than the compressor in app.audio.normalization that hurt
    # the local model, and it only runs on the Groq path. Skipped when ffmpeg
    # is not installed.
    groq_asr_loudnorm: bool = True
    groq_asr_loudnorm_filter: str = "loudnorm=I=-20:TP=-2:LRA=7"
    # The vocabulary prompt (WHISPER_INITIAL_PROMPT) steers large-v3 more than
    # it helps it - measured 18 wrong with it, 17 without. Off on this path.
    groq_asr_use_prompt: bool = False
    groq_asr_timeout_seconds: float = 60.0
    # When Groq cannot be used - no key, no network, a rate limit, a recording
    # over the 25 MB upload cap - transcribe locally instead. A slower, less
    # accurate note beats a lost one.
    asr_fallback_to_local: bool = True
    # Context handed to the recogniser for a spoken question, and only for one.
    # A note is 15 seconds of speech and carries its own context; a question is
    # 1.5 to 3 seconds of voice with nothing around it, so near-soundalikes win:
    # "notes" heard as "questions", "interview" as "legislate". Measured on
    # six real questions, two runs each, words wrong: no prompt 16; this prompt
    # 8. Rejected: a prompt ending "...related to a topic?" (6 wrong, but copied
    # "a topic" into a question), and one listing the user's topic names (8
    # wrong, and inserted "interview purpose", a topic that was not said). This
    # one leaves nothing specific enough to copy. Its only measured side effect
    # was "Read the whole note" as "...notes", which reads as the same request.
    question_asr_prompt: str = (
        "Questions about my own notes. Do I have notes on... "
        "What did I write about... Read my notes on..."
    )
    # "base" mishears technical vocabulary badly - measured: "linked list" ->
    # "lengthless", "computer science" -> "computer size", "means planning how"
    # -> "needs flattening powers of". "small" fixes those and is the default
    # for it. Cost: a ~460MB download on the first real transcription, cached
    # afterwards, and captures take noticeably longer than on "base". Drop back
    # to "base" on a slow machine; "medium" is better again and slower still.
    whisper_model: str = "small"
    whisper_device: str = "cpu"
    # int8 quantises the model to run faster, losing some precision. It is the
    # right trade here: "small" at int8 still beats "base" at float32. Use
    # "float32" for the most accurate transcription on CPU, several times slower.
    whisper_compute_type: str = "int8"
    # Fixed to English rather than auto-detected. Detection on a few seconds of
    # accented speech is unreliable - measured: English read as Hindi at 0.37
    # confidence, which flipped the pipeline into `translate` and stored a
    # sentence the speaker never said. Set to None to restore auto-detection
    # (the multilanguage behaviour the LNT paper describes), or to any other
    # code to pin a different language.
    whisper_language: str | None = "en"
    whisper_beam_size: int = 5
    whisper_vad_filter: bool = True
    # Drop segments Whisper itself thinks contain no speech. It reports a
    # `no_speech_prob` per segment and will still emit text above it - trained
    # on YouTube captions, it fills silence with sign-offs like "Thank you for
    # watching." Measured: a near-silent capture produced exactly that at
    # no_speech_prob 0.61, and the app stored it as the user's words. A
    # hallucinated note is worse than a missing one: the user never said it and
    # has no way to know it is there.
    whisper_no_speech_threshold: float = 0.6

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
    #
    # Off by default, which is a deliberate departure from the paper. Section
    # 3.3 chunks at every pause and recognises each piece alone; that suited the
    # 2021 Google API, which had no cross-clip context to lose. Whisper reads a
    # 30-second window and depends on it, so splitting actively hurts: measured,
    # a pause mid-sentence produced the standalone sentences "Like." and
    # "Thanks.", and one clause came back duplicated. True restores the paper's
    # route, and with it per-chunk confidence and real sentence boundaries.
    whisper_chunk_audio: bool = False
    # Domain vocabulary Whisper is primed with. It strongly prefers words it has
    # seen in the prompt, so listing the terms actually spoken stops them losing
    # to common soundalikes - measured: "deques" came back as "DQ" without it.
    #
    # This default is the computer-science vocabulary this project is used for.
    # It is a per-deployment hint with no universally correct value: change it
    # to match whatever subject is being recorded, via WHISPER_INITIAL_PROMPT.
    # Keep it short - a long prompt starts steering the transcript rather than
    # just its vocabulary.
    whisper_initial_prompt: str | None = (
        "A lecture on computer science. Terms used: system design, scalability, "
        "architecture, database, cache, load balancer, API, server, latency, "
        "throughput, linked list, array, stack, queue, deque, binary tree, graph, "
        "hash table, algorithm, data structure, recursion, complexity, deadlock, "
        "mutex, semaphore, normalization, index, transaction."
    )
    # Carries the tail of the previous chunk's text into the next chunk's
    # prompt, so a fragment like "like" is not transcribed as the standalone
    # sentence "Like." - see `LNTTranscriber._prompt_for_chunk`.
    whisper_carry_context: bool = True

    # ---- Transcript correction (post-ASR LLM review) ----
    # Whisper decides between candidates on sound plus a shallow language
    # prior; it does not reason about meaning, so a near-homophone that is a
    # real word wins when the audio is ambiguous ("still works" -> "steelworks").
    # An LLM does reason about meaning and repairs exactly that. Off costs
    # nothing: with no key configured the transcript passes through untouched.
    llm_correct_transcript: bool = True
    transcript_correction_max_tokens: int = 1200
    # Guards against the model rewriting rather than repairing. A transcription
    # fix swaps a few words; anything that changes the length by more than this,
    # or leaves less than this much of the wording intact, is prose improvement
    # and is rejected - see `app/nlp/correction.py`.
    transcript_correction_max_length_drift: float = 0.25
    # A floor on that percentage, in words. A proportion is meaningless at small
    # counts: repairing "Various system design" to "What is system design" adds
    # one word, which is 33% of a three-word question and would be rejected,
    # while the same edit in a hundred-word note is 1%. The allowance is
    # whichever of the two is larger.
    transcript_correction_max_word_drift: int = 2
    transcript_correction_min_similarity: float = 0.60
    # Below this, there is too little surrounding meaning to disambiguate
    # anything, and an over-eager rewrite does proportionally more damage.
    transcript_correction_min_words: int = 8
    # Questions get a much lower bar, because the two carry opposite risks. A
    # note IS the content: rewriting it destroys what the user said, and a short
    # note is where that does proportionally most damage. A question is never
    # stored as content, is almost always short, and a mishearing sends the
    # search after the wrong thing - measured: "What is system design" heard as
    # "Various system design".
    transcript_correction_min_words_question: int = 2
    # Segments below this avg_logprob are named to the LLM as the passages where
    # a misheard word most likely is, so it checks those words against the
    # sentence instead of reading the whole note with equal suspicion.
    # Measured on Groq large-v3: the segment holding the errors scored -0.78,
    # clean segments -0.34 to -0.36. This only points the model somewhere; the
    # plausibility guards on what it may change are unchanged.
    transcript_correction_unclear_logprob: float = -0.5
    transcript_correction_max_unclear: int = 6

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
    # Extra output tokens allowed on top of whatever a caller asks for, to cover
    # a reasoning model's internal thinking. gpt-oss and similar models spend
    # output tokens reasoning before they emit any visible text, so a caller
    # asking for 40 tokens of summary gets an empty string: the budget is gone
    # before the answer starts. Callers size their budget for the text they
    # want, which is right; this covers what the model spends getting there.
    # Set to 0 for a non-reasoning model.
    groq_reasoning_headroom: int = 512

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
    # chroma   - local ChromaDB under chroma_dir
    # pgvector - same Postgres database as the notes (needs DATABASE_URL
    #            to be Postgres and the pgvector extension available)
    # memory   - brute-force numpy, no persistence; what the tests use
    vector_store: str = "chroma"  # chroma | pgvector | memory
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
    # Whether a spoken answer ends with where it came from ("From Deadlock,
    # under Operating Systems."). Off: the clause is vague exactly where it
    # matters ("and 1 other place" names nothing) and repeats after every
    # answer. The sources are still on the response in full for any client that
    # wants to show or speak them - this only controls the spoken sentence.
    speak_answer_provenance: bool = False

    # ---- Reading notes back verbatim ----
    # Re-recording the same explanation is normal: the user says it again
    # because the first attempt was misheard, or because they are revising. It
    # leaves several notes whose wording is nearly the same, and reading all of
    # them aloud sounds exactly like reading one note twice - which is what it
    # was reported as.
    #
    # Measured on a real library, word-sequence similarity separates the two
    # cases cleanly: unrelated notes scored 0.13, a fuller re-recording of the
    # same explanation 0.47-0.50, and near-identical retakes 0.73-0.89. 0.6
    # sits in the gap with room on both sides.
    read_aloud_collapse_repeats: bool = True
    read_aloud_repeat_threshold: float = 0.6

    # ---- Conversation sessions (Shift opens one, Enter asks inside it) ----
    # A follow-up is rewritten into a standalone question before retrieval.
    # Embedding "how does it relate to system design" searches for "it relate",
    # so the notes the user means never surface and the answer is grounded in
    # the wrong ones. The rewrite changes only what is searched for - every
    # answer is still built solely from the notes that search returns.
    conversation_rewrite_followups: bool = True
    conversation_rewrite_max_tokens: int = 120
    # Turns of history given to the rewrite and to the answerer. Older turns
    # rarely disambiguate a pronoun and cost tokens on every question.
    conversation_context_turns: int = 4
    # Turns kept per session at all.
    conversation_max_turns: int = 12
    # Sessions are ended explicitly; this only reclaims ones abandoned when a
    # tab was closed mid-conversation.
    conversation_ttl_seconds: int = 1800

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
    # How long before a reminder's due time the voice console should announce
    # it out loud (see ReminderService.due_soon). Blind users cannot glance at
    # a screen to notice something is coming up, so this fires proactively.
    reminder_alert_lead_minutes: int = 60
    # How long an event mention ("I have a meeting") waits for its missing
    # date or time answer before being abandoned. Long enough for the user to
    # think and answer, short enough that an unrelated later note is never
    # mistaken for the answer to a question the user has forgotten about.
    reminder_clarification_ttl_minutes: int = 30

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
