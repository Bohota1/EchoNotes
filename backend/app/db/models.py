"""SQLAlchemy models. Full column list and rationale in `docs/data-model.md`.

Hierarchy tables (`subjects`, `topics`, `notes`) follow Idea11y's Frame/Cluster/Note structure.
`analyses` holds one row per capture with every LNT Section 3.4-3.5 artefact, so a note's summary,
themes, LDA topics and quality score can be re-read without re-running the pipeline.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# TODO: Subject, Topic, Note, Analysis, Entity, Reminder, Settings
#   Subject   id, name, is_unfiled, created_at
#   Topic     id, subject_id, name, kind, summary, summary_stale, created_at
#   Note      id, topic_id, note_type, source, text, raw_transcript, source_language,
#             summary, audio_path, image_path, created_at, updated_at
#   Analysis  id, note_id, word_count, word_frequencies, themes, topics_lda,
#             readability, cohesion, coherence, entropy, quality_score
#   Entity    id, note_id, kind, value, normalized, span_start, span_end
#   Reminder  id, note_id, entity_id, title, due_at, status
#   Settings  single row: voice_coding, feedback_mode, announce_summaries,
#             announce_quality, capture_trigger
