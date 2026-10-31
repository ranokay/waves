"""A download runs the FFmpeg the Settings status card names.

A GUI launch gets a bare PATH, so the download's own fallback must use the
same package-manager discovery as the card instead of ``shutil.which`` alone.
"""

from __future__ import annotations

import stat
import sys
from unittest.mock import MagicMock

import pytest

from waves import system_ffmpeg
from waves.config import Settings
from waves.desktop.ffmpeg import manager as fm
from waves.download import Download

posix_only = pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX executable bits")
pytestmark = posix_only


def _make(folder):
    folder.mkdir(parents=True, exist_ok=True)
    exe = folder / "ffmpeg"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    return str(exe)


@pytest.fixture(autouse=True)
def _clean_probe_cache(monkeypatch):
    monkeypatch.setattr(system_ffmpeg, "_probe_cache", {})
    monkeypatch.setattr(system_ffmpeg, "_probe_slow", {})


@pytest.fixture(autouse=True)
def _isolated_ffmpeg_settings(monkeypatch):
    """Download writes the process-wide Settings singleton: restore the path
    and the three gated flags after every test."""
    data = Settings().data
    monkeypatch.setattr(data, "path_binary_ffmpeg", None)
    monkeypatch.setattr(data, "video_convert_mp4", True)
    monkeypatch.setattr(data, "extract_flac", True)
    monkeypatch.setattr(data, "extract_flac_all", True)


def test_a_download_runs_the_ffmpeg_settings_shows(tmp_path, monkeypatch):
    broken = tmp_path / "local"
    brew = tmp_path / "brew"
    good = _make(brew)
    _make(broken)
    monkeypatch.setattr(system_ffmpeg.shutil, "which", lambda name: None)
    monkeypatch.setattr(system_ffmpeg, "known_dirs", lambda: (str(broken), str(brew)))
    monkeypatch.setattr(system_ffmpeg, "probe_version", lambda path: "n8.1" if path == good else "")

    assert fm.FfmpegManager(tmp_path / "app").status()["path"] == good
    dl = Download(
        tidal_obj=MagicMock(),
        skip_existing=False,
        path_base=str(tmp_path),
        fn_logger=MagicMock(),
        progress=MagicMock(),
    )
    assert dl.settings.data.path_binary_ffmpeg == good
    assert dl.ffmpeg_missing is False


def test_a_download_stays_off_a_broken_system_binary(tmp_path, monkeypatch):
    _make(tmp_path)
    monkeypatch.setattr(system_ffmpeg.shutil, "which", lambda name: None)
    monkeypatch.setattr(system_ffmpeg, "known_dirs", lambda: (str(tmp_path),))
    monkeypatch.setattr(system_ffmpeg, "probe_version", lambda path: "")

    dl = Download(
        tidal_obj=MagicMock(),
        skip_existing=False,
        path_base=str(tmp_path),
        fn_logger=MagicMock(),
        progress=MagicMock(),
    )
    assert not dl.settings.data.path_binary_ffmpeg
    assert dl.ffmpeg_missing is True
    assert dl.settings.data.video_convert_mp4 is False
    assert dl.settings.data.extract_flac is False


def test_a_download_reader_sees_a_slow_binary_as_its_fallback_once(tmp_path, monkeypatch):
    """The build runs on the GUI thread after the resolver: its fallback reads
    the memoized slow result instead of forking the binary a second time."""
    import subprocess

    exe = _make(tmp_path)
    monkeypatch.setattr(system_ffmpeg.shutil, "which", lambda name: None)
    monkeypatch.setattr(system_ffmpeg, "known_dirs", lambda: (str(tmp_path),))
    runs = []

    def slow(argv, **kw):
        runs.append(argv)
        raise subprocess.TimeoutExpired(argv, kw.get("timeout"))

    monkeypatch.setattr(system_ffmpeg.subprocess, "run", slow)
    dl = Download(
        tidal_obj=MagicMock(),
        skip_existing=False,
        path_base=str(tmp_path),
        fn_logger=MagicMock(),
        progress=MagicMock(),
    )
    assert dl.settings.data.path_binary_ffmpeg == exe
    assert len(runs) == 1
