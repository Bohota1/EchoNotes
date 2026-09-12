"""Graph orchestration - the one place that turns a captured note into its
place in the course knowledge graph and its generated content (NexaNota
Sections 4.1/4.3.2/4.3.3), replacing `app.understanding.organizer.organize`
and `app.hierarchy.service`.

    organize_note(db, note)
        1. extract 2-3 topics from the note's text                (4.1)
        2. place them under a Subject (the paper's "course")
        3. link the note to its topics, primary one mirrored onto
           `Note.topic_id` for single-topic consumers               (RAG, reminders)
        4. connect the note's topics to each other (co-occurrence,
           always) and to the rest of the course's topics (LLM,
           best-effort)                                             (4.3.2, D3)
        5. recommend 1-2 cross-disciplinary topics, best-effort      (4.3.2)
        6. generate the note's 3-area content                       (4.3.3, D2)
        7. suggest web resources for any newly created topic         (4.3.2)

Every step after (1) is best-effort and independently guarded: a note is
always filed and always gets *some* content, even if every LLM call in
this module fails or no LLM is configured at all.
"""

from __future__ import annotations

import logging
import re

from sqlalchemy.orm import Session

from app.db.models import Note, Topic
from app.db.repositories import (
    NoteContentRepository,
    NoteRepository,
    NoteTopicRepository,
    SubjectRepository,
    TopicConnectionRepository,
    TopicRepository,
    WebResourceRepository,
)

logger = logging.getLogger(__name__)

_EXPLICIT_PLACEMENT = re.compile(
    r"\b(?:file|put|save)\s+this\s+under\s+(?P<name>[A-Za-z][\w\s\-']{1,60}?)(?:[.,;!?]|$)",
    re.IGNORECASE,
)


def _infer_subject_name(text: str) -> str | None:
    """"File this under Operating Systems." - the one piece of the old
    explicit-placement logic worth keeping: an unambiguous spoken
    instruction should win over any inference, LLM or not."""
    match = _EXPLICIT_PLACEMENT.search(text or "")
    if not match:
        return None
    name = match.group("name").strip()
    return name.title() if name else None


def _resolve_subject(db: Session, note: Note):
    from app.config import get_settings

    explicit = _infer_subject_name(note.cleaned_text)
    if explicit:
        subject, _created = SubjectRepository(db).get_or_create(explicit)
        return subject
    default_name = get_settings().default_subject_name
    subject, _created = SubjectRepository(db).get_or_create(default_name)
    return subject


def organize_note(db: Session, note: Note) -> Topic | None:
    """Run the whole graph hand-off for one note. Returns the primary topic,
    or None for empty text (nothing to organize)."""
    text = (note.cleaned_text or "").strip()
    if not text:
        return None

    from app.graph.connections import co_occurring_connections, llm_connections
    from app.graph.cross_disciplinary import recommend_cross_disciplinary
    from app.graph.note_generator import generate_note_content
    from app.graph.topic_extraction import extract_topics
    from app.graph.web_resources import suggest_resources

    subject = _resolve_subject(db, note)
    topic_repo = TopicRepository(db)

    extracted = extract_topics(text)
    if not extracted:
        # Never leave a note with nothing - fall back to the subject's own
        # name as a single topic, same spirit as the old design's "Unfiled".
        from app.graph.topic_extraction import ExtractedTopic

        extracted = [ExtractedTopic(name=subject.name, confidence=0.1)]

    # (topic, the ExtractedTopic that resolved to it) pairs, one per distinct
    # topic. Kept as pairs rather than two parallel lists so a later dedupe
    # cannot silently desync which confidence belongs to which topic.
    resolved: list[tuple[Topic, ExtractedTopic]] = []
    newly_created: list[Topic] = []
    seen_ids: set[str] = set()
    for item in extracted:
        # Fuzzy, not exact: extraction runs independently per note, so
        # "Array" and "Arrays" are the same topic to a person even though
        # neither extraction call knows the other one exists. An exact match
        # here would spawn a near-duplicate topic every time wording varies
        # slightly - see `TopicRepository.get_or_create_fuzzy`.
        topic, created = topic_repo.get_or_create_fuzzy(subject.id, item.name)
        if topic.id in seen_ids:
            # Two of THIS note's own extracted names resolved to the same
            # topic - e.g. "Database" and "Database Project" are close
            # enough to match each other, not just an existing topic. Keep
            # the first (higher-ranked) occurrence; linking the same topic
            # to this note twice would violate note_topics' uniqueness and
            # abort the whole capture's transaction, not just the filing.
            continue
        seen_ids.add(topic.id)
        resolved.append((topic, item))
        if created:
            newly_created.append(topic)

    topics: list[Topic] = [t for t, _ in resolved]

    # --- link the note to its topics (primary mirrored onto Note.topic_id) -
    primary, primary_item = resolved[0]
    method = "llm" if primary_item.confidence >= 0.55 else "heuristic"
    NoteRepository(db).set_assignment(
        note.id,
        topic_id=primary.id,
        method=method,
        confidence=primary_item.confidence,
        reason=f"extracted from note text as topic 1 of {len(topics)}",
    )
    NoteTopicRepository(db).set_for_note(
        note.id,
        [
            {"topic_id": t.id, "rank": rank, "confidence": item.confidence}
            for rank, (t, item) in enumerate(resolved)
        ],
    )

    # --- connections: always link this note's own topics to each other ----
    conn_repo = TopicConnectionRepository(db)
    by_name = {t.name: t for t in topics}
    for edge in co_occurring_connections([t.name for t in topics]):
        a, b = by_name.get(edge.topic_a), by_name.get(edge.topic_b)
        if a and b:
            conn_repo.create(
                subject.id, a.id, b.id,
                label=edge.label, confidence=edge.confidence, method=edge.method,
            )

    # --- connections: best-effort, whole-subject, only when the graph just
    # grew (skip the LLM call on a note that only reused existing topics) --
    if newly_created:
        subject_topics = topic_repo.list_for_subject(subject.id)
        by_name_all = {t.name: t for t in subject_topics}
        for edge in llm_connections([t.name for t in subject_topics]):
            a, b = by_name_all.get(edge.topic_a), by_name_all.get(edge.topic_b)
            if a and b:
                conn_repo.create(
                    subject.id, a.id, b.id,
                    label=edge.label, confidence=edge.confidence, method=edge.method,
                )

        # --- cross-disciplinary recommendations (4.3.2) --------------------
        for rec in recommend_cross_disciplinary([t.name for t in subject_topics]):
            rec_topic, rec_created = topic_repo.get_or_create(subject.id, rec.name)
            if rec_created:
                rec_topic.is_recommended = True
                db.flush()
                conn_repo.create(
                    subject.id, primary.id, rec_topic.id,
                    label=rec.reason, confidence=0.5, method="llm",
                )

    # --- note content: the 3-area Note-Taking Area (4.3.3) -----------------
    generated = generate_note_content(text, [t.name for t in topics])
    NoteContentRepository(db).upsert_generated(
        note.id,
        definition=generated.definition,
        example_analysis=generated.example_analysis,
        summary=generated.summary,
        edit_markdown=_initial_markdown(generated),
        method=generated.method,
    )

    # --- web resources for any topic this note just created (4.3.2) --------
    resource_repo = WebResourceRepository(db)
    for topic in newly_created:
        suggestions = suggest_resources(topic.name)
        if suggestions:
            resource_repo.replace_for_topic(
                topic.id,
                [
                    {
                        "title": s.title,
                        "resource_type": s.resource_type,
                        "search_query": s.search_query,
                        "url": None,
                        "verified": False,
                    }
                    for s in suggestions
                ],
            )

    db.flush()
    return primary


def _initial_markdown(generated) -> str:
    """The Edit Area's starting text (NexaNota 4.3.3): the generated
    Note-Taking Area, laid out so a student edits it in place rather than
    starting from a blank field."""
    parts = []
    if generated.definition:
        parts.append(f"**Definition:** {generated.definition}")
    if generated.example_analysis:
        parts.append(f"**Example:** {generated.example_analysis}")
    if generated.summary:
        parts.append(f"**Summary:** {generated.summary}")
    return "\n\n".join(parts)
