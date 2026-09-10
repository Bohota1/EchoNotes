"""Earcons - Idea11y Section 4.3.

Idea11y played a beep when a screen reader user arrived at a note a collaborator
was working on, choosing a non-speech cue "to minimize disruption in the user's
workflow", and let users pick earcon, speech, both, or none.

EchoNotes is single-user, so the same machinery signals capture and note state
instead. The four-way feedback setting is kept exactly as the paper offered it,
because the underlying reason holds regardless of what is being signalled: a
200ms tone costs a fraction of the attention that a spoken sentence does, and
during rapid work that difference is the whole point.

Tones are synthesised in the browser with the Web Audio API rather than shipped
as files - no network wait, so the recording cue lands the instant the key goes
down. The server names the cue; `frontend/src/a11y/earcons.ts` plays it.
"""

from __future__ import annotations

from enum import Enum


class Earcon(str, Enum):
    RECORDING_START = "recording_start"
    RECORDING_STOP = "recording_stop"
    NOTE_SAVED = "note_saved"
    NOTE_MOVED = "note_moved"
    RESULTS_FOUND = "results_found"
    NO_RESULTS = "no_results"
    REMINDER_DUE = "reminder_due"
    LIST_END = "list_end"
    ERROR = "error"


class FeedbackMode(str, Enum):
    EARCON = "earcon"
    SPEECH = "speech"
    BOTH = "both"
    NONE = "none"


#: Spoken equivalent for every cue, used in SPEECH and BOTH modes. A user who
#: has not learned the tones yet, or who has turned them off, must still be told
#: what happened.
SPOKEN_EQUIVALENT: dict[Earcon, str] = {
    Earcon.RECORDING_START: "Recording",
    Earcon.RECORDING_STOP: "Stopped",
    Earcon.NOTE_SAVED: "Note saved",
    Earcon.NOTE_MOVED: "Note moved",
    Earcon.RESULTS_FOUND: "Results found",
    Earcon.NO_RESULTS: "Nothing found",
    Earcon.REMINDER_DUE: "Reminder due",
    Earcon.LIST_END: "End of list",
    Earcon.ERROR: "Error",
}


def feedback_for(earcon: Earcon, mode: FeedbackMode) -> dict[str, str | None]:
    """What to play and what to say for one cue, under the current mode."""
    if mode == FeedbackMode.NONE:
        return {"earcon": None, "speech": None}
    if mode == FeedbackMode.EARCON:
        return {"earcon": earcon.value, "speech": None}
    if mode == FeedbackMode.SPEECH:
        return {"earcon": None, "speech": SPOKEN_EQUIVALENT[earcon]}
    return {"earcon": earcon.value, "speech": SPOKEN_EQUIVALENT[earcon]}
