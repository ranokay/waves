"""Navigation bookkeeping must react to NAVIGATIONS, not to arrivals.

THREE BUGS FENCED OFF HERE
-------------------------
1. ``onBrowseLoaded`` called ``markNav``, which bumps ``_navSeq``. The Browse
   landing re-emits on every background revalidate (near enough every launch,
   since the landing embeds the home-feed rows), so a search issued right
   after launch had its results discarded by ``onSearchResults``' staleness
   guard: the status bar read "n results" while the pane still showed the
   empty-state hint. Payload arrivals go through ``markRender``, which
   stamps the perf timer without touching the sequence.

2. ``navBack`` marked the navigation and recorded a forward entry BEFORE its
   empty-history fallback, so a Back press that changed nothing (the search
   root, nothing recorded, no surface open) still bumped ``_navSeq``, killing
   an in-flight search, and left one dead Forward press per over-press.

3. ``crumbTrimRevisit``'s ``_navRestoring`` guard never fired: the trim runs
   off a 0ms timer, by which time ``_navRestore`` has already cleared the flag.
   A Back or Forward landing on a section root could therefore trim away the
   very history it had just walked into.

Runs in a SUBPROCESS for the same reason as test_search_results_surface_steal:
building the bridge installs process-global handlers.
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

_EMPTY_RESULTS = {"groups": []}


@pytest.mark.qml
def test_nav_sequence_and_history_guards():
    run_scenario(
        Path(__file__),
        "--run-scenario",
        timeout=120,
        sandbox_prefix="waves-navguard-test-",
        failure_message="navigation bookkeeping regressed.",
    )


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

    def settle(ms: int = 120) -> None:
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    settle()

    # 1. A BACKGROUND BROWSE REVALIDATE IS NOT A NAVIGATION. The user is on the
    #    search page waiting for results; the boot revalidate lands first.
    q("openSearch()")
    settle()
    q("navHistory = []")
    q("_searchSeq = _navSeq")
    seq_before = q("_navSeq")
    bridge.browseLoaded.emit({"sections": [], "error": False})
    settle()
    seq_held = q("_navSeq") == seq_before
    bridge.searchResults.emit(dict(_EMPTY_RESULTS))
    settle()
    search_survived = q("_navLabel") == "search render" and q("navOrigin") == "search"

    # 2. A BACK PRESS THAT LANDS NOWHERE IS A COMPLETE NO-OP. Nothing recorded,
    #    no surface open: the mouse side button (or the macOS back gesture)
    #    must not bump the sequence or record a forward entry.
    q("openSearch()")
    settle()
    q("navHistory = []")
    q("navForwardHistory = []")
    q("_searchSeq = _navSeq")
    seq_before = q("_navSeq")
    q("navBack()")
    settle()
    noop_back = q("_navSeq") == seq_before and q("navForwardHistory.length") == 0
    bridge.searchResults.emit(dict(_EMPTY_RESULTS))
    settle()
    noop_back = noop_back and q("_navLabel") == "search render"

    # 3. BACK MUST NOT TRIM THE HISTORY IT JUST WALKED INTO. Collapsing the
    #    whole trail when a section root also sits earlier in it makes the
    #    next Back fall through to the level-up fallback.
    q("openSearch()")
    settle()
    q(
        "navHistory = [{v:'search',label:'Search'},"
        " {v:'library',cat:'home',label:'My Music'},"
        " {v:'search',label:'Search'}]"
    )
    # No settle here on purpose: the 0ms trim timer must not run between
    # seeding the history and the Back press, or it would collapse the seeded
    # trail itself (arriving at a root already in the trail is the trim's
    # intended job). What is under test is the trim that fires AFTER the Back.
    q("navBack()")
    settle()
    kept_history = q("navHistory.length") == 2

    print(
        f"seqHeld={seq_held} searchSurvived={search_survived} noopBack={noop_back} keptHistory={kept_history}",
        flush=True,
    )
    ok = seq_held and search_survived and noop_back and kept_history
    return EXIT_OK if ok else EXIT_REGRESSED


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_run_scenario())
