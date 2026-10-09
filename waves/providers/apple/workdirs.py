"""Apple temp folders: one leased run folder per Waves process, and the sweep.

Every temporary folder the Apple engine and runner make (a fetch's workdir,
a FLAC conversion's, an integrity hold) lives in this process's run folder,
``waves-apple-run-*`` under the system temp dir. The process holds a lease on
it: an OS lock on its ``.lease`` file, which the OS drops when the process
ends, however it ends. ``sweep_stale`` removes every run folder whose lease is
free, with whatever a killed fetch left inside, and never one whose lease a
live Waves holds.

Two kinds of folder carry no lease to read: a run folder whose lease file is
missing (it is being made, or a temp cleaner took the file) and the flat
``waves-apple-*`` workdirs of builds without run folders, which may still be
running beside this one. The sweep removes those once nothing in them has
changed for ``UNOWNED_IDLE_SEC``: a fetch writes into its folder every few
seconds, so an hour without a write means no fetch owns it. Any other folder
that merely starts with the prefix stays. On a file system that refuses
locks, no lease can be read and run folders stay.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import NamedTuple

from waves import file_locks

LEASE_NAME = ".lease"
UNOWNED_IDLE_SEC = 3600.0
_RUN_PREFIX = "waves-apple-run-"
# tempfile.mkdtemp names: the prefix, then eight characters of this alphabet.
_RUN_NAME = re.compile(r"waves-apple-run-[a-z0-9_]{8}")
_FLAT_NAME = re.compile(r"waves-apple-(?:(?:alac|flac|quarantine)-)?[a-z0-9_]{8}")


class _RunFolder(NamedTuple):
    path: Path
    # The descriptor holding the lease, or None where the file system refuses
    # the lock (every sweep on it then reads the folder as in use).
    lease: int | None


_lock = threading.Lock()
_run: _RunFolder | None = None


def make_workdir(kind: str) -> Path:
    """A fresh ``<kind>-*`` folder inside this process's run folder."""
    with _lock:
        try:
            return Path(tempfile.mkdtemp(prefix=f"{kind}-", dir=_run_folder()))
        except FileNotFoundError:
            # The run folder went away: a temp purge, or another Waves' sweep
            # in the instant between this process creating the lease and
            # locking it. A fresh run folder serves this and later work.
            _forget_run()
            return Path(tempfile.mkdtemp(prefix=f"{kind}-", dir=_run_folder()))


def run_folder() -> Path | None:
    """This process's run folder, or None before its first workdir."""
    with _lock:
        return _run.path if _run is not None else None


def sweep_stale() -> list[Path]:
    """Remove the Apple temp folders no live Waves owns; the folders removed."""
    try:
        entries = list(os.scandir(tempfile.gettempdir()))
    except OSError:
        return []
    removed: list[Path] = []
    for entry in entries:
        if not entry.is_dir(follow_symlinks=False):
            continue
        path = Path(entry.path)
        if _RUN_NAME.fullmatch(entry.name):
            # Never this process's own, read per folder so one made during the
            # sweep counts: on a file system that emulates the lock per
            # process, probing our own lease would release it.
            if path == run_folder() or not _unowned_run(path):
                continue
        elif not (_FLAT_NAME.fullmatch(entry.name) and _idle(path)):
            continue
        shutil.rmtree(path, ignore_errors=True)
        if not path.exists():
            removed.append(path)
    return removed


def _run_folder() -> Path:
    global _run
    base = Path(tempfile.gettempdir())
    if _run is not None and _run.path.parent == base:
        return _run.path
    _forget_run()
    folder = Path(tempfile.mkdtemp(prefix=_RUN_PREFIX, dir=base))
    _run = _RunFolder(folder, file_locks.try_lock(folder / LEASE_NAME))
    return folder


def _forget_run() -> None:
    global _run
    if _run is not None and _run.lease is not None:
        file_locks.release(_run.lease)
    _run = None


def _unowned_run(folder: Path) -> bool:
    """Whether no live Waves owns this run folder."""
    if not (folder / LEASE_NAME).exists():
        return _idle(folder)
    fd = file_locks.try_lock(folder / LEASE_NAME, create=False)
    if fd is None:
        return False
    # Released before the removal: Windows cannot delete a file held open.
    file_locks.release(fd)
    return True


def _idle(folder: Path) -> bool:
    """Whether nothing in ``folder`` has changed for ``UNOWNED_IDLE_SEC``."""
    newest = 0.0
    try:
        newest = folder.lstat().st_mtime
        for root, dirs, files in os.walk(folder):
            for name in (*dirs, *files):
                newest = max(newest, os.lstat(os.path.join(root, name)).st_mtime)
    except OSError:
        # Changing under the walk: something is writing to it.
        return False
    return time.time() - newest >= UNOWNED_IDLE_SEC
