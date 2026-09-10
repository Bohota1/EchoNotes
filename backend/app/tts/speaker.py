"""Composing what to say for common events.

`app.tts.engine` decides *how* something is spoken. This module decides *what* -
the wording of the routine announcements the system makes, kept in one place so
they stay consistent and so their phrasing can be reviewed as a set rather than
found scattered across endpoints.

House style, because these are heard and not read:

  - Identifying information first. "Note saved under Deadlock" beats "Your note
    has been saved under the topic Deadlock".
  - No filler. No "Okay", no "Sure", no "I've gone ahead and".
  - Say what happened, not what the system did internally.
"""

from __future__ import annotations

from app.tts.earcons import Earcon
from app.tts.engine import SpeechDirective, speak


def note_saved(topic_name: str, note_type: str | None = None) -> SpeechDirective:
    text = f"Note saved under {topic_name}." if topic_name else "Note saved."
    return speak(text, note_type=note_type, earcon=Earcon.NOTE_SAVED.value)


def note_moved(topic_name: str, subject_name: str = "") -> SpeechDirective:
    if subject_name and subject_name != topic_name:
        text = f"Moved to {topic_name}, under {subject_name}."
    else:
        text = f"Moved to {topic_name}."
    return speak(text, earcon=Earcon.NOTE_MOVED.value)


def recording_started() -> SpeechDirective:
    return speak("Recording.", interrupt=True, earcon=Earcon.RECORDING_START.value)


def recording_stopped() -> SpeechDirective:
    return speak("Stopped.", interrupt=True, earcon=Earcon.RECORDING_STOP.value)


def error(message: str) -> SpeechDirective:
    """Errors interrupt. A failure the user does not hear is a failure they
    will act as though never happened."""
    return speak(message, interrupt=True, earcon=Earcon.ERROR.value)


def answer(text: str, note_type: str | None = None) -> SpeechDirective:
    """An answer waits its turn rather than cutting off whatever is being read."""
    return speak(text, note_type=note_type, interrupt=False)
