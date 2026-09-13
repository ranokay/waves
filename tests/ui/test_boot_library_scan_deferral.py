"""The launch library sweep waits for the boot reveal.

THE STUTTER THIS FENCES OFF
---------------------------
The first library scan used to start inside the bridge constructor, so its
directory walk ran on pool threads through the whole launch sequence. Python
threads hold the interpreter between syscalls, the GUI thread must run for
every frame the boot water presents, and the probe showed exactly that
arithmetic on screen: 59-73 ms GUI stalls with the walk busy, the water
visibly stuttering under the wordmark (livetest report, 2026-09-01).

Construction now dispatches only the cheap badge seed (a sqlite read) and
parks the sweep behind a pending flag; the QML reveal (bootRevealed) or a
failsafe timer releases it, whichever comes first, and the release is
one-shot so the loser is a no-op.

Runs the REAL bridge constructor in a SUBPROCESS, like the QML scenarios and
for the same reason: building the bridge installs process-global handlers
that must not leak into the suite. No QML is loaded; bootRevealed is called
directly, which is exactly what the overlay's zoom tail does.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from support.offline import patch_offline
from support.qml import EXIT_NO_QT, EXIT_OK, run_scenario, sandbox_qml_settings

_EXIT_SCANNED_AT_BOOT = 1  # the constructor claimed the sweep itself
_EXIT_NOT_ARMED = 2  # nothing pending and no failsafe: the sweep is simply lost
_EXIT_NOT_RELEASED = 3  # bootRevealed left the sweep parked
_EXIT_RERELEASED = 4  # a second release dispatched a second sweep


@pytest.mark.qml
def test_the_launch_sweep_waits_for_the_reveal():
    run_scenario(
        Path(__file__),
        "--run-scenario",
        timeout=120,
        sandbox_prefix="waves-boot-scan-defer-",
        failure_message="the boot sweep deferral regressed",
    )


def _run_scenario() -> int:
    try:
        from PySide6.QtGui import QGuiApplication
    except Exception as exc:  # pragma: no cover - environment guard
        print(f"Qt unavailable: {exc}", file=sys.stderr)
        return EXIT_NO_QT

    patch_offline()
    QGuiApplication.instance() or QGuiApplication([])
    sandbox_qml_settings()
    try:
        from waves.waves_ui.backend import WavesBridge
    except Exception as exc:  # pragma: no cover - environment guard
        print(f"Qt platform/backend unavailable: {exc}", file=sys.stderr)
        return EXIT_NO_QT

    bridge = WavesBridge(tidal=None)

    # The constructor's contract: the sweep is parked, not started. The
    # sandbox has no library folder configured, but that must not matter:
    # the deferral is decided before the root is even read, or a configured
    # machine would be back to scanning under the boot water.
    if bridge._library_index_building:
        print("a scan was already claimed during construction", file=sys.stderr)
        return _EXIT_SCANNED_AT_BOOT
    if not getattr(bridge, "_boot_library_scan_pending", False) or not bridge._boot_library_scan_timer.isActive():
        print("no pending flag or no running failsafe timer after construction", file=sys.stderr)
        return _EXIT_NOT_ARMED

    # The reveal releases it: the pending flag drops and the rebuild is
    # dispatched. Counted through _rebuild_library_index so the assert holds
    # whether or not a root is configured.
    releases: list = []
    orig = bridge._rebuild_library_index
    bridge._rebuild_library_index = lambda **kw: (releases.append(kw), orig(**kw))[1]
    bridge.bootRevealed()
    if len(releases) != 1 or getattr(bridge, "_boot_library_scan_pending", True):
        print(f"after bootRevealed: releases={len(releases)}, pending flag not cleared", file=sys.stderr)
        return _EXIT_NOT_RELEASED
    if bridge._boot_library_scan_timer.isActive():
        print("the failsafe timer is still armed after the release", file=sys.stderr)
        return _EXIT_NOT_RELEASED

    # One-shot: a stray second reveal (or the failsafe losing the race) must
    # not dispatch a second sweep.
    bridge.bootRevealed()
    bridge._start_boot_library_scan()
    if len(releases) != 1:
        print(f"a second release dispatched again: releases={len(releases)}", file=sys.stderr)
        return _EXIT_RERELEASED
    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_run_scenario())
