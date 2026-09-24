"""Destructive queue CLEARs confirm; Completed CLEAR and STOP stay one-click.

WHAT THIS FENCES OFF
--------------------
1. A misclick on a section header discarding work. CLEAR on the Failed,
   Stopped and Queued sections arms first (the button says SURE?): the first
   click clears nothing, the second click inside the armed window clears.
2. A dismissed confirm costing work. Letting the armed window lapse leaves
   the queue intact and the button back at CLEAR.
3. Tidy-up getting harder. CLEAR on Completed stays one click.
4. The panic control slowing down. STOP stays one click, and its
   screen-reader name says what it will discard.

Drives the REAL Main.qml with REAL mouse clicks on the header buttons, over
rows seeded through the REAL bridge queue, so the wiring is what is under
test, not the function behind it.

Runs in a SUBPROCESS like the other Main.qml scenarios: building the bridge
installs process-global handlers that must not leak into the suite.
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
def test_destructive_clears_confirm_and_stop_stays_one_click():
    run_scenario(
        Path(__file__),
        "--run-scenario",
        timeout=180,
        sandbox_prefix="waves-queue-clear-confirm-test-",
        failure_message="the queue CLEAR confirm gate regressed.",
    )


def _run_scenario() -> int:
    try:
        from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer, QUrl
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtQml import QQmlApplicationEngine, QQmlEngine, QQmlExpression
        from PySide6.QtQuick import QQuickWindow
        from PySide6.QtTest import QTest
    except Exception as exc:
        print(f"Qt unavailable: {exc}", file=sys.stderr)
        return EXIT_NO_QT

    from support.offline import PARK_LOGIN_QML, patch_offline

    patch_offline()

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
    if not isinstance(root, QQuickWindow):
        print("root object is not a window", file=sys.stderr)
        return EXIT_PRECONDITION

    def q(expr: str):
        e = QQmlExpression(QQmlEngine.contextForObject(root), root, expr)
        r = e.evaluate()
        if e.hasError():
            raise RuntimeError(e.error().toString())
        return r[0] if isinstance(r, tuple) else r

    def settle(ms: int) -> None:
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def seed(statuses: list[tuple[int, str]]) -> None:
        bridge._queue = [
            {
                "qid": qid,
                "media_id": f"m{qid}",
                "status": st,
                "type": "track",
                "name": f"row-{qid}",
                "progress": 0,
                "template": "",
                "collection": False,
                "artist": "",
                "tracks": 0,
                "art": "",
            }
            for qid, st in statuses
        ]
        bridge._queue_index = {it["qid"]: it for it in bridge._queue}
        bridge._qdirty_added = []
        bridge._qdirty_changed = {}
        bridge._qdirty_removed = []
        bridge._qdirty_full = True
        bridge._emit_queue()
        settle(400)

    def bridge_statuses() -> list[str]:
        return [str(it.get("status")) for it in list(bridge._queue)]

    def visual_items():
        # Delegates a ListView instantiates have no QObject parent, so
        # findChildren never sees them; childItems does.
        stack = [root.contentItem()]
        while stack:
            it = stack.pop()
            yield it
            stack.extend(it.childItems())

    def header_of(it):
        p = it
        while p is not None:
            if p.objectName() == "queueSectionHeader":
                return p
            p = p.parentItem()
        return None

    def clear_btn(section: str):
        for it in visual_items():
            if it.property("label") not in ("CLEAR", "SURE?"):
                continue
            head = header_of(it)
            if head is not None and str(head.property("section")) == section:
                return it
        return None

    def btn_label(btn) -> str:
        return str(btn.property("label") or "")

    def click(btn) -> bool:
        # Center of the button in window coordinates, like the shelf tests.
        p = btn.mapToScene(btn.boundingRect().center())
        QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, QPoint(int(p.x()), int(p.y())))
        settle(500)
        return True

    def stop_btn():
        for it in visual_items():
            if it.property("label") == "STOP":
                return it
        return None

    bad: list[str] = []

    settle(150)
    q(PARK_LOGIN_QML)
    seed([(1, "failed"), (2, "cancelled"), (3, "queued"), (4, "done")])
    # A done row rides Downloading until the linger clock promotes it; the
    # Completed header under test is the destination, so move it there the
    # way the clock would.
    q(
        "for (var i = 0; i < queueModel.count; ++i)"
        " if (queueModel.get(i).status === 'done') {"
        " queueModel.setProperty(i, 'moved', true);"
        " queueModel.setProperty(i, 'uiGroup', 'completed'); }"
        " queuePartition(); updateQueueCounts();"
    )
    q("root.width = 1200")
    q("root.height = 800")
    q("root.visible = true")
    settle(150)
    q("queueDrawer.open()")
    settle(500)
    if not bool(q("queueDrawer.visible")):
        print("the queue drawer would not open", file=sys.stderr)
        return EXIT_PRECONDITION
    for section in ("failed", "stopped", "queued", "completed"):
        if clear_btn(section) is None:
            print(f"no CLEAR header for section {section}; model may not have partitioned", file=sys.stderr)
            return EXIT_PRECONDITION

    # 1+2. Failed CLEAR arms instead of clearing; letting the window lapse
    # disarms with the queue intact; re-arming and clicking again clears.
    btn = clear_btn("failed")
    click(btn)
    if "failed" not in bridge_statuses():
        bad.append("first click on Failed CLEAR cleared the row: no confirm gate")
    btn = clear_btn("failed")
    if btn is None or btn_label(btn) != "SURE?":
        bad.append("first click on Failed CLEAR showed no confirm gate")
    else:
        # Poll for the disarm rather than assuming its exact length.
        disarmed = False
        for _ in range(40):
            settle(250)
            now = clear_btn("failed")
            if now is not None and btn_label(now) == "CLEAR":
                disarmed = True
                break
        if "failed" not in bridge_statuses():
            bad.append("a dismissed Failed CLEAR confirm still cleared the queue")
        if not disarmed:
            bad.append("the Failed CLEAR confirm never disarmed back to CLEAR")
        else:
            click(clear_btn("failed"))
            btn = clear_btn("failed")
            if btn is None or btn_label(btn) != "SURE?":
                bad.append("re-arming Failed CLEAR after a lapse showed no confirm gate")
            else:
                click(btn)
                settle(400)
                if "failed" in bridge_statuses():
                    bad.append("second click on armed Failed CLEAR did not clear")

    # Stopped CLEAR: same two-step.
    btn = clear_btn("stopped")
    if btn is None:
        bad.append("Stopped CLEAR header vanished before its own check")
    else:
        click(btn)
        if "cancelled" not in bridge_statuses():
            bad.append("first click on Stopped CLEAR cleared the row: no confirm gate")
        btn = clear_btn("stopped")
        if btn is None or btn_label(btn) != "SURE?":
            bad.append("first click on Stopped CLEAR showed no confirm gate")
        else:
            click(btn)
            settle(400)
            if "cancelled" in bridge_statuses():
                bad.append("second click on armed Stopped CLEAR did not clear")

    # Queued CLEAR: same two-step.
    btn = clear_btn("queued")
    if btn is None:
        bad.append("Queued CLEAR header vanished before its own check")
    else:
        click(btn)
        if "queued" not in bridge_statuses():
            bad.append("first click on Queued CLEAR cleared the row: no confirm gate")
        btn = clear_btn("queued")
        if btn is None or btn_label(btn) != "SURE?":
            bad.append("first click on Queued CLEAR showed no confirm gate")
        else:
            click(btn)
            settle(400)
            if "queued" in bridge_statuses():
                bad.append("second click on armed Queued CLEAR did not clear")

    # 3. Completed CLEAR stays one click.
    btn = clear_btn("completed")
    if btn is None:
        bad.append("Completed CLEAR header missing")
    else:
        click(btn)
        settle(400)
        if "done" in bridge_statuses():
            bad.append("Completed CLEAR did not clear in one click")

    # 4. STOP stays one click and names what it will discard.
    seed([(11, "queued"), (12, "queued")])
    q("queueDrawer.open()")
    settle(500)
    stop = stop_btn()
    if stop is None:
        bad.append("STOP missing with queued work")
    else:
        spoken = str(stop.property("accessibleLabel") or "")
        if "download" not in spoken.lower() or "2" not in spoken:
            bad.append(f"STOP does not say what it will discard (accessibleLabel={spoken!r})")
        click(stop)
        settle(500)
        after = bridge_statuses()
        if len(after) != 2 or any(st != "cancelled" for st in after):
            bad.append(f"STOP did not stop in one click; queue is now {after}")

    if bad:
        for line in bad:
            print(f"REGRESSED: {line}", file=sys.stderr)
        return EXIT_REGRESSED
    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_run_scenario())
