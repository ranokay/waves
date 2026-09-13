"""Failed queue rows get their own section, above the active work.

WHAT THIS FENCES OFF
--------------------
Issue #18: failed downloads used to sit lost inside the Downloading group and
"Clear finished" swept them away, so a failure was easy to miss and, once
cleared, impossible to retry without restarting. The drawer now partitions
rows into [Completed, Failed, Downloading, Queued], the Failed section header
carries a RETRY ALL control driven by root.failedCount, and a retried row
leaves the section the moment its status changes.

Issue #27 added a Stopped section for the rows STOP ends (status
``cancelled``), between Failed and Downloading, with its own RETRY ALL and
CLEAR driven by root.stoppedCount: a stop is not an error, so it never shares
Failed's red header, and a failure is never lost among stopped rows.

The scenario drives root.reconcileQueue() with hand-built rows (the same
payload shape the bridge emits) and asserts on the model's uiGroup order and
the counts, all pure QML facts, offline.

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
def test_failed_rows_form_their_own_section_with_a_count():
    run_scenario(
        Path(__file__),
        "--run-scenario",
        timeout=120,
        sandbox_prefix="waves-failed-section-test-",
        failure_message="the Failed queue section regressed.",
    )


def _run_scenario() -> int:
    try:
        from PySide6.QtCore import QEventLoop, QTimer, QUrl
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtQml import QQmlApplicationEngine, QQmlEngine, QQmlExpression
    except Exception as exc:
        print(f"Qt unavailable: {exc}", file=sys.stderr)
        return EXIT_NO_QT

    from support.offline import PARK_LOGIN_QML, patch_offline

    patch_offline()

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
    q(PARK_LOGIN_QML)

    def row(qid: int, status: str) -> str:
        return (
            f"{{qid: {qid}, name: 'r{qid}', type: 'track', status: '{status}', progress: 0, "
            f"media_id: 'm{qid}', template: '', collection: false, artist: '', tracks: 0, art: ''}}"
        )

    # One row per state: the partition must land [failed, failed, stopped,
    # downloading, queued] with Completed empty (nothing has moved there).
    # The stopped row counts in stoppedCount alone, never in failedCount.
    rows = ", ".join([row(1, "queued"), row(2, "failed"), row(3, "running"), row(4, "failed"), row(5, "cancelled")])
    q(f"reconcileQueue([{rows}])")
    settle(60)
    groups = [q(f"queueModel.get({i}).uiGroup") for i in range(int(q("queueModel.count")))]
    partitioned = groups == ["failed", "failed", "stopped", "downloading", "queued"]
    counted = (
        int(q("failedCount")) == 2
        and int(q("stoppedCount")) == 1
        and int(q("downloadingCount")) == 1
        and int(q("queuedCount")) == 1
    )

    # A retried row leaves its section as soon as its status changes, whether
    # it was failed or stopped.
    rows2 = ", ".join([row(1, "queued"), row(2, "queued"), row(3, "running"), row(4, "failed"), row(5, "queued")])
    q(f"reconcileQueue([{rows2}])")
    settle(60)
    groups2 = [q(f"queueModel.get({i}).uiGroup") for i in range(int(q("queueModel.count")))]
    regrouped = groups2 == ["failed", "downloading", "queued", "queued", "queued"]
    recounted = int(q("failedCount")) == 1 and int(q("stoppedCount")) == 0

    # A queue of nothing but stopped rows (the usual sight right after STOP)
    # is one Stopped section and no Failed section at all.
    rows3 = ", ".join([row(1, "cancelled"), row(2, "cancelled")])
    q(f"reconcileQueue([{rows3}])")
    settle(60)
    groups3 = [q(f"queueModel.get({i}).uiGroup") for i in range(int(q("queueModel.count")))]
    all_stopped = groups3 == ["stopped", "stopped"] and int(q("failedCount")) == 0 and int(q("stoppedCount")) == 2

    # The bulk entry points each header calls must exist on the bridge.
    has_slot = all(
        bool(q(f"typeof waves.{name} === 'function'"))
        for name in ("retryAllFailed", "retryAllStopped", "clearFailed", "clearStopped")
    )

    # The headers as RENDERED: open the drawer on a mixed queue and read the
    # section labels the list actually instantiated. The Stopped header is
    # the soft red (a step under Failed's hot red), bold, and counts its own
    # rows; nothing else in the suite ever rendered a section header, so
    # the label chain and the colour chain were unpinned.
    from PySide6.QtCore import QObject

    q(f"reconcileQueue([{rows}])")
    q("queueDrawer.open()")
    settle(400)
    labels = {}
    for obj in root.findChildren(QObject):
        text = obj.property("text")
        if (
            isinstance(text, str)
            and " · " in text
            and text.split(" · ")[0] in ("COMPLETED", "FAILED", "STOPPED", "DOWNLOADING", "QUEUED")
        ):
            labels[text.split(" · ")[0]] = obj
    stopped = labels.get("STOPPED")
    failed = labels.get("FAILED")
    headers_rendered = stopped is not None and failed is not None
    stopped_header_ok = False
    if headers_rendered:
        stopped_header_ok = (
            stopped.property("text") == "STOPPED · 1"
            and failed.property("text") == "FAILED · 2"
            and stopped.property("color").name() == q("root.redContTx").name()
            and failed.property("color").name() == q("root.red").name()
            and stopped.property("color").name() != failed.property("color").name()
            and stopped.property("font").bold()
        )

    ok = partitioned and counted and regrouped and recounted and all_stopped and has_slot and stopped_header_ok
    print(
        f"partitioned={partitioned} counted={counted} regrouped={regrouped} "
        f"recounted={recounted} all_stopped={all_stopped} has_slot={has_slot} "
        f"headers_rendered={headers_rendered} stopped_header_ok={stopped_header_ok} "
        f"labels={sorted(labels)} groups={groups} groups2={groups2}",
        flush=True,
    )
    return EXIT_OK if ok else EXIT_REGRESSED


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_run_scenario())
