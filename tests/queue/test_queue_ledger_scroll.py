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
from support.qml import (
    EXIT_NO_QT,
    EXIT_OK,
    EXIT_PRECONDITION,
    EXIT_REGRESSED,
    boot_main_qml,
    checkpoint,
    run_scenario,
    scoped_q,
    wait_until,
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


def _run_scenario() -> int:
    try:
        booted = boot_main_qml()
    except Exception as exc:  # pragma: no cover - environment guard
        print(f"Main.qml did not boot: {exc}", file=sys.stderr)
        return EXIT_PRECONDITION
    if booted == EXIT_NO_QT:
        return EXIT_NO_QT
    _, q, _, bridge = booted

    from PySide6.QtQml import QQmlEngine, QQmlExpression

    # The queue ListView lives inside QueueDrawer.qml:
    # evaluate expressions naming its ids in that file's own scope.
    qd = scoped_q(q, "queueDrawer.background")
    q("queueDrawer.open()")
    bad: list[str] = []

    def wait_for(predicate, message: str) -> bool:
        # 4s: the card's height Behavior runs 280ms and a live tick's decrypt
        # runs about 200ms; a loaded machine can stretch either.
        try:
            wait_until(predicate, timeout_ms=4000, message=message)
        except AssertionError:
            bad.append(message)
            return False
        return True

    def walk(obj):
        yield obj
        for child in obj.children():
            yield from walk(child)

    def find(obj, name: str):
        if obj is None:
            return None
        for node in walk(obj):
            if node.property("objectName") == name:
                return node
        return None

    def row():
        return qd("queueList.itemAtIndex(0)")

    def ledger():
        return find(row(), "qLedgerList")

    def lq(expr: str):
        """Evaluate an expression in the ledger's own component scope.

        The ledger lives inside the queue row's delegate component, so its id
        is not in the drawer file's root context; evaluating against the list
        object itself is what reaches it.
        """
        obj = ledger()
        if obj is None:
            raise RuntimeError("the expanded row has no ledger list")
        e = QQmlExpression(QQmlEngine.contextForObject(obj), obj, expr)
        r = e.evaluate()
        if e.hasError():
            raise RuntimeError(e.error().toString())
        return r[0] if isinstance(r, tuple) else r

    def titles_under(root_expr: str) -> list[str]:
        """The qTrackTitle texts under a QML object expression, by title."""
        out = qd(
            f"""(function () {{
                var out = [];
                function walk(o) {{
                    if (!o) return;
                    if (o.objectName === 'qTrackTitle') out.push('' + o.text);
                    var kids = o.children;
                    for (var i = 0; i < (kids ? kids.length : 0); ++i) walk(kids[i]);
                }}
                walk({root_expr});
                return out.join('|');
            }})()"""
        )
        return [t for t in str(out or "").split("|") if t]

    def js_has(root_expr: str, name: str) -> bool:
        """Whether a named object exists under a QML object expression."""
        return bool(
            qd(
                f"""(function () {{
                    var hit = false;
                    function walk(o) {{
                        if (!o || hit) return;
                        if (o.objectName === '{name}') {{ hit = true; return; }}
                        var kids = o.children;
                        for (var i = 0; i < (kids ? kids.length : 0); ++i) walk(kids[i]);
                    }}
                    walk({root_expr});
                    return hit;
                }})()"""
            )
        )

    def built_titles() -> list[str]:
        """The ledger rows that actually EXIST (the cost), by title."""
        return titles_under("queueList.itemAtIndex(0)")

    def item_prop(index: int, name: str, prop: str) -> str:
        """A named descendant's property on the ledger delegate at `index`."""
        hit = find(lq(f"qLedger.itemAtIndex({index})"), name)
        return "" if hit is None else str(hit.property(prop))

    def has_more_line() -> bool:
        """Whether the old capped-ledger remainder line is still present."""
        return js_has("queueList.itemAtIndex(0)", "qTrackMore")

    def first_visible() -> int:
        return int(lq("qLedger.indexAt(10, qLedger.contentY + 5)"))

    def seed(count: int, kind: str, name: str, states: dict[int, str] | None = None) -> int:
        qid = bridge._enqueue(name, kind, media_id=f"c-{name}", collection=True, tracks=count)
        bridge.queueChanged.emit(list(bridge._queue))
        wait_for(lambda: row() is not None, "the drawer lists the seeded job")
        for num, status in (states or {}).items():
            bridge._track_lifecycle(
                qid,
                {"id": str(num - 1), "num": num, "title": f"track {num}", "status": status},
            )
        bridge._merge_queue_tracks(
            qid,
            [{"id": str(i), "num": i + 1, "title": f"track {i + 1}", "duration": "3:00"} for i in range(count)],
        )
        wait_for(
            lambda: bool(
                qd(
                    f"(function(){{ var it = queueList.itemAtIndex(0); return it !== null && it.ledgerLen === {count} }})()"
                )
            ),
            f"the row holds all {count} tracks",
        )
        return qid

    try:
        wait_until(lambda: bool(q("queueDrawer.visible")), message="the queue drawer opens")
    except AssertionError:
        print("the queue drawer would not open", file=sys.stderr)
        return EXIT_PRECONDITION
    checkpoint("collapsed")
    peek = int(q("root.queueLedgerPeek"))
    if not 0 < peek <= 5:
        bad.append(f"the hover peek ceiling is {peek}; it must stay small, the sliver shows about one row")

    # A collection far past the old ceiling. Collapsed and unhovered first:
    # the cost of a row nobody opened must be zero, whatever its size.
    qid = seed(BIG, "playlist", "Enormous Mixtape", MISSING)
    built = len(built_titles())
    if built != 0:
        bad.append(f"a collapsed {BIG}-track row already built {built} ledger rows, want 0")

    checkpoint("expanded")
    q(f"root.queueExpanded = ({{ {qid}: true }})")
    if ledger() is None:
        titles = built_titles()
        print(
            f"the expanded row has no scrolling ledger list; it built {len(titles)} of {BIG} tracks "
            f"(track {BIG} present: {'track ' + str(BIG) in titles})",
            file=sys.stderr,
        )
        return EXIT_REGRESSED
    if not wait_for(lambda: int(lq("qLedger.count")) == BIG, "the ledger lists every track"):
        bad.append(f"the ledger lists {lq('qLedger.count')} tracks, want all {BIG}")
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
    elif not wait_for(
        lambda: rows <= len(built_titles()) <= window_bound(rows),
        f"the open ledger builds only its {rows}-row window plus cache",
    ):
        built = len(built_titles())
        bad.append(f"an expanded {BIG}-track row built {built} ledger rows, want at most {window_bound(rows)}")
    if not bool(lq("qLedger.interactive")):
        bad.append("a ledger longer than its box does not scroll")
    if rows > 0:
        want_box = rows * pitch - gap
        if not wait_for(
            lambda: abs(float(lq("qLedger.height")) - want_box) < 0.5,
            f"the open ledger takes its {want_box}px box",
        ):
            bad.append(f"the open ledger is {lq('qLedger.height')}px tall, want its {want_box}px box")
    if has_more_line():
        bad.append("the ledger still carries an 'N more tracks' line instead of scrolling")
    if not wait_for(lambda: bool(lq("qLedgerScroll.visible")), "the ledger shows its scrollbar"):
        bad.append("an open ledger that scrolls shows no scrollbar")
    elif float(lq("qLedgerScroll.x")) < float(lq("qLedger.width")):
        bad.append("the ledger scrollbar sits over the rows instead of beside them")
    elif (
        float(lq("qLedgerScroll.x")) + float(lq("qLedgerScroll.width"))
        > float(qd("queueList.itemAtIndex(0).width")) + 0.5
    ):
        bad.append("the ledger scrollbar overflows the row's right edge")

    checkpoint("reachable")
    # Failed and unavailable tracks past the old ceiling are reachable, under
    # their own outcomes.
    lq("qLedger.positionViewAtIndex(4, ListView.Beginning)")
    if not wait_for(lambda: item_prop(4, "qTrackTitle", "text") == "track 5", "track 5 is reachable"):
        bad.append(f"track 5 is not reachable (row shows {item_prop(4, 'qTrackTitle', 'text')!r})")
    if item_prop(4, "qTrackWord", "target") != "UNAVAILABLE":
        bad.append(f"track 5 reads {item_prop(4, 'qTrackWord', 'target')!r}, want UNAVAILABLE")
    lq("qLedger.positionViewAtIndex(1099, ListView.Beginning)")
    if not wait_for(lambda: item_prop(1099, "qTrackTitle", "text") == "track 1100", "track 1100 is reachable"):
        bad.append(f"track 1100 is not reachable (row shows {item_prop(1099, 'qTrackTitle', 'text')!r})")
    if item_prop(1099, "qTrackWord", "target") != "FAILED":
        bad.append(f"track 1100 reads {item_prop(1099, 'qTrackWord', 'target')!r}, want FAILED")

    checkpoint("live tick")
    # A live tick: Main.qml replaces the per-qid array with a fresh same-length
    # one and changes one track. Built delegates must survive, the reader must
    # not move, and the changed track must repaint in place.
    lq(f"qLedger.positionViewAtIndex({PARK_AT}, ListView.Beginning)")
    if not wait_for(lambda: lq(f"qLedger.itemAtIndex({PARK_AT})") is not None, "the parked row is built"):
        bad.append(f"the ledger built no delegate at {PARK_AT} to watch across a tick")
    y0 = float(lq("qLedger.contentY"))
    top0 = first_visible()
    held = lq(f"qLedger.itemAtIndex({PARK_AT})")
    held_next = lq(f"qLedger.itemAtIndex({PARK_AT + 1})")
    bridge._track_lifecycle(
        qid,
        {"id": str(PARK_AT), "num": PARK_AT + 1, "title": f"track {PARK_AT + 1}", "status": "failed"},
    )
    if not wait_for(
        lambda: item_prop(PARK_AT, "qTrackWord", "text") == "FAILED",
        "the changed track repaints in place",
    ):
        bad.append(f"the changed track still reads {item_prop(PARK_AT, 'qTrackWord', 'text')!r}, want FAILED")
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

    checkpoint("growth")
    # A track arriving live grows the list by one slot without moving the
    # reader, and the new tail is reachable.
    bridge._track_lifecycle(qid, {"id": "late", "title": "late arrival", "status": "queued"})
    if not wait_for(lambda: int(lq("qLedger.count")) == BIG + 1, "the live track joins the ledger"):
        bad.append(f"a track arriving live left the ledger at {lq('qLedger.count')} rows, want {BIG + 1}")
    if abs(float(lq("qLedger.contentY")) - y0) > 1:
        bad.append("a track arriving live moved the scrolled ledger")
    if first_visible() != top0:
        bad.append("a track arriving live changed the first visible row")
    if lq(f"qLedger.itemAtIndex({PARK_AT})") is not held:
        bad.append("a track arriving live recreated the delegate at the reader's position")
    lq("qLedger.positionViewAtEnd()")
    if not wait_for(lambda: item_prop(BIG, "qTrackTitle", "text") == "late arrival", "the live tail is reachable"):
        bad.append(f"the live tail is not reachable (last row shows {item_prop(BIG, 'qTrackTitle', 'text')!r})")
    if rows > 0 and not wait_for(
        lambda: rows <= len(built_titles()) <= window_bound(rows),
        "the ledger's end builds only its window plus cache",
    ):
        bad.append(f"at its end the ledger built {len(built_titles())} rows, want at most {window_bound(rows)}")

    checkpoint("pref")
    # The box's size is a setting, and an open row follows it live.
    bridge.setWavesPref("queue_ledger_rows", 6)
    if not wait_for(lambda: int(q("root.queueLedgerRows")) == 6, "Main.qml re-reads the row count"):
        bad.append(f"set to 6 rows, Main.qml reads queueLedgerRows {q('root.queueLedgerRows')}")
    want_box = 6 * pitch - gap
    if not wait_for(
        lambda: abs(float(lq("qLedger.height")) - want_box) < 0.5,
        f"the ledger follows the setting to {want_box}px",
    ):
        bad.append(f"set to 6 rows, the open ledger is {lq('qLedger.height')}px tall, want {want_box}px")
    if not wait_for(
        lambda: 6 <= len(built_titles()) <= window_bound(6),
        "six rows build only their window plus cache",
    ):
        bad.append(f"set to 6 rows, the ledger built {len(built_titles())} rows, want at most {window_bound(6)}")
    bridge.setWavesPref("queue_ledger_rows", 12)
    wait_for(lambda: int(q("root.queueLedgerRows")) == 12, "Main.qml re-reads the restored row count")

    checkpoint("fold")
    # Folding drops the model back to the peek's slots and then none, and
    # reopening lists every track again from the top: the remove half of the
    # incremental sync, which a live tick never exercises.
    q("root.queueExpanded = ({})")
    if not wait_for(lambda: int(lq("qLedger.count")) == 0, "a folded ledger drops its slots"):
        bad.append(f"a folded ledger still holds {lq('qLedger.count')} slots, want none")
    if not wait_for(lambda: float(lq("qtrackClip.implicitHeight")) < 0.5, "a folded ledger closes its box"):
        bad.append(f"a folded ledger's box is still {lq('qtrackClip.implicitHeight')}px tall")
    q(f"root.queueExpanded = ({{ {qid}: true }})")
    if not wait_for(lambda: int(lq("qLedger.count")) == BIG + 1, "a reopened ledger lists every track"):
        bad.append(f"a reopened ledger holds {lq('qLedger.count')} slots, want {BIG + 1}")
    if first_visible() != 0:
        bad.append(f"a reopened ledger starts at row {first_visible()}, want its first track")

    checkpoint("album")
    # An ordinary album is untouched: every track, and no scroll.
    q("root.queueExpanded = ({})")
    bridge._queue.clear()
    bridge._queue_index.clear()
    bridge.queueChanged.emit([])
    qid = seed(SMALL, "album", "Ordinary Record")
    q(f"root.queueExpanded = ({{ {qid}: true }})")
    if not wait_for(lambda: len(built_titles()) == SMALL, "the album lists every track"):
        bad.append(f"an expanded {SMALL}-track album built {len(built_titles())} ledger rows, want all {SMALL}")
    if bool(lq("qLedger.interactive")):
        bad.append("an album that fits still scrolls")
    if not wait_for(
        lambda: abs(float(lq("qLedger.height")) - (SMALL * pitch - gap)) < 0.5,
        "the album's ledger fits its rows",
    ):
        bad.append(
            f"an album that fits is {lq('qLedger.height')}px tall, want all {SMALL} rows ({SMALL * pitch - gap}px)"
        )
    if has_more_line():
        bad.append("an album that fits still carries an 'N more tracks' line")

    if bad:
        for b in bad:
            print(b, file=sys.stderr)
        return EXIT_REGRESSED
    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_run_scenario())
