"""Entity extraction - EchoNotes Features 2 and 5.

Pulls out the things a note commits the user to: tasks, dates, deadlines and people. What is
found here is what `reminders/` acts on, and what the "note info" shortcut announces.

Every entity keeps its character span into the note text so the UI can announce "deadline,
Friday, in sentence two" instead of an isolated value.
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class EntityKind(str, Enum):
    PERSON = "person"
    DATE = "date"
    DEADLINE = "deadline"
    TASK = "task"
    CONTACT = "contact"


def extract_people(text: str) -> list[dict[str, Any]]:
    """Named people, via NLTK named-entity chunking plus the user's known contacts."""
    raise NotImplementedError


def extract_dates(text: str) -> list[dict[str, Any]]:
    """Absolute and relative dates ("next Tuesday", "in two weeks"), normalized to ISO-8601.

    Relative dates resolve against the capture time, not the time of processing, which matters
    when a long lecture is processed after the fact.
    """
    raise NotImplementedError


def extract_tasks(text: str) -> list[dict[str, Any]]:
    """Imperative or commitment phrasing: "I need to", "remind me to", "submit ... by"."""
    raise NotImplementedError


def extract_contacts(text: str) -> list[dict[str, Any]]:
    """Phone numbers and email addresses, normalized to E.164 where possible."""
    raise NotImplementedError


def extract_all(text: str, captured_at=None) -> list[dict[str, Any]]:
    """Run every extractor and return one merged, span-sorted, de-duplicated list."""
    raise NotImplementedError
