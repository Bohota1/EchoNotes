"""Voice coding - Idea11y Section 4.3, adapted.

Idea11y read notes from different collaborators (or of different colours) in **distinct
synthesized voices**, "to help screen reader users process multiple pieces of information in
parallel i.e., note text in tandem with its creator/color". EchoNotes has one user, so the second
channel becomes the **note type**: the listener hears that something is a to-do without an extra
spoken clause in front of every item.

As in the paper, the **default is a single consistent voice** and voice coding is opt-in.
"""

from __future__ import annotations

from enum import Enum


class VoiceMode(str, Enum):
    CONSISTENT = "consistent"  # paper default
    BY_TYPE = "by_type"        # paper's "by creator / by color", adapted


#: Web Speech API voice names, resolved on the client against what the platform offers.
VOICE_BY_NOTE_TYPE: dict[str, str] = {
    "academic": "voice-a",
    "brainstorm": "voice-b",
    "todo": "voice-c",
}

DEFAULT_VOICE = "voice-a"


def voice_for(note_type: str, mode: VoiceMode = VoiceMode.CONSISTENT) -> str:
    """Pick the voice profile for a note under the current mode."""
    raise NotImplementedError
