"""Waves removes the Apple temp folders no live Waves owns.

Each process keeps its Apple temp folders in one run folder whose lease,
beside it, it holds. The sweep after launch removes every run folder whose
lease is free, and, once nothing in them has changed for an hour, the flat
workdirs of builds without run folders and lease files whose folder is gone.
A folder a live Waves owns, a run folder without a lease file, and anything
else that merely shares the prefix, stays.
"""

from __future__ import annotations

import gc
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from support.bridge_stub import BridgeStub

from waves import file_locks
from waves.providers.apple import workdirs


def _idle_for(folder: Path, seconds: float) -> Path:
    """Backdate everything in ``folder`` as if nothing wrote it for ``seconds``."""
    stamp = time.time() - seconds
    for root, dirs, files in os.walk(folder):
        for name in (*dirs, *files):
            os.utime(os.path.join(root, name), (stamp, stamp))
    os.utime(folder, (stamp, stamp))
    return folder


def _touched(path: Path) -> Path:
    path.touch()
    return path


def _folder(path: Path, *, lease: bool = False) -> Path:
    """A temp folder holding a fetch's fragment, with a free lease if asked."""
    workdir = path / "alac-x1y2z3w4"
    workdir.mkdir(parents=True)
    (workdir / "song_00001.m4s").write_bytes(b"\0" * 4096)
    if lease:
        workdirs.lease_of(path).touch()
    return path


def test_the_sweep_removes_what_no_live_waves_owns(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    hour = workdirs.UNOWNED_IDLE_SEC
    in_use = workdirs.make_workdir("alac")  # this process's fetch in flight
    # A Waves that died mid-fetch a moment ago: its lease is free.
    stale = _folder(tmp_path / "waves-apple-run-dead0001", lease=True)
    # A run folder without a lease file, idle an hour: nothing proves its
    # owner is gone.
    unleased = _idle_for(_folder(tmp_path / "waves-apple-run-lost0001"), hour + 60)
    # Lease files whose folder is gone: one idle an hour, one just made, and
    # one idle but held.
    stray_lease = _idle_for(_touched(tmp_path / "waves-apple-run-gone0001.lease"), hour + 60)
    fresh_lease = _touched(tmp_path / "waves-apple-run-new00001.lease")
    held_lease = _idle_for(_touched(tmp_path / "waves-apple-run-held0001.lease"), hour + 60)
    holder = file_locks.try_lock(held_lease, create=False)
    assert holder is not None
    # Flat workdirs of a build without run folders: idle for an hour, and
    # one that build may still be writing.
    flat_idle = [
        _idle_for(_folder(tmp_path / name), hour + 60)
        for name in (
            "waves-apple-abcd1234",
            "waves-apple-alac-abcd1234",
            "waves-apple-flac-ab_d1234",
            "waves-apple-quarantine-0a1b2c3d",
        )
    ]
    flat_busy = _folder(tmp_path / "waves-apple-alac-busy0001")
    # Same prefix, not Waves' temp folders: a test sandbox, a longer name, a file.
    lookalikes = [
        _idle_for(_folder(tmp_path / "waves-apple-setup-abcd1234"), hour + 60),
        _idle_for(_folder(tmp_path / "waves-apple-abcd12345"), hour + 60),
    ]
    plain_file = tmp_path / "waves-apple-efgh5678"
    plain_file.write_text("not a folder")

    try:
        removed = workdirs.sweep_stale()
    finally:
        file_locks.release(holder)

    assert sorted(removed) == sorted([stale, stray_lease, *flat_idle])
    assert not workdirs.lease_of(stale).exists()
    assert in_use.is_dir()
    assert workdirs.lease_of(in_use.parent).is_file()
    assert unleased.is_dir()
    assert flat_busy.is_dir()
    assert fresh_lease.is_file()
    assert held_lease.is_file()
    assert all(folder.is_dir() for folder in lookalikes)
    assert plain_file.is_file()


def test_a_run_folder_appears_only_once_its_lease_is_held(tmp_path, monkeypatch):
    """A sweep can never see a live Waves' run folder with its lease still free."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    mkdir = os.mkdir
    checked: list[Path] = []

    def mkdir_after_the_lease(path, *args, **kwargs):
        folder = Path(path)
        if folder.name.startswith("waves-apple-run-"):
            lease = workdirs.lease_of(folder)
            assert lease.is_file(), "the folder appeared before its lease"
            assert file_locks.try_lock(lease, create=False) is None, "the lease is still free"
            checked.append(folder)
        return mkdir(path, *args, **kwargs)

    monkeypatch.setattr(os, "mkdir", mkdir_after_the_lease)

    workdir = workdirs.make_workdir("alac")

    assert checked == [workdir.parent]


def test_a_run_folder_that_cannot_be_made_leaves_no_lease_behind(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    mkdir = os.mkdir

    def no_space(path, *args, **kwargs):
        if Path(path).name.startswith("waves-apple-run-"):
            raise OSError(28, "No space left on device")
        return mkdir(path, *args, **kwargs)

    monkeypatch.setattr(os, "mkdir", no_space)
    with pytest.raises(OSError, match="No space"):
        workdirs.make_workdir("alac")
    assert list(tmp_path.iterdir()) == []

    monkeypatch.setattr(os, "mkdir", mkdir)
    workdir = workdirs.make_workdir("alac")
    assert workdirs.lease_of(workdir.parent).is_file()


def test_without_file_locks_the_run_folder_is_unleased_and_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(file_locks, "lock_new", lambda path: None)
    workdir = workdirs.make_workdir("alac")
    _idle_for(workdir.parent, workdirs.UNOWNED_IDLE_SEC + 60)

    assert not workdirs.lease_of(workdir.parent).exists()
    assert workdirs.sweep_stale() == []
    assert workdir.is_dir()


_OWNER = """\
import sys, tempfile, time
tempfile.tempdir = sys.argv[1]
from waves.providers.apple import workdirs
print(workdirs.make_workdir("alac"), flush=True)
time.sleep(120)
"""


@pytest.mark.integration
def test_a_folder_stays_while_its_waves_lives_and_goes_once_it_is_killed(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    owner = subprocess.Popen(  # noqa: S603 (fixed argv: this interpreter, the owner script above)
        [sys.executable, "-c", _OWNER, str(tmp_path)], stdout=subprocess.PIPE, text=True
    )
    try:
        workdir = Path(owner.stdout.readline().strip())
        (workdir / "song_00001.m4s").write_bytes(b"\0" * 4096)
        assert workdirs.sweep_stale() == []
        assert workdir.is_dir()
    finally:
        owner.kill()  # SIGKILL off Windows: the lease is all it leaves behind
        owner.wait(10)
        owner.stdout.close()

    assert workdirs.sweep_stale() == [workdir.parent]
    assert not workdir.parent.exists()
    assert not workdirs.lease_of(workdir.parent).exists()


def test_a_workdir_still_lands_after_its_run_folder_was_removed(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    first = workdirs.make_workdir("song")
    shutil.rmtree(first.parent)  # a temp purge took it

    second = workdirs.make_workdir("song")

    assert second.is_dir()
    assert second.parent != first.parent
    assert workdirs.lease_of(second.parent).is_file()
    assert workdirs.sweep_stale() == []


def test_the_launch_reveal_sweeps_stale_apple_folders(tmp_path, monkeypatch):
    from waves.desktop.backend import WavesBridge

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(gc, "freeze", lambda: None)
    stale = _folder(tmp_path / "waves-apple-run-dead0001", lease=True)
    started = []
    bridge = BridgeStub(
        _boot_reveal_hook=None,
        threadpool=SimpleNamespace(start=started.append),
        _load_search_cache=lambda: None,
    )

    WavesBridge.bootRevealed(bridge)
    for worker in started:
        worker.fn(*worker.args, **worker.kwargs)

    assert not stale.exists()
