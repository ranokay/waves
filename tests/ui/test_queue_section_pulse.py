"""The queue's section headers pulse the number that GREW.

WHAT THIS FENCES OFF
--------------------
A finished row's promotion moves it out of Downloading and into Completed in
one tick: one count falls, the other rises. The pulse was routed through a
root-wide ``compBump`` signal that every section header listened to, each
deciding whether the bump was its own with a ``section === "completed"`` test.
The view POOLS those headers, so the instance answering the signal was not
reliably the completed one, and what the drawer actually animated was
DOWNLOADING counting DOWN: a bounce celebrating a number shrinking, on the one
header where shrinking is not the news, while the count that had just gone up
sat still.

Each header now watches its own count and pulses only on a rise. Proved on the
real Main.qml in a subprocess, by driving a real promotion through the real
queue model and reading which header's animation ran.
"""

from __future__ import annotations

import sys

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
def test_the_pulse_follows_the_count_that_rose() -> None:
    run_scenario(
        __file__,
        "--run-scenario",
        timeout=180,
        sandbox_prefix="waves-queue-section-pulse-",
        failure_message="the wrong section header is pulsing",
    )


@pytest.mark.qml
def test_the_first_row_into_an_empty_section_pulses_too() -> None:
    """An audit read the arming as unable to serve the header a promotion
    CREATES, on the grounds that the tick fires while no such header is
    listening yet. It reaches it anyway, and the two properties this design
    already has are why: the tick arms every header that exists at that
    moment, the view hands one of those POOLED headers to the section that
    just appeared, and the timer fires afterwards and asks what section it is
    holding by then. Pinned here because it is not obvious from either half,
    and because an arming added "to be safe" on header creation is the
    tempting wrong answer (it also needs a staleness window, and that window
    is what makes a recycled header replay an old pulse)."""
    run_scenario(
        __file__,
        "--run-first-row",
        timeout=180,
        sandbox_prefix="waves-queue-section-pulse-",
        failure_message="a section gaining its first row did not pulse",
    )


# The queue's section headers, and the pulse animation inside one of them.
# Returned one at a time as plain scalars / objects: a JS map comes back from
# QQmlExpression as an opaque QJSValue.
_SECTIONS = """
(function(){
    var out = []
    var walk = function(o){
        if (!o) return
        if (o.objectName === "queueSectionHeader") out.push("" + o.section)
        var c = o.children || []
        for (var i = 0; i < c.length; i++) walk(c[i])
    }
    walk(queueList)
    return out.join(",")
})()
"""


def _pulse_of(section: str) -> str:
    """The pulse state of the header holding ``section``: the animation's own
    identity and whether it runs, pipe-joined.

    Each header owns one pulse animation, so the animation's JS string
    ("QQuickSequentialAnimation(0x...)") is stable for that header's lifetime.
    The view pools these headers and can hand the section from one to another
    while the promotion settles, so a verdict keyed to the section NAME alone
    can read the pulse of the instance already on its way out.
    """
    return """
(function(){
    var found = null
    var walk = function(o){
        if (!o || found) return
        if (o.objectName === "queueSectionHeader" && ("" + o.section) === "__SECTION__") {
            // `data`, not `children`: an animation is not an Item, so it
            // sits in the header's resources rather than its child items.
            var k = o.data || []
            for (var j = 0; j < k.length; j++) if (k[j].objectName === "queueSectionPulse") found = k[j]
        }
        var c = o.children || []
        for (var i = 0; i < c.length && !found; i++) walk(c[i])
    }
    walk(queueList)
    if (!found) return "__NONE__"
    return String(found) + "|" + (found.running ? "1" : "0")
})()
""".replace("__SECTION__", section)


def _run_scenario(first_row: bool = False) -> int:
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
        from waves.waves_ui.app import _load_mono
        from waves.waves_ui.backend import WavesBridge
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

    # The queue ListView lives inside QueueDrawer.qml (#315 slice 4):
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

    # Two downloads in flight, and one already promoted, so BOTH headers the
    # promotion touches exist before the one under test moves.
    for i in range(3):
        bridge._enqueue(f"Album {i}", "album", media_id=f"al-{i}", collection=True, tracks=9)
    bridge.queueChanged.emit(list(bridge._queue))
    settle(160)
    qids = [int(it["qid"]) for it in bridge._queue]
    # Downloading, which is the section the promotion takes the row OUT of and
    # the one that was bouncing as its count fell.
    for it in bridge._queue:
        it["status"] = "running"
    bridge.queueChanged.emit(list(bridge._queue))
    settle(160)
    downloading = int(
        q(
            "(function(){ var n = 0; for (var i = 0; i < queueModel.count; i++)"
            " if (queueModel.get(i).uiGroup === 'downloading') n++; return n })()"
        )
    )
    if downloading != len(qids):
        print(f"the rows did not land in Downloading: {downloading} of {len(qids)}", file=sys.stderr)
        return EXIT_PRECONDITION
    if not first_row:
        # One row promoted first, so the Completed header already exists and
        # the measured promotion below is a plain count change on two live
        # headers. The first_row run deliberately skips this: there COMPLETED
        # does not exist yet, and the promotion under test is what creates it.
        q(f"root.promoteCompleted({qids[0]})")
        settle(400)

    # The tick under test: one row leaves Downloading, one joins Completed.
    first = qids[0] if first_row else qids[1]
    q(f"root.promoteCompleted({first})")
    # Past the headers' arming frame and inside the 330ms pulse. Polled, not
    # sampled once: a single fixed settle can land before the arming frame on
    # a loaded machine and past the whole pulse on a very slow one, and both
    # read as "COMPLETED did not pulse".
    #
    # The read keys to the INSTANCE holding the section, sampled to the end of
    # the window: the view hands a pooled header to a section while the row
    # lands, so judging the pulse the instant one is seen can bless an
    # animation on the instance being swapped away. The verdict below is the
    # holder at the END, the header the section keeps: it must have pulsed,
    # and only a rise may pulse.
    running_by_section: dict[str, str] = {}
    holder_by_section: dict[str, str] = {}
    sections: list[str] = []
    for _ in range(20):
        settle(16)
        sections = [x for x in str(qd(_SECTIONS)).split(",") if x]
        if "completed" not in sections:
            continue
        for section in sections:
            state = str(qd(_pulse_of(section)))
            ident, _, running = state.partition("|")
            if ident == "__NONE__":
                # NOT a precondition: a header with no pulse animation is the
                # regression this test exists to catch. Routing it to a skip
                # meant deleting the animation turned the guard green.
                print(f"the {section!r} header has no pulse animation", file=sys.stderr)
                return EXIT_REGRESSED
            holder_by_section[section] = ident
            if running == "1":
                running_by_section[section] = ident
    if "completed" not in sections or "downloading" not in sections:
        print(f"the two headers the promotion touches were not both built: {sections}", file=sys.stderr)
        return EXIT_PRECONDITION
    bad: list[str] = []
    for section in sections:
        running = running_by_section.get(section) == holder_by_section.get(section)
        # Completed just gained the promoted row; every other section either
        # lost one or did not move, and a loss must never be celebrated.
        if section == "completed" and not running:
            bad.append("COMPLETED gained a row and did not pulse")
        if section != "completed" and section in running_by_section:
            bad.append(f"{section.upper()} pulsed without its count rising")

    if bad:
        for b in bad:
            print(b, file=sys.stderr)
        return EXIT_REGRESSED
    return EXIT_OK


if __name__ == "__main__" and ("--run-scenario" in sys.argv or "--run-first-row" in sys.argv):
    sys.exit(_run_scenario(first_row="--run-first-row" in sys.argv))
