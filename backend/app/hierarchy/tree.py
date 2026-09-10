"""The three-level hierarchy - Idea11y Section 4.1 (Design Goal 1), adapted.

Idea11y decomposed a whiteboard into **Frame - Cluster - Note**. EchoNotes has
no whiteboard, so the same three levels carry note-taking meaning instead:

    Subject          (Idea11y: Frame)   ->  h1
      Topic/Project  (Idea11y: Cluster) ->  h2  + generated summary
        Note         (Idea11y: Note)    ->  li

Three levels, never four. Idea11y kept the outline shallow because a screen
reader user builds a mental model from serial, ephemeral speech; every extra
level costs them working memory.

A note with no home goes to the **Unfiled** subject, the analogue of Idea11y's
"Unframed Section".

This module is a pure, in-memory read model: a `Hierarchy` is built fresh
from the database on every read (`app.hierarchy.service.build_hierarchy`) and
discarded afterwards. It never writes to SQLite itself - `move_note` below
mutates the dataclass tree only, so it is safe to unit-test the tree logic in
isolation; the real, persisted move goes through
`app.hierarchy.service.move_note` -> `app.db.repositories.NoteRepository`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class TopicKind(str, Enum):
    TOPIC = "topic"
    PROJECT = "project"


@dataclass
class NoteNode:
    id: str
    text: str
    note_type: str
    source: str
    created_at: datetime
    updated_at: datetime
    quality_score: float | None = None


@dataclass
class TopicNode:
    id: str
    name: str
    kind: TopicKind | str
    summary: str = ""          # Idea11y's AI-generated cluster summary
    summary_stale: bool = False
    notes: list[NoteNode] = field(default_factory=list)


@dataclass
class SubjectNode:
    id: str
    name: str
    is_unfiled: bool = False
    topics: list[TopicNode] = field(default_factory=list)


@dataclass
class Hierarchy:
    subjects: list[SubjectNode] = field(default_factory=list)

    def counts(self) -> dict[str, object]:
        """Totals for the Library Overview (Idea11y's board overview)."""
        note_count = 0
        topic_count = 0
        notes_by_type: dict[str, int] = {}
        for subject in self.subjects:
            topic_count += len(subject.topics)
            for topic in subject.topics:
                for note in topic.notes:
                    note_count += 1
                    notes_by_type[note.note_type] = notes_by_type.get(note.note_type, 0) + 1
        return {
            "subject_count": len(self.subjects),
            "topic_count": topic_count,
            "note_count": note_count,
            "notes_by_type": notes_by_type,
        }

    def find_note(self, note_id: str) -> NoteNode | None:
        for subject in self.subjects:
            for topic in subject.topics:
                for note in topic.notes:
                    if note.id == note_id:
                        return note
        return None

    def find_topic(self, topic_id: str) -> TopicNode | None:
        for subject in self.subjects:
            for topic in subject.topics:
                if topic.id == topic_id:
                    return topic
        return None

    def find_subject(self, subject_id: str) -> SubjectNode | None:
        for subject in self.subjects:
            if subject.id == subject_id:
                return subject
        return None

    def topic_of(self, note_id: str) -> TopicNode | None:
        for subject in self.subjects:
            for topic in subject.topics:
                for note in topic.notes:
                    if note.id == note_id:
                        return topic
        return None

    def move_note(self, note_id: str, target_topic_id: str) -> None:
        """Re-file a note within the in-memory tree only. Idea11y Section 4.2:
        move via a drop-down of current clusters. Marks both the source and
        destination topic's summary stale, since moving a note changes what
        both clusters are about."""
        source_topic: TopicNode | None = None
        note: NoteNode | None = None
        for subject in self.subjects:
            for topic in subject.topics:
                for n in topic.notes:
                    if n.id == note_id:
                        source_topic, note = topic, n
                        break
                if note is not None:
                    break
            if note is not None:
                break

        if note is None or source_topic is None:
            raise KeyError(f"no note {note_id} in this hierarchy")

        target_topic = self.find_topic(target_topic_id)
        if target_topic is None:
            raise KeyError(f"no topic {target_topic_id} in this hierarchy")

        if target_topic.id == source_topic.id:
            return

        source_topic.notes.remove(note)
        target_topic.notes.append(note)
        source_topic.summary_stale = True
        target_topic.summary_stale = True
