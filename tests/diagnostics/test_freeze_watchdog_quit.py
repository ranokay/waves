"""The freeze watchdog must not invent a freeze out of an ordinary quit.

WHAT THIS FENCES OFF
--------------------
The watchdog re-arms a faulthandler countdown from a GUI-thread timer; if the
event loop stalls past it, every thread's stack is appended to crash.log.

Quitting is the one time the GUI thread blocks on purpose. shutdown() drains
four worker pools after the event loop has already exited, up to eight seconds
of it, and the watchdog cannot tick through that. The countdown armed by the
last tick expired and wrote a full all-thread traceback, so a quit during a
download produced a freeze record for a freeze that never happened. Two things
made it worse: faulthandler writes straight to the descriptor without passing
the scrubber, and crash.log is rotated only at process start, so the fake
stacks accumulated and crowded the window export_bundle ships.

Pinned here:

* stopping the watchdog really does cancel the pending dump, proved by
  blocking past the deadline and finding the crash file still empty;
* shutdown() stops it BEFORE it starts draining the pools, not after.
"""

from __future__ import annotations

import faulthandler
import os
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from waves.desktop.diagnostics import export as diagnostics
from waves.desktop.queue.runtime import JobRuntime


def _qt_app():
    from support.qml import require_qt

    require_qt()
    from PySide6.QtCore import QCoreApplication

    return QCoreApplication.instance() or QCoreApplication([])


def _armed_watchdog(tmp_path, dump_sec=0.25):
    """Start the real watchdog against a temp crash file, armed to fire fast."""
    _qt_app()
    crash = tmp_path / "crash.log"
    handle = crash.open("a")
    diagnostics._watchdog.start(handle, dump_sec=dump_sec)  # start() ticks once, which arms the dump
    return crash, handle


@pytest.mark.qml
def test_set_verbose_off_arms_the_always_on_dump(tmp_path, monkeypatch):
    """The boot path with default prefs: set_verbose(False) must leave a dump
    armed at the always-on threshold, not stop the watchdog. Without this the
    freeze record exists only on verbose installs."""
    _qt_app()
    # Short arm for test speed; set_verbose reads the constant at call time.
    # raising=False so this test fails (not errors) before the constant exists.
    monkeypatch.setattr(diagnostics, "_WATCHDOG_ALWAYS_DUMP_SEC", 0.25, raising=False)
    crash = tmp_path / "crash.log"
    handle = crash.open("a")
    old_crash = diagnostics._crash_file
    diagnostics.set_crash_file(handle)
    try:
        diagnostics.set_verbose(False)
        time.sleep(0.6)  # stand in for a frozen event loop
    finally:
        diagnostics._watchdog.stop()
        faulthandler.cancel_dump_traceback_later()
        diagnostics.set_crash_file(old_crash)
        handle.close()
    assert "Timeout" in crash.read_text(), "default prefs left no freeze dump armed"


@pytest.mark.qml
def test_a_pending_dump_fires_when_the_thread_blocks(tmp_path):
    """The control. Without this the test below proves nothing: it would pass
    just as happily if the watchdog never armed anything in the first place."""
    crash, handle = _armed_watchdog(tmp_path)
    try:
        time.sleep(0.6)  # stand in for shutdown()'s pool drain
    finally:
        diagnostics._watchdog.stop()
        faulthandler.cancel_dump_traceback_later()
        handle.close()
    assert "Timeout" in crash.read_text(), "the watchdog never armed, so this file's other test is vacuous"


@pytest.mark.qml
def test_stopping_the_watchdog_cancels_the_pending_dump(tmp_path):
    crash, handle = _armed_watchdog(tmp_path)
    try:
        diagnostics.stop_freeze_watchdog()
        time.sleep(0.6)  # the same block, now with the watchdog stopped
    finally:
        faulthandler.cancel_dump_traceback_later()
        handle.close()
    assert crash.read_text() == "", f"a quit still wrote a freeze dump:\n{crash.read_text()[:400]}"


def test_the_dump_wait_leaves_a_full_tick_of_headroom():
    """Every tick re-arms the countdown, so what the dump measures is the gap
    between two TICKS, not the wait itself. At a 2.5s wait on a 2s tick only
    0.5s of it was headroom, and a block starting just before a tick was due
    fired a full dump after half a second: the effective threshold was 0.5s or
    2.5s depending on nothing but phase."""
    tick = diagnostics._WATCHDOG_TICK_MS / 1000.0
    shortest_stall_that_dumps = diagnostics._WATCHDOG_DUMP_SEC - tick
    assert shortest_stall_that_dumps >= diagnostics._WATCHDOG_STALL_TARGET_SEC, (
        f"a {shortest_stall_that_dumps:.1f}s stall dumps every thread's stack, "
        f"but the target is {diagnostics._WATCHDOG_STALL_TARGET_SEC}s"
    )


def test_shutdown_stops_the_watchdog_before_it_drains_the_pools():
    """Order is the whole point: stopping it afterwards is stopping it after
    the drain has already blocked long enough to fire the dump."""
    from waves.desktop.backend import WavesBridge

    order: list[str] = []

    class _Pool:
        def __init__(self, name):
            self._name = name

        def clear(self):
            pass

        def waitForDone(self, _ms):
            order.append(f"drain:{self._name}")
            return True

    class _Store:
        def close(self):
            pass

    stub = SimpleNamespace(
        _teardown_library_watch=lambda: None,
        _library_gen=0,
        _event_abort=None,
        _jobs=JobRuntime(),
        _event_run=None,
        _ffmpeg_abort=None,
        dl_pool=_Pool("dl"),
        _scan_pool=_Pool("scan"),
        threadpool=_Pool("threadpool"),
        _own_pool=_Pool("own"),
        _ownership=_Store(),
        _library=_Store(),
        _preview_clips={},
    )

    real_stop = diagnostics.stop_freeze_watchdog
    diagnostics.stop_freeze_watchdog = lambda: order.append("watchdog-stopped")  # type: ignore[assignment]
    try:
        WavesBridge.shutdown(stub)
    finally:
        diagnostics.stop_freeze_watchdog = real_stop  # type: ignore[assignment]

    assert "watchdog-stopped" in order, "shutdown() never stopped the freeze watchdog"
    assert order.index("watchdog-stopped") < min(i for i, step in enumerate(order) if step.startswith("drain:")), (
        f"the watchdog was still armed while the pools drained: {order}"
    )


_EXIT_PROBE = """
import faulthandler, sys
from PySide6.QtCore import QCoreApplication
from waves.desktop.diagnostics import export as diagnostics

app = QCoreApplication([])
real_cancel = faulthandler.cancel_dump_traceback_later
def cancel():
    print("CANCELLED-AT-EXIT", flush=True)
    real_cancel()
faulthandler.cancel_dump_traceback_later = cancel
diagnostics._watchdog.start(None)  # arms the countdown, and nothing stops it
"""


@pytest.mark.qml
def test_a_countdown_still_armed_at_exit_is_cancelled_before_teardown():
    """A countdown left armed when the interpreter exits fires from inside
    Py_FinalizeEx, where faulthandler walks frames that are already being
    freed and can spin forever: the process prints its last line and then sits
    at 100% CPU. That is how the test suite itself hung after one in-process
    bridge started the watchdog. shutdown() covers the normal quit; this pins
    the net for every other exit: the module cancels the dump at atexit, which
    runs before faulthandler's own teardown."""
    from support.qml import require_qt

    require_qt()
    proc = subprocess.run(
        [sys.executable, "-c", _EXIT_PROBE],
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
    )
    assert proc.returncode == 0, proc.stderr[-800:]
    assert "CANCELLED-AT-EXIT" in proc.stdout, (
        "the armed freeze-watchdog countdown was never cancelled at interpreter exit:\n" + proc.stderr[-800:]
    )
