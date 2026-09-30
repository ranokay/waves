"""Both preview sizes support keyboard playback and one seek per drag."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from support.paths import QML_DIR
from support.qml import EXIT_NO_QT, EXIT_OK, EXIT_PRECONDITION, run_scenario


@pytest.mark.qml
def test_preview_keyboard_and_scrub_gesture():
    run_scenario(Path(__file__), "--run-scenario", sandbox_prefix="waves-preview-keys-")


def _run_scenario() -> int:
    try:
        from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer, QUrl
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtQml import QQmlApplicationEngine, QQmlEngine, QQmlExpression
        from PySide6.QtTest import QTest
    except ImportError:
        return EXIT_NO_QT

    app = QGuiApplication.instance() or QGuiApplication([])
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("monoFont", app.font().family())
    engine.rootContext().setContextProperty("uiFontFamily", app.font().family())
    engine.loadData(
        b"""
import QtQuick
import QtQuick.Window
import "."
Window {
    id: window
    width: 480; height: 180; visible: true
    property bool compact: false
    property string state: ""
    property real previewDuration: 120000
    property real previewPosition: 30000
    property bool previewScrubbing: false
    property int seekCalls: 0
    property real ledPulse: 1
    property real shimmerPhase: 0
    property bool queueEdgeHeld: false
    function pvSt(kind, pid) { return state }
    function pvFrac(kind, pid) { return previewPosition / previewDuration }
    function fmtMs(ms) { return Math.floor(ms / 1000) + "s" }
    function togglePreview(kind, pid, start) { state = state === "playing" ? "paused" : "playing" }
    function stopPreview() { state = "" }
    function scrubPreviewVisual(frac) { previewPosition = frac * previewDuration }
    function seekPreview(frac) { seekCalls++; previewPosition = frac * previewDuration }
    PreviewBar {
        host: window; pid: "track"; kind: "track"; label: "Preview Song"
        x: 20; y: 30; width: 420; height: 40; visible: !window.compact
    }
    TrackPreview {
        host: window; pid: "track"; label: "Preview Song"
        x: 20; y: 90; width: implicitWidth; height: implicitHeight; visible: window.compact
    }
}
""",
        QUrl.fromLocalFile(str(QML_DIR / "KeyboardPreviewHarness.qml")),
    )
    if not engine.rootObjects():
        return EXIT_PRECONDITION
    root = engine.rootObjects()[0]

    def q(body: str):
        expression = QQmlExpression(QQmlEngine.contextForObject(root), root, body)
        result = expression.evaluate()
        if expression.hasError():
            raise AssertionError(expression.error().toString())
        return result[0] if isinstance(result, tuple) else result

    def settle():
        loop = QEventLoop()
        QTimer.singleShot(250, loop.quit)
        loop.exec()

    def control(name: str, body: str):
        return q(
            "(function() { function find(o) {"
            f"if (o.visible && o.enabled && o.Accessible && o.Accessible.name === {json.dumps(name)}) return o;"
            "var children = o.children || []; for (var i = 0; i < children.length; ++i) {"
            "var hit = find(children[i]); if (hit) return hit; } return null; }"
            f"var c = find(contentItem); if (!c) throw new Error('missing {name}'); {body} }})()"
        )

    def key(name: str, code):
        assert control(name, "return c.activeFocusOnTab;") is True
        control(name, "c.forceActiveFocus();")
        QTest.keyClick(root, code)
        settle()

    settle()
    for compact in (False, True):
        root.setProperty("compact", compact)
        root.setProperty("state", "")
        settle()
        key("Preview Song", Qt.Key_Space)
        assert root.property("state") == "playing"
        key("Pause preview", Qt.Key_Return)
        assert root.property("state") == "paused"
        key("Resume preview", Qt.Key_Space)
        assert root.property("state") == "playing"
        root.setProperty("previewPosition", 30000)
        key("Preview position", Qt.Key_Right)
        assert root.property("previewPosition") == 35000
        key("Preview position", Qt.Key_Left)
        assert root.property("previewPosition") == 30000
        key("Preview position", Qt.Key_Home)
        assert root.property("previewPosition") == 0
        key("Preview position", Qt.Key_End)
        assert root.property("previewPosition") == 120000
        geo = json.loads(
            control(
                "Preview position",
                "var p = c.mapToItem(null, 0, 0); return JSON.stringify([p.x, p.y, c.width, c.height]);",
            )
        )
        x, y, width, height = geo
        before = root.property("seekCalls")
        QTest.mousePress(root, Qt.LeftButton, Qt.NoModifier, QPoint(round(x + width / 4), round(y + height / 2)))
        QTest.mouseMove(root, QPoint(round(x + width / 2), round(y + height / 2)))
        assert root.property("seekCalls") == before
        QTest.mouseRelease(root, Qt.LeftButton, Qt.NoModifier, QPoint(round(x + width * 0.75), round(y + height / 2)))
        assert root.property("seekCalls") == before + 1
        assert not root.property("previewScrubbing")
        assert abs(root.property("previewPosition") - 90000) < 2500
        key("Stop preview", Qt.Key_Space)
        assert root.property("state") == ""
    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_run_scenario())
