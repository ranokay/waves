"""Find and probe an FFmpeg the user installed themselves.

An app opened from the Finder, the Dock or a desktop launcher gets a bare PATH
(on macOS only ``/usr/bin:/bin:/usr/sbin:/sbin``), so a Homebrew, MacPorts or
Linuxbrew FFmpeg that the user's terminal finds is invisible to a plain PATH
lookup. After PATH, look in the folders those package managers install into.
Windows installers (winget, Chocolatey, Scoop) put FFmpeg on the PATH that
Explorer hands every app, so PATH alone covers it there.

The same answer serves Settings, previews, the FLAC check and every download.
A broken install left in a package-manager folder is passed over for one that
runs; one that only timed out (a snap cold start, a first-run virus scan)
stays a fallback, so a copy that may be hung never shadows a working one
further down the list.
"""

from __future__ import annotations

import errno
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable

#: Suppress the console window a child process would otherwise open in the
#: packaged Windows app (see ``waves/flac_verify.py``). 0 elsewhere.
CREATE_NO_WINDOW: int = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

#: Probing means fork+exec+wait, which can block for the whole timeout when the
#: file lives on a hung mount. The GUI thread pays this on status(), so keep it
#: short.
PROBE_TIMEOUT = 4
#: How long a probe that timed out (or failed transiently) waits before a
#: worker may probe it again.
PROBE_SLOW_RETRY_S = 60.0
#: Spawn errors that say the file itself cannot run, unlike a transient
#: EAGAIN/ETXTBSY that says "not right now".
_PERMANENT_PROBE_ERRORS = frozenset({errno.ENOEXEC})
#: Spawn errors a later repair can fix without changing (mtime, size): a
#: ``chmod +x``, a missing loader/interpreter installed behind an existing
#: script, or the file vanishing between the stat and the exec. Caching them
#: would keep a repaired binary unavailable until restart.
_UNCACHED_PROBE_ERRORS = frozenset({errno.EACCES, errno.EPERM, errno.ENOENT})

_MACOS_DIRS = ("/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin")
_LINUX_DIRS = ("/usr/local/bin", "/usr/bin", "/home/linuxbrew/.linuxbrew/bin", "/snap/bin")
_WINDOWS_DIRS: tuple[str, ...] = ()


def known_dirs() -> tuple[str, ...]:
    """Folders the user's package managers install into, per platform."""
    if sys.platform == "darwin":
        return _MACOS_DIRS
    if sys.platform.startswith("win"):
        return _WINDOWS_DIRS
    return _LINUX_DIRS


def _path_candidates(name: str) -> list[str]:
    """Every executable ``name`` on PATH, in PATH order.

    ``shutil.which`` alone returns only the first, so a broken first copy would
    hide a working one later on the user's PATH."""
    path = os.environ.get("PATH", os.defpath)
    candidates: list[str] = []
    for folder in path.split(os.pathsep):
        # An empty PATH component means the current directory.
        candidate = shutil.which(name, path=folder or os.curdir)
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    if not candidates:
        found = shutil.which(name)
        if found:
            candidates.append(found)
    return candidates


def find_system_ffmpeg(name: str = "ffmpeg", works: Callable[[str], bool] | None = None) -> str:
    """Path to an FFmpeg on PATH or in a package manager's folder, else "".
    With ``works``, a candidate it rejects (a broken install left behind) is
    passed over for the next one."""
    candidates = _path_candidates(name)
    for folder in known_dirs():
        candidate = os.path.join(folder, name)
        if candidate not in candidates and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            candidates.append(candidate)
    for candidate in candidates:
        if works is None or works(candidate):
            return candidate
    return ""


def working_system_ffmpeg(name: str = "ffmpeg", *, retry_slow: bool = False) -> str:
    """The user's own FFmpeg that a download, a preview or the FLAC check runs.

    One answer for status() and every job, so Settings never names one system
    binary while a job runs another. A broken first candidate is passed over;
    one too slow to answer the probe is kept as a fallback. ``retry_slow`` lets
    a worker-thread caller give a slow binary a fresh probe once its pause is
    over, so a cold start that warmed up gets its version back; the GUI thread
    (status()) never re-forks on one.
    """
    hit = find_system_ffmpeg(name, works=lambda path: bool(probe_version(path)))
    if hit:
        return hit
    return find_system_ffmpeg(name, works=_probe_retry_slow if retry_slow else probe_was_slow)


# Probing a binary means fork+exec+wait on it, which can block for the whole
# timeout when the file lives on a hung/stale mount. status() runs on the GUI
# thread (it's the synchronous ffmpegStatus slot), so keep the timeout short and
# memoize by (path, size, mtime): the first probe pays the cost, repeated
# status() calls (Settings open, every ffmpegStatusChanged) reuse the result and
# never re-fork. A different binary at the same path (size/mtime change) evicts.
_probe_cache: dict[str, tuple[float, int, str]] = {}
# A binary that did not answer within the timeout (a cold start from snap, a
# virus scan of a large ffmpeg.exe on its first run) or hit a transient spawn
# error is not known to be broken: it stays a candidate (a fallback one, see
# working_system_ffmpeg), and a worker may probe it again once its pause is
# over. (mtime, size, monotonic deadline for the next probe.)
_probe_slow: dict[str, tuple[float, int, float]] = {}


def probe_version(path: str) -> str:
    """Return the ``ffmpeg version <x>`` (or ``ffprobe version <x>``) token,
    or "" if the binary won't run.

    Memoized per (path, mtime, size) so a repeated ``status()`` on the GUI
    thread doesn't re-fork a subprocess. A short timeout bounds the worst case
    (hung/stale-mount binary) instead of freezing the UI. A binary that timed
    out or hit a transient spawn error is recorded slow and cached as "", so
    status() does not fork it again.
    """
    try:
        st = os.stat(path)
    except OSError:
        _probe_cache.pop(path, None)
        return ""
    key = (st.st_mtime, st.st_size)
    cached = _probe_cache.get(path)
    if cached is not None and cached[:2] == key:
        return cached[2]
    return _spawn_probe(path, key)


def _spawn_probe(path: str, key: tuple[float, int]) -> str:
    """Fork the binary, record the result in the cache and slow record."""
    try:
        out = subprocess.run(
            [path, "-version"],
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT,
            creationflags=CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        _record_slow(path, key)
        return ""
    except OSError as exc:
        return _record_probe_error(path, key, exc)
    except Exception:
        _probe_slow.pop(path, None)
        _probe_cache[path] = (key[0], key[1], "")
        return ""
    ver = _version_token(out)
    _probe_slow.pop(path, None)
    _probe_cache[path] = (key[0], key[1], ver)
    return ver


def _version_token(out) -> str:
    """The version token in an ``-version`` answer, or "" for a nonzero exit."""
    if out.returncode != 0:
        return ""
    first = (out.stdout or "").split("\n", 1)[0]
    m = re.search(r"(?:ffmpeg|ffprobe) version (\S+)", first)
    return m.group(1) if m else first.strip()


def _record_slow(path: str, key: tuple[float, int]) -> None:
    _probe_slow[path] = (key[0], key[1], time.monotonic() + PROBE_SLOW_RETRY_S)
    _probe_cache[path] = (key[0], key[1], "")


def _record_probe_error(path: str, key: tuple[float, int], exc: OSError) -> str:
    """Classify a spawn error: permanent, chmod-repairable, or transient."""
    if exc.errno in _UNCACHED_PROBE_ERRORS:
        _probe_slow.pop(path, None)
        _probe_cache.pop(path, None)
    elif exc.errno in _PERMANENT_PROBE_ERRORS:
        _probe_slow.pop(path, None)
        _probe_cache[path] = (key[0], key[1], "")
    else:
        _record_slow(path, key)
    return ""


def probe_was_slow(path: str) -> bool:
    """Whether the last probe of ``path`` timed out (or failed transiently)."""
    try:
        st = os.stat(path)
    except OSError:
        return False
    rec = _probe_slow.get(path)
    return rec is not None and rec[:2] == (st.st_mtime, st.st_size)


def _probe_retry_slow(path: str) -> bool:
    """(worker thread) A slow binary (timed out or hit a transient spawn
    error), probed again once its pause is over: a cold start that warmed up
    answers (the cached empty version is replaced, so status() shows the real
    one from then on), while one that keeps hanging earns another pause and
    stays a last resort."""
    try:
        st = os.stat(path)
    except OSError:
        return False
    rec = _probe_slow.get(path)
    if rec is None or rec[:2] != (st.st_mtime, st.st_size):
        return False
    if time.monotonic() < rec[2]:
        return True
    # Keep the cached "" and slow record while the probe runs: a concurrent
    # status() on the GUI thread reads them and does not fork the same binary.
    return bool(_spawn_probe(path, (st.st_mtime, st.st_size))) or probe_was_slow(path)
