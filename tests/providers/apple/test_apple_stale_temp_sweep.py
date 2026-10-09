"""Waves removes the Apple temp folders no live Waves owns (issue #660).

A killed Waves left its fetch's fragments in a ``waves-apple-*`` folder under
the temp dir for good. Each process now keeps its Apple temp folders in one
run folder it holds a lease on, and the sweep after launch removes every run
folder whose lease is free, plus the flat folders older builds made. A
folder a live Waves owns, and anything else that merely shares the prefix,
stays.
"""

from __future__ import annotations

import gc
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from support.bridge_stub import BridgeStub

from waves.providers.apple import workdirs


def _stale_run_folder(base: Path, name: str = "waves-apple-run-dead0001") -> Path:
    """A run folder whose Waves died mid-fetch: a free lease, a fragment left."""
    workdir = base / name / "alac-x1y2z3w4"
    workdir.mkdir(parents=True)
    (workdir / "song_00001.m4s").write_bytes(b"\0" * 4096)
    (base / name / workdirs.LEASE_NAME).touch()
    return base / name


def test_the_sweep_removes_what_no_live_waves_owns(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    in_use = workdirs.make_workdir("alac")  # this process's fetch in flight
    stale = _stale_run_folder(tmp_path)
    # A run folder whose lease file is not written yet: its owner may be
    # creating it this instant.
    being_made = tmp_path / "waves-apple-run-made0001"
    being_made.mkdir()
    legacy = [
        tmp_path / name
        for name in (
            "waves-apple-abcd1234",
            "waves-apple-alac-abcd1234",
            "waves-apple-flac-ab_d1234",
            "waves-apple-quarantine-0a1b2c3d",
        )
    ]
    for folder in legacy:
        folder.mkdir()
        (folder / "staged.m4a").write_bytes(b"\0")
    # Same prefix, not Waves' temp folders: a test sandbox, a longer name, a file.
    lookalikes = [tmp_path / "waves-apple-setup-abcd1234", tmp_path / "waves-apple-abcd12345"]
    for folder in lookalikes:
        folder.mkdir()
    plain_file = tmp_path / "waves-apple-efgh5678"
    plain_file.write_text("not a folder")

    removed = workdirs.sweep_stale()

    assert sorted(removed) == sorted([stale, *legacy])
    assert not stale.exists() and not any(folder.exists() for folder in legacy)
    assert in_use.is_dir() and (in_use.parent / workdirs.LEASE_NAME).is_file()
    assert being_made.is_dir()
    assert all(folder.is_dir() for folder in lookalikes) and plain_file.is_file()


_OWNER = """\
import sys, tempfile, time
tempfile.tempdir = sys.argv[1]
from waves.providers.apple import workdirs
print(workdirs.make_workdir("alac"), flush=True)
time.sleep(120)
"""


@pytest.mark.integration
def test_a_folder_stays_while_its_waves_lives_and_goes_once_it_is_killed(tmp_path):
    owner = subprocess.Popen(  # noqa: S603 (fixed argv: this interpreter, the owner script above)
        [sys.executable, "-c", _OWNER, str(tmp_path)], stdout=subprocess.PIPE, text=True
    )
    try:
        workdir = Path(owner.stdout.readline().strip())
        (workdir / "song_00001.m4s").write_bytes(b"\0" * 4096)
        assert workdirs.sweep_stale(tmp_path) == []
        assert workdir.is_dir()
    finally:
        owner.kill()  # SIGKILL off Windows: the lease is all it leaves behind
        owner.wait(10)
        owner.stdout.close()

    assert workdirs.sweep_stale(tmp_path) == [workdir.parent]
    assert not workdir.parent.exists()


def test_a_workdir_still_lands_after_its_run_folder_was_removed(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    first = workdirs.make_workdir("song")
    shutil.rmtree(first.parent)  # a temp purge took it

    second = workdirs.make_workdir("song")

    assert second.is_dir() and second.parent != first.parent
    assert (second.parent / workdirs.LEASE_NAME).is_file()
    assert workdirs.sweep_stale(tmp_path) == []


def test_the_launch_reveal_sweeps_stale_apple_folders(tmp_path, monkeypatch):
    from waves.desktop.backend import WavesBridge

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(gc, "freeze", lambda: None)
    stale = _stale_run_folder(tmp_path)
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
