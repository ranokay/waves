"""A track that appears twice in a collection follows its state on both rows.

WHAT THIS FENCES OFF
--------------------
The queue ledger renders the collection's running order, and a playlist or a
mix can list the same track more than once. The engine reports that track ONCE
per event (its per-job registry is keyed by track id), so the drawer has to
apply each state event to every ledger row carrying the id.

A state handler that stops at the first match, while its sibling that carries
the percentage does not, moves the second copy of a repeated track's bar but
leaves it QUEUED: after the job finishes it still reads as if it had never
been fetched. Harmless while the ledger is album-only (an album never lists an
id twice); opening the ledger to playlists and mixes makes it reachable.

Proved on the real Main.qml (subprocess, like its siblings): a playlist whose
running order repeats an id, one state event for that id, and both rows are
expected to carry the new status and quality while the untouched neighbour is
left alone.
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
def test_a_repeated_track_moves_on_every_row_it_occupies():
    run_scenario(
        Path(__file__),
        "--run-scenario",
        timeout=180,
        sandbox_prefix="waves-queue-repeated-track-",
        failure_message="a repeated track's second row was left behind:",
    )


def _run_scenario() -> int:  # (one straight line of scene setup)
    try:
        from PySide6.QtCore import QEventLoop, QTimer, QUrl
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtQml import QQmlApplicationEngine, QQmlEngine, QQmlExpression
    except Exception as exc:  # pragma: no cover - environment guard
        print(f"Qt unavailable: {exc}", file=sys.stderr)
        return EXIT_NO_QT

    from support.offline import PARK_LOGIN_QML, patch_offline

    patch_offline()
    app = QGuiApplication.instance() or QGuiApplication([])
    sandbox_qml_settings()
    try:
        from waves.desktop.app import _load_mono
        from waves.desktop.backend import WavesBridge
    except Exception as exc:  # pragma: no cover - environment guard
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
        e = QQmlExpression(QQmlEngine.contextForObject(root), root, expr)
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
    q("queueDrawer.open()")
    settle(120)
    if not bool(q("queueDrawer.visible")):
        print("the queue drawer would not open", file=sys.stderr)
        return EXIT_PRECONDITION

    # A playlist whose running order lists track 7 twice, around a track 8.
    qid = bridge._enqueue("Repeats", "playlist", media_id="p-1", collection=True, tracks=3)
    bridge.queueChanged.emit(list(bridge._queue))
    settle(150)
    bridge._merge_queue_tracks(
        qid,
        [
            {"id": "7", "num": 1, "title": "same song", "duration": "3:00"},
            {"id": "8", "num": 2, "title": "other song", "duration": "3:00"},
            {"id": "7", "num": 3, "title": "same song", "duration": "3:00"},
        ],
    )
    settle(150)

    def statuses() -> str:
        return str(
            q(
                f"(function(){{ var a = root.queueTracks[{qid}] || []; "
                "return a.map(function(t){ return t.id + ':' + t.status + ':' + (t.quality || '-'); }).join(' | '); })()"
            )
        )

    bad: list[str] = []
    got = statuses()
    if got != "7:pending:- | 8:pending:- | 7:pending:-":
        print(f"the ledger did not seed as expected: {got!r}", file=sys.stderr)
        return EXIT_PRECONDITION

    # One state event for the repeated id, as the engine sends it (the
    # registry is keyed by id, so there is exactly one).
    bridge._track_lifecycle(qid, {"id": "7", "title": "same song", "status": "running"})
    settle(200)
    got = statuses()
    if got != "7:running:- | 8:pending:- | 7:running:-":
        bad.append(f"after track 7 started, the ledger read {got!r}; both of its rows must be running")

    bridge._track_lifecycle(qid, {"id": "7", "status": "done", "quality": {"tier": "LOSSLESS"}})
    settle(200)
    got = statuses()
    if got != "7:done:LOSSLESS | 8:pending:- | 7:done:LOSSLESS":
        bad.append(f"after track 7 landed, the ledger read {got!r}; both of its rows must be done at LOSSLESS")

    if bad:
        for b in bad:
            print(b, file=sys.stderr)
        return EXIT_REGRESSED
    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_run_scenario())
