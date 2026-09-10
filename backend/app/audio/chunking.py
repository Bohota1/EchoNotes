"""Silence-based chunking - LNT Section 3.3.

The paper: "The audio file is chunked based on the silence or pauses into audio chunks by
specifying arguments such as threshold value (in dfbs), and minimum silence duration (in
milliseconds)."

Each chunk is recognized separately and a "." is appended after each recognized chunk, which is
how the framework recovers sentence boundaries that speech recognition does not provide. That
period is what makes the sentence tokenization in Section 3.4.5 possible, so the two behaviours
must stay in step.
"""

from __future__ import annotations

from pathlib import Path


def split_on_silence(
    source: Path,
    silence_thresh_dbfs: int = -40,
    min_silence_len_ms: int = 500,
    keep_silence_ms: int = 250,
) -> list[Path]:
    """Split a normalized recording into chunks at pauses; return the chunk paths in order."""
    raise NotImplementedError
