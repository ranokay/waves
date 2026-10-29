"""The extraction stage seals a copied-out FLAC's signature.

TIDAL packages FLAC inside fragmented MP4. The ``-acodec copy`` extraction
keeps the audio frames bit for bit, but ffmpeg's FLAC muxer copies the
STREAMINFO from the ``dfLa`` box verbatim, so a package without a signature
yields a file that ``flac -t`` and strict players call corrupt. The engine
decodes the extracted file once and fills the header in — unless the
downsample stage or the transcode is about to re-encode it, or the item was
stopped, in which case nothing is written and nothing lands.
"""

from __future__ import annotations

import hashlib
import pathlib
import subprocess
from threading import Event
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from downloads.fakes import make_download as _make_download
from downloads.fakes import make_track as _track
from mutagen.flac import FLAC
from support.audio_fixtures import ffmpeg_path

from waves import flac_verify
from waves.constants import DownsampleTarget
from waves.download import Download, StreamInfo


@pytest.fixture
def download_instance() -> Download:
    """A Download whose only real members are the ones the extraction seal uses."""
    downloader = Download.__new__(Download)
    downloader.fn_logger = MagicMock()
    downloader.event_abort = Event()
    return downloader


def _extract_settings(**extra) -> SimpleNamespace:
    return SimpleNamespace(data=SimpleNamespace(path_binary_ffmpeg="ffmpeg", **extra))


def _ffmpeg_ok() -> MagicMock:
    ffmpeg_mock = MagicMock()
    ffmpeg_mock.option.return_value = ffmpeg_mock
    ffmpeg_mock.input.return_value = ffmpeg_mock
    ffmpeg_mock.output.return_value = ffmpeg_mock
    return ffmpeg_mock


@pytest.mark.parametrize(
    ("enabled", "rate", "depth", "sealed"),
    [
        (True, 96000, 24, False),  # both drop: the encoder writes the header
        (True, 44100, 24, False),  # depth drops only
        (True, 44100, 16, True),  # already at the target: the copy stays as is
        (False, 96000, 24, True),  # downsampling off
    ],
)
def test_extract_flac_seals_only_when_the_downsample_keeps_the_copy(
    download_instance: Download, tmp_path: pathlib.Path, enabled: bool, rate: int, depth: int, sealed: bool
) -> None:
    """A track the downsample stage re-encodes is not decoded once more for a seal."""
    download_instance.settings = _extract_settings(
        downsample_enabled=enabled, downsample_target=DownsampleTarget.BIT16_48
    )
    flac_mock = MagicMock()
    flac_mock.info.sample_rate = rate
    flac_mock.info.bits_per_sample = depth

    with (
        patch("waves.download.FFmpeg", return_value=_ffmpeg_ok()),
        patch("waves.download.FLAC", return_value=flac_mock),
        patch("waves.download.seal_file") as seal_mock,
    ):
        seal_mock.return_value = SimpleNamespace(status=flac_verify.OK, detail="")
        out = download_instance._extract_flac(tmp_path / "merged")

    assert out == tmp_path / "merged.flac"
    assert seal_mock.called is sealed


def test_extract_flac_seal_unreadable_header_still_seals(download_instance: Download, tmp_path: pathlib.Path) -> None:
    """When the header cannot be read the seal runs, which is always safe."""
    download_instance.settings = _extract_settings(downsample_enabled=True, downsample_target=DownsampleTarget.BIT16_48)
    with (
        patch("waves.download.FFmpeg", return_value=_ffmpeg_ok()),
        patch("waves.download.FLAC", side_effect=OSError("unreadable")),
        patch("waves.download.seal_file") as seal_mock,
    ):
        seal_mock.return_value = SimpleNamespace(status=flac_verify.OK, detail="")
        download_instance._extract_flac(tmp_path / "merged")

    seal_mock.assert_called_once()


def test_extract_flac_seal_follows_the_items_stop(download_instance: Download, tmp_path: pathlib.Path) -> None:
    """The seal's decode is told to stop with the item, and a stopped seal is quiet."""
    download_instance.settings = _extract_settings()
    download_instance.event_abort = Event()
    event_stop = Event()
    seen: list[bool] = []

    def seal(path, ffmpeg, *, fill_sample_count, should_continue):
        assert fill_sample_count is True
        seen.append(should_continue())
        event_stop.set()
        seen.append(should_continue())
        return SimpleNamespace(status=flac_verify.CANCELLED, detail="")

    with (
        patch("waves.download.FFmpeg", return_value=_ffmpeg_ok()),
        patch("waves.download.seal_file", side_effect=seal),
    ):
        download_instance._extract_flac(tmp_path / "merged", event_stop=event_stop)

    assert seen == [True, False]
    download_instance.fn_logger.warning.assert_not_called()
    download_instance.fn_logger.exception.assert_not_called()
    download_instance.fn_logger.info.assert_not_called()

    # The whole run's abort stops it too.
    download_instance.event_abort.set()
    calls: list[bool] = []

    def seal_abort(path, ffmpeg, *, fill_sample_count, should_continue):
        calls.append(should_continue())
        return SimpleNamespace(status=flac_verify.CANCELLED, detail="")

    with (
        patch("waves.download.FFmpeg", return_value=_ffmpeg_ok()),
        patch("waves.download.seal_file", side_effect=seal_abort),
    ):
        download_instance._extract_flac(tmp_path / "merged", event_stop=Event())
    assert calls == [False]


@pytest.mark.ffmpeg
def test_extract_flac_seals_unset_md5(download_instance: Download, tmp_path: pathlib.Path) -> None:
    """An extracted FLAC whose header came with no MD5 leaves with the real one.

    TIDAL's fragmented-MP4 packaging carries a STREAMINFO without MD5 or sample
    count, and the copy-out extraction keeps that header verbatim, so every
    extracted file failed ``flac -t``. Build that exact shape (FLAC with a zeroed
    header, packaged as DASH segments, concatenated like the segment merge does),
    run the real extraction, and check the header now matches the decoded PCM.
    """
    ffmpeg = ffmpeg_path()

    def run(*args: str) -> bytes:
        # argv is ffmpeg from PATH plus literal test arguments.
        return subprocess.run([ffmpeg, "-v", "error", *args], capture_output=True, check=True).stdout  # noqa: S603

    download_instance.settings = SimpleNamespace(data=SimpleNamespace(path_binary_ffmpeg=ffmpeg))
    src = tmp_path / "src.flac"
    run(
        "-y",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=2",
        "-ac",
        "2",
        "-ar",
        "48000",
        "-sample_fmt",
        "s32",
        "-bits_per_raw_sample",
        "24",
        "-c:a",
        "flac",
        str(src),
    )
    pcm = run("-i", str(src), "-f", "s24le", "-")
    md5_real = int.from_bytes(hashlib.md5(pcm).digest(), "big")  # noqa: S324
    assert FLAC(src).info.md5_signature == md5_real, "ffmpeg's own encoder writes a sound MD5"

    # The header TIDAL's packager ships: no signature, no sample count.
    zeroed = FLAC(src)
    zeroed.info.md5_signature = 0
    zeroed.info.total_samples = 0
    zeroed.save()
    dash = tmp_path / "dash"
    dash.mkdir()
    run("-y", "-i", str(src), "-c", "copy", "-f", "dash", "-seg_duration", "1", str(dash / "m.mpd"))
    merged = tmp_path / "merged"
    with merged.open("wb") as out:
        for part in [dash / "init-stream0.m4s", *sorted(dash.glob("chunk-stream0-*.m4s"))]:
            out.write(part.read_bytes())

    extracted = download_instance._extract_flac(merged)

    info = FLAC(extracted).info
    assert info.md5_signature == md5_real
    assert info.total_samples == len(pcm) // (3 * 2)
    assert info.bits_per_sample == 24

    # A header that already matches is left alone: a second pass writes nothing.
    download_instance.fn_logger.reset_mock()
    download_instance._flac_seal_streaminfo(extracted)
    download_instance.fn_logger.info.assert_not_called()

    # A signature that is set but wrong is damage, reported and never papered
    # over with the hash of whatever the audio now is.
    wrong = FLAC(extracted)
    wrong.info.md5_signature = md5_real ^ 1
    wrong.save()
    download_instance.fn_logger.reset_mock()
    download_instance._flac_seal_streaminfo(extracted)
    download_instance.fn_logger.warning.assert_called_once()
    assert FLAC(extracted).info.md5_signature == md5_real ^ 1


class _WritesTheOutput:
    """The minimal FFmpeg stand-in: each run writes its own output file."""

    def __init__(self, executable: str | None = None) -> None:
        self._out: pathlib.Path | None = None

    def option(self, *args: str) -> _WritesTheOutput:
        return self

    def input(self, **kwargs) -> _WritesTheOutput:
        return self

    def output(self, **kwargs) -> _WritesTheOutput:
        self._out = pathlib.Path(kwargs["url"])
        return self

    def execute(self) -> None:
        assert self._out is not None
        self._out.write_bytes(b"the extracted FLAC")


def _pipeline(tmp_path: pathlib.Path) -> Download:
    """A real pipeline whose only stubbed stage is the network download."""
    dl = _make_download(tmp_path, skip_existing=False)
    dl.settings.data.extract_flac = True
    dl.settings.data.path_binary_ffmpeg = "ffmpeg"
    dl.settings.data.downsample_enabled = False
    dl._handle_metadata_and_extras = lambda *args, **kwargs: None

    def download(media, stream_info, path_file, event_stop=None):
        path_file.write_bytes(b"raw stream bytes")
        return True, path_file

    dl._download = download
    return dl


def _run_pipeline(dl: Download, tmp_path: pathlib.Path, event_stop: Event | None = None) -> tuple[bool, pathlib.Path]:
    return dl._perform_actual_download(
        media=_track("42"),
        path_media_dst=tmp_path / "Song.flac",
        stream_info=StreamInfo(codecs="flac", requires_flac_extraction=True, single_file=True),
        is_parent_album=False,
        event_stop=event_stop,
    )


def test_a_stop_during_the_seal_leaves_the_item_unlanded(tmp_path: pathlib.Path) -> None:
    """The unsealed file must not land: the item answers like every other stop,
    without being reported as a failure, and the destination never appears."""
    dl = _pipeline(tmp_path)
    event_stop = Event()

    def extract(path: pathlib.Path, transcode: bool = False, event_stop: Event | None = None) -> pathlib.Path:
        assert event_stop is not None
        event_stop.set()
        return path.with_suffix(".flac")

    with patch.object(Download, "_extract_flac", side_effect=extract):
        ok, landed = _run_pipeline(dl, tmp_path, event_stop)

    assert ok is False
    assert landed == tmp_path / "Song.flac"
    assert not landed.exists(), "a stopped seal leaves the item out of the library"
    dl.fn_logger.error.assert_not_called()
    dl.fn_logger.exception.assert_not_called()


def test_a_seal_failure_only_logs_and_the_item_still_lands(tmp_path: pathlib.Path) -> None:
    """Sealing is best effort: a raise is logged and the extracted file lands as is."""
    dl = _pipeline(tmp_path)

    with (
        patch("waves.download.FFmpeg", _WritesTheOutput),
        patch("waves.download.seal_file", side_effect=RuntimeError("decoder crashed")),
    ):
        ok, landed = _run_pipeline(dl, tmp_path)

    assert ok is True
    assert landed == tmp_path / "Song.flac"
    assert landed.read_bytes() == b"the extracted FLAC"
    dl.fn_logger.exception.assert_called_once()
