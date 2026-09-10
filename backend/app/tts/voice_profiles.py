"""Voice coding - Idea11y Section 4.3, adapted.

Idea11y read notes from different collaborators in **distinct synthesized
voices**, "to help screen reader users process multiple pieces of information in
parallel i.e., note text in tandem with its creator/color". EchoNotes has one
user, so the second channel becomes the **note type**: a to-do sounds different
from a lecture note, and the listener learns that without an extra spoken clause
in front of every item.

As in the paper, the **default is a single consistent voice** and voice coding
is opt-in (`TTS_VOICE_CODING=by_type`). The paper made the same choice, and for
the same reason: distinct voices are a real cognitive aid to some users and an
irritation to others.

Voice *names* here are logical, not platform voices. The browser resolves them
against whatever the user actually has installed via
`frontend/src/a11y/voices.ts`; a server-side pyttsx3 run just uses the rate and
pitch. Hard-coding "Microsoft Zira" would break on every other machine.
"""

from __future__ import annotations

from dataclasses import dataclass

CONSISTENT = "consistent"
BY_TYPE = "by_type"


@dataclass(frozen=True)
class VoiceProfile:
    voice: str
    rate: int = 0  # 0 means "use the configured default rate"
    pitch: float = 1.0


#: The default voice, used for everything when voice coding is off.
DEFAULT_PROFILE = VoiceProfile(voice="default", rate=0, pitch=1.0)

#: Pitch is varied rather than picking three unrelated voices: a pitch shift on
#: one familiar voice stays intelligible at high speech rates, where switching
#: voice engines mid-list does not.
PROFILE_BY_NOTE_TYPE: dict[str, VoiceProfile] = {
    "academic": VoiceProfile(voice="voice-academic", rate=0, pitch=1.0),
    "brainstorm": VoiceProfile(voice="voice-brainstorm", rate=0, pitch=1.12),
    "todo": VoiceProfile(voice="voice-todo", rate=0, pitch=0.9),
}


def voice_for(note_type: str | None, mode: str = CONSISTENT) -> VoiceProfile:
    """The profile to speak a piece of text in.

    Falls back to the default for an unknown type rather than raising: an
    unrecognised note type should sound ordinary, not stop the response.
    """
    if mode != BY_TYPE or not note_type:
        return DEFAULT_PROFILE
    return PROFILE_BY_NOTE_TYPE.get(note_type, DEFAULT_PROFILE)


def describe_voice_coding(mode: str) -> str:
    """One spoken sentence explaining the current setting, for the settings UI."""
    if mode == BY_TYPE:
        return (
            "Voice coding is on. Lecture notes, ideas and to-dos are each read "
            "in a different voice."
        )
    return "Voice coding is off. Everything is read in one voice."
