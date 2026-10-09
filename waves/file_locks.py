"""Exclusive file locks that live on an open descriptor.

The OS drops the lock when the descriptor closes, and so when the process
ends, however it ends: a lock file a crash left behind is never a lock. On a
local file system the lock belongs to the descriptor, so a second
``try_lock`` on the same file fails even in the process holding the first.
"""

from __future__ import annotations

import contextlib
import os


def try_lock(path: str | os.PathLike, *, create: bool = True) -> int | None:
    """A descriptor holding an exclusive lock on ``path``, or None.

    None when the file cannot be opened (with ``create`` False, when it does
    not exist), when another descriptor holds the lock, or when the file
    system refuses locks.
    """
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


def release(fd: int) -> None:
    """Drop a lock ``try_lock`` took: closing its descriptor drops it."""
    with contextlib.suppress(OSError):
        os.close(fd)
