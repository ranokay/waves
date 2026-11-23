"""Staging names and path fitting around a download.

A maximal destination name still stages and swaps, a playlist symlink into a
missing directory never crashes, the sizing probe rides the pooled session and
degrades on failure, and an over-long path shortens in place instead of moving
to the home folder.
"""

from __future__ import annotations

import pathlib
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pathvalidate.error import ErrorReason, ValidationError

from waves.download import Download
from waves.paths import _shorten_to_valid_length, path_file_sanitize


def _downloader(tmp_path: pathlib.Path) -> Download:
    d = Download.__new__(Download)
    d.fn_logger = MagicMock()
    d._FILE_OPERATION_RETRIES = 2
    d._FILE_OPERATION_RETRY_DELAY_SEC = 0
    d._dirs_ensured = set()
    # The engine records the folders a run put a file into, which is what
    # decides where the m3u writer may write (_note_dir_filled).
    d._dirs_filled = set()
    d._dirs_filled_lock = threading.Lock()
    d.path_base = str(tmp_path)
    d.skip_existing = True
    d.settings = SimpleNamespace(
        data=SimpleNamespace(
            format_track="Tracks/{artist_name} - {track_title}",
            filename_delimiter_artist=", ",
            filename_delimiter_album_artist=", ",
            use_primary_album_artist=False,
            symlink_to_track=True,
        )
    )
    return d


# ---- the staging name must fit NAME_MAX even for a maximal track name -------


def test_a_maximal_destination_name_still_stages_and_swaps(tmp_path: pathlib.Path) -> None:
    d = _downloader(tmp_path)
    src = tmp_path / "src.flac"
    src.write_text("audio", encoding="utf-8")
    dst = tmp_path / ("x" * 250 + ".flac")

    assert d._stage_and_swap(src, dst, skip_if_exists=False) is True
    assert dst.read_text(encoding="utf-8") == "audio"
    assert not src.exists(), "the source is consumed on success"
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == [], "no staging file may be left behind"


# ---- a playlist symlink for an already-owned track must not crash the job ---


def test_a_symlink_into_a_missing_playlist_dir_creates_the_dir(tmp_path: pathlib.Path) -> None:
    d = _downloader(tmp_path)
    dst = tmp_path / "Tracks" / "song.flac"
    dst.parent.mkdir()
    dst.write_text("audio", encoding="utf-8")
    src = tmp_path / "Playlists" / "Road Songs" / "song.flac"  # parent never created

    with patch("waves.download.format_path_media", return_value="Tracks/song"):
        out = d.media_move_and_symlink(SimpleNamespace(), src, ".flac")

    assert out == dst
    assert src.is_symlink() and src.resolve() == dst.resolve()


def test_a_failed_symlink_is_logged_and_never_raises(tmp_path: pathlib.Path) -> None:
    d = _downloader(tmp_path)
    dst = tmp_path / "Tracks" / "song.flac"
    dst.parent.mkdir()
    dst.write_text("audio", encoding="utf-8")
    src = tmp_path / "Playlists" / "PL" / "song.flac"

    with (
        patch("waves.download.format_path_media", return_value="Tracks/song"),
        patch.object(pathlib.Path, "symlink_to", side_effect=OSError("no symlinks here")),
    ):
        out = d.media_move_and_symlink(SimpleNamespace(), src, ".flac")

    assert out == dst
    assert d.fn_logger.error.called, "the failure is diagnosable"


# ---- the sizing probe rides the pooled session and never fails the track ---


def _probe(tmp_path: pathlib.Path) -> Download:
    d = _downloader(tmp_path)
    d.progress = MagicMock()
    d.progress.add_task.return_value = 7
    return d


def test_the_sizing_probe_uses_the_pooled_session_and_follows_redirects(tmp_path: pathlib.Path) -> None:
    d = _probe(tmp_path)
    response = MagicMock()
    response.headers = {"content-length": str(4 * 1048576)}
    session = MagicMock()
    session.head.return_value = response

    with patch.object(Download, "_shared_http", return_value=session):
        p_task, total, block = d._setup_progress("Song", ["https://cdn.example/x"], False)

    assert p_task == 7 and total == 4.0 and block == 1048576
    assert session.head.call_args.kwargs.get("allow_redirects") is True


def test_a_failed_probe_degrades_to_indeterminate_progress(tmp_path: pathlib.Path) -> None:
    d = _probe(tmp_path)
    session = MagicMock()
    session.head.side_effect = OSError("blip")

    with patch.object(Download, "_shared_http", return_value=session):
        _p_task, total, block = d._setup_progress("Song", ["https://cdn.example/x"], False)

    assert total is None, "an unsizable download still downloads"
    assert block == 1048576
    assert d.fn_logger.error.called, "the blip is logged, not swallowed"


# ---- an over-long path shortens in place instead of moving to home ----------


def test_an_over_long_path_stays_inside_the_download_base(tmp_path: pathlib.Path) -> None:
    base = tmp_path / "Library"
    over_long = base / ("a" * 250) / ("b" * 250) / ("c" * 250) / ("d" * 250) / "01. Song.flac"

    result = path_file_sanitize(over_long, adapt=True)

    assert result != pathlib.Path.home() / over_long.name
    assert str(result).startswith(str(base)), "the track never leaves the library"
    assert result.name == "01. Song.flac"


def test_shortening_is_deterministic_per_album_folder(tmp_path: pathlib.Path) -> None:
    parent = tmp_path / ("a" * 250) / ("b" * 250) / ("c" * 250) / ("d" * 250)
    one = path_file_sanitize(parent / "01. One.flac", adapt=True)
    two = path_file_sanitize(parent / "02. Two.flac", adapt=True)
    assert one.parent == two.parent, "every track of the album lands in one folder"


def test_shorten_helper_halves_then_drops_components() -> None:
    def cap_20(p: pathlib.Path) -> pathlib.Path:
        if len(str(p)) > 20:
            raise ValidationError(reason=ErrorReason.INVALID_LENGTH, description="too long")
        return p

    out = _shorten_to_valid_length(pathlib.Path("/base/artistartistartist/albumalbumalbum"), cap_20)
    assert len(str(out)) <= 20
    assert str(out).startswith("/base"), "shallow components (the base) survive"
