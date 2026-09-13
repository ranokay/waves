"""A slow Apple probe never freezes the window.

The setup refresh re-probes the container runtime on a worker precisely so a
slow runtime (a cold Docker daemon, a stretched API call) cannot hold the GUI
thread: the frame clock keeps ticking, a queue row's cancel still lands, and
the drawer still opens while the probe sleeps. The scenario runs the real
Main.qml with a deliberately delayed probe and counts GUI-loop heartbeats.
"""

from __future__ import annotations

import sys
import time

import pytest
from support.qml import (
    EXIT_OK,
    EXIT_REGRESSED,
    boot_main_qml,
    run_scenario,
)


@pytest.mark.qml
def test_a_slow_setup_probe_keeps_the_event_loop_responsive():
    run_scenario(
        __file__,
        "--run-scenario",
        timeout=180,
        sandbox_prefix="waves-apple-probe-responsive-",
        failure_message="the window froze while the setup probe ran",
    )


def _run_scenario() -> int:
    booted = boot_main_qml()
    if isinstance(booted, int):
        return booted
    _root, q, settle, bridge = booted

    from PySide6.QtCore import QEventLoop, QTimer

    def slow_probe(timeout=10):
        time.sleep(1.2)
        return {"name": "docker", "available": True, "running": False, "hint": ""}

    bridge._refresh_apple_container_cache = slow_probe
    states: list[str] = []
    bridge.appleRuntimeStateChanged.connect(lambda *a: states.append(str(a[0]) if a else ""))

    failures = []
    qid = bridge._enqueue("Probe Row", "track", media_id="probe-1", artist="Lab", tracks=0)
    bridge._emit_queue()
    settle(100)

    ticks: list[int] = []
    loop = QEventLoop()
    heartbeat = QTimer()
    heartbeat.setInterval(25)
    heartbeat.timeout.connect(lambda: ticks.append(1))
    heartbeat.start()
    bridge.refreshAppleSetup()

    # Half the probe in: the event loop must have ticked again and again, and
    # the probe must still be in flight (or the delay proved nothing).
    QTimer.singleShot(600, loop.quit)
    loop.exec()
    heartbeat.stop()
    if len(ticks) < 10:
        failures.append(f"the event loop ticked only {len(ticks)} times during the probe")
    if "done" in states:
        failures.append("the delayed probe finished before its delay, so nothing was delayed")

    # A cancel and a drawer open still land while the worker sleeps.
    if next((it for it in bridge._queue if int(it["qid"]) == qid), None) is None:
        failures.append("the queued row was never in the queue")
    bridge.cancelQueueItem(qid)
    settle(100)
    if next((it for it in bridge._queue if int(it["qid"]) == qid), None) is not None:
        failures.append("a cancel did not land during the probe")
    q("queueDrawer.open()")
    settle(150)
    if not bool(q("queueDrawer.visible")):
        failures.append("the queue drawer would not open while the probe ran")

    waited = 0
    while "done" not in states and waited < 5000:
        settle(50)
        waited += 50
    if "downloading" not in states or "done" not in states:
        failures.append(f"the refresh did not show checking then done: {states}")

    if failures:
        for line in failures:
            print(line, file=sys.stderr)
        return EXIT_REGRESSED
    print("ok")
    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    sys.exit(_run_scenario())
