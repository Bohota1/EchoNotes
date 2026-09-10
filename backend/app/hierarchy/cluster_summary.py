"""Per-topic cluster summaries - Idea11y Section 4.1 - and the shared
extractive/LLM summarizer that Phase 5's roll-ups (`app.hierarchy.summarization`)
reuse.

The paper: "To facilitate understanding of a cluster theme, Idea11y provides a
concise, AI-generated summary of all notes within each cluster. The summary is
updated in real-time as users add/edit notes within that cluster." Idea11y
used gpt-4o-mini; the provider here is configurable through the shared
`app.llm` abstraction (`get_llm_client()`), never called directly.

The summary is the first thing announced when the user lands on a topic
heading, so it has to be one short sentence. Idea11y's own examples are the
target length: "Improving train efficiency and speed.", "Security measures
for access control."

These functions are synchronous, matching the rest of the working pipeline
(`app.understanding.service`, `app.pipeline.capture_pipeline`) - nothing in
this project actually performs async I/O (the LLM client and SQLAlchemy
session are both synchronous), so `async def` here would be ceremony with no
benefit and a mismatch with how every other stage is called.
"""

from __future__ import annotations

import logging

from app.config import get_settings
from app.llm import get_llm_client

logger = logging.getLogger(__name__)

SUMMARY_PROMPT = """\
Summarise the following notes in ONE short sentence, at most {max_words} words.
State what the notes are about. Do not count them, do not add a preamble, do not use quotes.
The sentence is read aloud by a screen reader, so it must be plain and self-contained.

Notes:
{notes}
"""


def extractive_summary(texts: list[str], max_words: int = 12) -> str:
    """No-LLM summary: the most representative single text, trimmed.

    "Representative" means closest to the centroid of the group's hashed
    bag-of-words vectors (`app.hierarchy.embeddings`) - a cheap proxy for
    "the note most other notes here resemble". This is what keeps EchoNotes
    fully usable with `LLM_PROVIDER=null`, and it is also what
    `app.hierarchy.clustering` uses to name a freshly-formed cluster.
    """
    cleaned = [t.strip() for t in texts if t and t.strip()]
    if not cleaned:
        return ""

    if len(cleaned) == 1:
        chosen = cleaned[0]
    else:
        import numpy as np

        from app.hierarchy.embeddings import cosine_similarity, embed_text

        vectors = [embed_text(t) for t in cleaned]
        centroid = np.mean(vectors, axis=0)
        best_idx = max(
            range(len(cleaned)), key=lambda i: cosine_similarity(vectors[i], centroid)
        )
        chosen = cleaned[best_idx]

    words = chosen.split()
    if len(words) <= max_words:
        return chosen
    return " ".join(words[:max_words]) + "..."


def generate_summary(note_texts: list[str], max_words: int | None = None) -> str:
    """One summary for a group of notes.

    Used both as a short, one-line Topic summary (Idea11y Section 4.1,
    `max_words` defaults to `topic_summary_max_words`) and, with a larger
    `max_words`, as the roll-up summarizer for a Subject or a time range
    (Phase 5, `app.hierarchy.summarization`).
    """
    max_words = max_words or get_settings().topic_summary_max_words
    cleaned = [t for t in note_texts if t and t.strip()]
    if not cleaned:
        return "No notes yet."

    client = get_llm_client()
    if client.available:
        try:
            prompt = SUMMARY_PROMPT.format(
                max_words=max_words, notes="\n".join(f"- {t}" for t in cleaned[:40])
            )
            response = client.complete(prompt, max_tokens=max(40, max_words * 3))
            text = response.text.strip().strip('"')
            if text:
                return text
        except Exception:
            logger.exception("LLM summary failed, falling back to extractive")

    return extractive_summary(cleaned, max_words=max_words)


def refresh_summary(db, topic_id: str) -> str:
    """Regenerate and persist a topic's summary. Called whenever a child note
    changes (via `mark_stale` below, at write time) and lazily read back the
    next time the topic's summary is actually needed - see the module-level
    note on why this is not inline on the note-writing path."""
    from app.db.repositories import NoteRepository, TopicRepository

    topic_repo = TopicRepository(db)
    topic = topic_repo.get(topic_id)
    if topic is None:
        raise ValueError(f"no topic {topic_id}")

    notes = NoteRepository(db).list_by_topic(topic_id, limit=200)
    texts = [n.cleaned_text for n in notes if n.cleaned_text]
    summary = generate_summary(texts)
    topic_repo.set_summary(topic_id, summary)
    return summary


def mark_stale(db, topic_id: str) -> None:
    """Flag a topic for regeneration.

    Writing a note must not block on an LLM call, so the summary is marked
    stale here and only actually regenerated the next time it is read
    (`refresh_summary`, called from `app.hierarchy.summarization` and from
    `POST /hierarchy/topics/{id}/summary`); the outline shows the previous
    summary in the meantime rather than blanking it out.
    """
    from app.db.repositories import TopicRepository

    TopicRepository(db).mark_stale(topic_id)
