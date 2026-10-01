"""A pointer resting on a video result actually starts its preview.

The grid thumbnails restart their dwell when the pointer MOVES, so a cursor
travelling across the results never fires a preview. Rest has to be measured
from the pointer's own travel, not from raw point updates: hover effects move
the thumbnail under a still cursor, which re-delivers hover events every
frame, and restarting on those held the dwell off forever (the preview simply
never started). This drives the real Main.qml: move onto a thumbnail, hold
still, and assert the dwell completes and the peek opens.
"""

from __future__ import annotations

import json
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
    seed_tidal_search,
)

_VIDEO = (
    '{"id":"v1","title":"House On Fire","artist":"Rise Against","artists":[],'
    '"art":"","art_big":"","duration":"3:33","explicit":false,"added":"",'
    '"date":"2018-01-09","quality":"1080p"}'
)


@pytest.mark.qml
def test_resting_on_a_video_result_opens_the_peek():
    run_scenario(
        Path(__file__),
        "--run-scenario",
        timeout=180,
        sandbox_prefix="waves-video-dwell-test-",
        failure_message="a pointer resting on a video result no longer starts its preview",
    )


def _run_scenario() -> int:
    try:
        from PySide6.QtCore import QEventLoop, QPoint, QTimer, QUrl
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtQml import QQmlApplicationEngine, QQmlEngine, QQmlExpression
        from PySide6.QtQuick import QQuickWindow
        from PySide6.QtTest import QTest
    except Exception as exc:  # pragma: no cover - environment guard
        print(f"Qt unavailable: {exc}", file=sys.stderr)
        return EXIT_NO_QT

    app = QGuiApplication.instance() or QGuiApplication([])
    sandbox_qml_settings()
    try:
        from waves.desktop.app import _load_mono
        from waves.desktop.backend import WavesBridge
    except Exception as exc:  # pragma: no cover - environment guard
        print(f"Qt platform/backend unavailable: {exc}", file=sys.stderr)
        return EXIT_NO_QT

    from support.offline import PARK_LOGIN_QML, patch_offline

    patch_offline()  # BEFORE the bridge: its __init__ fires the sign-in check
    # Bridge BEFORE engine: constructing WavesBridge with a live
    # QQmlApplicationEngine crashed engine.load() natively (PySide6
    # 6.11.1, offscreen, seen when the host audio setup changed), and
    # the sibling harnesses that build the bridge first never crashed.
    bridge = WavesBridge(tidal=None)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("waves", bridge)
    engine.rootContext().setContextProperty("monoFont", _load_mono())
    engine.rootContext().setContextProperty("uiFontFamily", app.font().family())
    engine.load(QUrl.fromLocalFile(str(QML_MAIN)))
    roots = engine.rootObjects()
    if not roots:
        print("Main.qml failed to load", file=sys.stderr)
        return EXIT_PRECONDITION
    root = roots[0]
    if not isinstance(root, QQuickWindow):
        print("root object is not a window", file=sys.stderr)
        return EXIT_PRECONDITION

    def q(expr: str):
        r = QQmlExpression(QQmlEngine.contextForObject(root), root, expr).evaluate()
        return r[0] if isinstance(r, tuple) else r

    def settle(ms: int = 150) -> None:
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    root.resize(1280, 900)
    root.show()
    settle(400)
    q("bootOverlay.done = true")
    q("bootContentShown = 1")
    q(PARK_LOGIN_QML)
    q("root.openSearch()")
    seed_tidal_search(q, bridge, videos=[json.loads(_VIDEO)], expanded=("videos",))
    q("root.searchReveal = 1")
    q("root.searchBuilding = false")
    settle(700)

    centre = q(
        "(function(){"
        " var cell = root.searchGroupFor('tidal').videoGridItem.children[0];"
        " if (!cell || !cell.item) return '';"
        " var t = cell.item.children[0];"
        " if (!t || t.videoId === undefined) return '';"
        " var p = t.mapToItem(null, t.width/2, t.height/2);"
        " return '' + Math.round(p.x) + ',' + Math.round(p.y);"
        "})()"
    )
    if not centre:
        print("no video thumbnail in the grid to hover", file=sys.stderr)
        return EXIT_PRECONDITION
    x, y = (int(n) for n in str(centre).split(","))

    QTest.mouseMove(root, QPoint(x - 30, y - 30))
    settle(120)
    QTest.mouseMove(root, QPoint(x, y))  # arrive, then hold perfectly still

    # Without a session the resolve fails and the card closes again, so watch
    # for the opening rather than the end state. Generous headroom over the
    # dwell: this asserts it completes at all, not how fast.
    opened = False
    for _ in range(40):
        settle(50)
        if q("root.peekNow ? 1 : 0") == 1:
            opened = True
            break
        # A peek that opened and closed inside one tick still armed this.
        if q("root.peekCooldown ? 1 : 0") == 1:
            opened = True
            break

    if not opened:
        print(
            f"the dwell never completed while the pointer rested on the thumbnail (hovered={q('root.peekThumbHover')})",
            file=sys.stderr,
        )
        return EXIT_REGRESSED
    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_run_scenario())
