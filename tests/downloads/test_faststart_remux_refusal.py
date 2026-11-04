"""A refused remux swap keeps the merged file and lands the track.

WHAT THIS FENCES OFF
--------------------
``_faststart_remux`` writes a sibling faststart container and swaps it over the
merged raw file. That swap used to be one bare ``os.replace`` outside the
FFmpeg-failure guard, so a transient refusal (a Windows scanner lock, a sharing
violation, a read-only folder) raised out of the method. The caller runs in a
temporary directory that is cleaned on the way out, so the only complete
download was deleted and the track landed as failed even though a playable file
existed. The swap now rides the shared ``_retry_file_operation`` budget: a
refusal that outlasts it keeps the raw bytes, removes the sibling, reports the
refusal and returns the input path. A brief refusal still lands the remuxed
file.
"""

from __future__ import annotations

import os
import pathlib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from tidalapi.media import Track

from waves.download import Download, StreamInfo

_ORIGINAL_BYTES = b"original merged fragmented-mp4 bytes"
_REMUXED_BYTES = b"remuxed non-fragmented-mp4 bytes"


def _downloader() -> Download:
    """A Download stand-in carrying only what the remux and its retries read."""
    dl = Download.__new__(Download)
    dl.fn_logger = MagicMock()
    dl.settings = SimpleNamespace(data=SimpleNamespace(path_binary_ffmpeg="ffmpeg"))
    dl._FILE_OPERATION_RETRIES = 3
    dl._FILE_OPERATION_RETRY_DELAY_SEC = 0
    return dl


def _ffmpeg_writing(payload: bytes, failure: Exception | None = None) -> MagicMock:
    """An FFmpeg stand-in that writes ``payload`` to the requested output.

    ``execute`` reads the output URL from the recorded ``output`` call, so the
    sibling under test is a real file with real bytes. With ``failure`` it
    writes the payload first (a partial output) and raises that failure.
    """
    ffmpeg = MagicMock()
    ffmpeg.option.return_value = ffmpeg
    ffmpeg.input.return_value = ffmpeg
    ffmpeg.output.return_value = ffmpeg

    def execute() -> None:
        path_out = pathlib.Path(ffmpeg.output.call_args.kwargs["url"])
        path_out.write_bytes(payload)
        if failure is not None:
            raise failure

    ffmpeg.execute.side_effect = execute
    return ffmpeg


def _sibling(path_file: pathlib.Path, container_ext: str = ".m4a") -> pathlib.Path:
    return path_file.with_name(f"{path_file.stem}.faststart{container_ext}")


def _merged(tmp_path: pathlib.Path) -> pathlib.Path:
    path_file = tmp_path / "merged"
    path_file.write_bytes(_ORIGINAL_BYTES)
    return path_file


def _refuse_replace(*_args) -> None:
    raise PermissionError(1, "Operation not permitted")


def test_a_refused_replacement_keeps_the_merged_file(tmp_path: pathlib.Path) -> None:
    """Every refused attempt: no raise, input bytes intact, no sibling, bounded."""
    dl = _downloader()
    path_file = _merged(tmp_path)
    ffmpeg = _ffmpeg_writing(_REMUXED_BYTES)
    attempts: list[tuple] = []

    def refuse_swap(source, destination) -> None:
        attempts.append((source, destination))
        raise PermissionError(1, "Operation not permitted")

    with (
        patch("waves.download.FFmpeg", return_value=ffmpeg),
        patch("waves.download.os.replace", side_effect=refuse_swap),
        patch("waves.download.time.sleep") as sleep_mock,
    ):
        result = dl._faststart_remux(path_file, ".m4a")

    assert result == path_file
    assert path_file.read_bytes() == _ORIGINAL_BYTES
    assert not _sibling(path_file).exists()
    assert len(attempts) == dl._FILE_OPERATION_RETRIES
    assert sleep_mock.call_count == dl._FILE_OPERATION_RETRIES - 1
    warning = str(dl.fn_logger.warning.call_args_list)
    assert "raw" in warning
    assert dl.fn_logger.error.called


def test_a_transient_refusal_lands_the_remuxed_file(tmp_path: pathlib.Path) -> None:
    """One refusal then acceptance: the remuxed bytes land, no sibling remains."""
    dl = _downloader()
    path_file = _merged(tmp_path)
    ffmpeg = _ffmpeg_writing(_REMUXED_BYTES)
    replace_original = os.replace
    attempts: list[int] = []

    def refuse_once(source, destination) -> None:
        attempts.append(1)
        if len(attempts) == 1:
            raise PermissionError(1, "Operation not permitted")
        replace_original(source, destination)

    with (
        patch("waves.download.FFmpeg", return_value=ffmpeg),
        patch("waves.download.os.replace", side_effect=refuse_once),
        patch("waves.download.time.sleep") as sleep_mock,
    ):
        result = dl._faststart_remux(path_file, ".m4a")

    assert result == path_file
    assert path_file.read_bytes() == _REMUXED_BYTES
    assert not _sibling(path_file).exists()
    assert len(attempts) == 2
    assert sleep_mock.call_count == 1


def test_an_ffmpeg_failure_keeps_the_merged_file(tmp_path: pathlib.Path) -> None:
    """The existing guarantee: an FFmpeg failure drops the partial and keeps the raw."""
    dl = _downloader()
    path_file = _merged(tmp_path)
    ffmpeg = _ffmpeg_writing(b"partial bytes", failure=RuntimeError("ffmpeg failed"))

    with patch("waves.download.FFmpeg", return_value=ffmpeg):
        result = dl._faststart_remux(path_file, ".m4a")

    assert result == path_file
    assert path_file.read_bytes() == _ORIGINAL_BYTES
    assert not _sibling(path_file).exists()


def test_a_refused_sibling_cleanup_does_not_raise(tmp_path: pathlib.Path) -> None:
    """A refused swap whose sibling cleanup is also refused still keeps the raw file."""
    dl = _downloader()
    dl._FILE_OPERATION_RETRIES = 2
    path_file = _merged(tmp_path)
    ffmpeg = _ffmpeg_writing(_REMUXED_BYTES)

    def refuse_unlink(_self, missing_ok=False) -> None:
        raise PermissionError(1, "Operation not permitted")

    with (
        patch("waves.download.FFmpeg", return_value=ffmpeg),
        patch("waves.download.os.replace", side_effect=_refuse_replace),
        patch("waves.download.time.sleep"),
        patch.object(pathlib.Path, "unlink", refuse_unlink),
    ):
        result = dl._faststart_remux(path_file, ".m4a")

    assert result == path_file
    assert path_file.read_bytes() == _ORIGINAL_BYTES


def _track() -> Track:
    track = Track.__new__(Track)
    track.id = 718
    track.audio_modes = ["STEREO"]
    track.artists = []
    track.name = "Refused Swap"
    track.version = None
    return track


def _pipeline_download(path_base: pathlib.Path) -> Download:
    dl = Download(
        tidal_obj=MagicMock(),
        skip_existing=True,
        path_base=str(path_base),
        fn_logger=MagicMock(),
        progress=MagicMock(),
    )
    dl.settings = SimpleNamespace(
        data=SimpleNamespace(
            path_binary_ffmpeg="ffmpeg",
            extract_flac=False,
            downsample_enabled=False,
            video_convert_mp4=False,
        )
    )
    return dl


def test_a_refused_replacement_lands_the_track(tmp_path: pathlib.Path) -> None:
    """The caller returns success with the raw file, not a failed track.

    Drives the real ``_perform_actual_download`` through the remux step at
    ``waves/download.py:2953``; only the provider fetch, tagging and move are
    faked, so a raise here is the failure the issue reports.
    """
    dl = _pipeline_download(tmp_path)
    path_dst = tmp_path / "Refused Swap.m4a"
    ffmpeg = _ffmpeg_writing(_REMUXED_BYTES)
    stream_info = StreamInfo(file_extension=".m4a", delivered={"audio_type": "stereo"})

    def fetch(media, stream_info, path_file, event_stop):
        path_file.write_bytes(_ORIGINAL_BYTES)
        return True, path_file

    with (
        patch.object(Download, "_download", side_effect=fetch),
        patch.object(Download, "_handle_metadata_and_extras", return_value=None),
        patch.object(Download, "_move_file", return_value=True),
        patch.object(Download, "_record_name_written"),
        patch("waves.download.name_builder_item", return_value="Refused Swap"),
        patch("waves.download.FFmpeg", return_value=ffmpeg),
        patch("waves.download.os.replace", side_effect=_refuse_replace),
        patch("waves.download.time.sleep"),
    ):
        ok, landed = dl._perform_actual_download(_track(), path_dst, stream_info, False, None)

    assert ok is True
    assert landed == path_dst
    assert dl.fn_logger.warning.called
