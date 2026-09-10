"""Speech output.

The browser's Web Speech API does the speaking, as in Idea11y Section 4.5, so the voice stays in
the user's own device and their preferred rate and pitch settings apply. The server only decides
*what* is said and *in which voice profile*; `pyttsx3` is a fallback for headless runs.
"""

from __future__ import annotations

from typing import Any


def build_utterance(text: str, note_type: str | None = None, mode: str = "consistent") -> dict[str, Any]:
    """Return {"text", "voice", "rate", "interrupt"} for the client to speak."""
    raise NotImplementedError


def speak_locally(text: str) -> None:
    """Server-side speech via pyttsx3. Headless and CLI use only."""
    raise NotImplementedError
