"""Contacts - EchoNotes Feature 5.

Resolves people named in a note against the user's known contacts, so a note can offer an
action - call, message, email - rather than just mentioning a name.

EchoNotes never places a call or sends a message on its own. It offers the action and the user
confirms; an accidental outbound message is not recoverable and not visible to check.
"""

from __future__ import annotations

from typing import Any


def resolve_person(name: str) -> dict[str, Any] | None:
    """Match a spoken name to a stored contact, tolerating recognizer spelling errors."""
    raise NotImplementedError


def suggest_actions(contact: dict[str, Any], note_text: str) -> list[dict[str, str]]:
    """Offer call / message / email as confirmable actions, never auto-executed."""
    raise NotImplementedError
