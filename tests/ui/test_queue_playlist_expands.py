"""A downloading playlist (or mix) row expands to its per-track ledger.

WHAT THIS FENCES OFF
--------------------
The queue drawer's expandable row (click for the ordered per-track ledger,
hover for the peek) must not be gated to ``model.type === "album"``. The
per-track registry behind that ledger is kept for EVERY collection job, and a
playlist row already reports "12/50 tracks", but the user cannot open it: no
chevron, no peek, no way to see which track is downloading.

Two things hold:

* the QML gates expansion on ``collection`` alone, so playlist and mix rows
  render the ledger, and
* ``loadQueueTracks`` orders that ledger by the collection's own track list
  for playlists and mixes too, instead of only knowing how to ask an album.

The first is proved on the real Main.qml (subprocess, like its siblings); the
second on the bridge alone with stub collection objects.
"""

from __future__ import annotations

import os
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
    scoped_q,
)


@pytest.mark.qml
def test_playlist_and_mix_rows_expand_to_a_ledger():
    run_scenario(
        Path(__file__),
        "--run-scenario",
        timeout=180,
        sandbox_prefix="waves-queue-playlist-expand-",
        failure_message="a playlist row would not open its ledger:",
    )


def _bridge_for_fetch(monkeypatch):
    """A bridge whose worker pool runs inline, so the fetch is synchronous."""
    from support.qml import require_qt

    require_qt()
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication

    QGuiApplication.instance() or QGuiApplication([])
    from waves.desktop import backend as be
    from waves.desktop import diagnostics
    from waves.desktop.session import WavesTidal

    # This bridge lives in the pytest process, so it must not read the
    # developer's real waves.json: with verbose diagnostics on there, __init__
    # started the real freeze watchdog, whose QTimer re-armed a faulthandler
    # countdown from every later in-process event loop, and the one still
    # pending at exit fired inside interpreter teardown and spun forever
    # (the suite printed its summary and never exited). Default prefs, no live
    # login, and a check that the watchdog stayed off.
    monkeypatch.setattr(WavesTidal, "login_token", lambda self: False)
    monkeypatch.setattr(be.WavesBridge, "_load_waves_prefs", lambda self: self._default_waves_prefs())
    monkeypatch.setattr(be, "name_builder_title", lambda t: getattr(t, "name", ""))
    bridge = be.WavesBridge(tidal=None)
    assert diagnostics._watchdog._timer is None, "a bridge built with default prefs must not start the freeze watchdog"

    class _Inline:
        def start(self, w):
            w.run()

    bridge.threadpool = _Inline()
    fetched = []
    bridge._queueTracksFetched.disconnect()
    bridge._queueTracksFetched.connect(lambda qid, rows: fetched.append((qid, rows)))
    return be, bridge, fetched


@pytest.mark.qml
def test_load_queue_tracks_orders_a_playlist_by_its_own_list(monkeypatch):
    be, bridge, fetched = _bridge_for_fetch(monkeypatch)

    a, b = be.Track.__new__(be.Track), be.Track.__new__(be.Track)
    a.id, a.name, a.duration = "t-a", "First", 100
    b.id, b.name, b.duration = "t-b", "Second", 200
    for t in (a, b):
        t.artists, t.artist = [], None

    class _Playlist:
        def items(self, limit=100, offset=0):
            return [] if offset else [a, b]

    pl = _Playlist()
    bridge._objs["playlist"]["pl-1"] = pl
    qid = bridge._enqueue("Mixtape", "playlist", media_id="pl-1", collection=True, tracks=2)
    bridge.loadQueueTracks(qid)
    assert fetched and fetched[-1][0] == qid
    assert [(r["id"], r["num"], r["title"]) for r in fetched[-1][1]] == [("t-a", 1, "First"), ("t-b", 2, "Second")]


@pytest.mark.qml
def test_load_queue_tracks_orders_a_mix_by_its_own_list(monkeypatch):
    be, bridge, fetched = _bridge_for_fetch(monkeypatch)
    t = be.Track.__new__(be.Track)
    t.id, t.name, t.duration, t.artists, t.artist = "m-1", "Only", 90, [], None

    class _Mix(be.Mix):
        # A real Mix subclass: the mix items read rides the provider's
        # collection_items, whose dispatcher matches on the real type.
        def __init__(self):
            pass

        def items(self):
            return [t, object()]  # a non-track entry is dropped, not crashed on

    bridge._objs["mix"]["mx-1"] = _Mix()
    qid = bridge._enqueue("Daily Mix", "mix", media_id="mx-1", collection=True, tracks=1)
    bridge.loadQueueTracks(qid)
    assert [(r["id"], r["num"]) for r in fetched[-1][1]] == [("m-1", 1)]


def _run_scenario() -> int:
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

    # The queue ListView lives inside QueueDrawer.qml:
    # evaluate expressions naming its ids in that file's own scope.
    qd = scoped_q(q, "queueDrawer.background")

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

    bad: list[str] = []
    for kind, name in (("playlist", "Mixtape"), ("mix", "Daily Mix")):
        qid = bridge._enqueue(name, kind, media_id=f"{kind}-1", collection=True, tracks=2)
        bridge.queueChanged.emit(list(bridge._queue))
        settle(120)
        # A running track, reported the way a real download does.
        bridge._track_lifecycle(qid, {"id": "1", "num": 1, "title": "Opener", "status": "running"})
        settle(60)
        row = f"(function(){{ var n = queueList.count; for (var i = 0; i < n; i++) {{ var it = queueList.itemAtIndex(i); if (it && it.model && it.model.qid === {qid}) return it }} return null }})()"
        if not bool(qd(row + " !== null")):
            print(f"no drawer row for the {kind} job", file=sys.stderr)
            return EXIT_PRECONDITION
        if not bool(qd(row + ".expandable")):
            bad.append(f"the {kind} row is not expandable")
            continue
        # Expand through the row's own toggle: that is the click path, and it
        # asks the bridge for the ordered list (empty here: no object, so the
        # merge falls back to the registry, which holds the running track).
        qd(row + ".qtoggle()")
        settle(400)
        titles = str(
            qd(
                """(function () {
                var out = [];
                function walk(o) {
                    if (!o) return;
                    if (o.objectName === 'qTrackTitle') out.push('' + o.text);
                    var kids = o.children;
                    for (var i = 0; i < (kids ? kids.length : 0); ++i) walk(kids[i]);
                }
                walk(ROW);
                return out.join(' | ');
            })()""".replace("ROW", row)
            )
        )
        if "Opener" not in titles:
            bad.append(f"the expanded {kind} row does not list its running track (ledger: {titles!r})")

    if bad:
        for b in bad:
            print(b, file=sys.stderr)
        return EXIT_REGRESSED
    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_run_scenario())
