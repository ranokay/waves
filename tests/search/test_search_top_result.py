"""A specific search answers at the top of the results page.

WHAT THIS FENCES OFF
--------------------
Two things bury the one result a specific search ("this song by this artist")
is after, even though TIDAL ranked it first in its reply:

1. A "Relevance" sort that re-sorts every section by POPULARITY. A single
   released this week has a popularity of 0, so it sinks under every older
   track sharing a word with the query, and the user must switch to
   "Release date" to find it.
2. The mixed All view stacking its sections in a fixed order (artists, then
   albums, then tracks), so even a perfect album or track match sits under
   whichever artists TIDAL fuzzy-matched on one word of the query.

HOW THIS STAYS FIXED
--------------------
Relevance is TIDAL's order, kept as it arrived (Popularity is its own sort
option), and the backend carries TIDAL's own ``top_hit`` in the payload as
``top``: a row dict tagged with its kind, which the mixed view pins above
every section as TOP RESULT (album, track, video or playlist; an artist top
hit is dropped because the artist strip already leads with that artist).

The scenario boots the REAL Main.qml offscreen, renders a payload whose
top hit is a low-popularity album, and asserts: the TOP RESULT row sits
above the ARTISTS header; the tracks section keeps the API's order under
Relevance (the pop-0 track stays first); the Popularity option reorders
it; a section filter hides the pin; a payload without a top hit renders
no pin. It also saves a screenshot of the page for eyeballing.

Runs in a SUBPROCESS, like the other bridge scenarios: building the
bridge installs process-global handlers that must not leak into the suite.
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

_WIN_W, _WIN_H = 1100, 900


def _results(top: bool) -> dict:
    """A search reply shaped like the backend's: the wanted single is
    ranked first by TIDAL in albums and tracks but has popularity 0."""

    def artist(i: int) -> dict:
        return {"id": f"ar{i}", "name": f"Artist {i}", "art": "", "roles": "", "popularity": 40}

    def album(i: int, pop: int) -> dict:
        return {
            "id": f"al{i}",
            "title": f"Album {i}",
            "artist": "Some Artist",
            "artist_id": "ar0",
            "art": "",
            "year": "2026",
            "date": f"2026-01-{i + 1:02d}",
            "tracks": 1,
            "duration_sec": 200,
            "quality": "LOSSLESS",
            "popularity": pop,
            "explicit": False,
            "added": "",
        }

    def track(i: int, pop: int) -> dict:
        return {
            "id": f"t{i}",
            "title": f"Track {i}",
            "artist": "Some Artist",
            "artist_id": "ar0",
            "album": f"Album {i}",
            "album_id": f"al{i}",
            "num": 1,
            "vol": 1,
            "art": "",
            "year": "2026",
            "date": f"2026-01-{i + 1:02d}",
            "duration": "3:20",
            "duration_sec": 200,
            "quality": "LOSSLESS",
            "popularity": pop,
            "explicit": False,
            "added": "",
        }

    pops = [0, 64, 58, 60, 59]  # the wanted single first, older hits behind it
    return {
        "groups": [
            {
                "provider": "tidal",
                "artists_layout": "strip",
                "artists": [artist(i) for i in range(3)],
                "albums": [album(i, p) for i, p in enumerate(pops)],
                "tracks": [track(i, p) for i, p in enumerate(pops)],
                "videos": [],
                "playlists": [],
                "mixes": [],
                "top": {"kind": "album", **album(0, 0)} if top else None,
                "error": "",
            }
        ]
    }


def _run_scenario() -> int:
    # Optional second argument: a PNG path to save the rendered page to.
    shot = sys.argv[2] if len(sys.argv) > 2 else ""
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
        from support.offline import PARK_LOGIN_QML, patch_offline

        patch_offline()
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

    settle()
    q(PARK_LOGIN_QML)
    q("openSearch()")
    settle()

    failures: list[str] = []

    # 1. A search whose top hit is the pop-0 album.
    q("_searchSeq = _navSeq")
    bridge.searchResults.emit(_results(top=True))
    if not pump(lambda: not q("searchBuilding")):
        print("search never finished building", file=sys.stderr)
        return EXIT_PRECONDITION
    settle()

    tidal = "root.searchGroupFor('tidal')"
    if not q(tidal + ".topVisible"):
        failures.append("TOP RESULT header not visible in the All view")
    top_y = q(tidal + ".topHeadItem.y")
    artists_y = q(tidal + ".artistsHeadItem.y")
    if not (top_y < artists_y):
        failures.append(f"TOP RESULT header (y={top_y}) is not above ARTISTS (y={artists_y})")
    # The pinned row is the album's own delegate, rendered and sized.
    pin_h = q(tidal + ".topRepeater.itemAt(0) ? " + tidal + ".topRepeater.itemAt(0).height : 0")
    if not (pin_h and pin_h > 40):
        failures.append(f"pinned row has no height (h={pin_h})")

    # 2. Relevance keeps TIDAL's order: the pop-0 single stays first.
    if q("sortBox.currentIndex") != 0:
        failures.append("sort control does not default to Relevance")
    if q(tidal + ".modelFor('tracks').get(0).id") != "t0" or q(tidal + ".modelFor('albums').get(0).id") != "al0":
        failures.append("Relevance re-sorted the sections away from TIDAL's order")

    # 3. Popularity is its own option and does reorder.
    # Chosen the way a user does it (the control's own activation), so the
    # choice is also written to the pref that restores it on the next launch.
    q("sortBox.currentIndex = 3")
    q("sortBox.activated(3)")
    settle(50)
    if q(tidal + ".modelFor('tracks').get(0).id") != "t1":
        failures.append("Popularity sort did not put the most popular track first")
    if q('waves.wavesPref("search_sort")') != "popularity":
        failures.append("choosing Popularity did not persist search_sort")
    q("sortBox.currentIndex = 0")
    q("sortBox.activated(0)")
    settle(50)
    if q(tidal + ".modelFor('tracks').get(0).id") != "t0":
        failures.append("returning to Relevance did not restore TIDAL's order")
    if q('waves.wavesPref("search_sort")') != "relevance":
        failures.append("returning to Relevance did not persist search_sort")

    if shot:
        q("results.contentY = 0")
        settle(100)
        q(f'results.grabToImage(function(r) {{ r.saveToFile("{shot}") }})')
        pump(lambda: Path(shot).exists(), 4000)

    # 4. A section filter hides the pin (the section is in relevance order).
    q('filterType = "albums"')
    settle(50)
    if q(tidal + ".topVisible"):
        failures.append("TOP RESULT still visible under the Albums filter")
    q('filterType = "all"')
    settle(50)

    # 5. A reply without a top hit renders no pin.
    q("_searchSeq = _navSeq")
    bridge.searchResults.emit(_results(top=False))
    if not pump(lambda: not q("searchBuilding")):
        print("second search never finished building", file=sys.stderr)
        return EXIT_PRECONDITION
    settle()
    if q(tidal + ".topVisible") or q(tidal + ".topRow") is not None:
        failures.append("a reply without a top hit still shows TOP RESULT")

    for f in failures:
        print(f"FAIL: {f}", flush=True)
    print(f"checks failed: {len(failures)}", flush=True)
    return EXIT_REGRESSED if failures else EXIT_OK


@pytest.mark.qml
def test_specific_search_answers_at_the_top():
    run_scenario(
        Path(__file__),
        "--run-scenario",
        "",
        timeout=120,
        sandbox_prefix="waves-searchtop-test-",
        failure_message="search top-result regression.",
    )


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_run_scenario())
