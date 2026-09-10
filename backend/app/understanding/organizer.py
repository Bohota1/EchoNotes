"""Filing a note into the hierarchy - EchoNotes Feature 3.

Decides which Subject and which Topic/Project a new note belongs to, given what the LNT stages
found (themes, LDA topics) and what the classifier decided (note type).

Precedence, which mirrors Idea11y's rule that an explicit bounded region outranks colour and
colour outranks proximity:

  1. The user said so out loud ("file this under Operating Systems") - always wins.
  2. An existing subject or topic matches strongly by embedding similarity.
  3. The dominant LDA topic and extracted themes suggest a new topic under an existing subject.
  4. Nothing matches - the note goes to Unfiled, and the user is told so.

Case 4 is announced, never silent. A note filed somewhere the user did not expect is worse than
one they know is waiting to be filed.
"""

from __future__ import annotations

from typing import Any


def detect_explicit_placement(text: str) -> dict[str, str] | None:
    """Catch spoken filing instructions and return {"subject": ..., "topic": ...}."""
    raise NotImplementedError


def match_existing_topic(note_embedding, candidates: list[dict[str, Any]], threshold: float = 0.72):
    """Nearest existing topic above the similarity threshold, or None."""
    raise NotImplementedError


def propose_new_topic(themes: list[dict[str, Any]], lda_topics: list[dict[str, Any]]) -> str:
    """Name a new topic from the strongest theme or labelled LDA topic."""
    raise NotImplementedError


def organize(ctx) -> tuple[str, str]:
    """Return (subject_id, topic_id) for the note in the given PipelineContext."""
    raise NotImplementedError
