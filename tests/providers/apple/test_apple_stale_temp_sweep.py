"""Waves removes the Apple temp folders no live Waves owns.

Each process keeps its Apple temp folders in one run folder it holds a lease
on. The sweep after launch removes every run folder whose lease is free, and
the folders without a lease to read (a run folder that lost its lease file,
the flat workdirs of builds without run folders) once nothing in them has
changed for an hour. A folder a live Waves owns, and anything else that
merely shares the prefix, stays.
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

from waves.providers.apple import workdirs


def _idle_for(folder: Path, seconds: float) -> Path:
    """Backdate everything in ``folder`` as if nothing wrote it for ``seconds``."""
    stamp = time.time() - seconds
    for root, dirs, files in os.walk(folder):
        for name in (*dirs, *files):
            os.utime(os.path.join(root, name), (stamp, stamp))
    os.utime(folder, (stamp, stamp))
    return folder


def _folder(path: Path, *, lease: bool = False) -> Path:
    """A temp folder holding a fetch's fragment, with a free lease if asked."""
    workdir = path / "alac-x1y2z3w4"
    workdir.mkdir(parents=True)
    (workdir / "song_00001.m4s").write_bytes(b"\0" * 4096)
    if lease:
        (path / workdirs.LEASE_NAME).touch()
    return path


def test_the_sweep_removes_what_no_live_waves_owns(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    hour = workdirs.UNOWNED_IDLE_SEC
    in_use = workdirs.make_workdir("alac")  # this process's fetch in flight
    # A Waves that died mid-fetch a moment ago: its lease is free.
    stale = _folder(tmp_path / "waves-apple-run-dead0001", lease=True)
    # A run folder whose lease file is not written yet, and one that lost it
    # an hour ago.
    being_made = _folder(tmp_path / "waves-apple-run-made0001")
    lost_lease = _idle_for(_folder(tmp_path / "waves-apple-run-lost0001"), hour + 60)
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

    removed = workdirs.sweep_stale()

    assert sorted(removed) == sorted([stale, lost_lease, *flat_idle])
    assert in_use.is_dir() and (in_use.parent / workdirs.LEASE_NAME).is_file()
    assert being_made.is_dir() and flat_busy.is_dir()
    assert all(folder.is_dir() for folder in lookalikes) and plain_file.is_file()


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


def test_a_workdir_still_lands_after_its_run_folder_was_removed(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    first = workdirs.make_workdir("song")
    shutil.rmtree(first.parent)  # a temp purge took it

    second = workdirs.make_workdir("song")

    assert second.is_dir() and second.parent != first.parent
    assert (second.parent / workdirs.LEASE_NAME).is_file()
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
