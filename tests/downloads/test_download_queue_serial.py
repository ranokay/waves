"""The download queue runs ONE item at a time, strictly in queue order.

WHAT THIS FENCES OFF
--------------------
Parallelism belongs inside a collection (the engine's per-collection track
executor, sized by downloads_concurrent_max, which it reads live from settings
on each run), never to the queue: a 21-track album whose tracks carry the 3-5s
anti-hammer delay and share the 10-connection HTTP pool must not be overtaken
by single tracks queued after it. The queue's promise is order.

So two things must hold:
1. dl_pool is created with exactly one thread, regardless of the setting.
2. Saving settings must NOT resize dl_pool back up.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from waves.desktop import backend as backend_mod

BACKEND_SRC = Path(inspect.getsourcefile(backend_mod))


def _source() -> str:
    return BACKEND_SRC.read_text(encoding="utf-8")


# Source pins, not behavior coverage: these fence the serial-queue wiring in
# backend.py (constructing a full bridge needs the Qt session, so there is no
# cheaper seam). The user-facing promise — one item at a time, in order — is
# proved behaviorally by test_a_one_thread_pool_actually_runs_submissions_in_order
# below.


def test_wiring_dl_pool_is_serial():
    """backend.py still creates dl_pool with an explicit one-thread cap."""
    src = _source()
    m = re.search(r"self\.dl_pool = QtCore\.QThreadPool\(\).*?setMaxThreadCount\(([^)]*)\)", src, re.DOTALL)
    assert m, "dl_pool must still be created with an explicit thread cap"
    assert m.group(1).strip() == "1", (
        f"dl_pool sized to {m.group(1).strip()!r}: the queue must stay serial "
        "(one item at a time, in order); track-level parallelism belongs to the "
        "engine's per-collection executor, not here"
    )


def test_wiring_settings_save_never_resizes_the_pool():
    """The settings save path adds no second setMaxThreadCount: the serial order
    above must survive a save, and the knob below keeps its meaning through the
    engine's own executor instead."""
    src = _source()
    assert src.count("dl_pool.setMaxThreadCount") == 1, (
        "a second setMaxThreadCount call would widen the queue back out from under the serial design"
    )


def test_wiring_the_knob_still_reaches_the_track_executor():
    """downloads_concurrent_max still sizes the engine's per-collection executor
    (read live at download time). Behaviorally backed by the held-download and
    queue-withdrawal suites that drive downloads_concurrent_max; this pins the
    wiring so the knob cannot be silently dropped from the executor call."""
    """downloads_concurrent_max must keep meaning something: the engine's
    per-collection executor is sized by it, read live at download time."""
    from waves import download as engine_dl

    src = Path(inspect.getsourcefile(engine_dl)).read_text(encoding="utf-8")
    assert "max_workers=self.settings.data.downloads_concurrent_max" in src


@pytest.mark.qml
def test_a_one_thread_pool_actually_runs_submissions_in_order():
    """Behavioral pin, not a source grep: the serial design leans on
    QThreadPool draining equal-priority runnables in submission order, so
    prove it with a real pool rather than assuming it."""
    from threading import Event

    from PySide6.QtCore import QRunnable, QThreadPool

    order: list[int] = []
    done = Event()

    class _Job(QRunnable):
        def __init__(self, i: int):
            super().__init__()
            self.i = i

        def run(self) -> None:
            order.append(self.i)
            if self.i == 19:
                done.set()

    pool = QThreadPool()
    pool.setMaxThreadCount(1)
    for i in range(20):
        pool.start(_Job(i))
    assert done.wait(10), "the pool never drained"
    pool.waitForDone(10000)
    assert order == list(range(20)), "queue items ran out of submission order"
