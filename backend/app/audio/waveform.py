"""Waveform rendering - LNT Figures 2 and 3.

Used for the paper-replication figures and for debugging normalization. Never part of the
user-facing flow: nothing in EchoNotes' UI depends on seeing a waveform.
"""

from __future__ import annotations

from pathlib import Path


def render_waveform(source: Path, out_png: Path, title: str = "") -> Path:
    """Plot amplitude against time and save a PNG."""
    raise NotImplementedError


def render_before_after(raw: Path, normalized: Path, out_png: Path) -> Path:
    """Stack the raw and normalized waveforms, reproducing Figures 2 and 3."""
    raise NotImplementedError
