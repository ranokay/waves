"""An FFmpeg the user installed is found even when the app's PATH is bare."""

from __future__ import annotations

import errno
import os
import stat
import subprocess
import sys
from types import SimpleNamespace

import pytest

from waves import system_ffmpeg

posix_only = pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX executable bits")


def _make(folder, executable=True):
    folder.mkdir(parents=True, exist_ok=True)
    exe = folder / "ffmpeg"
    exe.write_text("#!/bin/sh\n")
    if executable:
        exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    return str(exe)


@pytest.fixture(autouse=True)
def _clean_probe_cache(monkeypatch):
    monkeypatch.setattr(system_ffmpeg, "_probe_cache", {})
    monkeypatch.setattr(system_ffmpeg, "_probe_slow", {})


@posix_only
def test_path_hit_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(system_ffmpeg.shutil, "which", lambda name, **_kw: "/on/path/ffmpeg")
    monkeypatch.setattr(system_ffmpeg, "known_dirs", lambda: (str(tmp_path),))
    _make(tmp_path)
    assert system_ffmpeg.find_system_ffmpeg() == "/on/path/ffmpeg"


@posix_only
def test_package_manager_folder_found_when_path_is_bare(tmp_path, monkeypatch):
    monkeypatch.setattr(system_ffmpeg.shutil, "which", lambda name, **_kw: None)
    missing = tmp_path / "missing"
    present = tmp_path / "brew"
    exe = _make(present)
    monkeypatch.setattr(system_ffmpeg, "known_dirs", lambda: (str(missing), str(present)))
    assert system_ffmpeg.find_system_ffmpeg() == exe


@posix_only
def test_non_executable_file_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(system_ffmpeg.shutil, "which", lambda name, **_kw: None)
    _make(tmp_path, executable=False)
    monkeypatch.setattr(system_ffmpeg, "known_dirs", lambda: (str(tmp_path),))
    assert system_ffmpeg.find_system_ffmpeg() == ""


@posix_only
def test_a_broken_install_is_passed_over_for_one_that_works(tmp_path, monkeypatch):
    broken = tmp_path / "local"
    brew = tmp_path / "brew"
    bad, good = _make(broken), _make(brew)
    monkeypatch.setattr(system_ffmpeg.shutil, "which", lambda name, **_kw: None)
    monkeypatch.setattr(system_ffmpeg, "known_dirs", lambda: (str(broken), str(brew)))
    assert system_ffmpeg.find_system_ffmpeg(works=lambda p: p == good) == good
    assert system_ffmpeg.find_system_ffmpeg(works=lambda p: False) == ""
    assert system_ffmpeg.find_system_ffmpeg() == bad


def test_macos_looks_in_homebrew(monkeypatch):
    monkeypatch.setattr(system_ffmpeg.sys, "platform", "darwin")
    assert "/opt/homebrew/bin" in system_ffmpeg.known_dirs()
    assert "/opt/local/bin" in system_ffmpeg.known_dirs()


def test_linux_looks_in_linuxbrew(monkeypatch):
    monkeypatch.setattr(system_ffmpeg.sys, "platform", "linux")
    assert "/home/linuxbrew/.linuxbrew/bin" in system_ffmpeg.known_dirs()
    assert "/snap/bin" in system_ffmpeg.known_dirs()
    assert "/opt/homebrew/bin" not in system_ffmpeg.known_dirs()


def test_windows_uses_the_path_only(monkeypatch):
    monkeypatch.setattr(system_ffmpeg.sys, "platform", "win32")
    assert system_ffmpeg.known_dirs() == ()


@posix_only
def test_status_never_reports_a_broken_system_ffmpeg_installed(tmp_path, monkeypatch):
    from waves.desktop.ffmpeg import manager as fm

    _make(tmp_path)
    monkeypatch.setattr(system_ffmpeg.shutil, "which", lambda name, **_kw: None)
    monkeypatch.setattr(system_ffmpeg, "known_dirs", lambda: (str(tmp_path),))
    monkeypatch.setattr(system_ffmpeg, "probe_version", lambda path: "")
    assert fm._which_ffmpeg("macos") == ""
    assert fm.FfmpegManager(tmp_path / "app").status()["state"] == "missing"


@posix_only
def test_an_ffmpeg_too_slow_for_the_probe_is_kept_and_not_probed_again(tmp_path, monkeypatch):
    """A cold first run (snap, a virus scan) that outlasts the probe is not a
    broken install: jobs keep it, and the GUI thread never forks it again."""
    exe = _make(tmp_path)
    monkeypatch.setattr(system_ffmpeg.shutil, "which", lambda name, **_kw: None)
    monkeypatch.setattr(system_ffmpeg, "known_dirs", lambda: (str(tmp_path),))
    runs = []

    def slow(argv, **kw):
        runs.append(argv)
        raise subprocess.TimeoutExpired(argv, kw.get("timeout"))

    monkeypatch.setattr(system_ffmpeg.subprocess, "run", slow)
    assert system_ffmpeg.working_system_ffmpeg() == exe
    assert system_ffmpeg.working_system_ffmpeg() == exe
    assert len(runs) == 1


@posix_only
def test_a_broken_path_copy_is_passed_over_for_a_later_path_copy(tmp_path, monkeypatch):
    """PATH can hold several ffmpeg copies: the first one being broken must not
    hide a working copy later in the same list."""
    first = tmp_path / "first"
    second = tmp_path / "second"
    bad = _make(first)
    good = _make(second)
    monkeypatch.setenv("PATH", os.pathsep.join((str(first), str(second))))
    monkeypatch.setattr(system_ffmpeg, "known_dirs", lambda: ())

    def run(argv, **kw):
        if argv[0] == bad:
            raise subprocess.TimeoutExpired(argv, kw.get("timeout"))
        return SimpleNamespace(returncode=0, stdout="ffmpeg version 7.1 built", stderr="")

    monkeypatch.setattr(system_ffmpeg.subprocess, "run", run)
    assert system_ffmpeg.working_system_ffmpeg() == good


@posix_only
def test_an_empty_path_component_means_the_working_directory(tmp_path, monkeypatch):
    """PATH=dir: means cwd too: a broken copy in dir must not hide ./ffmpeg."""
    broken_dir = tmp_path / "broken"
    broken = _make(broken_dir)
    good = _make(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", os.pathsep.join((str(broken_dir), "")))
    monkeypatch.setattr(system_ffmpeg, "known_dirs", lambda: ())

    def run(argv, **kw):
        if argv[0] == broken:
            raise subprocess.TimeoutExpired(argv, kw.get("timeout"))
        return SimpleNamespace(returncode=0, stdout="ffmpeg version 7.1 built", stderr="")

    monkeypatch.setattr(system_ffmpeg.subprocess, "run", run)
    assert os.path.samefile(system_ffmpeg.working_system_ffmpeg(), good)


@posix_only
def test_a_slow_ffmpeg_does_not_shadow_a_working_one(tmp_path, monkeypatch):
    """The first candidate hangs the probe (it may be hung for good): a copy
    further down the list that answers is the one jobs and status get."""
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    hung = _make(tmp_path / "a")
    good = _make(tmp_path / "b")
    monkeypatch.setattr(system_ffmpeg.shutil, "which", lambda name, **_kw: None)
    monkeypatch.setattr(
        system_ffmpeg,
        "known_dirs",
        lambda: (str(tmp_path / "a"), str(tmp_path / "b")),
    )

    def run(argv, **kw):
        if argv[0] == hung:
            raise subprocess.TimeoutExpired(argv, kw.get("timeout"))
        return SimpleNamespace(returncode=0, stdout="ffmpeg version 7.1 built", stderr="")

    monkeypatch.setattr(system_ffmpeg.subprocess, "run", run)
    assert system_ffmpeg.working_system_ffmpeg() == good
    assert system_ffmpeg.probe_version(good) == "7.1"


@posix_only
def test_a_slow_ffmpeg_is_probed_again_for_a_job_once_its_pause_is_over(tmp_path, monkeypatch):
    """A worker-thread caller gives the slow copy a fresh probe after its
    pause: a cold start that warmed up answers, and status() shows its real
    version from then on."""
    exe = _make(tmp_path)
    monkeypatch.setattr(system_ffmpeg.shutil, "which", lambda name, **_kw: None)
    monkeypatch.setattr(system_ffmpeg, "known_dirs", lambda: (str(tmp_path),))
    monkeypatch.setattr(system_ffmpeg, "PROBE_SLOW_RETRY_S", -1.0)  # the pause is already over
    runs = []
    warmed = []

    def run(argv, **kw):
        runs.append(argv)
        if not warmed:
            raise subprocess.TimeoutExpired(argv, kw.get("timeout"))
        return SimpleNamespace(returncode=0, stdout="ffmpeg version 7.1 built", stderr="")

    monkeypatch.setattr(system_ffmpeg.subprocess, "run", run)
    assert system_ffmpeg.working_system_ffmpeg(retry_slow=True) == exe
    assert len(runs) == 2  # the first probe, and the retry its expired pause allowed
    assert system_ffmpeg.working_system_ffmpeg() == exe  # status() never re-forks
    assert len(runs) == 2
    warmed.append(True)
    assert system_ffmpeg.working_system_ffmpeg(retry_slow=True) == exe
    assert system_ffmpeg.probe_version(exe) == "7.1"
    assert not system_ffmpeg._probe_slow


def test_a_missing_loader_is_passed_over_not_kept_as_a_fallback(tmp_path, monkeypatch):
    """The file exists but cannot start (missing ELF loader or interpreter):
    it is broken, not slow, so jobs must not keep it as a fallback."""
    _make(tmp_path)
    monkeypatch.setattr(system_ffmpeg.shutil, "which", lambda name, **_kw: None)
    monkeypatch.setattr(system_ffmpeg, "known_dirs", lambda: (str(tmp_path),))

    def broken(argv, **kw):
        raise OSError(errno.ENOENT, "No such file or directory")

    monkeypatch.setattr(system_ffmpeg.subprocess, "run", broken)
    assert system_ffmpeg.working_system_ffmpeg() == ""
    assert not system_ffmpeg._probe_slow


def test_a_repaired_loader_is_found_without_restart(tmp_path, monkeypatch):
    """Installing the missing loader/interpreter changes neither mtime nor
    size: an ENOENT result must not stay cached as broken."""
    binary = tmp_path / "ffmpeg"
    binary.write_bytes(b"BIN")
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        if len(calls) == 1:
            raise OSError(errno.ENOENT, "No such file or directory")
        return SimpleNamespace(returncode=0, stdout="ffmpeg version 7.1", stderr="")

    monkeypatch.setattr(system_ffmpeg.subprocess, "run", run)
    assert system_ffmpeg.probe_version(str(binary)) == ""
    assert system_ffmpeg.probe_version(str(binary)) == "7.1"
    assert len(calls) == 2
    assert not system_ffmpeg._probe_slow


def test_a_permission_error_is_probed_again_after_the_binary_is_repaired(tmp_path, monkeypatch):
    """chmod +x changes no mtime/size: an EACCES result must not be cached as
    a permanently broken copy."""
    binary = tmp_path / "ffmpeg"
    binary.write_bytes(b"BIN")
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        if len(calls) == 1:
            raise OSError(errno.EACCES, "Permission denied")
        return SimpleNamespace(returncode=0, stdout="ffmpeg version 7.1", stderr="")

    monkeypatch.setattr(system_ffmpeg.subprocess, "run", run)
    assert system_ffmpeg.probe_version(str(binary)) == ""
    assert system_ffmpeg.probe_version(str(binary)) == "7.1"
    assert len(calls) == 2
    assert not system_ffmpeg._probe_slow


@posix_only
def test_a_worker_retry_keeps_the_gui_probe_cached(tmp_path, monkeypatch):
    """While a worker re-probes a slow binary, a concurrent status() reads the
    cached empty result instead of forking the same binary on the GUI thread."""
    exe = _make(tmp_path)
    monkeypatch.setattr(system_ffmpeg.shutil, "which", lambda name, **_kw: None)
    monkeypatch.setattr(system_ffmpeg, "known_dirs", lambda: (str(tmp_path),))
    monkeypatch.setattr(system_ffmpeg, "PROBE_SLOW_RETRY_S", -1.0)
    runs = []
    gui_results = []

    def run(argv, **kw):
        runs.append(argv)
        if len(runs) == 2:
            gui_results.append(system_ffmpeg.probe_version(exe))
        raise subprocess.TimeoutExpired(argv, kw.get("timeout"))

    monkeypatch.setattr(system_ffmpeg.subprocess, "run", run)
    assert system_ffmpeg.working_system_ffmpeg(retry_slow=True) == exe
    assert gui_results == [""]
    assert len(runs) == 2


def test_a_probe_reads_the_ffprobe_version_token(tmp_path, monkeypatch):
    binary = tmp_path / "ffprobe"
    binary.write_bytes(b"BIN")
    monkeypatch.setattr(
        system_ffmpeg.subprocess,
        "run",
        lambda argv, **kw: SimpleNamespace(
            returncode=0, stdout="ffprobe version 7.1 Copyright (c) 2007-2025", stderr=""
        ),
    )
    assert system_ffmpeg.probe_version(str(binary)) == "7.1"


def test_a_probe_that_cannot_exec_is_not_forked_again(tmp_path, monkeypatch):
    """A permanently broken binary is memoized like a timed-out one: status()
    must not pay a fork per call for a copy that cannot run."""
    binary = tmp_path / "ffmpeg"
    binary.write_bytes(b"BIN")
    runs = []

    def broken(argv, **kw):
        runs.append(argv)
        raise OSError(errno.ENOEXEC, "Exec format error")

    monkeypatch.setattr(system_ffmpeg.subprocess, "run", broken)
    assert system_ffmpeg.probe_version(str(binary)) == ""
    assert system_ffmpeg.probe_version(str(binary)) == ""
    assert len(runs) == 1
    assert not system_ffmpeg._probe_slow


@posix_only
def test_a_transient_exec_failure_stays_a_retryable_fallback(tmp_path, monkeypatch):
    """EAGAIN/ETXTBSY says "not right now", not "broken": the copy stays a
    fallback and a worker's retry after the pause can warm it up."""
    exe = _make(tmp_path)
    monkeypatch.setattr(system_ffmpeg.shutil, "which", lambda name, **_kw: None)
    monkeypatch.setattr(system_ffmpeg, "known_dirs", lambda: (str(tmp_path),))
    monkeypatch.setattr(system_ffmpeg, "PROBE_SLOW_RETRY_S", -1.0)
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        if len(calls) == 1:
            raise OSError(errno.EAGAIN, "Resource temporarily unavailable")
        return SimpleNamespace(returncode=0, stdout="ffmpeg version 7.1 built", stderr="")

    monkeypatch.setattr(system_ffmpeg.subprocess, "run", run)
    assert system_ffmpeg.working_system_ffmpeg(retry_slow=True) == exe
    assert system_ffmpeg.probe_version(exe) == "7.1"
    assert not system_ffmpeg._probe_slow


def test_a_probe_passes_the_windows_no_console_flag(tmp_path, monkeypatch):
    """The packaged Windows app runs console-less: every probe must spawn with
    CREATE_NO_WINDOW or a console flashes over the UI."""
    binary = tmp_path / "ffmpeg"
    binary.write_bytes(b"BIN")
    seen = {}
    monkeypatch.setattr(system_ffmpeg, "CREATE_NO_WINDOW", 0x08000000)

    def run(argv, **kw):
        seen.update(kw)
        return SimpleNamespace(returncode=0, stdout="ffmpeg version 7.1", stderr="")

    monkeypatch.setattr(system_ffmpeg.subprocess, "run", run)
    system_ffmpeg.probe_version(str(binary))
    assert seen["creationflags"] == 0x08000000
