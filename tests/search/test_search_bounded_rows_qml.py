"""A search section builds only the rows it shows, top-first.

Runs in a subprocess like the other Main.qml scenarios: building the bridge
installs process-global handlers that must not leak into the suite.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from support.qml import EXIT_OK, boot_main_qml, run_scenario


@pytest.mark.qml
def test_search_sections_build_only_the_rows_they_show():
    run_scenario(Path(__file__), "--run-scenario", sandbox_prefix="waves-search-bounded-test-")


def _album(i: int) -> dict:
    return {
        "id": f"al{i}",
        "title": f"Album {i}",
        "artist": "Lab Artist",
        "artist_id": "ar0",
        "art": "",
        "year": 2020,
        "date": "2020-01-01",
        "tracks": 10,
        "duration_sec": 2400,
        "quality": "LOSSLESS",
        "popularity": 10,
        "explicit": False,
        "kind": "album",
        "artists": [{"id": "ar0", "name": "Lab Artist"}],
    }


def _scenario() -> int:
    booted = boot_main_qml()
    if not isinstance(booted, tuple):
        return booted
    _root, q, settle, bridge = booted
    from search.fakes import qml_search_payload

    q("openSearch()")
    settle(50)
    q("root._searchSeq = root._navSeq")
    bridge.searchResults.emit(qml_search_payload(albums=[_album(i) for i in range(30)]))
    # Realise the page: without a layout the rows are never built and this
    # scenario would pass against nothing at all.
    q("results.contentHeight")
    settle(50)

    failures: list[str] = []

    def check(cond, what: str) -> None:
        if not cond:
            failures.append(what)

    # The only thing a fresh search still waits for is the library (the
    # badges): the page's rows build by window from the frame they arrive,
    # so the veil must be down without waiting on rows beyond the opening
    # screen.
    check(
        q("root.searchBuilding") is False,
        "the veil is still waiting on result rows",
    )
    settle(1150)

    # The mixed view shows five; every row past the cap must stay unbuilt
    # (its Loader exists for count/geometry, but loads nothing).
    check(
        q("searchResultsView.albumRepeater.itemAt(6).active") is False,
        "a row past the cap is active before SHOW ALL",
    )
    check(
        q("searchResultsView.albumRepeater.itemAt(6).item === null") is True,
        "a row past the cap was built before SHOW ALL",
    )

    # SHOW ALL: the screen right under the rows already shown builds in the
    # click (the first frame is the finished one); the rows further down
    # incubate with their heights reserved.
    q("searchResultsView.toggleExpanded('albums')")
    check(
        q("searchResultsView.albumRepeater.itemAt(5).item !== null") is True,
        "SHOW ALL left the screen under the cap unbuilt in the click",
    )
    check(
        q("searchResultsView.albumRepeater.itemAt(29).item === null") is True,
        "SHOW ALL built the far rows inline instead of incubating them",
    )
    settle(1500)
    check(
        q("searchResultsView.albumRepeater.itemAt(29).item !== null") is True,
        "the incubated rows never arrived",
    )
    # SHOW LESS keeps the built rows: hidden, not destroyed, so a second
    # SHOW ALL costs nothing.
    before = q("String(searchResultsView.albumRepeater.itemAt(29))")
    q("searchResultsView.toggleExpanded('albums')")
    settle(100)
    check(
        q("searchResultsView.albumRepeater.itemAt(29).item !== null") is True,
        "SHOW LESS destroyed the built rows",
    )
    check(
        q("searchResultsView.albumRepeater.itemAt(29).visible") is False,
        "a row past the cap stayed visible after SHOW LESS",
    )
    check(
        q("String(searchResultsView.albumRepeater.itemAt(29))") == before,
        "SHOW LESS rebuilt the kept rows instead of hiding them",
    )

    if failures:
        for f in failures:
            print("REGRESSED:", f, file=sys.stderr)
        return 1
    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_scenario())
