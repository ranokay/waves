"""A playlist entry listed twice lands one file.

The claim alone still steps a twin aside on disk, but the late-skip guard lands
the second entry on the first one's file while a stranger never skips.
"""

from __future__ import annotations

import pathlib
import threading
from collections import defaultdict
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from waves.download import Download, StreamInfo


def _make_download(tmp_path: pathlib.Path, *, skip_existing: bool = True) -> Download:
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


def test_the_claim_alone_still_steps_the_twin_aside_on_disk(tmp_path):
    """The control case, and the reason the guard above it has to exist: with a
    file actually on disk the claim answers "occupied" for the item's OWN copy.
    The existing claim tests never create the file, so this arm was untested."""
    dl = _make_download(tmp_path)
    dst = tmp_path / "Song.flac"
    dst.write_bytes(b"landed by the first twin")

    picked, _claim = dl._claim_destination(dst, "42")

    assert picked != dst, "if this ever passes, the claim became owner-aware and the guard can be revisited"
    assert picked.name == "Song_01.flac"


class _ReachedTheClaim(Exception):
    """Raised by the claim spy: the guard did NOT late-skip this pass."""


def _twin_run(dl: Download, dst: pathlib.Path, media) -> tuple[bool, pathlib.Path]:
    """Drive _perform_actual_download to the late-skip guard, with the network
    download stubbed to 'succeeded'.

    Returns the (ok, path) of a late skip. Raises _ReachedTheClaim when the
    guard let the pass through to _claim_destination, which is exactly the
    distinction every test below turns on: skipping onto the twin's file, or
    going on to write a second one.
    """

    def _fake_download(self, *, media, stream_info, path_file, event_stop=None, **kw):
        return True, path_file

    def _plan(self, *a, **k):
        return defaultdict(float)

    def _spy_claim(self, *a, **k):
        raise _ReachedTheClaim

    with (
        patch.object(Download, "_download", _fake_download),
        patch.object(Download, "_finalize_plan", _plan),
        patch.object(Download, "_note_stage", lambda *a, **k: None),
        patch.object(Download, "_claim_destination", _spy_claim),
    ):
        return dl._perform_actual_download(
            media=media,
            path_media_dst=dst,
            stream_info=StreamInfo(),
            is_parent_album=False,
        )


def _track(item_id: str):
    return SimpleNamespace(id=item_id, name="Song", artist=SimpleNamespace(name="Artist"), artists=[], duration=200)


def test_the_second_entry_skips_onto_the_file_the_first_one_landed(tmp_path):
    """The twin returns the landed path and writes nothing."""
    dl = _make_download(tmp_path)
    dst = tmp_path / "Song.flac"
    dst.write_bytes(b"landed by the first twin")
    media = _track("42")

    with patch("waves.download.read_item_id", lambda p: "42"):
        ok, landed = _twin_run(dl, dst, media)

    assert ok is True
    assert landed == dst, "the twin must land on the first one's file, not a numbered copy of it"
    assert not (tmp_path / "Song_01.flac").exists()


def test_a_genuinely_different_track_of_the_same_name_is_not_skipped(tmp_path):
    """The guard must not swallow a real collision: a DIFFERENT item at that
    name is a distinct track, and it still gets its own numbered file."""
    dl = _make_download(tmp_path)
    dst = tmp_path / "Song.flac"
    dst.write_bytes(b"a different track that happens to share the name")
    media = _track("42")

    with patch("waves.download.read_item_id", lambda p: "999"):
        try:
            _twin_run(dl, dst, media)
        except _ReachedTheClaim:
            pass
        else:
            raise AssertionError("a colliding stranger must not be treated as this item's own copy")


def test_a_forced_redownload_does_not_late_skip_its_own_file(tmp_path):
    """REDOWNLOAD turns skipping off for that thread, and the guard rides that
    switch: the point of the force is to overwrite the copy in place."""
    dl = _make_download(tmp_path, skip_existing=False)
    dst = tmp_path / "Song.flac"
    dst.write_bytes(b"the copy being replaced")
    media = _track("42")

    with patch("waves.download.read_item_id", lambda p: "42"):
        try:
            _twin_run(dl, dst, media)
        except _ReachedTheClaim:
            pass
        else:
            raise AssertionError("a forced redownload must reach the move, not skip itself")


def test_an_untagged_stranger_on_the_name_is_not_read_as_this_item(tmp_path):
    """An untagged stranger on the name must be stepped around, not read as
    this item: the late twin check matches ids POSITIVELY instead of reusing
    the pre-write skip check, which answers "identity unknown, treat as this
    item" before the bytes are fetched but is wrong here. Reading a stranger as
    this item makes a distinct track skip instead of uniquifying, taking its
    lyrics and cover with it."""
    dl = _make_download(tmp_path)
    dst = tmp_path / "Song.flac"
    dst.write_bytes(b"a different track, written by something that tags nothing")
    media = _track("42")

    with patch("waves.download.read_item_id", lambda p: None):
        try:
            _twin_run(dl, dst, media)
        except _ReachedTheClaim:
            pass
        else:
            raise AssertionError("an untagged stranger was treated as this item's own copy")


def test_an_empty_destination_is_never_read_as_this_item(tmp_path):
    """The other half of the same trap: a file that is not there reads as
    "identity unknown" too, and answering yes to that late-skips EVERY download
    in the run so nothing is ever written.

    Guarded twice over on purpose, and this test stays green if either guard is
    removed: the existence check refuses an absent destination outright, and the
    positive id match refuses it again because an unreadable file yields no id.
    The pair is cheap and the failure it prevents is total."""
    dl = _make_download(tmp_path)
    dst = tmp_path / "Song.flac"  # deliberately NOT created
    media = _track("42")

    with patch("waves.download.read_item_id", lambda p: None):
        try:
            _twin_run(dl, dst, media)
        except _ReachedTheClaim:
            pass
        else:
            raise AssertionError("an absent destination was treated as an already-landed copy")
