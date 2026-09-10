"""Hierarchy orchestration - the one place that combines
`app.db.repositories`, `app.hierarchy.tree`, `app.hierarchy.outline` and
`app.hierarchy.cluster_summary` into the operations the API, the voice
commands and the capture pipeline actually call.

Keeping this separate from `api/v1/hierarchy.py` means the same logic backs
the HTTP endpoints (`api/v1/hierarchy.py`), the voice-command handlers
(`app.hierarchy.commands`) and the pipeline hook
(`app.pipeline.capture_pipeline`), so there is exactly one implementation of
"how a note gets filed" and "what the outline looks like" - never two that
can drift apart, per the Phase 3 spec's "one source of truth" requirement.
"""

from __future__ import annotations

from app.hierarchy.outline import to_outline
from app.hierarchy.tree import Hierarchy, NoteNode, SubjectNode, TopicNode

# `Note.source` on the row is a Phase 1 `CaptureSource` value
# (dummy | microphone | upload | text); the hierarchy/outline schemas use the
# Phase 3 `NoteSource` value (voice | ocr | manual). The two were defined
# independently before either phase existed, so this is the single place that
# reconciles them - `api/v1/serializers.note_out` imports this same function
# rather than keeping its own copy, so there is exactly one mapping.
_SOURCE_TO_NOTE_SOURCE = {
    "dummy": "voice",
    "microphone": "voice",
    "upload": "ocr",
    "text": "manual",
}


def note_source_label(db_source: str) -> str:
    """Map a `CaptureSource` value to the `NoteSource` value the hierarchy
    schemas expect. "upload" is treated as OCR since that is EchoNotes' only
    current non-audio, non-typed capture path (Feature 7); flag this if a
    future upload source is not an OCR image."""
    return _SOURCE_TO_NOTE_SOURCE.get(db_source, "manual")


def build_hierarchy(db) -> Hierarchy:
    """Read the whole hierarchy out of SQLite into the in-memory dataclass tree.

    The database is the only source of truth; this tree is rebuilt on every
    read (cheap at personal-note-taking scale - hundreds to a few thousand
    notes) rather than cached, so the outline can never show something the
    database disagrees with.
    """
    from app.db.repositories import SubjectRepository

    subjects: list[SubjectNode] = []
    for subject in SubjectRepository(db).list():
        topics: list[TopicNode] = []
        for topic in sorted(subject.topics, key=lambda t: t.name.lower()):
            notes = [
                NoteNode(
                    id=n.id,
                    text=n.cleaned_text,
                    note_type=n.understanding.note_type if n.understanding else "academic",
                    source=note_source_label(n.source),
                    created_at=n.created_at,
                    updated_at=n.updated_at,
                    quality_score=n.understanding.quality_score if n.understanding else None,
                )
                for n in sorted(topic.notes, key=lambda n: n.created_at, reverse=True)
            ]
            topics.append(
                TopicNode(
                    id=topic.id,
                    name=topic.name,
                    kind=topic.kind,
                    summary=topic.summary,
                    summary_stale=topic.summary_stale,
                    notes=notes,
                )
            )
        subjects.append(
            SubjectNode(
                id=subject.id, name=subject.name, is_unfiled=subject.is_unfiled, topics=topics
            )
        )
    return Hierarchy(subjects=subjects)


def get_outline(db) -> dict:
    """`GET /hierarchy` and `GET /hierarchy/outline` payload: nested JSON plus narration."""
    return to_outline(build_hierarchy(db))


def get_overview(db) -> dict:
    from app.hierarchy.overview import build_overview

    return build_overview(build_hierarchy(db))


def create_subject(db, name: str):
    from app.db.repositories import SubjectRepository

    return SubjectRepository(db).get_or_create(name)


def create_topic(db, subject_id: str, name: str, kind: str = "topic"):
    from app.db.repositories import TopicRepository

    return TopicRepository(db).get_or_create(subject_id, name, kind=kind)


def move_note(db, note_id: str, target_topic_id: str):
    """Idea11y Section 4.2: re-file a note by target topic id (the outline's
    drop-down of current clusters). Marks both the old and new topic's
    summary stale, since moving a note changes what both clusters are about."""
    from app.db.repositories import NoteRepository, TopicRepository

    note_repo = NoteRepository(db)
    topic_repo = TopicRepository(db)

    note = note_repo.get(note_id)
    if note is None:
        raise LookupError(f"no note {note_id}")
    target = topic_repo.get(target_topic_id)
    if target is None:
        raise LookupError(f"no topic {target_topic_id}")

    old_topic_id = note.topic_id
    note_repo.move_to_topic(note_id, target_topic_id)
    if old_topic_id and old_topic_id != target_topic_id:
        topic_repo.mark_stale(old_topic_id)
    topic_repo.mark_stale(target_topic_id)

    # Phase 4 (Team Member 3): the vector index stores each note's subject and
    # topic so retrieval can filter on them. A move makes that copy stale, and
    # a stale copy means "what did I write about X in <subject>" filters on
    # where the note used to be. Refreshed here because this is the single
    # choke point every move goes through - by id, by name, and by voice
    # command. Never raises: a stale index is a worse search result, not a
    # failed move.
    from app.rag.indexer import reindex_note_metadata

    reindex_note_metadata(db, note)
    return note, target


def move_note_by_name(db, note_id: str, target_name: str):
    """Resolve `target_name` (fuzzy: topic name first, then subject name) to a
    Topic, creating a new Topic (and Subject, if needed) when nothing close
    enough exists, then move the note there.

    Backs both `POST /hierarchy/notes/{id}/move-by-name` and the
    "move this note to X" voice command (`app.hierarchy.commands`) - the two
    places a spoken destination name needs turning into a real topic id.
    Returns `(note, topic, subject, created_new_topic)`.
    """
    from app.db.repositories import SubjectRepository, TopicRepository

    topic_repo = TopicRepository(db)
    subject_repo = SubjectRepository(db)

    created_new_topic = False
    topic = topic_repo.find_best_name_match(target_name)
    if topic is None:
        subject = subject_repo.find_best_name_match(target_name)
        if subject is not None:
            topic, created_new_topic = topic_repo.get_or_create(subject.id, "General")
        else:
            new_subject, _ = subject_repo.get_or_create(target_name.title())
            topic, created_new_topic = topic_repo.get_or_create(new_subject.id, target_name.title())

    note, target = move_note(db, note_id, topic.id)
    return note, target, target.subject, created_new_topic


def refresh_topic_summary(db, topic_id: str) -> str:
    from app.hierarchy.cluster_summary import refresh_summary

    return refresh_summary(db, topic_id)


def recluster_subject(db, subject_id: str) -> dict:
    from app.hierarchy.clustering import recluster_subject as _recluster

    return _recluster(db, subject_id)
