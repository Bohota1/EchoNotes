"""Phase 5 - Summarization by Subject, Project, Topic and time range.

Reuses Topic summaries as the leaf of every roll-up, per the spec:

    Subject -> Topics -> Topic summaries -> Subject-level summary

so a Subject-level summary stays cheap even for a subject with hundreds of
notes: it summarizes a handful of topic summaries, never every note directly.
A time-range summary is the one exception - a range cuts across topics, so it
falls back to the notes' own text directly (see `summarize_range`).

All three summarizers go through `app.hierarchy.cluster_summary.generate_summary`,
so they share the same LLM-with-extractive-fallback behaviour as Topic
summaries.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from app.config import get_settings
from app.hierarchy.cluster_summary import generate_summary

logger = logging.getLogger(__name__)


@dataclass
class RollupSummary:
    scope: str  # "subject" | "topic" | "range"
    scope_id: str | None
    scope_name: str | None
    note_count: int
    summary: str
    spoken: str
    method: str  # "llm" | "extractive" | "cached" | "empty"


def _llm_available() -> bool:
    from app.llm import get_llm_client

    return get_llm_client().available


def _plural(n: int, word: str) -> str:
    return word if n == 1 else f"{word}s"


def summarize_topic(db, topic_id: str, *, force_refresh: bool = False) -> RollupSummary:
    """The topic's own generated summary (Idea11y Section 4.1), refreshed
    first if it is stale or missing, or if `force_refresh` is set."""
    from app.db.repositories import TopicRepository

    topic_repo = TopicRepository(db)
    topic = topic_repo.get(topic_id)
    if topic is None:
        raise ValueError(f"no topic {topic_id}")

    note_count = topic_repo.count_notes(topic_id)

    if force_refresh or topic.summary_stale or not topic.summary:
        from app.hierarchy.cluster_summary import refresh_summary

        summary = refresh_summary(db, topic_id)
        method = "llm" if _llm_available() else "extractive"
    else:
        summary = topic.summary
        method = "cached"

    spoken = f"{topic.name}. {note_count} {_plural(note_count, 'note')}. {summary}"
    return RollupSummary(
        scope="topic",
        scope_id=topic.id,
        scope_name=topic.name,
        note_count=note_count,
        summary=summary,
        spoken=spoken,
        method=method,
    )


def summarize_subject(db, subject_id: str) -> RollupSummary:
    """Subject -> Topics -> topic summaries -> subject-level roll-up."""
    from app.db.repositories import SubjectRepository, TopicRepository

    subject_repo = SubjectRepository(db)
    topic_repo = TopicRepository(db)
    subject = subject_repo.get(subject_id)
    if subject is None:
        raise ValueError(f"no subject {subject_id}")

    topics = topic_repo.list_for_subject(subject_id)
    note_count = sum(topic_repo.count_notes(t.id) for t in topics)

    topic_summaries: list[str] = []
    for topic in topics:
        if topic.summary_stale or not topic.summary:
            from app.hierarchy.cluster_summary import refresh_summary

            refresh_summary(db, topic.id)
            db.refresh(topic)
        if topic.summary:
            topic_summaries.append(f"{topic.name}: {topic.summary}")

    if not topic_summaries:
        summary = "No notes yet."
        method = "empty"
    else:
        summary = generate_summary(
            topic_summaries, max_words=get_settings().rollup_summary_max_words
        )
        method = "llm" if _llm_available() else "extractive"

    topic_count = len(topics)
    spoken = (
        f"{subject.name}. {topic_count} {_plural(topic_count, 'topic')}, "
        f"{note_count} {_plural(note_count, 'note')}. {summary}"
    )
    return RollupSummary(
        scope="subject",
        scope_id=subject.id,
        scope_name=subject.name,
        note_count=note_count,
        summary=summary,
        spoken=spoken,
        method=method,
    )


def summarize_range(
    db,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    subject_id: str | None = None,
    topic_id: str | None = None,
) -> RollupSummary:
    """Roll-up summary of every note captured in `[start, end)`, optionally
    scoped to one Subject or Topic.

    Falls back to the notes' own cleaned text directly rather than to their
    topic summaries: a time range cuts across topics, and a note's topic
    summary may well describe notes outside the requested window.
    """
    from app.db.repositories import NoteRepository, SubjectRepository, TopicRepository

    notes = NoteRepository(db).list_between(
        start=start, end=end, subject_id=subject_id, topic_id=topic_id
    )

    scope_name: str | None = None
    scope_id = topic_id or subject_id
    if topic_id:
        topic = TopicRepository(db).get(topic_id)
        scope_name = topic.name if topic else None
    elif subject_id:
        subject = SubjectRepository(db).get(subject_id)
        scope_name = subject.name if subject else None

    if not notes:
        summary = "No notes in that time range."
        method = "empty"
    else:
        texts = [n.cleaned_text for n in notes if n.cleaned_text]
        summary = generate_summary(texts, max_words=get_settings().range_summary_max_words)
        method = "llm" if _llm_available() else "extractive"

    range_desc = _describe_range(start, end)
    scope_prefix = f"{scope_name}, " if scope_name else ""
    note_count = len(notes)
    spoken = f"{scope_prefix}{range_desc}. {note_count} {_plural(note_count, 'note')}. {summary}"

    return RollupSummary(
        scope="range",
        scope_id=scope_id,
        scope_name=scope_name,
        note_count=note_count,
        summary=summary,
        spoken=spoken,
        method=method,
    )


def _describe_range(start: datetime | None, end: datetime | None) -> str:
    if start and end:
        return f"from {start.date()} to {end.date()}"
    if start:
        return f"since {start.date()}"
    if end:
        return f"up to {end.date()}"
    return "across all time"
