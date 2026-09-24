"""The wordmark fade must not share its frames with the landing build.

WHAT THIS FENCES OFF
--------------------
On a warm cache the Browse landing payload arrives ~1.5s into launch, in
the middle of the boot wordmark's 900ms fade-up (bootIntro). Applying it
there costs the fade its frames: even the asynchronous build's section
shells drop a visible frame gap, and the fade stutters. onBrowseLoaded parks
a first build that arrives while bootIntro is running, and bootIntro's
onFinished applies it the moment the composed mark is still.

HOW THIS STAYS FIXED
--------------------
Three behaviors, each asserted here:
1. A non-error payload arriving mid-fade with nothing on screen is parked,
   not applied.
2. The parked payload is applied when the fade finishes.
3. An error payload goes straight through even mid-fade: the boot's error
   path must never sit on the wordmark.

Runs in a SUBPROCESS for the same reason as test_boot_handover_gate:
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
    checkpoint,
    run_scenario,
    sandbox_qml_settings,
    wait_until,
)


@pytest.mark.qml
def test_fade_parks_the_first_landing_and_applies_it_after():
    run_scenario(Path(__file__), "--run-scenario", timeout=120, sandbox_prefix="waves-fade-park-test-")


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

    class _QuietBridge(WavesBridge):
        # Same silencing as test_boot_handover_gate: payloads in this scenario
        # are driven by hand, never by a real fetch.
        def loadBrowse(self) -> None:
            return

    engine = QQmlApplicationEngine()
    bridge = _QuietBridge(tidal=None)
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

    def settle(ms: int = 120) -> None:
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    settle()  # one wall-clock beat so the engine finishes loading; state below polls
    # Freeze the boot machinery so the fade state is driven purely by this
    # scenario. Payloads carry no sections, so no delegate ever incubates:
    # browseChips is the applied/not-applied witness.
    q("bootSeq.stop()")
    q("bootHandover.stop()")
    q("bootBlk.stop()")
    q("bootZoom.stop()")
    q("handoverCap.stop()")
    q("bootOverlay.done = false")
    q("browseSections = []")
    q("_browseParked = null")

    # 1. Mid-fade, first build: the payload must park, not apply.
    checkpoint("fade-park")
    q("bootIntro.restart()")
    try:
        wait_until(lambda: bool(q("bootIntro.running")), message="fade-park: bootIntro running")
    except AssertionError:
        print("CHECKPOINT fade-park FAILED: could not hold bootIntro running", file=sys.stderr)
        return EXIT_PRECONDITION
    bridge.browseLoaded.emit({"sections": [], "genres": ["parked-genre"], "moods": [], "decades": [], "error": False})
    try:
        wait_until(lambda: bool(q("_browseParked !== null")), message="fade-park: payload parked")
    except AssertionError:
        print("CHECKPOINT fade-park FAILED: mid-fade payload was not parked", file=sys.stderr)
        return EXIT_REGRESSED
    if q("(browseChips.genres || []).length") != 0:
        print("CHECKPOINT fade-park FAILED: mid-fade payload was applied during the fade", file=sys.stderr)
        return EXIT_REGRESSED

    # 2. The fade finishing must apply the parked payload.
    checkpoint("fade-apply")
    q("bootIntro.complete()")
    try:
        wait_until(lambda: bool(q("_browseParked === null")), message="fade-apply: parked applied")
    except AssertionError:
        print("CHECKPOINT fade-apply FAILED: parked payload still held after the fade", file=sys.stderr)
        return EXIT_REGRESSED
    if q("(browseChips.genres || [])[0]") != "parked-genre":
        print("CHECKPOINT fade-apply FAILED: parked payload was not applied when the fade finished", file=sys.stderr)
        return EXIT_REGRESSED

    # 3. An error payload mid-fade must go straight through.
    checkpoint("fade-error-passthrough")
    q("browseSections = []")
    q("browseChips = ({ genres: [], moods: [], decades: [] })")
    q("browseError = false")
    q("bootIntro.restart()")
    try:
        wait_until(lambda: bool(q("bootIntro.running")), message="fade-error-passthrough: bootIntro running")
    except AssertionError:
        print("CHECKPOINT fade-error-passthrough FAILED: could not hold bootIntro running", file=sys.stderr)
        return EXIT_PRECONDITION
    bridge.browseLoaded.emit({"sections": [], "genres": [], "moods": [], "decades": [], "error": True})
    try:
        wait_until(lambda: bool(q("browseError")), message="fade-error-passthrough: error applied")
    except AssertionError:
        print("CHECKPOINT fade-error-passthrough FAILED: error payload did not apply during the fade", file=sys.stderr)
        return EXIT_REGRESSED
    if not bool(q("_browseParked === null")):
        print("CHECKPOINT fade-error-passthrough FAILED: error payload was parked instead of applied", file=sys.stderr)
        return EXIT_REGRESSED
    q("bootIntro.stop()")

    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_run_scenario())
