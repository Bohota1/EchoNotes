"""Outline rendering - Idea11y Section 4.1 (Design Goal 1).

The paper transforms board content "into a header-subheader-bullet list
format, following BLV users' conventional practice of organizing ideas on
document editors ... this way, screen reader users can easily navigate to
different clusters and notes using familiar keyboard shortcuts (e.g.
'H'/'Shift+H' in JAWS/NVDA to navigate by heading levels)."

That is the whole point of this module: emit **real heading levels**, not a
custom tree widget. The server produces a structure the client renders as
h1 / h2 / ul-li, so what the user navigates is the browser's own heading
list, and it emits a full spoken **narration** of the same structure for a
pure-voice client (`GET /hierarchy`'s `narration` field) - Team Member 3's
voice-query system can read it aloud verbatim without having to know
anything about the JSON shape underneath.
"""

from __future__ import annotations

from typing import Any

from app.hierarchy.overview import build_overview
from app.hierarchy.tree import Hierarchy, NoteNode, SubjectNode, TopicNode


def _plural(n: int, word: str) -> str:
    return word if n == 1 else f"{word}s"


def _are(n: int) -> str:
    return "is" if n == 1 else "are"


def to_outline(hierarchy: Hierarchy) -> dict[str, Any]:
    """Serialize the hierarchy into the outline structure the front end
    renders and the voice narration a screen reader announces.

    {
      "overview": {...},
      "subjects": [
        {"id", "name", "is_unfiled", "level": 1,
         "topics": [
           {"id", "name", "kind", "level": 2, "summary", "summary_stale",
            "notes": [{"id", "topic_id", "text", "note_type", "source",
                       "created_at", "updated_at", "quality_score"}]}
         ]}
      ],
      "narration": "You have 3 subjects. Under Discrete Structure, ..."
    }
    """
    overview = build_overview(hierarchy)
    subjects_payload = [_subject_payload(subject) for subject in hierarchy.subjects]
    narration = build_narration(hierarchy, overview=overview)
    return {"overview": overview, "subjects": subjects_payload, "narration": narration}


def _subject_payload(subject: SubjectNode) -> dict[str, Any]:
    return {
        "id": subject.id,
        "name": subject.name,
        "is_unfiled": subject.is_unfiled,
        "level": 1,
        "topics": [_topic_payload(topic) for topic in subject.topics],
    }


def _topic_payload(topic: TopicNode) -> dict[str, Any]:
    kind = topic.kind.value if hasattr(topic.kind, "value") else topic.kind
    return {
        "id": topic.id,
        "name": topic.name,
        "kind": kind,
        "level": 2,
        "summary": topic.summary,
        "summary_stale": topic.summary_stale,
        "notes": [_note_payload(note, topic.id) for note in topic.notes],
    }


def _note_payload(note: NoteNode, topic_id: str) -> dict[str, Any]:
    return {
        "id": note.id,
        "topic_id": topic_id,
        "text": note.text,
        "note_type": note.note_type,
        "source": note.source,
        "created_at": note.created_at,
        "updated_at": note.updated_at,
        "quality_score": note.quality_score,
    }


def to_markdown(hierarchy: Hierarchy) -> str:
    """Same outline as markdown headings and bullets.

    Idea11y offered "Save as Word Document" so users could take the outline
    into the editor they already work in. This is that export, in a format
    that converts cleanly.
    """
    lines: list[str] = []
    for subject in hierarchy.subjects:
        heading = f"{subject.name} (Unfiled)" if subject.is_unfiled else subject.name
        lines.append(f"# {heading}")
        for topic in subject.topics:
            lines.append(f"## {topic.name}")
            if topic.summary:
                lines.append(f"_{topic.summary}_")
                lines.append("")
            for note in topic.notes:
                lines.append(f"- {note.text}")
            lines.append("")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def build_narration(hierarchy: Hierarchy, overview: dict[str, Any] | None = None) -> str:
    """The full spoken script for the whole hierarchy: overview, then every
    subject and its topic counts, then every topic's note count and summary.

    Matches the Phase 3 spec's example almost verbatim:

        You have 3 subjects. Under Discrete Structure, there are 4 topics.
        Under Graph Theory, there are 6 notes. The topic summary is: ...

    Front-loaded, short sentences throughout (`docs/accessibility.md`
    non-negotiable #5): identifying information first, one fact per sentence,
    nothing a listener has to hold in their head to parse the next clause.
    """
    overview = overview or build_overview(hierarchy)
    lines = [overview["spoken"]]

    for subject in hierarchy.subjects:
        if not subject.topics:
            continue
        subject_label = f"{subject.name}, unfiled notes" if subject.is_unfiled else subject.name
        topic_count = len(subject.topics)
        lines.append(
            f"Under {subject_label}, there {_are(topic_count)} {topic_count} "
            f"{_plural(topic_count, 'topic')}."
        )
        for topic in subject.topics:
            note_count = len(topic.notes)
            lines.append(
                f"Under {topic.name}, there {_are(note_count)} {note_count} "
                f"{_plural(note_count, 'note')}."
            )
            if topic.summary:
                lines.append(f"The topic summary is: {topic.summary}")

    return " ".join(lines)


def announcement_for_node(node: SubjectNode | TopicNode | NoteNode, verbosity: str = "normal") -> str:
    """The string a screen reader should hear for one node, identifying
    information first: "Deadlock, topic, 6 notes." rather than "Topic
    containing 6 notes called Deadlock." (`docs/accessibility.md` #5)."""
    if isinstance(node, SubjectNode):
        label = "unfiled subject" if node.is_unfiled else "subject"
        topic_count = len(node.topics)
        return f"{node.name}, {label}, {topic_count} {_plural(topic_count, 'topic')}"

    if isinstance(node, TopicNode):
        kind = node.kind.value if hasattr(node.kind, "value") else node.kind
        note_count = len(node.notes)
        base = f"{node.name}, {kind}, {note_count} {_plural(note_count, 'note')}"
        if verbosity != "brief" and node.summary:
            base += f". Summary: {node.summary}"
        return base

    if isinstance(node, NoteNode):
        return f"{node.note_type} note: {node.text}"

    return ""
