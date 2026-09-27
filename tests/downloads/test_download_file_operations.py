import pathlib
from threading import Lock
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from waves.constants import DownsampleTarget
from waves.download import Download


@pytest.fixture
def download_instance() -> Download:
    """Create a Download instance for file operation tests.

    Returns:
        Download: Configured download instance.
    """
    downloader = Download.__new__(Download)
    downloader.fn_logger = MagicMock()
    downloader._FILE_OPERATION_RETRIES = 2
    downloader._FILE_OPERATION_RETRY_DELAY_SEC = 0
    downloader._dirs_ensured = set()
    # The in-flight name claims every destination goes through, whether or
    # not skipping is on, and the names this run has already written (see
    # _perform_actual_download).
    downloader._names_reserved = {}
    downloader._names_written = {}
    downloader._names_reserved_lock = Lock()

    return downloader


def test_move_file_retries_transient_replace_failure(download_instance: Download, tmp_path: pathlib.Path) -> None:
    """Verify overwrite moves are retried when the destination is temporarily locked.

    Args:
        download_instance (Download): Download instance under test.
        tmp_path (pathlib.Path): Temporary test directory.
    """
    source_path: pathlib.Path = tmp_path / "source.flac"
    destination_path: pathlib.Path = tmp_path / "destination.flac"
    source_path.write_text("new", encoding="utf-8")
    destination_path.write_text("old", encoding="utf-8")

    replace_original = pathlib.Path.replace
    replace_calls: int = 0

    def replace_once_locked(self: pathlib.Path, target: pathlib.Path) -> pathlib.Path:
        nonlocal replace_calls
        replace_calls += 1
        if replace_calls == 1:
            raise PermissionError(32, "The process cannot access the file because it is being used by another process")
        return replace_original(self, target)

    with patch.object(pathlib.Path, "replace", replace_once_locked):
        result: bool = download_instance._move_file(source_path, destination_path, overwrite=True)

    assert result is True
    assert destination_path.read_text(encoding="utf-8") == "new"
    assert not source_path.exists()
    assert replace_calls == 2


def test_move_file_skip_existing_keeps_destination(download_instance: Download, tmp_path: pathlib.Path) -> None:
    """Verify shared album extras are skipped when another track already wrote them.

    Args:
        download_instance (Download): Download instance under test.
        tmp_path (pathlib.Path): Temporary test directory.
    """
    source_path: pathlib.Path = tmp_path / "cover-source.jpg"
    destination_path: pathlib.Path = tmp_path / "cover.jpg"
    source_path.write_bytes(b"new-cover")
    destination_path.write_bytes(b"existing-cover")

    result: bool = download_instance._move_file(
        source_path,
        destination_path,
        overwrite=False,
        skip_if_exists=True,
    )

    assert result is True
    assert destination_path.read_bytes() == b"existing-cover"
    assert not source_path.exists()


def test_retry_file_operation_does_not_sleep_after_final_attempt(download_instance: Download) -> None:
    """Verify file operation retries do not delay after the final failed attempt.

    Args:
        download_instance (Download): Download instance under test.
    """

    def operation() -> bool:
        raise PermissionError(32, "The process cannot access the file because it is being used by another process")

    with patch("waves.download.time.sleep") as sleep_mock:
        result: bool = download_instance._retry_file_operation(operation, "locked operation")

    assert result is False
    assert sleep_mock.call_count == 1


def test_media_move_and_symlink_skips_symlink_when_unlink_fails(
    download_instance: Download,
    tmp_path: pathlib.Path,
) -> None:
    """Verify symlink creation is skipped when the original source cannot be removed.

    Args:
        download_instance (Download): Download instance under test.
        tmp_path (pathlib.Path): Temporary test directory.
    """
    source_path: pathlib.Path = tmp_path / "source.flac"
    source_path.write_text("audio", encoding="utf-8")

    download_instance.path_base = str(tmp_path / "library")
    download_instance.skip_existing = False
    download_instance.settings = SimpleNamespace(
        data=SimpleNamespace(
            filename_delimiter_artist=", ",
            filename_delimiter_album_artist=", ",
            format_track="Tracks/{artist_name} - {track_title}",
            use_primary_album_artist=False,
        ),
    )

    media = MagicMock()
    media.id = 111
    media.waves_identity_id = None
    # The plain download path records the fresh file under its id before
    # post-processing; the symlink step refuses a source without that evidence.
    download_instance._record_name_written(source_path, "111")

    with (
        patch("waves.download.format_path_media", return_value="Tracks/Artist - Title"),
        patch.object(download_instance, "_move_file", return_value=True),
        patch.object(download_instance, "_unlink_with_retry", return_value=False),
        patch.object(pathlib.Path, "symlink_to") as symlink_to_mock,
    ):
        result_path: pathlib.Path = download_instance.media_move_and_symlink(
            media,
            source_path,
            ".flac",
        )

    assert result_path == tmp_path / "library" / "Tracks" / "Artist - Title.flac"
    symlink_to_mock.assert_not_called()
    download_instance.fn_logger.error.assert_called_once()


def test_downsample_audio_raises_when_output_move_fails(
    download_instance: Download,
    tmp_path: pathlib.Path,
) -> None:
    """Verify downsample replacement failures are propagated.

    Args:
        download_instance (Download): Download instance under test.
        tmp_path (pathlib.Path): Temporary test directory.
    """
    source_path: pathlib.Path = tmp_path / "source.flac"
    source_path.write_text("audio", encoding="utf-8")
    download_instance.settings = SimpleNamespace(
        data=SimpleNamespace(
            downsample_target=DownsampleTarget.BIT16_48,
            path_binary_ffmpeg="ffmpeg",
        ),
    )
    flac_mock: MagicMock = MagicMock()
    flac_mock.info.sample_rate = 96000
    flac_mock.info.bits_per_sample = 24
    ffmpeg_mock: MagicMock = MagicMock()
    ffmpeg_mock.option.return_value = ffmpeg_mock
    ffmpeg_mock.input.return_value = ffmpeg_mock
    ffmpeg_mock.output.return_value = ffmpeg_mock

    with (
        patch("waves.download.FLAC", return_value=flac_mock),
        patch("waves.download.FFmpeg", return_value=ffmpeg_mock),
        patch.object(download_instance, "_move_file", return_value=False),
        pytest.raises(OSError),
    ):
        download_instance._downsample_audio(source_path)


def test_move_file_fresh_destination_is_atomic_and_clean(
    download_instance: Download,
    tmp_path: pathlib.Path,
) -> None:
    """Verify a fresh move places the complete file and leaves no temp artifacts.

    Args:
        download_instance (Download): Download instance under test.
        tmp_path (pathlib.Path): Temporary test directory.
    """
    source_path: pathlib.Path = tmp_path / "source.flac"
    destination_path: pathlib.Path = tmp_path / "dest.flac"
    source_path.write_bytes(b"audio-data")

    result: bool = download_instance._move_file(source_path, destination_path, overwrite=True)

    assert result is True
    assert destination_path.read_bytes() == b"audio-data"
    assert not source_path.exists()
    assert list(tmp_path.glob(".*.tmp")) == []


def test_move_file_cross_filesystem_completes_via_staged_copy(
    download_instance: Download,
    tmp_path: pathlib.Path,
) -> None:
    """Verify a fresh move still completes when a same-filesystem rename is impossible.

    Args:
        download_instance (Download): Download instance under test.
        tmp_path (pathlib.Path): Temporary test directory.
    """
    source_path: pathlib.Path = tmp_path / "source.flac"
    destination_path: pathlib.Path = tmp_path / "dest.flac"
    source_path.write_bytes(b"hi-res")

    replace_original = pathlib.Path.replace

    def replace_no_cross_device(self: pathlib.Path, target: pathlib.Path) -> pathlib.Path:
        # Force the direct source -> destination rename to fail like a cross-device
        # move, but allow the temp-sibling -> destination swap (same filesystem).
        if self == source_path:
            raise OSError("Invalid cross-device link")
        return replace_original(self, target)

    with patch.object(pathlib.Path, "replace", replace_no_cross_device):
        result: bool = download_instance._move_file(source_path, destination_path, overwrite=True)

    assert result is True
    assert destination_path.read_bytes() == b"hi-res"
    assert not source_path.exists()
    assert list(tmp_path.glob(".*.tmp")) == []


def test_move_file_interrupted_cross_filesystem_copy_leaves_no_partial(
    download_instance: Download,
    tmp_path: pathlib.Path,
) -> None:
    """Verify a crash mid-copy never leaves a half-written file under the real name.

    This is the guarantee that stops an interrupted download from blocking its own
    re-download: the destination must not exist, the source must survive for the
    retry, and the staged temp file must be cleaned up.

    Args:
        download_instance (Download): Download instance under test.
        tmp_path (pathlib.Path): Temporary test directory.
    """
    source_path: pathlib.Path = tmp_path / "source.flac"
    destination_path: pathlib.Path = tmp_path / "dest.flac"
    source_path.write_bytes(b"hi-res-audio")

    replace_original = pathlib.Path.replace

    def replace_no_cross_device(self: pathlib.Path, target: pathlib.Path) -> pathlib.Path:
        if self == source_path:
            raise OSError("Invalid cross-device link")
        return replace_original(self, target)

    def copy_crash(src: pathlib.Path, dst: pathlib.Path) -> None:
        # Write a partial temp file, then simulate a crash / power loss mid-copy.
        dst.write_bytes(b"hi-r")
        raise OSError("simulated interruption during copy")

    with (
        patch.object(pathlib.Path, "replace", replace_no_cross_device),
        patch.object(download_instance, "_copy_file_contents", copy_crash),
    ):
        result: bool = download_instance._move_file(source_path, destination_path, overwrite=True)

    assert result is False
    assert not destination_path.exists()
    assert source_path.read_bytes() == b"hi-res-audio"
    assert list(tmp_path.glob(".*.tmp")) == []


class TestSourceIsThisItem:
    """The playlist-folder file is replaced only on positive evidence it is this item."""

    def _media(self, item_id="42"):
        from types import SimpleNamespace

        return SimpleNamespace(id=item_id)

    def test_a_symlink_is_always_this_step_s_own(self, download_instance, tmp_path):
        link = tmp_path / "link.flac"
        target = tmp_path / "real.flac"
        target.write_bytes(b"x")
        link.symlink_to(target)
        assert download_instance._source_is_this_item(link, self._media()) is True

    def test_a_missing_source_has_nothing_to_protect(self, download_instance, tmp_path):
        assert download_instance._source_is_this_item(tmp_path / "gone.flac", self._media()) is True

    def test_a_file_this_run_wrote_counts(self, download_instance, tmp_path):
        src = tmp_path / "src.flac"
        src.write_bytes(b"x")
        download_instance._names_written[str(src)] = "42"
        assert download_instance._source_is_this_item(src, self._media("42")) is True

    def test_a_stranger_s_file_does_not_count(self, download_instance, tmp_path):
        from unittest.mock import patch as _patch

        src = tmp_path / "src.flac"
        src.write_bytes(b"x")
        with _patch("waves.download.read_item_id", return_value="99"):
            assert download_instance._source_is_this_item(src, self._media("42")) is False

    def test_an_untagged_file_is_never_evidence_for_a_deletion(self, download_instance, tmp_path):
        from unittest.mock import patch as _patch

        src = tmp_path / "src.flac"
        src.write_bytes(b"x")
        with _patch("waves.download.read_item_id", return_value=""):
            assert download_instance._source_is_this_item(src, self._media("42")) is False

    def test_an_unreadable_occupant_is_not_this_item(self, download_instance, tmp_path):
        from unittest.mock import patch as _patch

        src = tmp_path / "src.flac"
        src.write_bytes(b"x")
        with _patch("waves.download.read_item_id", side_effect=OSError("gone")):
            assert download_instance._source_is_this_item(src, self._media("42")) is False


class TestSymlinkFallbackCopy:
    """Where links are refused, the playlist folder keeps a real copy."""

    def test_a_refused_symlink_falls_back_to_a_copy(self, download_instance, tmp_path):
        from types import SimpleNamespace

        src_dir = tmp_path / "playlist"
        src_dir.mkdir()
        src = src_dir / "song.flac"
        src.write_bytes(b"audio")
        download_instance.path_base = str(tmp_path)
        download_instance.skip_existing = False
        download_instance.settings = MagicMock()
        download_instance._note_dir_filled = MagicMock()
        download_instance.fn_logger = MagicMock()
        media = SimpleNamespace(id="42", name="Song", artists=[], full_name=None)

        def refuse(self, target):
            raise OSError("symlink privilege missing")

        with (
            patch("waves.download.format_path_media", return_value="track/song"),
            patch.object(pathlib.Path, "symlink_to", refuse),
            patch("waves.download.read_item_id", return_value="42"),
            patch("waves.download._waves_item_id", return_value="42"),
            patch("waves.download._waves_owned_ids", return_value={"42"}),
        ):
            out = download_instance.media_move_and_symlink(media, src, ".flac")

        assert out == tmp_path / "track" / "song.flac"
        assert src.read_bytes() == b"audio", "the playlist folder keeps a real copy, not an empty name"
        assert download_instance._note_dir_filled.called

    def test_a_stranger_s_file_is_left_where_it_is(self, download_instance, tmp_path):
        from types import SimpleNamespace

        src_dir = tmp_path / "playlist"
        src_dir.mkdir()
        src = src_dir / "song.flac"
        src.write_bytes(b"someone else's file")
        download_instance.path_base = str(tmp_path)
        download_instance.skip_existing = False
        download_instance.settings = MagicMock()
        download_instance.fn_logger = MagicMock()
        media = SimpleNamespace(id="42", name="Song", artists=[], full_name=None)

        with (
            patch("waves.download.format_path_media", return_value="track/song"),
            patch("waves.download.read_item_id", return_value="99"),
            patch("waves.download._waves_item_id", return_value="42"),
            patch("waves.download._waves_owned_ids", return_value={"42"}),
        ):
            out = download_instance.media_move_and_symlink(media, src, ".flac")

        assert out == src
        assert src.read_bytes() == b"someone else's file"


class TestTmpWriteMode:
    """The open mode decides the encoding, never the content type."""

    def test_a_str_for_a_binary_mode_is_encoded(self, download_instance, tmp_path):
        out = download_instance.write_to_tmp_file(tmp_path, mode="xb", content="lyrics text")
        assert out != ""
        assert pathlib.Path(out).read_bytes() == b"lyrics text"
