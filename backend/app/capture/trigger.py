"""Capture trigger - EchoNotes Feature 1, the "hardware trigger".

The trigger is abstracted so the spacebar used today can be swapped for a physical button later
without touching the pipeline.

Active trigger for this build: **spacebar push-to-talk**, handled in the browser
(`frontend/src/components/Capture/SpacebarTrigger.tsx`). The rules that stop the spacebar from
stealing screen-reader and button activation are specified in `docs/accessibility.md`.

`SystemHotkeyTrigger` exists for capturing while EchoNotes is not the focused window.
"""

from __future__ import annotations

import abc
from collections.abc import Callable
from enum import Enum


class TriggerEvent(str, Enum):
    PRESS = "press"      # start recording
    RELEASE = "release"  # stop recording and run the pipeline
    CANCEL = "cancel"    # discard the recording (Escape)


class TriggerSource(abc.ABC):
    """Something that can say "start recording now" and "stop"."""

    @abc.abstractmethod
    def start(self, on_event: Callable[[TriggerEvent], None]) -> None: ...

    @abc.abstractmethod
    def stop(self) -> None: ...


class BrowserSpacebarTrigger(TriggerSource):
    """No-op on the server: the browser owns the key events and uploads the finished audio.

    Present so the trigger type is uniform across deployments.
    """

    def start(self, on_event): ...

    def stop(self): ...


class SystemHotkeyTrigger(TriggerSource):
    """Global OS-level hotkey, for capturing while another window has focus."""

    def start(self, on_event):
        raise NotImplementedError

    def stop(self):
        raise NotImplementedError


class GPIOTrigger(TriggerSource):
    """Physical button on a Raspberry Pi or microcontroller. Placeholder for later hardware."""

    def start(self, on_event):
        raise NotImplementedError

    def stop(self):
        raise NotImplementedError


def get_trigger(kind: str) -> TriggerSource:
    return {
        "spacebar": BrowserSpacebarTrigger,
        "hotkey": SystemHotkeyTrigger,
        "gpio": GPIOTrigger,
    }[kind]()
