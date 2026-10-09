"""Apple temp folders: one leased run folder per Waves process, and the sweep.

Every temporary folder the Apple engine and runner make (a fetch's workdir,
a FLAC conversion's, an integrity hold) lives in this process's run folder,
``waves-apple-run-*`` under the system temp dir. The process holds a lease on
it: an OS lock on its ``.lease`` file, which the OS drops when the process
ends, however it ends. A run folder whose lease nobody holds belongs to no
live Waves, so ``sweep_stale`` removes it with whatever a killed fetch left
inside. A run folder with no lease file is kept: it is being made, or its
lease went missing, and neither proves its owner is gone.

Older builds made flat ``waves-apple-*`` folders with no lease. Nothing makes
them any more, so the sweep also removes folders carrying exactly those
names; any other folder that merely starts with the prefix stays.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import tempfile
import threading
from pathlib import Path

LEASE_NAME = ".lease"
_RUN_PREFIX = "waves-apple-run-"
# tempfile.mkdtemp names: the prefix, then eight characters of this alphabet.
_RUN_NAME = re.compile(r"waves-apple-run-[a-z0-9_]{8}")
_LEGACY_NAME = re.compile(r"waves-apple-(?:(?:alac|flac|quarantine)-)?[a-z0-9_]{8}")

_lock = threading.Lock()
# This process's run folder and the descriptor holding its lease (None where
# the file system refuses the lock: the folder then reads as in use, never
# as stale, to every sweep on that file system).
_run: tuple[Path, int | None] | None = None


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
        return _run[0] if _run is not None else None


def sweep_stale(base: str | os.PathLike | None = None) -> list[Path]:
    """Remove the Apple temp folders under ``base`` that no live Waves owns.

    ``base`` defaults to the system temp dir. Returns the folders removed.
    """
    root = Path(tempfile.gettempdir() if base is None else base)
    own = run_folder()
    try:
        entries = list(os.scandir(root))
    except OSError:
        return []
    removed: list[Path] = []
    for entry in entries:
        if not entry.is_dir(follow_symlinks=False):
            continue
        path = Path(entry.path)
        if _RUN_NAME.fullmatch(entry.name):
            # Never this process's own: on a file system that emulates the
            # lock per process, probing our lease would release it.
            if path == own or not _unowned(path):
                continue
        elif not _LEGACY_NAME.fullmatch(entry.name):
            continue
        shutil.rmtree(path, ignore_errors=True)
        if not path.exists():
            removed.append(path)
    return removed


def _run_folder() -> Path:
    global _run
    base = Path(tempfile.gettempdir())
    if _run is not None and _run[0].parent == base:
        return _run[0]
    _forget_run()
    folder = Path(tempfile.mkdtemp(prefix=_RUN_PREFIX, dir=base))
    _run = (folder, _try_lock(folder / LEASE_NAME, create=True))
    return folder


def _forget_run() -> None:
    global _run
    if _run is not None and _run[1] is not None:
        _unlock(_run[1])
    _run = None


def _unowned(folder: Path) -> bool:
    """Whether a run folder's lease is free: its owner has exited."""
    fd = _try_lock(folder / LEASE_NAME, create=False)
    if fd is None:
        return False
    # Released before the removal: Windows cannot delete a file held open.
    _unlock(fd)
    return True


def _try_lock(path: Path, *, create: bool) -> int | None:
    """An open descriptor holding an exclusive lock on ``path``, or None."""
    try:
        fd = os.open(path, os.O_RDWR | (os.O_CREAT if create else 0), 0o600)
    except OSError:
        return None
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    return fd


def _unlock(fd: int) -> None:
    # Closing drops the lock on both platforms.
    with contextlib.suppress(OSError):
        os.close(fd)
