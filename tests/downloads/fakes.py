"""Download-job stand-ins shared by the download pipeline tests.

``make_download`` builds a ``Download`` with stubbed collaborators: a bare
magic-mock engine object, real threading events, and default path/ffmpeg
settings. ``make_track`` is the minimal media double the guard tests drive
the pipeline with.
"""

from __future__ import annotations

import pathlib
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

from waves.download import Download


def make_download(tmp_path: pathlib.Path, *, skip_existing: bool = True) -> Download:
    """A ``Download`` with stubbed collaborators and real threading events."""
    dl = Download(
        tidal_obj=MagicMock(),
        skip_existing=skip_existing,
        path_base=str(tmp_path),
        fn_logger=MagicMock(),
        progress=MagicMock(),
    )
    dl.settings = MagicMock()
    dl.settings.data.filename_illegal_replacement = ""
    dl.settings.data.filename_illegal_map = None
    dl.settings.data.extract_flac = False
    dl.settings.data.downsample_enabled = False
    dl.settings.data.video_convert_mp4 = False
    dl.settings.data.path_binary_ffmpeg = ""
    dl.event_abort = threading.Event()
    dl.event_run = threading.Event()
    dl.event_run.set()

    return dl


def make_track(item_id: str):
    """The minimal media double the guard tests drive the pipeline with."""
    return SimpleNamespace(id=item_id, name="Song", artist=SimpleNamespace(name="Artist"), artists=[], duration=200)
