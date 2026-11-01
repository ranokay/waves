"""An expanded queue row reaches every track, however long the collection.

WHAT THIS FENCES OFF
--------------------
The per-track ledger was written for albums, where a row is 10 to 30 tracks,
and it built every row at once. Opened to playlists and mixes it was capped at
500 rows to keep the GUI thread alive, and the cap hid the rest: a 1207-track
playlist listed 500 tracks and then "N more tracks", a line that did nothing
for the tracks it stood in for. The tracks that failed or that TIDAL refused
past track 500 could not be seen anywhere (upstream issue #54).

The ledger is now a scrolling list that builds only the rows in its window,
with the visible-row count a setting. Proved on the real Main.qml (subprocess,
like its siblings):

- a row nobody opened builds no ledger rows at all;
- a huge playlist lists every track, builds only its window plus the cache
  buffer, and its LAST track is reachable;
- a failed and an unavailable track past the old ceiling are reachable under
  their own outcomes;
- a live tick (a fresh same-length track array, one track's state changed)
  recreates no built delegate, keeps the scroll position and first visible
  row, and repaints the changed track in place;
- a track arriving live grows the list without moving the reader, and the new
  tail is reachable;
- the open list stops at a fixed box of rows (a setting, followed live), with
  no "N more tracks" remainder;
- an ordinary album shows every track and does not scroll.
"""

from __future__ import annotations

import math
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

# Well past the old ceiling of 500, and not a round number, so an off-by-one
# at either end shows up.
BIG = 1207
SMALL = 12
# A track TIDAL refused, and a failed one past where the old cap stopped.
MISSING = {5: "unavailable", 1100: "failed"}
# Where the live-tick proof parks the ledger: a track well past the old cap.
PARK_AT = 1098


@pytest.mark.qml
def test_every_track_of_a_huge_playlist_is_reachable():
    run_scenario(
        Path(__file__),
        "--run-scenario",
        timeout=180,
        sandbox_prefix="waves-queue-ledger-scroll-",
        failure_message="the scrolling ledger regressed:",
    )


def _run_scenario() -> int:  # noqa: C901 (one straight scenario, six checks)
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

    def found(name: str) -> str:
        """An expression naming the first drawer row's descendant `name`."""
        return f"""(function (name) {{
            var hit = null;
            function walk(o) {{
                if (!o || hit) return;
                if (o.objectName === name) {{ hit = o; return; }}
                var kids = o.children;
                for (var i = 0; i < (kids ? kids.length : 0); ++i) walk(kids[i]);
            }}
            walk(queueList.itemAtIndex(0));
            return hit;
        }})('{name}')"""

    def ledger():
        """The expanded row's ledger list, found inside the row delegate."""
        obj = qd(found("qLedgerList"))
        if obj is None:
            raise RuntimeError("the expanded row has no ledger list")
        return obj

    def lq(expr: str):
        """Evaluate an expression in the ledger's own component scope.

        The ledger lives inside the queue row's delegate component, so its id
        is not in the drawer file's root context; evaluating against the list
        object itself is what reaches it.
        """
        obj = ledger()
        e = QQmlExpression(QQmlEngine.contextForObject(obj), obj, expr)
        r = e.evaluate()
        if e.hasError():
            raise RuntimeError(e.error().toString())
        return r[0] if isinstance(r, tuple) else r

    def built_titles() -> list[str]:
        """The ledger rows that actually EXIST (the cost), by title."""
        out = lq(
            """(function () {
                var out = [];
                function walk(o) {
                    if (!o) return;
                    if (o.objectName === 'qTrackTitle') out.push('' + o.text);
                    var kids = o.children;
                    for (var i = 0; i < (kids ? kids.length : 0); ++i) walk(kids[i]);
                }
                walk(qLedger);
                return out.join('|');
            })()"""
        )
        return [t for t in str(out or "").split("|") if t]

    def item_prop(index: int, name: str, prop: str) -> str:
        """A named descendant's property on the ledger delegate at `index`."""
        return str(
            lq(
                f"""(function () {{
                var it = qLedger.itemAtIndex({index});
                if (!it) return '';
                var hit = null;
                function walk(o) {{
                    if (!o || hit) return;
                    if (o.objectName === '{name}') {{ hit = o; return; }}
                    var kids = o.children;
                    for (var i = 0; i < (kids ? kids.length : 0); ++i) walk(kids[i]);
                }}
                walk(it);
                return hit ? '' + hit.{prop} : '';
            }})()"""
            )
        )

    def first_visible() -> int:
        return int(lq("qLedger.indexAt(10, qLedger.contentY + 5)"))

    def seed(count: int, kind: str, name: str, states: dict[int, str] | None = None) -> int:
        qid = bridge._enqueue(name, kind, media_id=f"c-{name}", collection=True, tracks=count)
        bridge.queueChanged.emit(list(bridge._queue))
        settle(150)
        for num, status in (states or {}).items():
            bridge._track_lifecycle(
                qid,
                {"id": str(num - 1), "num": num, "title": f"track {num}", "status": status},
            )
        settle(60)
        bridge._merge_queue_tracks(
            qid,
            [{"id": str(i), "num": i + 1, "title": f"track {i + 1}", "duration": "3:00"} for i in range(count)],
        )
        settle(150)
        return qid

    bad: list[str] = []
    peek = int(q("root.queueLedgerPeek"))
    if not 0 < peek <= 5:
        bad.append(f"the hover peek ceiling is {peek}; it must stay small, the sliver shows about one row")

    # A collection far past the old ceiling. Collapsed and unhovered first:
    # the cost of a row nobody opened must be zero, whatever its size.
    qid = seed(BIG, "playlist", "Enormous Mixtape", MISSING)
    if not bool(qd("queueList.itemAtIndex(0) !== null")):
        print("no drawer row", file=sys.stderr)
        return EXIT_PRECONDITION
    built = len(built_titles())
    if built != 0:
        bad.append(f"a collapsed {BIG}-track row already built {built} ledger rows, want 0")

    q(f"root.queueExpanded = ({{ {qid}: true }})")
    settle(600)
    if qd(found("qLedgerList")) is None:
        print("the expanded row has no scrolling ledger list", file=sys.stderr)
        return EXIT_REGRESSED
    count = int(lq("qLedger.count"))
    if count != BIG:
        bad.append(f"the ledger lists {count} tracks, want all {BIG}")
    built = len(built_titles())
    # The open box is the setting's rows; the ListView only builds its window
    # plus the cache buffer, so the delegate count follows the window, never
    # the job. Derive the bound from the QML's own numbers so it cannot drift.
    rows = int(q("root.queueLedgerRows === undefined ? 0 : root.queueLedgerRows"))
    cache = float(lq("qLedger.cacheBuffer"))
    pitch = float(lq("qLedger.pitch"))
    gap = float(lq("qLedger.spacing"))

    def window_bound(n: int) -> int:
        return n + 2 * math.ceil(cache / pitch) + 2

    if rows <= 0:
        bad.append("the ledger has no visible-row setting to bound its window")
    elif not rows <= built <= window_bound(rows):
        bad.append(
            f"an expanded {BIG}-track row built {built} ledger rows, want the {rows}-row window plus its cache (at most {window_bound(rows)})"
        )
    if not bool(lq("qLedger.interactive")):
        bad.append("a ledger longer than its box does not scroll")
    box = float(lq("qLedger.height"))
    want_box = rows * pitch - gap
    if rows > 0 and abs(box - want_box) > 0.5:
        bad.append(f"the open ledger is {box}px tall, want its {want_box}px box")
    if bool(qd(f"{found('qTrackMore')} !== null")):
        bad.append("the ledger still carries an 'N more tracks' line instead of scrolling")
    bar = found("qLedgerScroll")
    if not bool(qd(f"{bar} !== null && {bar}.visible")):
        bad.append("an open ledger that scrolls shows no scrollbar")
    elif float(qd(f"{bar}.x")) < float(lq("qLedger.width")):
        bad.append("the ledger scrollbar sits over the rows instead of beside them")

    # Failed and unavailable tracks past the old ceiling are reachable, under
    # their own outcomes.
    lq("qLedger.positionViewAtIndex(4, ListView.Beginning)")
    settle(300)
    if item_prop(4, "qTrackTitle", "text") != "track 5":
        bad.append(f"track 5 is not reachable (row shows {item_prop(4, 'qTrackTitle', 'text')!r})")
    if item_prop(4, "qTrackWord", "target") != "UNAVAILABLE":
        bad.append(f"track 5 reads {item_prop(4, 'qTrackWord', 'target')!r}, want UNAVAILABLE")
    lq("qLedger.positionViewAtIndex(1099, ListView.Beginning)")
    settle(300)
    if item_prop(1099, "qTrackTitle", "text") != "track 1100":
        bad.append(f"track 1100 is not reachable (row shows {item_prop(1099, 'qTrackTitle', 'text')!r})")
    if item_prop(1099, "qTrackWord", "target") != "FAILED":
        bad.append(f"track 1100 reads {item_prop(1099, 'qTrackWord', 'target')!r}, want FAILED")

    # A live tick: Main.qml replaces the per-qid array with a fresh same-length
    # one and changes one track. Built delegates must survive, the reader must
    # not move, and the changed track must repaint in place.
    lq(f"qLedger.positionViewAtIndex({PARK_AT}, ListView.Beginning)")
    settle(300)
    y0 = float(lq("qLedger.contentY"))
    top0 = first_visible()
    held = lq(f"qLedger.itemAtIndex({PARK_AT})")
    held_next = lq(f"qLedger.itemAtIndex({PARK_AT + 1})")
    if held is None or held_next is None:
        bad.append(f"the ledger built no delegate at {PARK_AT} to watch across a tick")
    bridge._track_lifecycle(
        qid,
        {"id": str(PARK_AT), "num": PARK_AT + 1, "title": f"track {PARK_AT + 1}", "status": "failed"},
    )
    settle(400)
    if lq(f"qLedger.itemAtIndex({PARK_AT})") is not held:
        bad.append("a live tick recreated the delegate at the reader's position")
    if lq(f"qLedger.itemAtIndex({PARK_AT + 1})") is not held_next:
        bad.append("a live tick recreated a neighbour delegate")
    y1 = float(lq("qLedger.contentY"))
    if abs(y1 - y0) > 1:
        bad.append(f"a live tick moved the scrolled ledger from {y0} to {y1}")
    if first_visible() != top0:
        bad.append(f"a live tick changed the first visible row from {top0} to {first_visible()}")
    if item_prop(PARK_AT, "qTrackWord", "target") != "FAILED":
        bad.append("a live tick did not repaint the changed track in place")
    if item_prop(PARK_AT, "qTrackWord", "text") != "FAILED":
        bad.append(f"the changed track still reads {item_prop(PARK_AT, 'qTrackWord', 'text')!r}, want FAILED")

    # A track arriving live grows the list by one slot without moving the
    # reader, and the new tail is reachable.
    bridge._track_lifecycle(qid, {"id": "late", "title": "late arrival", "status": "queued"})
    settle(400)
    if int(lq("qLedger.count")) != BIG + 1:
        bad.append(f"a track arriving live left the ledger at {qd('qLedger.count')} rows, want {BIG + 1}")
    if abs(float(lq("qLedger.contentY")) - y0) > 1:
        bad.append("a track arriving live moved the scrolled ledger")
    if first_visible() != top0:
        bad.append("a track arriving live changed the first visible row")
    if lq(f"qLedger.itemAtIndex({PARK_AT})") is not held:
        bad.append("a track arriving live recreated the delegate at the reader's position")
    lq("qLedger.positionViewAtEnd()")
    settle(400)
    if item_prop(BIG, "qTrackTitle", "text") != "late arrival":
        bad.append(f"the live tail is not reachable (last row shows {item_prop(BIG, 'qTrackTitle', 'text')!r})")
    built = len(built_titles())
    if rows > 0 and not rows <= built <= window_bound(rows):
        bad.append(f"at its end the ledger built {built} rows, want at most {window_bound(rows)}")

    # The box's size is a setting, and an open row follows it live.
    bridge.setWavesPref("queue_ledger_rows", 6)
    settle(400)
    live_rows = int(q("root.queueLedgerRows === undefined ? 0 : root.queueLedgerRows"))
    if live_rows != 6:
        bad.append(f"set to 6 rows, Main.qml reads queueLedgerRows {live_rows}")
    box = float(lq("qLedger.height"))
    if abs(box - (6 * pitch - gap)) > 0.5:
        bad.append(f"set to 6 rows, the open ledger is {box}px tall, want {6 * pitch - gap}px")
    built = len(built_titles())
    if not 6 <= built <= window_bound(6):
        bad.append(f"set to 6 rows, the ledger built {built} rows, want at most {window_bound(6)}")
    bridge.setWavesPref("queue_ledger_rows", 12)
    settle(300)

    # An ordinary album is untouched: every track, and no scroll.
    q("root.queueExpanded = ({})")
    settle(200)
    bridge._queue.clear()
    bridge._queue_index.clear()
    bridge.queueChanged.emit([])
    settle(150)
    qid = seed(SMALL, "album", "Ordinary Record")
    q(f"root.queueExpanded = ({{ {qid}: true }})")
    settle(600)
    built = len(built_titles())
    if built != SMALL:
        bad.append(f"an expanded {SMALL}-track album built {built} ledger rows, want all {SMALL}")
    if bool(lq("qLedger.interactive")):
        bad.append("an album that fits still scrolls")
    box = float(lq("qLedger.height"))
    if abs(box - (SMALL * pitch - gap)) > 0.5:
        bad.append(f"an album that fits is {box}px tall, want all {SMALL} rows ({SMALL * pitch - gap}px)")
    if bool(qd(f"{found('qTrackMore')} !== null")):
        bad.append("an album that fits still carries an 'N more tracks' line")

    if bad:
        for b in bad:
            print(b, file=sys.stderr)
        return EXIT_REGRESSED
    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_run_scenario())
