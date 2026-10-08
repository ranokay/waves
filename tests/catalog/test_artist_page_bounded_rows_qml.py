"""An artist page builds only the rows it shows, top-first.

Runs in a subprocess like the other Main.qml scenarios: building the bridge
installs process-global handlers that must not leak into the suite.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from support.qml import EXIT_OK, boot_main_qml, run_scenario


@pytest.mark.qml
def test_artist_sections_build_only_the_rows_they_show():
    run_scenario(Path(__file__), "--run-scenario", sandbox_prefix="waves-artist-bounded-test-")


def _album(i: int) -> dict:
    return {
        "id": f"al{i}",
        "title": f"Album {i}",
        "artist": "Long Artist",
        "art": "",
        "year": "2026",
        "date": "2026-01-01",
        "listed": "2026-01-01",
        "tracks": 10,
        "duration_sec": 2400,
        "quality": "LOSSLESS",
        "popularity": 1,
    }


def _track(i: int) -> dict:
    return {
        "id": f"tr{i}",
        "title": f"Track {i}",
        "artist": "Long Artist",
        "album": "Album 0",
        "album_id": "al0",
        "art": "",
        "year": "2026",
        "date": "2026-01-01",
        "duration": "3:00",
        "duration_sec": 180,
        "quality": "LOSSLESS",
        "popularity": 1,
    }


def _video(i: int) -> dict:
    return {
        "id": f"vi{i}",
        "title": f"Video {i}",
        "artist": "Long Artist",
        "art": "",
        "duration": "3:00",
        "quality": "VIDEO",
        "date": "2026-01-01",
    }


def _scenario() -> int:
    booted = boot_main_qml()
    if not isinstance(booted, tuple):
        return booted
    _root, q, settle, bridge = booted

    bridge.artistLoaded.emit(
        {
            "id": "artist-1",
            "name": "Long Artist",
            "art": "",
            "bio": "",
            "tracks": [_track(i) for i in range(120)],
            "albums": [_album(i) for i in range(120)],
            "eps": [_album(i) for i in range(60)],
            "videos": [_video(i) for i in range(30)],
        }
    )
    settle(400)
    # Realise the page: without a layout the rows are never built.
    q("artistView.contentHeight")
    settle(1200)

    failures: list[str] = []

    def check(cond, what: str) -> None:
        if not cond:
            failures.append(what)

    # The folded page shows five of each list, and rows past the cap stay
    # unbuilt until SHOW ALL.
    check(q("artistAlbumsModel.count") == 120, f"the albums model lost rows: {q('artistAlbumsModel.count')}")
    check(
        q("artistAlbumsRep.itemAt(5).visible") is False,
        "a row past the albums cap is visible while folded",
    )
    check(
        q("artistAlbumsRep.itemAt(6).active") is False,
        "an albums row past the cap is active before SHOW ALL",
    )
    check(
        q("artistAlbumsRep.itemAt(6).item === null") is True,
        "an albums row past the cap was built before SHOW ALL",
    )
    # The videos' folded preview is whole grid rows; cells past it stay
    # unbuilt too.
    check(
        q("artistVideosRep.itemAt(29).active") is False,
        "a videos cell past the preview stayed active while folded",
    )

    # SHOW ALL builds the screen under the rows already shown in the click;
    # the rest incubate and arrive in batches from the top down.
    q("root.toggleArtistExpand('albums')")
    check(
        q("artistAlbumsRep.itemAt(5).item !== null") is True,
        "SHOW ALL left the screen under the albums cap unbuilt in the click",
    )
    check(
        q("artistAlbumsRep.itemAt(119).item === null") is True,
        "SHOW ALL built the far albums rows inline instead of incubating them",
    )
    settle(3000)
    check(
        q("artistAlbumsRep.itemAt(119).item !== null") is True,
        "the incubated albums rows never arrived",
    )
    # SHOW LESS keeps the built rows: hidden, not destroyed.
    before = q("String(artistAlbumsRep.itemAt(119))")
    q("root.toggleArtistExpand('albums')")
    settle(100)
    check(
        q("artistAlbumsRep.itemAt(119).item !== null") is True,
        "SHOW LESS destroyed the built albums rows",
    )
    check(
        q("artistAlbumsRep.itemAt(119).visible") is False,
        "a kept albums row stayed visible after SHOW LESS",
    )
    check(
        q("String(artistAlbumsRep.itemAt(119))") == before,
        "SHOW LESS rebuilt the kept albums rows instead of hiding them",
    )

    # Collapsing a section tears its rows down (the header remains); the
    # unfold builds a screenful in the click and lets the rest arrive.
    q("root.toggleArtistSection('albums')")
    settle(50)
    check(q("artistAlbumsRep.count") == 0, "collapsing the albums section left its rows built")
    q("root.toggleArtistSection('albums')")
    check(
        q("artistAlbumsRep.itemAt(5).item !== null") is True,
        "unfolding left the albums screen unbuilt in the click",
    )
    settle(3000)
    check(
        q("artistAlbumsRep.itemAt(119).item !== null") is True,
        "the unfolded albums rows never filled in",
    )

    # A background revalidate swaps the payload in place: the rows the user
    # is reading (and any built beyond them) keep their delegates, matched
    # by id; a changed field lands on the same row.
    q("root.toggleArtistExpand('albums')")
    settle(3000)
    expanded_before = q("String(artistAlbumsRep.itemAt(6))")
    albums = [_album(i) for i in range(120)]
    albums[6]["title"] = "Album 6 (Remastered)"
    albums.append(_album(120))
    bridge.artistLoaded.emit(
        {
            "id": "artist-1",
            "name": "Long Artist",
            "art": "",
            "bio": "",
            "refresh": True,
            "tracks": [_track(i) for i in range(120)],
            "albums": albums,
            "eps": [_album(i) for i in range(60)],
            "videos": [_video(i) for i in range(30)],
        }
    )
    settle(500)
    check(q("artistAlbumsModel.count") == 121, f"the revalidate lost rows: {q('artistAlbumsModel.count')}")
    check(
        q("artistAlbumsModel.get(6).title") == "Album 6 (Remastered)", "the revalidate did not write the changed field"
    )
    check(
        q("String(artistAlbumsRep.itemAt(6))") == expanded_before,
        "the revalidate rebuilt the row delegates instead of reconciling them",
    )
    check(q("root.artistAlbumsExpanded") is True, "the revalidate collapsed the expanded section")

    if failures:
        for f in failures:
            print("REGRESSED:", f, file=sys.stderr)
        return 1
    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_scenario())
