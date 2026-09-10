"""Audio normalization - LNT Section 3.3.

The paper: "we normalize the pitch of the audio file using the pydub library ... This processing
will specifically handle certain noises caused by applauses from the audience or other outlier
noises." Figure 2 shows the raw waveform, Figure 3 the normalized one.
"""

from __future__ import annotations

from pathlib import Path


def normalize(source: Path, target_dbfs: float = -20.0) -> Path:
    """Bring the recording to a uniform loudness with pydub, writing to AUDIO_PROCESSED_DIR.

    Applies a gain of `target_dbfs - audio.dBFS`, the pydub-idiomatic normalization the paper
    refers to, then attenuates outlier peaks (applause, chair scrapes) so a single loud burst
    does not distort the silence threshold used by `chunking.split_on_silence`.
    """
    raise NotImplementedError


def strip_outlier_peaks(audio, percentile: float = 99.0):
    """Attenuate short bursts far above the running level, for example applause."""
    raise NotImplementedError
