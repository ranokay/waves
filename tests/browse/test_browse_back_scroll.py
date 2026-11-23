"""Back to Browse lands on your scroll position, never the top.

WHAT THIS FENCES OFF
--------------------
Going Back from a drilled page (a playlist, an album, any long listing) to the
Browse landing must land on the spot the user left, not at the top.

HOW THIS STAYS FIXED
--------------------
Browse renders through two always-alive panes (``browseLanding`` and
``browseDrill``, both ``BrowseScroll``): navigation only flips which pane is
visible, so the landing's ``contentY`` is simply still where the user left it.
Nothing is rebuilt on Back and nothing needs restoring; this test fails if
anyone reintroduces a teardown on the Back path (a model swap, a pane reset)
that loses the position. The hold-in-place machinery that remains in
``BrowseScroll`` covers CONTENT swaps (revalidate, endless-scroll growth); the
artist pane carries its own copy of that mechanism.

HOW IT IS RUN
-------------
The scenario boots the REAL ``Main.qml`` and drives ``openBrowseItem`` ->
``navBack`` with a playlist taller than the saved offset, asserting the
landing shows again at the saved spot. It lands at the top (exit 1) on a
regressed tree and on the saved spot (exit 0) otherwise. It runs in a
SUBPROCESS: constructing the bridge installs a process-global Qt message
handler / diagnostics logging that would otherwise leak into unrelated tests
in the same interpreter.
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

# A fixed window size makes contentHeight/maxY deterministic across machines, so
# the saved offset the scenario restores to does not depend on the CI window size.
_WIN_W, _WIN_H = 1100, 720


# ===========================================================================
# pytest wrapper: run the scenario isolated, assert the outcome by exit code.
# ===========================================================================
@pytest.mark.qml
def test_back_from_long_playlist_restores_browse_scroll():
    run_scenario(
        Path(__file__),
        "--run-scenario",
        timeout=120,
        sandbox_prefix="waves-backscroll-test-",
        failure_message="Back to Browse did not restore the scroll position (scroll-restore regression).",
    )


# ===========================================================================
# Standalone scenario (runs in its own interpreter via support.qml.run_scenario).
# ===========================================================================
def _landing() -> dict:
    """Ten card shelves: a tall, scrollable Browse landing that rebuilds through
    asynchronous Loaders (an async rebuild collapses contentHeight on
    the way back)."""

    def card(i: int, j: int) -> dict:
        return {"id": f"a{i}_{j}", "kind": "album", "title": f"Album {i}.{j}", "artist": f"Artist {j}"}

    return {
        "sections": [
            {"title": f"Shelf {i}", "rowKind": "cards", "items": [card(i, j) for j in range(12)]} for i in range(10)
        ],
        "genres": [],
        "moods": [],
        "decades": [],
        "error": False,
    }


def _playlist() -> dict:
    """A long track listing: taller than the saved landing offset, which is the
    precondition that let the stale-height check spend the restore early. No
    ``data``/``total`` keys, so browseCanGrow stays false and the endless-scroll
    path can never move contentY behind the scenario's back."""
    return {
        "key": "item:playlist:p1",
        "title": "Long Playlist",
        "header": {"title": "Long Playlist", "kind": "playlist"},
        "sections": [
            {
                "title": "Tracks",
                "rowKind": "tracks",
                "items": [
                    {
                        "id": f"t{n}",
                        "kind": "track",
                        "title": f"Track {n}",
                        "artist": f"Artist {n}",
                        "duration": "3:20",
                        "num": n + 1,
                    }
                    for n in range(120)
                ],
            }
        ],
        "error": False,
    }


def _run_scenario() -> int:
    # A deliberately linear boot -> drive -> assert scenario (C901 per-file-ignore).
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
    root.setProperty("width", _WIN_W)
    root.setProperty("height", _WIN_H)

    def q(expr: str):
        # Evaluate in Main.qml's own scope so its ids (the browse panes, the
        # nav functions) resolve. PySide6 returns evaluate()'s
        # valueIsUndefined out-param as a tuple.
        ctx = QQmlEngine.contextForObject(root)
        e = QQmlExpression(ctx, root, expr)
        r = e.evaluate()
        if e.hasError():
            raise RuntimeError(e.error().toString())
        return r[0] if isinstance(r, tuple) else r

    def pump(predicate, timeout_ms: int = 6000) -> bool:
        loop = QEventLoop()
        state = {"ok": False}

        def tick():
            try:
                if predicate():
                    state["ok"] = True
                    loop.quit()
            except Exception:
                loop.quit()

        poll = QTimer()
        poll.setInterval(25)
        poll.timeout.connect(tick)
        poll.start()
        QTimer.singleShot(timeout_ms, loop.quit)
        loop.exec()
        poll.stop()
        return state["ok"]

    def settle(ms: int = 200) -> None:
        pump(lambda: False, ms)

    # 1. Land on Browse and let the async shelves finish building.
    root.setProperty("browseOpen", True)
    root.setProperty("browseSections", [])  # force the fresh-build (async) path
    bridge.browseLoaded.emit(_landing())
    if not pump(
        lambda: (
            q("browsePageKey") == ""
            and not q("browseBuilding")
            and q("browseLanding.contentHeight") > q("browseLanding.height") + 200
        )
    ):
        print("Browse landing never became scrollable", file=sys.stderr)
        return EXIT_PRECONDITION
    settle()

    landing_ch = q("browseLanding.contentHeight")
    landing_max = max(0.0, landing_ch - q("browseLanding.height"))
    if landing_max <= 100:
        print("no scrollable landing in this environment", file=sys.stderr)
        return EXIT_PRECONDITION

    # 2. Scroll partway down and remember the spot.
    saved = round(landing_max * 0.6)
    q(f"browseLanding.contentY = {saved}")
    saved = q("browseLanding.contentY")
    if saved <= 10:
        print("could not establish a non-top scroll offset", file=sys.stderr)
        return EXIT_PRECONDITION

    # 3. Drill into a tall playlist: taller than the saved offset is the
    #    precondition that let the stale-height check disarm the restore.
    q('openBrowseItem("playlist", "p1")')
    bridge.browsePageLoaded.emit(_playlist())
    if not pump(
        lambda: (
            q("browsePageKey") == "item:playlist:p1"
            and (q("browseDrill.contentHeight") - q("browseDrill.height")) > saved
        )
    ):
        print("playlist page never grew taller than the saved position", file=sys.stderr)
        return EXIT_PRECONDITION

    # 4. Back to Browse. The landing pane never went away, so its height must
    #    already be the landing's and its position must be the saved spot; the
    #    pump only absorbs the event-loop turns the nav flip itself needs.
    q("navBack()")
    if not pump(lambda: q("browsePageKey") == "" and abs(q("browseLanding.contentHeight") - landing_ch) <= 1):
        print("Browse landing is not at its original height after Back", file=sys.stderr)
        return EXIT_PRECONDITION
    settle()

    final = q("browseLanding.contentY")
    restored = abs(final - saved) <= 2
    print(f"savedY={saved:.0f} finalY={final:.0f} restored={restored}", flush=True)
    return EXIT_OK if restored else EXIT_REGRESSED


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_run_scenario())
