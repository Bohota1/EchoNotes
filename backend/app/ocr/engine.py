"""OCR - EchoNotes Feature 7.

Captures handwritten or printed notes through the camera and converts them to text. The output
joins the main pipeline at the **Understand** stage, so an OCR note is classified, filed,
summarized, indexed and announced exactly like a spoken one.

Photographing a page without being able to see it is hard, so `assess_capture` exists to give
spoken guidance - "too dark", "hold steadier", "move back" - before the OCR runs. Without that,
the user only learns the photo was unusable after waiting for a failed result.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def preprocess_image(source: Path) -> Path:
    """Deskew, greyscale, denoise and threshold before recognition."""
    raise NotImplementedError


def assess_capture(source: Path) -> dict[str, Any]:
    """Return {"usable": bool, "spoken_guidance": str} - blur, exposure, framing, text coverage."""
    raise NotImplementedError


def extract_text(source: Path) -> str:
    """Run the configured OCR engine and return raw text."""
    raise NotImplementedError
