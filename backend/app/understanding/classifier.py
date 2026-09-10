"""Note classification - EchoNotes Feature 3.

Every note is classified into exactly one of three types:

    academic    lecture content, definitions, explanations, facts to revise
    brainstorm  ideas, "what if", possibilities, design thoughts
    todo        tasks, commitments, things with a deadline or an owner

The type drives three things: where the note is filed, whether the reminder pipeline runs on it,
and - when voice coding is on - which synthesized voice reads it (Idea11y Section 4.3, adapted
from note colour to note type).

Two-stage: a fast rule pass on strong cues, falling back to the LLM when the rules are unsure.
The rules exist because they run offline and instantly, and a user holding the spacebar should
not wait on a network round trip for the note to be filed.
"""

from __future__ import annotations

from enum import Enum


class NoteType(str, Enum):
    ACADEMIC = "academic"
    BRAINSTORM = "brainstorm"
    TODO = "todo"


#: Strong surface cues per type; checked before any model call.
RULE_CUES: dict[NoteType, tuple[str, ...]] = {
    NoteType.TODO: ("remind me", "i need to", "by tomorrow", "deadline", "due", "submit", "call"),
    NoteType.BRAINSTORM: ("what if", "idea", "maybe we", "could try", "brainstorm"),
    NoteType.ACADEMIC: ("definition", "theorem", "for example", "chapter", "lecture", "formula"),
}


def classify_by_rules(text: str) -> tuple[NoteType | None, float]:
    """Return (type, confidence). `None` when no rule fires strongly enough."""
    raise NotImplementedError


def classify_by_llm(text: str) -> tuple[NoteType, float]:
    """Ask the configured LLM for the type, constrained to the three labels."""
    raise NotImplementedError


def classify(text: str, min_rule_confidence: float = 0.7) -> tuple[NoteType, float]:
    """Rules first, LLM as fallback."""
    raise NotImplementedError
