"""Earcons - Idea11y Section 4.3.

Idea11y played a beep when a screen reader user arrived at a note a collaborator was working on,
choosing a non-speech cue "to minimize disruption in the user's workflow", and let users pick
earcon, speech, both, or none.

EchoNotes is single-user, so the same machinery signals capture and outline state instead. The
four-way feedback setting is kept exactly as the paper offered it.
"""

from __future__ import annotations

from enum import Enum


class Earcon(str, Enum):
    RECORDING_START = "recording_start"
    RECORDING_STOP = "recording_stop"
    NOTE_SAVED = "note_saved"
    NOTE_MOVED = "note_moved"
    LIST_END = "list_end"
    ERROR = "error"


class FeedbackMode(str, Enum):
    EARCON = "earcon"
    SPEECH = "speech"
    BOTH = "both"
    NONE = "none"


#: Spoken equivalent for every earcon, used in SPEECH and BOTH modes.
SPOKEN_EQUIVALENT: dict[Earcon, str] = {
    Earcon.RECORDING_START: "Recording",
    Earcon.RECORDING_STOP: "Stopped",
    Earcon.NOTE_SAVED: "Note saved",
    Earcon.NOTE_MOVED: "Note moved",
    Earcon.LIST_END: "End of list",
    Earcon.ERROR: "Error",
}


def feedback_for(earcon: Earcon, mode: FeedbackMode) -> dict[str, str | None]:
    """Return {"earcon": name or None, "speech": text or None} for the current mode."""
    raise NotImplementedError
