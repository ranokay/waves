"""The interface is painted before the launch zoom reveals it.

WHAT THIS FENCES OFF
--------------------
Qt Quick's renderer skips a subtree whose opacity is 0: nothing in it is
rastered, uploaded, or built until the frame it first becomes visible. The
interface hides that way during the launch sequence, so the whole Browse
page (every texture, every glyph, every material) was paid for in a single
frame, and the reveal starts 350ms into a 700ms wordmark zoom. The result
was a hitch in the middle of the zoom, in the same place every launch,
because the reveal always begins in the same place.

HOW THIS STAYS FIXED
--------------------
root.bootWarming lifts the interface to 0.004 while the version readout
drains, which is above the renderer's 0.001 skip threshold and far below
anything an eye can see over the launch scrim. The heavy first frame is
spent during the drain, where the only thing moving is a text readout on
its own timer.

Two ways this could regress, both pinned here:

1. warming wired to bootContentShown instead of its own dial, which would
   also ungate input and drop the launch shield (the interface must stay inert
   and shielded while invisible);
2. the warm starting with the zoom rather than before it, which would put
   the first frame back inside the animation it was moved out of.

The behavioral half runs in a SUBPROCESS for the same reason as the other
boot scenarios: building the bridge installs process-global handlers that
must not leak into the rest of the suite.
"""

from __future__ import annotations

import re
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


def test_the_warm_runs_before_the_zoom_not_inside_it():
    src = QML_MAIN.read_text()

    # The drain's starter arms the warm; the zoom is started later, by the
    # drain's own last tick (see test_boot_version_drain_order).
    handover = src[src.index("id: bootHandover") :]
    handover = handover[: handover.index("SequentialAnimation {")]
    assert "root.bootWarming = true" in handover, "the warm no longer starts with the version drain"
    assert "bootBlk.restart()" in handover

    zoom = src[src.index("id: bootZoom") :]
    zoom = zoom[: zoom.index("\n        }")]
    assert "bootWarming" not in zoom, "the warm moved into the zoom, which is the frame it exists to spare"


def test_warming_is_not_the_reveal_dial():
    # bootContentShown ungates input. If warming rode it, the
    # interface would be live under the launch screen again.
    src = QML_MAIN.read_text()

    assert re.search(r"property bool bootWarming: false", src)
    # The interface's own gate is uiShown, the dial folded together with a
    # pending terms gate: same input gating, and nothing paints while an
    # agreement is owed.
    assert "readonly property real uiShown: termsGate.wanted ? 0 : bootContentShown" in src
    assert "enabled: root.uiShown > 0" in src
    assert "enabled: root.bootContentShown === 0" in src  # the shield


@pytest.mark.qml
def test_the_interface_is_rendered_but_invisible_and_inert_while_warming():
    run_scenario(Path(__file__), "--run-scenario", timeout=120, sandbox_prefix="waves-boot-warm-test-")


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

    settle(120)  # one wall-clock beat so the engine finishes loading; state below polls
    # Back to the launch frame, then drive the dials by hand so the
    # assertions are about the bindings rather than about timing.
    for stop in ("bootSeq", "bootHandover", "bootBlk", "handoverCap", "bootZoom"):
        q(f"{stop}.stop()")
    q("bootOverlay.done = false")
    q("bootContentShown = 0")
    q("bootWarming = false")
    try:
        wait_until(lambda: float(q("mainColumn.opacity")) == 0.0, message="prewarm: cold frame hidden")
    except AssertionError:
        print("CHECKPOINT prewarm-cold FAILED: interface is not hidden at launch", file=sys.stderr)
        return EXIT_REGRESSED
    # Before the drain: nothing of the interface is drawn at all.
    cold = float(q("mainColumn.opacity")) == 0.0

    checkpoint("prewarm-warm")
    q("bootWarming = true")
    try:
        wait_until(lambda: float(q("mainColumn.opacity")) > 0.001, message="prewarm-warm: page painted")
    except AssertionError:
        print("CHECKPOINT prewarm-warm FAILED: warming never painted the page", file=sys.stderr)
        return EXIT_REGRESSED
    warm_op = float(q("mainColumn.opacity"))
    # Above the renderer's skip threshold, so the page is actually painted...
    rendered = warm_op > 0.001
    # ... and far below anything visible over the launch scrim.
    unseen = warm_op < 0.02
    # Warming must leave the interface inert and shielded.
    inert = not bool(q("mainColumn.enabled")) and bool(q("bootShield.enabled"))

    # The reveal still owns the fade: warming cannot clamp or offset it.
    checkpoint("prewarm-reveal")
    q("bootContentShown = 0.5")
    try:
        wait_until(
            lambda: abs(float(q("mainColumn.opacity")) - 0.5) < 1e-6, message="prewarm-reveal: reveal owns the fade"
        )
    except AssertionError:
        print("CHECKPOINT prewarm-reveal FAILED: warming clamped the reveal dial", file=sys.stderr)
        return EXIT_REGRESSED
    reveal_exact = abs(float(q("mainColumn.opacity")) - 0.5) < 1e-6
    q("bootContentShown = 1")
    try:
        wait_until(
            lambda: bool(q("mainColumn.enabled")) and not bool(q("bootShield.enabled")),
            message="prewarm-reveal: interface open",
        )
    except AssertionError:
        print("CHECKPOINT prewarm-reveal FAILED: interface did not open on reveal", file=sys.stderr)
        return EXIT_REGRESSED
    revealed_open = bool(q("mainColumn.enabled")) and not bool(q("bootShield.enabled"))

    ok = cold and rendered and unseen and inert and reveal_exact and revealed_open
    print(
        f"cold={cold} warm_opacity={warm_op} rendered={rendered} unseen={unseen} "
        f"inert={inert} reveal_exact={reveal_exact} revealed_open={revealed_open}",
        flush=True,
    )
    return EXIT_OK if ok else EXIT_REGRESSED


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_run_scenario())
