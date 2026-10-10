"""Apple temp folders: one leased run folder per Waves process, and the sweep.

Every temporary folder the Apple engine and runner make (a fetch's workdir,
a FLAC conversion's, an integrity hold) lives in this process's run folder,
``waves-apple-run-*`` under the system temp dir. The process holds a lease on
it: an OS lock on the ``.lease`` file beside it, which the OS drops when the
process ends, however it ends. The lease is locked before the folder exists,
so no sweep ever sees a run folder whose live owner has not locked it yet.
``sweep_stale`` removes every run folder whose lease is free, with whatever a
killed fetch left inside, and its lease file with it.

Some folders carry no lease to read: a run folder whose lease file is missing
(a temp cleaner took it, or the temp file system refuses locks) and the flat
``waves-apple-*`` workdirs of builds without run folders, which may still be
running beside this one. The sweep removes those once nothing in them has
changed for ``UNOWNED_IDLE_SEC``: a fetch writes into its folder every few
seconds, so an hour without a write means no fetch owns it. A lease file
whose folder is gone goes after the same hour, once nothing holds it. Any
other name that merely starts with the prefix stays.
"""

from __future__ import annotations

import contextlib
import os
import re
import secrets
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import NamedTuple

from waves import file_locks

LEASE_SUFFIX = ".lease"
UNOWNED_IDLE_SEC = 3600.0
_RUN_PREFIX = "waves-apple-run-"
# The prefix, then eight characters of tempfile.mkdtemp's alphabet.
_RUN_NAME = re.compile(r"waves-apple-run-[a-z0-9_]{8}")
_LEASE_FILE_NAME = re.compile(r"waves-apple-run-[a-z0-9_]{8}\.lease")
_FLAT_NAME = re.compile(r"waves-apple-(?:(?:alac|flac|quarantine)-)?[a-z0-9_]{8}")
_NEW_RUN_ATTEMPTS = 16


class _RunFolder(NamedTuple):
    path: Path
    # The descriptor holding the lease, or None where the file system refuses
    # the lock (the folder then has no lease file and ages out like any other).
    lease: int | None


_lock = threading.Lock()
_run: _RunFolder | None = None


def lease_of(folder: Path) -> Path:
    """A run folder's lease file: beside it, named after it."""
    return folder.with_name(folder.name + LEASE_SUFFIX)


def make_workdir(kind: str) -> Path:
    """A fresh ``<kind>-*`` folder inside this process's run folder."""
    with _lock:
        try:
            return Path(tempfile.mkdtemp(prefix=f"{kind}-", dir=_run_folder()))
        except FileNotFoundError:
            # A temp purge took the run folder: a fresh one serves this and
            # later work.
            _forget_run()
            return Path(tempfile.mkdtemp(prefix=f"{kind}-", dir=_run_folder()))


def run_folder() -> Path | None:
    """This process's run folder, or None before its first workdir."""
    with _lock:
        return _run.path if _run is not None else None


def sweep_stale() -> list[Path]:
    """Remove the Apple temp folders and lease files no live Waves owns.

    Returns the paths removed.
    """
    try:
        entries = list(os.scandir(tempfile.gettempdir()))
    except OSError:
        return []
    removed: list[Path] = []
    for entry in entries:
        path = Path(entry.path)
        if entry.is_dir(follow_symlinks=False):
            if _RUN_NAME.fullmatch(entry.name):
                # Never this process's own, read per folder so one made during
                # the sweep counts: on a file system that emulates the lock per
                # process, probing our own lease would release it.
                gone = path != run_folder() and _remove_unowned_run(path)
            else:
                gone = bool(_FLAT_NAME.fullmatch(entry.name)) and _idle(path) and _remove(path)
        elif entry.is_file(follow_symlinks=False) and _LEASE_FILE_NAME.fullmatch(entry.name):
            gone = _remove_stray_lease(path)
        else:
            gone = False
        if gone:
            removed.append(path)
    return removed


def _run_folder() -> Path:
    global _run
    base = Path(tempfile.gettempdir())
    if _run is not None and _run.path.parent == base:
        return _run.path
    _forget_run()
    for _ in range(_NEW_RUN_ATTEMPTS):
        folder = base / f"{_RUN_PREFIX}{secrets.token_hex(4)}"
        lease_path = lease_of(folder)
        if folder.exists() or lease_path.exists():
            continue
        lease = file_locks.try_lock(lease_path)
        if lease is None:
            # The file is this process's own, just made: the file system
            # refuses locks.
            with contextlib.suppress(OSError):
                lease_path.unlink()
            break
        try:
            folder.mkdir()
        except FileExistsError:
            file_locks.release(lease)
            with contextlib.suppress(OSError):
                lease_path.unlink()
            continue
        _run = _RunFolder(folder, lease)
        return folder
    folder = Path(tempfile.mkdtemp(prefix=_RUN_PREFIX, dir=base))
    _run = _RunFolder(folder, None)
    return folder


def _forget_run() -> None:
    global _run
    if _run is not None and _run.lease is not None:
        file_locks.release(_run.lease)
    _run = None


def _remove_unowned_run(folder: Path) -> bool:
    """Remove a run folder no live Waves owns, with its lease file."""
    lease_path = lease_of(folder)
    if not lease_path.exists():
        return _idle(folder) and _remove(folder)
    lease = file_locks.try_lock(lease_path, create=False)
    if lease is None:
        return False
    try:
        gone = _remove(folder)
    finally:
        # Released before the unlink: Windows cannot delete a file held open.
        file_locks.release(lease)
    if gone:
        with contextlib.suppress(OSError):
            lease_path.unlink()
    return gone


def _remove_stray_lease(lease_path: Path) -> bool:
    """Remove a lease file whose folder is gone, once nothing holds it."""
    folder = lease_path.with_name(lease_path.name.removesuffix(LEASE_SUFFIX))
    if folder.exists() or not _idle(lease_path):
        return False
    lease = file_locks.try_lock(lease_path, create=False)
    if lease is None:
        return False
    file_locks.release(lease)
    with contextlib.suppress(OSError):
        lease_path.unlink()
    return not lease_path.exists()


def _remove(folder: Path) -> bool:
    shutil.rmtree(folder, ignore_errors=True)
    return not folder.exists()


def _idle(path: Path) -> bool:
    """Whether nothing in ``path`` has changed for ``UNOWNED_IDLE_SEC``."""
    newest = 0.0
    try:
        newest = path.lstat().st_mtime
        for root, dirs, files in os.walk(path):
            for name in (*dirs, *files):
                newest = max(newest, os.lstat(os.path.join(root, name)).st_mtime)
    except OSError:
        # Changing under the walk: something is writing to it.
        return False
    return time.time() - newest >= UNOWNED_IDLE_SEC
