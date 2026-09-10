"""Date and deadline resolution - EchoNotes Feature 5.

Speech carries relative dates far more than writing does: "tomorrow", "next Tuesday", "in a
fortnight", "by the end of the month". Every one resolves against the **capture time**, not the
processing time, so a lecture transcribed the next morning still means the right day.
"""

from __future__ import annotations

from datetime import datetime


def parse_date(expression: str, reference: datetime | None = None) -> datetime | None:
    """Resolve a spoken date expression with `dateparser`, relative to `reference`."""
    raise NotImplementedError


def is_deadline_phrase(expression: str) -> bool:
    """Distinguish a deadline ("by Friday", "due Friday") from a plain mention ("on Friday")."""
    raise NotImplementedError


def speak_date(value: datetime) -> str:
    """Say a date the way a person would: "tomorrow at 4", "next Tuesday", "on 3 March"."""
    raise NotImplementedError
