"""Private, profile-scoped ownership for the desktop control endpoint."""

from __future__ import annotations

import errno
import hashlib
import os
import stat
from pathlib import Path

from waves.file_locks import release, try_lock


class OwnerBusy(Exception):
    """Another process holds this profile's owner lock."""


class OwnerUnavailable(Exception):
    """The owner lock or its private directory cannot be used safely."""


def _private(info: os.stat_result, kind: int, mode: int) -> bool:
    return stat.S_IFMT(info.st_mode) == kind and stat.S_IMODE(info.st_mode) == mode and info.st_uid == os.getuid()


def _same_file(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _contended(path: Path, expected: os.stat_result) -> bool:
    """Distinguish an existing owner from a lock or filesystem failure."""
    import fcntl

    fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    try:
        if not _same_file(expected, os.fstat(fd)):
            raise OwnerUnavailable()
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN):
                return True
            raise
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


class ProfileOwner:
    """Hold the owner lock until closed; never unlink the lock file."""

    def __init__(self, fd: int, control_dir: Path, endpoint_id: str) -> None:
        self._fd: int | None = fd
        self.control_dir = control_dir
        self.endpoint_id = endpoint_id

    @classmethod
    def acquire(cls, profile: Path) -> ProfileOwner:
        """Acquire ownership of an existing profile or raise a classified error."""
        try:
            return cls._acquire(profile)
        except (OSError, RuntimeError, AttributeError) as exc:
            raise OwnerUnavailable() from exc

    @classmethod
    def _acquire(cls, profile: Path) -> ProfileOwner:  # noqa: C901
        dir_fd = None
        lock_fd = None
        try:
            resolved = Path(profile).resolve(strict=True)
            if not resolved.is_dir():
                raise OwnerUnavailable()
            control = resolved / "provider-control"
            created = False
            try:
                control.mkdir(mode=0o700)
                created = True
            except FileExistsError:
                pass
            dir_fd = os.open(control, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            if created:
                os.fchmod(dir_fd, 0o700)
            directory = os.fstat(dir_fd)
            if not _private(directory, stat.S_IFDIR, 0o700) or not _same_file(directory, control.lstat()):
                raise OwnerUnavailable()

            lock_path = control / "owner.lock"
            try:
                new_fd = os.open("owner.lock", os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dir_fd)
            except FileExistsError:
                pass
            else:
                try:
                    os.fchmod(new_fd, 0o600)
                finally:
                    os.close(new_fd)
            lock_info = lock_path.lstat()
            if not _private(lock_info, stat.S_IFREG, 0o600) or lock_info.st_nlink != 1:
                raise OwnerUnavailable()
            lock_fd = try_lock(lock_path, create=False)
            if lock_fd is None:
                if _contended(lock_path, lock_info):
                    raise OwnerBusy()
                raise OwnerUnavailable()
            held = os.fstat(lock_fd)
            if (
                not _private(held, stat.S_IFREG, 0o600)
                or held.st_nlink != 1
                or not _same_file(lock_info, held)
                or not _same_file(held, lock_path.lstat())
                or not _same_file(directory, control.lstat())
            ):
                raise OwnerUnavailable()
            endpoint_id = hashlib.sha256(os.fsencode(resolved)).hexdigest()
            owner = cls(lock_fd, control, endpoint_id)
            lock_fd = None
            return owner
        finally:
            if lock_fd is not None:
                release(lock_fd)
            if dir_fd is not None:
                os.close(dir_fd)

    def duplicate_lock(self) -> int:
        """Return a caller-owned descriptor retaining this owner's lock."""
        if self._fd is None:
            raise OwnerUnavailable()
        return os.dup(self._fd)

    def close(self) -> None:
        if self._fd is not None:
            release(self._fd)
            self._fd = None

    def __enter__(self) -> ProfileOwner:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
