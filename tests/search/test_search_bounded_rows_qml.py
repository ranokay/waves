"""A search section builds only the rows it shows, top-first.

Runs in a subprocess like the other Main.qml scenarios: building the bridge
installs process-global handlers that must not leak into the suite.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from support.qml import EXIT_OK, boot_main_qml, run_scenario, wait_until_true


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


def _track(i: int) -> dict:
    return {
        "id": f"tr{i}",
        "title": f"Track {i}",
        "artist": "Lab Artist",
        "artist_id": "ar0",
        "album": "Album 0",
        "album_id": "al0",
        "art": "",
        "year": 2020,
        "date": "2020-01-01",
        "duration": "3:00",
        "duration_sec": 180,
        "quality": "LOSSLESS",
        "popularity": 10,
        "explicit": False,
        "kind": "track",
        "artists": [{"id": "ar0", "name": "Lab Artist"}],
    }


def _scenario() -> int:
    booted = boot_main_qml()
    if not isinstance(booted, tuple):
        return booted
    _root, q, settle, bridge = booted
    from search.fakes import qml_search_payload

    failures: list[str] = []

    def check(cond, what: str) -> None:
        if not cond:
            failures.append(what)

    def wait(expr: str, what: str, timeout_ms: int = 15000) -> None:
        check(wait_until_true(q, expr, what, timeout_ms=timeout_ms), what)

    q("openSearch()")
    settle(50)  # the tab's own layout pass, so the payload realizes rows

    q("root._searchSeq = root._navSeq")
    bridge.searchResults.emit(
        qml_search_payload(albums=[_album(i) for i in range(120)], tracks=[_track(i) for i in range(30)])
    )

    # The handler builds the screen the page opens on in its own turn, so
    # the first frame is the finished one; rows below the fold and past a
    # cap are still empty Loaders right after the payload applies.
    check(
        q("searchResultsView.albumRepeater.itemAt(0).item !== null") is True,
        "the opening screen's first album was not built in the payload's own turn",
    )
    check(
        q("searchResultsView.albumRepeater.itemAt(29).item === null") is True,
        "a far album row was built before its incubation",
    )
    check(
        q("searchResultsView.tracksRepeater.itemAt(0).item !== null") is True,
        "the opening screen's first track was not built in the payload's own turn",
    )

    q("results.contentHeight")
    # The veil is the library-badge wait, and this sandbox has no library:
    # nothing waits, and no row's load can raise it.
    check(q("root.searchBuilding") is False, "the veil is still waiting on result rows")

    wait("searchResultsView.countFor('albums') == 120", "the albums section never filled")

    # The mixed view shows five; every row past the cap must stay unbuilt
    # (its Loader exists for count/geometry, but loads nothing).
    check(
        q("searchResultsView.albumRepeater.itemAt(6).active") is False, "a row past the cap is active before SHOW ALL"
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
    # The reach bounds how far rows exist: past the window plus one batch
    # they stay inactive, so the section fills from the fold down instead of
    # the newest rows incubating first.
    check(
        q("searchResultsView.albumRepeater.itemAt(100).active") is False,
        "a row beyond the reach is active before its batch",
    )
    wait("searchResultsView.albumRepeater.itemAt(29).item !== null", "the incubated rows never arrived")
    wait("searchResultsView.albumRepeater.itemAt(119).item !== null", "the batching never reached the last row")

    # SHOW LESS keeps the built rows: hidden, not destroyed, so a second
    # SHOW ALL costs nothing.
    before = q("String(searchResultsView.albumRepeater.itemAt(29))")
    q("searchResultsView.toggleExpanded('albums')")
    settle(50)  # one layout pass for the visibility bindings
    check(q("searchResultsView.albumRepeater.itemAt(29).item !== null") is True, "SHOW LESS destroyed the built rows")
    check(
        q("searchResultsView.albumRepeater.itemAt(29).visible") is False,
        "a row past the cap stayed visible after SHOW LESS",
    )
    check(
        q("String(searchResultsView.albumRepeater.itemAt(29))") == before,
        "SHOW LESS rebuilt the kept rows instead of hiding them",
    )

    # A type chip shows its whole section the way SHOW ALL does: the screen
    # the page lands on builds in the click, the rest incubates.
    q("searchResultsView.setFilter('tracks')")
    check(q("root.filterType") == "tracks", "the chip did not switch the section filter")
    check(
        q("searchResultsView.tracksRepeater.itemAt(5).item !== null") is True,
        "the chip left the section's opening screen unbuilt in the click",
    )
    check(
        q("searchResultsView.tracksRepeater.itemAt(29).item === null") is True,
        "the chip built the far rows inline instead of incubating them",
    )
    wait("searchResultsView.tracksRepeater.itemAt(29).item !== null", "the chip's incubated rows never arrived")
    wait("searchResultsView.countFor('tracks') == 30", "the tracks section never filled")

    # A provider source chip can hide a whole section, moving the others:
    # the windows re-plan, so a later chip that brings the section back
    # builds its opening screen in the click. TIDAL first, so the plan that
    # lands while it is selected has no albums at all.
    q("searchResultsView.setFilter('all')")
    q("root.searchSourceFilter = 'tidal'")
    wait("root.effectiveSourceFilter === 'tidal'", "the tidal filter never applied")
    tidal = qml_search_payload(provider="tidal", tracks=[_track(i) for i in range(10)])
    apple = qml_search_payload(provider="apple", albums=[_album(i) for i in range(10)])
    q("root._searchSeq = root._navSeq")
    bridge.searchResults.emit(
        {
            "sources": [*tidal["sources"], *apple["sources"]],
            "sections": {
                **tidal["sections"],
                **{name: [*tidal["sections"].get(name, []), *rows] for name, rows in apple["sections"].items()},
            },
            "top": None,
        }
    )
    wait(
        "searchResultsView.countFor('albums') == 10 && searchResultsView.countFor('tracks') == 10",
        "the two-source payload never filled",
    )
    check(
        q("searchResultsView.sectionVisible('albums')") is False,
        "the tidal filter still shows the apple albums section",
    )
    q("root.searchSourceFilter = 'apple'")
    check(
        q("root.effectiveSourceFilter") == "apple" and q("searchResultsView.sectionVisible('albums')") is True,
        "the apple filter never applied",
    )
    check(
        q("searchResultsView.albumRepeater.itemAt(0).item !== null") is True,
        "a source chip left the newly visible section's opening screen unbuilt",
    )
    q("root.searchSourceFilter = 'all'")

    # A fresh search re-seeds the kept flags from the expansion state: a
    # section is not still kept because an earlier search's SHOW ALL built
    # it, so its rows past the cap go back to unbuilt.
    q("root._searchSeq = root._navSeq")
    bridge.searchResults.emit(
        qml_search_payload(albums=[_album(i) for i in range(30)], tracks=[_track(i) for i in range(30)])
    )
    q("results.contentHeight")
    wait("searchResultsView.countFor('albums') == 30", "the second payload never filled")
    check(
        q("searchResultsView.albumRepeater.itemAt(6).active") is False,
        "a kept flag from the previous search survived into the fresh page",
    )

    if failures:
        for f in failures:
            print("REGRESSED:", f, file=sys.stderr)
        return 1
    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_scenario())
