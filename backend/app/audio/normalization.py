"""Audio normalisation — LNT framework, Section 3.3.

The paper: *"we normalize the pitch of the audio file using the pydub library
... This processing will specifically handle certain noises caused by applauses
from the audience or other outlier noises."* Figure 2 shows the raw waveform,
Figure 3 the normalised one.

Two operations, in this order:

1. **Gain normalisation** — apply a uniform gain so the whole recording sits at
   a known loudness. This is what makes the silence threshold in
   `app.audio.chunking` mean the same thing for a quiet phone recording and a
   loud lecture hall; without it, a fixed −40 dBFS cut-off splits one recording
   into nothing and the other into hundreds of fragments.

2. **Outlier peak attenuation** — the applause handling the paper calls for.
   A burst far above the speech level drags the whole-file average up, so
   normalisation then pushes the actual speech down and the recogniser loses it.

Note the ordering matters and is the reverse of what seems natural: peaks are
measured against the *normalised* level, so normalise first, then attenuate.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.config import get_settings
from app.core.errors import AudioCaptureError

logger = logging.getLogger(__name__)


def _load(source: Path):
    from pydub import AudioSegment

    try:
        return AudioSegment.from_file(str(source))
    except Exception as exc:  # pydub raises a variety of things
        raise AudioCaptureError(f"could not read audio from {source}: {exc}") from exc


def match_target_amplitude(segment, target_dbfs: float):
    """Apply the uniform gain that brings `segment` to `target_dbfs`.

    This is the pydub-idiomatic normalisation the paper refers to. A silent
    segment has a dBFS of -inf and is returned untouched, since no finite gain
    makes silence louder.
    """
    if segment.dBFS == float("-inf"):
        return segment
    return segment.apply_gain(target_dbfs - segment.dBFS)


def attenuate_outlier_peaks(
    segment,
    window_ms: int = 100,
    tolerance_db: float = 12.0,
    reduction_db: float = 10.0,
):
    """Pull down short bursts that sit far above the speech level.

    Walks the recording in `window_ms` slices, takes the median slice loudness
    as the speech level, and attenuates any slice more than `tolerance_db`
    above it — applause, a slammed door, a chair scrape.

    The median is deliberate: a mean is dragged upward by the very bursts this
    is trying to find.
    """
    if len(segment) < window_ms * 3:
        return segment  # too short for a meaningful level estimate

    slices = [segment[i : i + window_ms] for i in range(0, len(segment), window_ms)]
    levels = [s.dBFS for s in slices if s.dBFS != float("-inf")]
    if not levels:
        return segment

    levels.sort()
    median = levels[len(levels) // 2]
    ceiling = median + tolerance_db

    rebuilt = slices[0][:0]  # empty segment with the same parameters
    attenuated = 0
    for chunk in slices:
        if chunk.dBFS != float("-inf") and chunk.dBFS > ceiling:
            chunk = chunk.apply_gain(-reduction_db)
            attenuated += 1
        rebuilt += chunk

    if attenuated:
        logger.info(
            "attenuated %d/%d slices above %.1f dBFS (median %.1f)",
            attenuated, len(slices), ceiling, median,
        )
    return rebuilt


def normalize_segment(segment, target_dbfs: float | None = None):
    """Full Section 3.3 normalisation on an in-memory segment."""
    settings = get_settings()
    target = target_dbfs if target_dbfs is not None else settings.audio_target_dbfs

    segment = match_target_amplitude(segment, target)
    segment = attenuate_outlier_peaks(segment)
    # Attenuating peaks lowers the overall level, so restore the target.
    return match_target_amplitude(segment, target)


def normalize(source: Path, target_dbfs: float | None = None) -> Path:
    """Normalise a recording and write it to AUDIO_PROCESSED_DIR.

    Returns the path of the normalised file.
    """
    settings = get_settings()
    segment = _load(source)
    before = segment.dBFS

    segment = normalize_segment(segment, target_dbfs)

    settings.audio_processed_dir.mkdir(parents=True, exist_ok=True)
    destination = settings.audio_processed_dir / f"{Path(source).stem}_normalized.wav"
    segment.export(str(destination), format="wav")

    logger.info(
        "normalised %s: %.2f -> %.2f dBFS (%s)",
        Path(source).name, before, segment.dBFS, destination.name,
    )
    return destination
