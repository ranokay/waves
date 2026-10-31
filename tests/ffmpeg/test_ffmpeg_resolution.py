"""Settings, previews, the FLAC check and jobs run the same working FFmpeg.

A broken first candidate (an uninstalled Homebrew keg, a stale MacPorts
symlink) must be passed over by every reader, not only by the status card, or
Settings names one binary while every job fails on another.
"""

from __future__ import annotations

import stat
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest
from support.bridge_stub import BridgeStub

from waves import system_ffmpeg
from waves.desktop.backend import WavesBridge
from waves.desktop.ffmpeg import manager as fm
from waves.providers.apple import runner

pytestmark = pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX executable bits")


def _make(folder, executable=True):
    folder.mkdir(parents=True, exist_ok=True)
    exe = folder / "ffmpeg"
    exe.write_text("#!/bin/sh\n")
    if executable:
        exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    return str(exe)


def _bind(stub, name):
    return getattr(WavesBridge, name).__get__(stub, type(stub))


def _bridge():
    stub = BridgeStub()
    stub._settings_save_lock = threading.Lock()
    stub.settings = SimpleNamespace(data=SimpleNamespace(path_binary_ffmpeg=None, ffmpeg_source=""))
    stub._ffmpeg_user_path = ""
    stub._ffmpeg = SimpleNamespace(is_installed=lambda: False, binary_path="/managed/bin/ffmpeg")
    stub._restore_ffmpeg_flags = lambda available: None
    stub._resolve_ffmpeg = lambda: ""
    stub._user_ffmpeg_path = lambda: ""
    stub._ffmpeg_source_label = _bind(stub, "_ffmpeg_source_label")
    stub._resolve_ffmpeg_locked = _bind(stub, "_resolve_ffmpeg_locked")
    return stub


@pytest.fixture(autouse=True)
def _clean_probe_cache(monkeypatch):
    monkeypatch.setattr(system_ffmpeg, "_probe_cache", {})
    monkeypatch.setattr(system_ffmpeg, "_probe_slow", {})


def _broken_then_working(tmp_path, monkeypatch):
    broken = tmp_path / "local"
    brew = tmp_path / "brew"
    good = _make(brew)
    _make(broken)
    monkeypatch.setattr(system_ffmpeg.shutil, "which", lambda name, **_kw: None)
    monkeypatch.setattr(system_ffmpeg, "known_dirs", lambda: (str(broken), str(brew)))
    monkeypatch.setattr(system_ffmpeg, "probe_version", lambda path: "n8.1" if path == good else "")
    return good


def test_every_ffmpeg_reader_picks_the_same_working_binary(tmp_path, monkeypatch):
    good = _broken_then_working(tmp_path, monkeypatch)
    stub = _bridge()

    assert fm.FfmpegManager(tmp_path / "app").status()["path"] == good
    assert WavesBridge._resolve_ffmpeg_locked(stub) == good
    assert stub.settings.data.path_binary_ffmpeg == good
    assert WavesBridge._ffmpeg_source_label(stub) == "system"
    assert WavesBridge._preview_ffmpeg_bin(stub) == good
    assert WavesBridge._flac_check_ffmpeg(stub) == good


def test_every_reader_reports_missing_when_only_a_broken_copy_exists(tmp_path, monkeypatch):
    _broken_then_working(tmp_path, monkeypatch)
    stub = _bridge()
    monkeypatch.setattr(system_ffmpeg, "probe_version", lambda path: "")

    assert fm.FfmpegManager(tmp_path / "app").status()["state"] == "missing"
    assert WavesBridge._resolve_ffmpeg_locked(stub) == ""
    assert stub.settings.data.path_binary_ffmpeg == ""
    assert WavesBridge._ffmpeg_source_label(stub) == "none"
    assert WavesBridge._preview_ffmpeg_bin(stub) is None
    assert WavesBridge._flac_check_ffmpeg(stub) == ""


def test_the_apple_flac_fallback_runs_the_same_discovered_binary(tmp_path, monkeypatch):
    good = _broken_then_working(tmp_path, monkeypatch)
    hooks = SimpleNamespace(
        provider=lambda: SimpleNamespace(ffmpeg_path=""),
        settings=lambda: SimpleNamespace(data=SimpleNamespace(path_binary_ffmpeg="")),
    )
    assert runner.flac_ffmpeg(hooks) == good


def test_a_slow_custom_binary_stays_the_selection(tmp_path, monkeypatch):
    """A timed-out custom override must not make Settings fall through to a
    different system binary: downloads keep the user's explicit choice."""
    custom = _make(tmp_path / "custom")
    good = _make(tmp_path / "brew")
    monkeypatch.setattr(system_ffmpeg.shutil, "which", lambda name, **_kw: None)
    monkeypatch.setattr(system_ffmpeg, "known_dirs", lambda: (str(tmp_path / "brew"),))

    def run(argv, **kw):
        if argv[0] == custom:
            raise subprocess.TimeoutExpired(argv, kw.get("timeout"))
        return SimpleNamespace(returncode=0, stdout="ffmpeg version 7.1 built", stderr="")

    monkeypatch.setattr(system_ffmpeg.subprocess, "run", run)
    status = fm.FfmpegManager(tmp_path / "app").status(custom)
    assert status["path"] == custom
    assert status["custom"] is True
    assert status["version"] == ""
    assert status["path"] != good


def test_gui_readers_never_re_probe_a_slow_binary(tmp_path, monkeypatch):
    """After the first probe times out, status(), the resolver, the source
    label, preview and the FLAC check all reuse the memoized result: the GUI
    thread never forks the binary again."""
    exe = _make(tmp_path)
    monkeypatch.setattr(system_ffmpeg.shutil, "which", lambda name, **_kw: None)
    monkeypatch.setattr(system_ffmpeg, "known_dirs", lambda: (str(tmp_path),))
    runs = []

    def slow(argv, **kw):
        runs.append(argv)
        raise subprocess.TimeoutExpired(argv, kw.get("timeout"))

    monkeypatch.setattr(system_ffmpeg.subprocess, "run", slow)
    stub = _bridge()

    assert system_ffmpeg.working_system_ffmpeg() == exe
    assert fm.FfmpegManager(tmp_path / "app").status()["path"] == exe
    assert WavesBridge._ffmpeg_source_label(stub) == "system"
    assert WavesBridge._resolve_ffmpeg_locked(stub) == exe
    assert WavesBridge._preview_ffmpeg_bin(stub) == exe
    assert WavesBridge._flac_check_ffmpeg(stub) == exe
    assert len(runs) == 1
