"""Generated audio fixtures for the tag, path and conversion tests.

``tone`` writes a short sine wave in the requested codec with ffmpeg; tests
that need real bytes carry the ``ffmpeg`` marker so the suite skips where the
binary is absent, and the GUI/ffmpeg group runs them where it matters.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def ffmpeg_path() -> str:
    """The ffmpeg binary; only call under the ffmpeg marker."""
    path = shutil.which("ffmpeg")
    assert path is not None, "ffmpeg is missing despite the ffmpeg marker"
    return path


def tone(path: str | Path, codec: str = "aac", *, duration: str = "1") -> Path:
    """Write a 440 Hz sine wave at ``path`` as ``codec``; return the path."""
    subprocess.run(  # noqa: S603 (fixed argv: a local tone fixture, no user input)
        [
            ffmpeg_path(),
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={duration}",
            "-c:a",
            codec,
            str(path),
        ],
        check=True,
    )
    return Path(path)
