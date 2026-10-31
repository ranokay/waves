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
#: How long a timed-out binary waits before a worker may probe it again.
PROBE_SLOW_RETRY_S = 60.0


def known_dirs() -> tuple[str, ...]:
    """Folders the user's package managers install into, per platform."""
    if sys.platform == "darwin":
        return ("/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin")
    if sys.platform.startswith("win"):
        return ()
    return ("/usr/local/bin", "/usr/bin", "/home/linuxbrew/.linuxbrew/bin", "/snap/bin")


def find_system_ffmpeg(name: str = "ffmpeg", works: Callable[[str], bool] | None = None) -> str:
    """Path to an FFmpeg on PATH or in a package manager's folder, else "".
    With ``works``, a candidate it rejects (a broken install left behind) is
    passed over for the next one."""
    found = shutil.which(name)
    candidates = [found] if found else []
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
    return find_system_ffmpeg(name, works=_probe_retry_slow if retry_slow else _probe_was_slow)


# Probing a binary means fork+exec+wait on it, which can block for the whole
# timeout when the file lives on a hung/stale mount. status() runs on the GUI
# thread (it's the synchronous ffmpegStatus slot), so keep the timeout short and
# memoize by (path, size, mtime): the first probe pays the cost, repeated
# status() calls (Settings open, every ffmpegStatusChanged) reuse the result and
# never re-fork. A different binary at the same path (size/mtime change) evicts.
_probe_cache: dict[str, tuple[float, int, str]] = {}
# A binary that did not answer within the timeout (a cold start from snap, a
# virus scan of a large ffmpeg.exe on its first run) is not known to be
# broken: it stays a candidate (a fallback one, see working_system_ffmpeg),
# and a worker may probe it again once its pause is over. (mtime, size,
# monotonic deadline for the next probe.)
_probe_slow: dict[str, tuple[float, int, float]] = {}


def probe_version(path: str) -> str:
    """Return the ``ffmpeg version <x>`` (or ``ffprobe version <x>``) token,
    or "" if the binary won't run.

    Memoized per (path, mtime, size) so a repeated ``status()`` on the GUI
    thread doesn't re-fork a subprocess. A short timeout bounds the worst case
    (hung/stale-mount binary) instead of freezing the UI. A binary that timed
    out is recorded slow and cached as "", so status() does not fork it again.
    """
    try:
        st = os.stat(path)
        key = (st.st_mtime, st.st_size)
    except OSError:
        _probe_cache.pop(path, None)
        return ""
    cached = _probe_cache.get(path)
    if cached is not None and cached[:2] == key:
        return cached[2]
    try:
        out = subprocess.run(
            [path, "-version"],
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT,
            creationflags=CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        _probe_slow[path] = (key[0], key[1], time.monotonic() + PROBE_SLOW_RETRY_S)
        _probe_cache[path] = (key[0], key[1], "")
        return ""
    except Exception:
        # A file that cannot exec (wrong arch, no read permission, a stale
        # mount) will not answer on the next status() either: memoize it so
        # the GUI thread forks it once, not once per call.
        _probe_cache[path] = (key[0], key[1], "")
        return ""
    if out.returncode != 0:
        ver = ""
    else:
        first = (out.stdout or "").splitlines()[0] if out.stdout else ""
        m = re.search(r"(?:ffmpeg|ffprobe) version (\S+)", first)
        ver = m.group(1) if m else (first.strip() or "")
    _probe_cache[path] = (key[0], key[1], ver)
    return ver


def _probe_was_slow(path: str) -> bool:
    try:
        st = os.stat(path)
    except OSError:
        return False
    rec = _probe_slow.get(path)
    return rec is not None and rec[:2] == (st.st_mtime, st.st_size)


def _probe_retry_slow(path: str) -> bool:
    """(worker thread) A slow binary, probed again once its pause is over: a
    cold start that warmed up answers (the cached empty version is replaced,
    so status() shows the real one from then on), while one that keeps
    hanging earns another pause and stays a last resort."""
    try:
        st = os.stat(path)
    except OSError:
        return False
    rec = _probe_slow.get(path)
    if rec is None or rec[:2] != (st.st_mtime, st.st_size):
        return False
    if time.monotonic() < rec[2]:
        return True
    _probe_cache.pop(path, None)  # the timeout's cached "" would answer instead
    _probe_slow.pop(path, None)  # a fresh timeout below re-adds it
    return bool(probe_version(path)) or _probe_was_slow(path)
