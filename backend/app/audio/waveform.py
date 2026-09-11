"""Waveform plots — LNT framework, Figures 2 and 3.

The paper illustrates normalisation with a before/after pair: Figure 2 is the
raw input waveform, Figure 3 the normalised one. These render that pair.

Diagnostics only. Nothing in the capture pipeline calls this, and nothing the
user sees depends on it — EchoNotes' users are blind or low vision, so a picture
of a waveform is for the report and for debugging a recording that chunked
badly, not for the interface.

`matplotlib` is imported lazily so it stays an optional dependency.
"""

from __future__ import annotations

import logging
import wave
from pathlib import Path

logger = logging.getLogger(__name__)


def _read_samples(path: Path):
    """Mono float samples in [-1, 1], and the sample rate."""
    import numpy as np

    with wave.open(str(path), "rb") as handle:
        frames = handle.readframes(handle.getnframes())
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        rate = handle.getframerate()

    dtype = {1: np.int8, 2: np.int16, 4: np.int32}.get(width)
    if dtype is None:
        raise ValueError(f"unsupported sample width: {width} bytes")

    samples = np.frombuffer(frames, dtype=dtype).astype(np.float32)
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)

    peak = float(np.iinfo(dtype).max)
    return samples / peak, rate


def render_waveform(source: Path, out_png: Path, title: str = "") -> Path:
    """Plot one recording's amplitude against time."""
    import matplotlib

    matplotlib.use("Agg")  # no display on a server
    import matplotlib.pyplot as plt
    import numpy as np

    samples, rate = _read_samples(Path(source))
    time = np.arange(len(samples)) / float(rate)

    figure, axes = plt.subplots(figsize=(10, 3))
    axes.plot(time, samples, linewidth=0.4)
    axes.set_xlabel("Time (s)")
    axes.set_ylabel("Amplitude")
    axes.set_title(title or Path(source).name)
    axes.set_ylim(-1, 1)
    figure.tight_layout()

    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(out_png, dpi=120)
    plt.close(figure)
    return out_png


def render_before_after(raw: Path, normalized: Path, out_png: Path) -> Path:
    """Stack the raw and normalised waveforms — the paper's Figures 2 and 3."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    figure, axes = plt.subplots(2, 1, figsize=(10, 5), sharex=True)
    panels = [(raw, "Figure 2: input audio"), (normalized, "Figure 3: normalised audio")]
    for panel, (path, label) in zip(axes, panels, strict=True):
        samples, rate = _read_samples(Path(path))
        panel.plot(np.arange(len(samples)) / float(rate), samples, linewidth=0.4)
        panel.set_title(label, fontsize=10)
        panel.set_ylabel("Amplitude")
        panel.set_ylim(-1, 1)

    axes[-1].set_xlabel("Time (s)")
    figure.tight_layout()

    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(out_png, dpi=120)
    plt.close(figure)
    return out_png
