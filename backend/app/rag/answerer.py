"""Answer generation - EchoNotes Feature 4.

Answers are spoken, which changes the rules:

  - Short. A listener cannot skim; put the answer in the first sentence.
  - Grounded. Only what the retrieved notes support.
  - Sourced. Name where it came from ("from your Operating Systems notes on Tuesday"), because a
    user who cannot see the citation list needs it in the sentence.
  - Honest about emptiness. "I have no notes about that" is a valid, useful answer; never
    improvise around missing notes.
"""

from __future__ import annotations

from typing import Any

ANSWER_PROMPT = """\
Answer the user's question using ONLY the notes below. The answer is read aloud, so:
- Give the answer in the first sentence. No preamble.
- Keep it under 40 words unless the question demands detail.
- Name which note or subject it came from.
- If the notes do not answer it, say so plainly.

Question: {question}

Notes:
{context}
"""


async def answer(question: str, retrieved: list[dict[str, Any]]) -> dict[str, Any]:
    """Return {"spoken": str, "sources": [note_id, ...], "confidence": float}."""
    raise NotImplementedError


def format_note_list(notes: list[dict[str, Any]]) -> str:
    """Speak a result list: how many, then each one numbered so the user can pick by number."""
    raise NotImplementedError
