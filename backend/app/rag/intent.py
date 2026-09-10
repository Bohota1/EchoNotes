"""Voice command intent - EchoNotes Feature 4.

A spoken command is not always a question. Feature 4 covers retrieval, navigation, question
answering, summarization and confirmation, and each needs a different response shape, so the
intent is resolved before anything is retrieved.

    RETRIEVE   "find my notes on deadlock"                 -> list of notes, spoken as a list
    NAVIGATE   "go to Operating Systems"                   -> move focus in the outline
    ASK        "what did the lecturer say about mutexes"   -> RAG answer with sources
    SUMMARIZE  "summarize this week's notes"               -> summary over a filtered set
    CREATE     "add a note under Thesis"                   -> dictate a new note
    REMIND     "what's due tomorrow"                       -> reminder list
    UNKNOWN                                                -> ask the user to rephrase
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class Intent(str, Enum):
    RETRIEVE = "retrieve"
    NAVIGATE = "navigate"
    ASK = "ask"
    SUMMARIZE = "summarize"
    CREATE = "create"
    REMIND = "remind"
    UNKNOWN = "unknown"


def parse_intent(utterance: str) -> tuple[Intent, dict[str, Any]]:
    """Return the intent and its slots: subject, topic, note_type, time range, query text.

    Time expressions ("last week", "yesterday") are resolved here into a concrete range and
    handed to the retriever as a metadata filter.
    """
    raise NotImplementedError
