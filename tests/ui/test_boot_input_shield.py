"""The launch screen is inert: nothing under it takes clicks or hover.

WHAT THIS FENCES OFF
--------------------
The interface hides during the launch sequence by opacity alone, and opacity
does not gate input in Qt Quick. Every control on the Browse landing was
therefore live while invisible: the cursor flipped to the pointing hand over
buttons nobody could see, and a click on the opening water could land on a
preview control and start full-volume audio with no player on screen
(reported as issue #13, "Waves autoplayed on startup").

HOW THIS STAYS FIXED
--------------------
Two gates, both driven by the same reveal dial (root.bootContentShown):

1. bootShield, a MouseArea filling bootOverlay, eats clicks, hover, and
   wheel while the dial is at 0 and stands down the moment the reveal
   starts painting the content.
2. mainColumn carries enabled: bootContentShown > 0, so the whole interface
   subtree (its MouseAreas AND its pointer handlers, which a covering
   MouseArea alone would not silence) is disabled while invisible.

Runs in a SUBPROCESS for the same reason as the other boot scenarios:
building the bridge installs process-global handlers that must not leak
into the rest of the suite.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from support.paths import QML_MAIN
from support.qml import (
    EXIT_NO_QT,
    EXIT_OK,
    EXIT_PRECONDITION,
    EXIT_REGRESSED,
    run_scenario,
    sandbox_qml_settings,
)


@pytest.mark.qml
def test_the_launch_screen_blocks_input_until_the_reveal():
    run_scenario(Path(__file__), "--run-scenario", timeout=120, sandbox_prefix="waves-boot-shield-test-")


def _run_scenario() -> int:
    try:
        from PySide6.QtCore import QEventLoop, QTimer, QUrl
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtQml import QQmlApplicationEngine, QQmlEngine, QQmlExpression
    except Exception as exc:
        print(f"Qt unavailable: {exc}", file=sys.stderr)
        return EXIT_NO_QT

    app = QGuiApplication.instance() or QGuiApplication([])
    sandbox_qml_settings()
    try:
        from waves.waves_ui.app import _load_mono
        from waves.waves_ui.backend import WavesBridge
    except Exception as exc:
        print(f"Qt platform/backend unavailable: {exc}", file=sys.stderr)
        return EXIT_NO_QT

    engine = QQmlApplicationEngine()
    bridge = WavesBridge(tidal=None)
    engine.rootContext().setContextProperty("waves", bridge)
    engine.rootContext().setContextProperty("monoFont", _load_mono())
    engine.rootContext().setContextProperty("uiFontFamily", app.font().family())
    engine.load(QUrl.fromLocalFile(str(QML_MAIN)))
    roots = engine.rootObjects()
    if not roots:
        print("Main.qml failed to load", file=sys.stderr)
        return EXIT_PRECONDITION
    root = roots[0]

    def q(expr: str):
        ctx = QQmlEngine.contextForObject(root)
        e = QQmlExpression(ctx, root, expr)
        r = e.evaluate()
        if e.hasError():
            raise RuntimeError(e.error().toString())
        return r[0] if isinstance(r, tuple) else r

    def settle(ms: int) -> None:
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    settle(120)
    # Back to the launch frame: silence the sequence, then drive the reveal
    # dial by hand so the assertions are about the bindings, not timing.
    for stop in ("bootSeq", "bootHandover", "bootBlk", "handoverCap"):
        q(f"{stop}.stop()")
    q("bootOverlay.done = false")
    q("bootContentShown = 0")
    settle(60)
    launch_shielded = bool(q("bootShield.enabled")) and bool(q("bootShield.hoverEnabled"))
    launch_inert = not bool(q("mainColumn.enabled"))
    # The shield must sit inside the overlay, over the wordmark frame.
    launch_covering = bool(q("bootShield.parent === bootOverlay")) and bool(
        q("bootShield.width === bootOverlay.width && bootShield.height === bootOverlay.height")
    )

    q("bootContentShown = 1")
    settle(60)
    revealed_open = bool(q("mainColumn.enabled")) and not bool(q("bootShield.enabled"))

    ok = launch_shielded and launch_inert and launch_covering and revealed_open
    print(
        f"launch_shielded={launch_shielded} launch_inert={launch_inert} "
        f"launch_covering={launch_covering} revealed_open={revealed_open}",
        flush=True,
    )
    return EXIT_OK if ok else EXIT_REGRESSED


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_run_scenario())
