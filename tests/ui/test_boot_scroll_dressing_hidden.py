"""The launch screen is clean water: no scroll dressing paints over it.

WHAT THIS FENCES OFF
--------------------
The edge fades and the crest pill live in one window-level BackToTop, a
sibling of the main column rather than a child of it, so the reveal fade
that hides the interface during the launch sequence does not reach them.
The landing is scrollable from its first frame, so the bottom fade would
sit at full strength across the opening water (and the top fade too,
whenever the restored scroll position is off zero): a dark band over the
wordmark frame.

HOW THIS STAYS FIXED
--------------------
The instance carries opacity: root.bootContentShown, the same gate the
interface column and the login overlay use. This pins the dressing to
invisible while the launch frame is up and to fully present once the
handover has run.

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
def test_the_edge_fades_stay_off_the_launch_screen():
    run_scenario(Path(__file__), "--run-scenario", timeout=120, sandbox_prefix="waves-boot-dressing-test-")


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
        from waves.desktop.app import _load_mono
        from waves.desktop.backend import WavesBridge
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
    # dial by hand so the assertion is about the binding, not about timing.
    for stop in ("bootSeq", "bootHandover", "bootBlk", "handoverCap"):
        q(f"{stop}.stop()")
    q("bootOverlay.done = false")
    q("bootContentShown = 0")
    settle(60)
    hidden = float(q("scrollDressing.opacity"))

    q("bootContentShown = 1")
    settle(60)
    shown = float(q("scrollDressing.opacity"))

    ok = hidden == 0.0 and shown == 1.0
    print(f"during_launch={hidden} after_handover={shown}", flush=True)
    return EXIT_OK if ok else EXIT_REGRESSED


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_run_scenario())
