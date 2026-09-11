"""Silence-based chunking — LNT framework, Section 3.3.

The paper: *"The audio file is chunked based on the silence or pauses into audio
chunks by specifying arguments such as threshold value (in dfbs), and minimum
silence duration (in milliseconds)."*

Each chunk is then recognised separately and a `"."` is appended to each
recognised chunk. That period is not cosmetic: speech recognition returns no
sentence boundaries, so the pauses the speaker made are the *only* sentence
signal the pipeline has. Everything downstream that counts sentences —
readability, coherence, summarisation — depends on it.

Two safeguards the paper does not spell out but a real recording needs:

* **A relative threshold.** A fixed −40 dBFS cut-off assumes a known recording
  level. The threshold is taken relative to the recording's own loudness, so it
  behaves the same on a quiet phone recording and a loud hall.
* **Splitting over-long chunks.** A speaker who does not pause for two minutes
  produces one two-minute chunk, which is slow to recognise and yields one
  enormous "sentence". Anything past `max_chunk_ms` is cut on its quietest
  point.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)


def _quietest_split_point(segment, max_chunk_ms: int, window_ms: int = 200) -> int:
    """Where to cut a chunk that never went silent.

    Searches only the second half of the allowed span, so each piece comes out
    close to the cap rather than as a sliver, and picks the quietest window in
    that band — most likely a breath rather than mid-word.

    When the audio is featureless (a tone, steady noise) every window measures
    the same, so ties resolve toward the middle of the band. Taking the first
    minimum instead would cut at the very start of the band every time, which
    produced a string of 200 ms slivers that the minimum-length filter then
    discarded — silently losing audio.
    """
    lower = max(window_ms, max_chunk_ms // 2)
    upper = min(len(segment) - window_ms, max_chunk_ms)
    if upper <= lower:
        return max(window_ms, min(max_chunk_ms, len(segment) // 2))

    offsets = list(range(lower, upper, window_ms)) or [lower]
    levels = [segment[o : o + window_ms].dBFS for o in offsets]

    quietest = min(levels)
    midpoint = (lower + upper) // 2
    candidates = [
        offset
        for offset, level in zip(offsets, levels, strict=True)
        # A tolerance rather than equality: dBFS is a float, and near-identical
        # windows should all count as candidates.
        if level <= quietest + 0.5
    ]
    return min(candidates, key=lambda offset: abs(offset - midpoint))


def _enforce_max_length(segment, max_chunk_ms: int) -> list:
    """Cut a chunk down until every piece is within the cap.

    Recurses on the tail only. Splitting head and tail both ways made the
    recursion lopsided when the cut landed near one end.
    """
    pieces: list = []
    while len(segment) > max_chunk_ms:
        cut = _quietest_split_point(segment, max_chunk_ms)
        pieces.append(segment[:cut])
        segment = segment[cut:]
    pieces.append(segment)
    return pieces


def split_segment_on_silence(
    segment,
    silence_thresh_dbfs: int | None = None,
    min_silence_len_ms: int | None = None,
    keep_silence_ms: int | None = None,
    relative_threshold: bool = True,
) -> list:
    """Split an in-memory segment at pauses. Returns a list of segments."""
    from pydub.silence import split_on_silence

    settings = get_settings()
    min_silence = min_silence_len_ms or settings.min_silence_len_ms
    keep = keep_silence_ms if keep_silence_ms is not None else settings.chunk_keep_silence_ms

    if silence_thresh_dbfs is not None:
        threshold = silence_thresh_dbfs
    elif relative_threshold and segment.dBFS != float("-inf"):
        threshold = int(segment.dBFS + settings.silence_thresh_offset_db)
    else:
        threshold = settings.silence_thresh_dbfs

    chunks = split_on_silence(
        segment,
        min_silence_len=min_silence,
        silence_thresh=threshold,
        keep_silence=keep,
    )

    # A recording with no pause at all yields nothing; treat it as one chunk
    # rather than losing the audio entirely.
    if not chunks:
        logger.info("no silence found at %d dBFS; treating as a single chunk", threshold)
        chunks = [segment]

    sized: list = []
    for chunk in chunks:
        sized.extend(_enforce_max_length(chunk, settings.max_chunk_ms))

    # Drop slivers too short to contain a word.
    sized = [c for c in sized if len(c) >= settings.min_chunk_ms]

    logger.info(
        "split %dms into %d chunk(s) at %d dBFS (min silence %dms)",
        len(segment), len(sized), threshold, min_silence,
    )
    return sized or [segment]


def split_on_silence_to_files(
    source: Path,
    silence_thresh_dbfs: int | None = None,
    min_silence_len_ms: int | None = None,
    keep_silence_ms: int | None = None,
) -> list[Path]:
    """Split a recording into chunk files on disk, in order.

    Used by the LNT transcription path, which recognises each chunk separately.
    """
    from pydub import AudioSegment

    settings = get_settings()
    segment = AudioSegment.from_file(str(source))
    chunks = split_segment_on_silence(
        segment, silence_thresh_dbfs, min_silence_len_ms, keep_silence_ms
    )

    chunk_dir = settings.audio_processed_dir / f"{Path(source).stem}_chunks"
    chunk_dir.mkdir(parents=True, exist_ok=True)

    paths: list[Path] = []
    for index, chunk in enumerate(chunks):
        path = chunk_dir / f"chunk_{index:03d}.wav"
        chunk.export(str(path), format="wav")
        paths.append(path)

    return paths
