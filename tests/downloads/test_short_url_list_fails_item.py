"""A manifest-proven short URL list is a fetch failure, not a done item.

``overgenerated_tail_urls`` (``waves/providers/tidal_manifest.py``) returns a
NEGATIVE count when tidalapi emitted fewer segment URLs than the DASH timeline
requires: the list itself is missing audio, whatever the URLs that do exist do.
Reading only ``n_tail_spurious > 0`` as harmless made that case byte-identical
to ``0``/``None``, so a short list whose URLs all downloaded merged, tagged and
moved into a "done" file missing its tail.

The item's fetch verdict is where this must fail: before the segment fan-out,
no file written, the caller's ordinary ``(False, path)``.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from tidalapi import Track

from waves.download import Download
from waves.model.downloader import DownloadSegmentResult
from waves.providers.base import StreamInfo


def _download() -> Download:
    dl = Download(
        tidal_obj=MagicMock(),
        skip_existing=False,
        path_base="./tmp",
        fn_logger=MagicMock(),
        progress=MagicMock(),
    )
    dl.settings = MagicMock()
    dl.settings.data.downloads_simultaneous_per_track_max = 1
    dl.event_abort = threading.Event()
    dl.event_run = threading.Event()
    dl.event_run.set()
    return dl


def _track() -> Track:
    track = Track.__new__(Track)
    track.artists = [SimpleNamespace(name="Aphex Twin")]
    track.name = "Xtal"
    return track


def test_proven_short_url_list_fails_the_item_and_writes_nothing(tmp_path):
    dl = _download()
    dst = tmp_path / "track.m4a"
    stream_info = StreamInfo(urls=["seg-0", "seg-1"], tail_spurious=-1)
    fetched: list[str] = []

    def fake_segment(url, path_base, block_size, task_id, to_stdout, event_stop):
        # Would succeed for every URL: the old bug wrote a file from exactly
        # this. The short list must fail before any of them is fetched.
        fetched.append(url)
        segment = path_base / f"seg-{len(fetched)}"
        segment.write_bytes(b"audio")
        return DownloadSegmentResult(result=True, url=url, path_segment=segment, id_segment=len(fetched) - 1)

    with patch.object(dl, "_download_segment", side_effect=fake_segment):
        ok, path = dl._download(_track(), dst, stream_info, None)

    assert ok is False
    assert path == dst
    assert fetched == []
    assert not dst.exists()
