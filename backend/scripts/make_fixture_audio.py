"""Generate the fixture recording used by DummyCaptureSource.

    python scripts/make_fixture_audio.py
    python scripts/make_fixture_audio.py --text "your sentence" --out path.wav

Prefers real synthesized speech so the dummy capture produces a genuine
transcript end to end:

  1. Windows SAPI through PowerShell - built into Windows, no dependency
  2. pyttsx3, if it happens to be installed
  3. silence, as a last resort; the pipeline still runs, the transcript is empty

Adds no dependency in any of those paths.
"""

from __future__ import annotations

import argparse
import platform
import subprocess
import sys
import wave
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_OUT = BACKEND_DIR / "data" / "fixtures" / "sample_capture.wav"

# Deliberately loaded: a to-do with a person, a deadline, a task and a second
# person, so a single dummy capture exercises every Phase 2 extractor.
DEFAULT_TEXT = (
    "Reminder to myself. I need to submit the operating systems assignment "
    "to Professor Rahman by next Friday. "
    "Also, call Sara about the database project meeting on March third. "
    "The key topic is deadlock detection and recovery."
)


def synthesize_with_sapi(text: str, out: Path) -> bool:
    """Windows SAPI via PowerShell. Returns True on success."""
    if platform.system() != "Windows":
        return False
    escaped = text.replace("'", "''")
    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$s.Rate = 0; "
        f"$s.SetOutputToWaveFile('{out}'); "
        f"$s.Speak('{escaped}'); "
        "$s.Dispose()"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"  SAPI failed: {exc}")
        return False
    if result.returncode != 0:
        print(f"  SAPI failed: {result.stderr.decode(errors='replace')[:200]}")
        return False
    return out.exists() and out.stat().st_size > 1024


def synthesize_with_pyttsx3(text: str, out: Path) -> bool:
    try:
        import pyttsx3
    except ImportError:
        return False
    engine = pyttsx3.init()
    engine.save_to_file(text, str(out))
    engine.runAndWait()
    return out.exists() and out.stat().st_size > 1024


def write_silence(out: Path, seconds: float = 3.0, sample_rate: int = 16_000) -> None:
    with wave.open(str(out), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(b"\x00\x00" * int(seconds * sample_rate))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", default=DEFAULT_TEXT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)

    print(f"writing {args.out}")
    for label, fn in (
        ("Windows SAPI", synthesize_with_sapi),
        ("pyttsx3", synthesize_with_pyttsx3),
    ):
        print(f"  trying {label} ...")
        if fn(args.text, args.out):
            with wave.open(str(args.out), "rb") as handle:
                seconds = handle.getnframes() / float(handle.getframerate())
            print(f"  done via {label}: {seconds:.1f}s, {args.out.stat().st_size} bytes")
            return 0

    print("  no speech synthesis available, writing silence")
    write_silence(args.out)
    print(f"  wrote silent fixture ({args.out.stat().st_size} bytes)")
    print("  NOTE: transcription of this fixture will be empty.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
