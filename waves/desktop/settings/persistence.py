"""Atomic preference/cache writes and the single background writer.

Callers snapshot values before submitting work. The writer serializes fsyncs,
coalesces pending writes by file, and drains them at application shutdown.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
import time
from collections.abc import Callable
from threading import Condition, Thread

logger = logging.getLogger("waves.settings")


def write_text_atomic(path_file: str, text: str) -> None:
    """Write a file so a crash mid-write cannot damage what is already there.

    Temp sibling, flushed to stable storage, then os.replace, which is atomic
    within one directory on POSIX and Windows alike. The fsync is the part that
    is easy to leave out and the part that matters: without it the rename can
    reach disk ahead of the bytes, so a power cut leaves an empty or partial
    file under the real name. These caches all self-heal, but healing means a
    fresh crawl or a lost set of preferences, which is dear next to one flush.
    Mirrors BaseConfig.save, which does the same for settings and token.

    The temp name is this write's OWN (mkstemp), for the same reason
    BaseConfig.save's is: nothing stops a second copy of Waves running against
    the same config folder, and two writers staging through one fixed ".tmp"
    sibling interleave into it, publish the mixture, and silently reset every
    preference on the next launch. The factory wipe knows this name shape.

    The temp file never outlives a failure, so a wedged write cannot leave
    litter next to the real file.

    Args:
        path_file (str): The destination file.
        text (str): The complete contents to write.
    """
    fd, path_tmp = tempfile.mkstemp(
        dir=os.path.dirname(path_file) or ".",
        prefix=f"{os.path.basename(path_file)}.",
        suffix=".tmp",
    )

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(path_tmp, path_file)
    except Exception:
        with contextlib.suppress(OSError):
            os.remove(path_tmp)

        raise


def write_json_atomic(path_file: str, payload, indent: int | None = None) -> None:
    """Serialize and write JSON through :func:`write_text_atomic`.

    Args:
        path_file (str): The destination file.
        payload: Anything json.dump accepts.
        indent (int | None, optional): Pretty-printing indent. Defaults to None.
    """
    write_text_atomic(path_file, json.dumps(payload, indent=indent))


class SingleFlightWriter:
    """One background thread owning the small config-file writes.

    The atomic writers above fsync, and both waves.json and settings.json were
    written from GUI-thread slots (every pref flip, every window-geometry
    debounce), so the GUI paid a disk sync per save. Callers snapshot
    their payload on their own thread (microseconds) and submit the disk work
    here keyed by file: consecutive submits for the same key coalesce to the
    NEWEST closure (latest snapshot wins, which is also what the old
    synchronous ordering produced), and the writes run one at a time, so the
    per-file tmp-sibling staging can never race itself. ``flush`` is the
    shutdown hook: it drains what is pending (inline if the thread cannot
    finish in time), so a pref set just before quit still lands."""

    def __init__(self, on_result: Callable[[str, Exception | None], None] | None = None) -> None:
        self._on_result = on_result
        self._cond = Condition()
        self._pending: dict[str, Callable] = {}
        self._writing = False
        self._thread = Thread(target=self._run, name="config-writer", daemon=True)
        self._thread.start()

    def submit(self, key: str, fn: Callable) -> None:
        with self._cond:
            self._pending[key] = fn
            self._cond.notify_all()

    def _write(self, key: str, fn: Callable) -> None:
        error = None
        try:
            fn()
        except Exception as exc:
            error = exc
            logger.exception("Background config write failed")
        if self._on_result is not None:
            try:
                self._on_result(key, error)
            except Exception:
                logger.exception("Config write result could not be delivered")

    def _run(self) -> None:
        while True:
            with self._cond:
                while not self._pending:
                    self._cond.wait()
                key = next(iter(self._pending))
                fn = self._pending.pop(key)
                self._writing = True
            try:
                self._write(key, fn)
            finally:
                with self._cond:
                    self._writing = False
                    self._cond.notify_all()

    def flush(self, timeout: float = 3.0) -> None:
        deadline = time.monotonic() + timeout
        with self._cond:
            while (self._pending or self._writing) and time.monotonic() < deadline:
                self._cond.wait(timeout=0.05)
            leftovers = list(self._pending.items())
            self._pending.clear()
        # Past the deadline with work still queued (a wedged disk, a dead
        # thread): write inline rather than lose a pref on quit.
        for key, fn in leftovers:
            self._write(key, fn)
