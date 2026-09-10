"""Per-topic cluster summaries - Idea11y Section 4.1.

The paper: "To facilitate understanding of a cluster theme, Idea11y provides a concise,
AI-generated summary of all notes within each cluster. The summary is updated in real-time as
users add/edit notes within that cluster." Idea11y used gpt-4o-mini; the provider here is
configurable.

The summary is the first thing announced when the user lands on a topic heading, so it has to be
one short sentence. Idea11y's own examples are the target length: "Improving train efficiency and
speed.", "Security measures for access control."
"""

from __future__ import annotations

SUMMARY_PROMPT = """\
Summarise this group of notes in ONE short sentence, at most 12 words.
State what the notes are about. Do not count them, do not add a preamble.
The sentence is read aloud by a screen reader, so it must be plain and self-contained.

Notes:
{notes}
"""


async def generate_summary(note_texts: list[str]) -> str:
    """One-sentence summary of the notes in a topic."""
    raise NotImplementedError


async def refresh_summary(topic_id: str) -> str:
    """Regenerate and persist a topic's summary. Called whenever a child note changes."""
    raise NotImplementedError


def mark_stale(topic_id: str) -> None:
    """Flag a topic for regeneration.

    Writing a note must not block on an LLM call, so the summary is marked stale and refreshed in
    the background; the outline shows the previous summary until the new one lands.
    """
    raise NotImplementedError
