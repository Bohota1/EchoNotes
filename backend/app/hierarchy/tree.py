"""The three-level hierarchy - Idea11y Section 4.1 (Design Goal 1), adapted.

Idea11y decomposed a whiteboard into **Frame - Cluster - Note**. EchoNotes has no whiteboard, so
the same three levels carry note-taking meaning instead:

    Subject          (Idea11y: Frame)   ->  h1
      Topic/Project  (Idea11y: Cluster) ->  h2  + generated summary
        Note         (Idea11y: Note)    ->  li

Three levels, never four. Idea11y kept the outline shallow because a screen reader user builds a
mental model from serial, ephemeral speech; every extra level costs them working memory.

A note with no home goes to the **Unfiled** subject, the analogue of Idea11y's "Unframed Section".
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
    quality_score: float | None = None


@dataclass
class TopicNode:
    id: str
    name: str
    kind: TopicKind
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

    def counts(self) -> dict[str, int]:
        """Totals for the Library Overview (Idea11y's board overview)."""
        raise NotImplementedError

    def find_note(self, note_id: str) -> NoteNode | None:
        raise NotImplementedError

    def move_note(self, note_id: str, target_topic_id: str) -> None:
        """Re-file a note. Idea11y Section 4.2: move via a drop-down of current clusters."""
        raise NotImplementedError
