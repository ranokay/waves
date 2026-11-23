"""Merging when the target file will not open.

The merged-file handler reports a clean failure instead of a NameError, for a
single segment and for many, and a real merge still joins the parts.
"""

from __future__ import annotations

import pathlib
import threading
from unittest.mock import MagicMock

from waves import download as download_mod
from waves.download import Download


def _make_download(tmp_path: pathlib.Path) -> Download:
    dl = Download(
        tidal_obj=MagicMock(),
        skip_existing=True,
        path_base=str(tmp_path),
        fn_logger=MagicMock(),
        progress=MagicMock(),
    )
    dl.settings = MagicMock()
    dl.event_abort = threading.Event()
    dl.event_run = threading.Event()
    dl.event_run.set()

    return dl


def test_a_target_that_will_not_open_is_a_clean_failure(tmp_path):
    """The per-item temp directory vanished between download and merge: the
    handler must report that cleanly, not read an unbound loop variable and
    replace the real error with a NameError."""
    dl = _make_download(tmp_path)
    gone = tmp_path / "not-there" / "merged.flac"
    segments = [
        download_mod.DownloadSegmentResult(True, "", tmp_path / f"seg{i}", i)
        for i in range(2)  # more than one, so the spurious-tail arm is reached
    ]

    assert dl._segments_merge(gone, segments) is False


def test_a_single_segment_target_that_will_not_open_fails_too(tmp_path):
    dl = _make_download(tmp_path)
    gone = tmp_path / "not-there" / "merged.flac"
    segments = [download_mod.DownloadSegmentResult(True, "", tmp_path / "seg0", 0)]

    assert dl._segments_merge(gone, segments) is False


def test_a_real_merge_still_works(tmp_path):
    dl = _make_download(tmp_path)
    segments = []
    for i in range(3):
        part = tmp_path / f"seg{i}"
        part.write_bytes(bytes([i]) * 4)
        segments.append(download_mod.DownloadSegmentResult(True, "", part, i))
    target = tmp_path / "merged.flac"

    assert dl._segments_merge(target, segments) is True
    assert target.read_bytes() == b"\x00" * 4 + b"\x01" * 4 + b"\x02" * 4
