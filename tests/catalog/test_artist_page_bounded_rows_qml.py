"""An artist page builds only the rows it shows, top-first.

Runs in a subprocess like the other Main.qml scenarios: building the bridge
installs process-global handlers that must not leak into the suite.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from support.qml import EXIT_OK, boot_main_qml, run_scenario, wait_until_true

_FIRST_BUILT_ALBUM = (
    "(function () { for (var i = 0; i < artistAlbumsModel.count; ++i) "
    "if (artistAlbumsRep.itemAt(i).item !== null) return i; return -1; })()"
)
# The albums row a content y falls on, from the section header's own
# geometry and the shared row pitch (the delegates have no y until a layout
# pass, and this must be read in the fill's own turn).
_ALBUM_AT_Y = (
    "Math.floor((%d - (artistAlbumsHead.y + artistAlbumsHead.height + artistCol.spacing)) / root._artistAlbumPitch)"
)


@pytest.mark.qml
def test_artist_sections_build_only_the_rows_they_show():
    run_scenario(
        Path(__file__),
        "--run-scenario",
        sandbox_prefix="waves-artist-bounded-test-",
        drop=("waves.qt",),
    )


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


def _payload(*, refresh: bool = False) -> dict:
    return {
        "id": "artist-1",
        "name": "Long Artist",
        "art": "",
        "bio": "",
        "refresh": refresh,
        "tracks": [_track(i) for i in range(120)],
        "albums": [_album(i) for i in range(120)],
        "eps": [_album(i) for i in range(60)],
        "videos": [_video(i) for i in range(30)],
    }


def _scenario() -> int:
    booted = boot_main_qml()
    if not isinstance(booted, tuple):
        return booted
    _root, q, settle, bridge = booted

    failures: list[str] = []

    def check(cond, what: str) -> None:
        if not cond:
            failures.append(what)

    def wait(expr: str, what: str, timeout_ms: int = 15000) -> None:
        check(wait_until_true(q, expr, what, timeout_ms=timeout_ms), what)

    bridge.artistLoaded.emit(_payload())

    # The fill builds the opening screen's rows in the payload's own turn,
    # before any incubation lands.
    check(q(_FIRST_BUILT_ALBUM) >= 0, "the opening screen built no album row in the payload's own turn")
    # Realise the page: without a layout the rest of the rows are never
    # built.
    q("artistView.contentHeight")
    wait("artistAlbumsModel.count == 120", "the artist page never filled")

    # The folded page shows five of each list; rows past the cap stay
    # unbuilt until SHOW ALL. The videos' folded preview is whole grid rows.
    check(q("artistAlbumsRep.itemAt(5).visible") is False, "a row past the albums cap is visible while folded")
    check(q("artistAlbumsRep.itemAt(6).active") is False, "an albums row past the cap is active before SHOW ALL")
    check(q("artistAlbumsRep.itemAt(6).item === null") is True, "an albums row past the cap was built before SHOW ALL")
    check(q("artistVideosRep.itemAt(29).active") is False, "a videos cell past the preview stayed active while folded")

    # Repeated landings elsewhere must not grow a folded section's reach: a
    # later SHOW ALL would otherwise activate the whole model at once and
    # the top-first batches would be gone. Another section's unfold rebuilds
    # its rows, and each landing re-checks every frontier.
    for _ in range(12):
        q("root.toggleArtistSection('eps')")
        q("root.toggleArtistSection('eps')")
        check(
            wait_until_true(
                q, "artistEpsRep.itemAt(4).item !== null", "an eps unfold never rebuilt its rows", timeout_ms=5000
            ),
            "an eps unfold never rebuilt its rows",
        )
    q("root.toggleArtistExpand('albums')")
    active = q(
        "(function () { var n = 0; for (var i = 0; i < 120; ++i) if (artistAlbumsRep.itemAt(i).active) n++; return n; })()"
    )
    check(active <= 40, f"a folded section's reach pre-grew ({active} rows active on SHOW ALL)")
    q("root.toggleArtistExpand('albums')")
    settle(50)  # one layout pass for the visibility bindings

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
    # Top-first: once a middle row has landed, the last row is still not
    # there (the batches grow in order, so nothing near the end can exist
    # before the middle does).
    wait("artistAlbumsRep.itemAt(20).item !== null", "the albums fill never reached a middle row")
    check(q("artistAlbumsRep.itemAt(119).item === null") is True, "the albums rows did not fill from the top down")
    wait("artistAlbumsRep.itemAt(119).item !== null", "the incubated albums rows never arrived", timeout_ms=30000)

    # SHOW LESS keeps the built rows: hidden, not destroyed.
    before = q("String(artistAlbumsRep.itemAt(119))")
    q("root.toggleArtistExpand('albums')")
    settle(50)  # one layout pass for the visibility bindings
    check(q("artistAlbumsRep.itemAt(119).item !== null") is True, "SHOW LESS destroyed the built albums rows")
    check(q("artistAlbumsRep.itemAt(119).visible") is False, "a kept albums row stayed visible after SHOW LESS")
    check(
        q("String(artistAlbumsRep.itemAt(119))") == before,
        "SHOW LESS rebuilt the kept albums rows instead of hiding them",
    )

    # Collapsing a section tears its rows down (the header remains); the
    # unfold builds a screenful in the click and lets the rest arrive.
    q("root.toggleArtistSection('albums')")
    settle(50)  # the model reassignment's delegate teardown pass
    check(q("artistAlbumsRep.count") == 0, "collapsing the albums section left its rows built")
    q("root.toggleArtistSection('albums')")
    check(q("artistAlbumsRep.itemAt(5).item !== null") is True, "unfolding left the albums screen unbuilt in the click")
    # The unfold shows the folded five; the rest is one SHOW ALL away, and
    # then fills in the same batches.
    q("root.toggleArtistExpand('albums')")
    wait("artistAlbumsRep.itemAt(119).item !== null", "the unfolded albums rows never filled in")

    # A background revalidate swaps the payload in place: the rows the user
    # is reading (and any built beyond them) keep their delegates, matched
    # by id; a changed field lands on the same row.
    q("if (!root.artistAlbumsExpanded) root.toggleArtistExpand('albums')")
    wait("artistAlbumsRep.itemAt(6).item !== null", "the re-shown albums rows never arrived")
    expanded_before = q("String(artistAlbumsRep.itemAt(6))")
    albums = [_album(i) for i in range(120)]
    albums[6]["title"] = "Album 6 (Remastered)"
    albums.append(_album(120))
    refreshed = _payload(refresh=True)
    refreshed["albums"] = albums
    bridge.artistLoaded.emit(refreshed)
    wait("artistAlbumsModel.count == 121", "the revalidate never landed")
    check(
        q("artistAlbumsModel.get(6).title") == "Album 6 (Remastered)", "the revalidate did not write the changed field"
    )
    check(
        q("String(artistAlbumsRep.itemAt(6))") == expanded_before,
        "the revalidate rebuilt the row delegates instead of reconciling them",
    )
    check(q("root.artistAlbumsExpanded") is True, "the revalidate collapsed the expanded section")

    # A Back into a long artist arms its saved spot: the fresh fill plans
    # the window around THAT screen, so the row at the landing spot is built
    # for the frame it appears in while rows above and below it stay
    # unbuilt. The state armed here is the one navBack leaves behind before
    # it reloads the artist (see _artistRestoreState).
    q("root.artistAlbumsExpanded = true")
    q("root._artistRestoreState = ({ id: 'artist-1', ex: {}, bio: false })")
    q("artistView.pendingRestoreKey = 'artist-1'")
    q("artistView.pendingRestoreY = 3000")
    bridge.artistLoaded.emit(_payload())
    # The plan's own turn: the window open around the landing spot, its rows
    # built, nothing above or below it yet.
    from_without_bio = q("root._artistSyncFromAlbums")
    spot = q(_ALBUM_AT_Y % 3000)
    first_built = q(_FIRST_BUILT_ALBUM)
    check(spot >= 0, "the restore spot falls above the albums section")
    check(first_built > 0, f"a Back restore built the rows above the landing spot (first built {first_built})")
    check(
        spot >= 0 and q(f"artistAlbumsRep.itemAt({spot}).item !== null") is True,
        "a Back restore left the row at the landing spot unbuilt",
    )
    check(
        q("artistAlbumsRep.itemAt(119).item === null") is True,
        "a Back restore built the rows below the landing spot inline",
    )
    q("artistView.contentHeight")
    wait("artistAlbumsRep.itemAt(119).item !== null", "the restored page's rows never filled in")

    # An expanded bio stands above the sections: the same restore spot
    # lands lower in the albums list (the plan walks the bio's real height,
    # not the bare header), and the row there is still the built one.
    with_bio = _payload()
    with_bio["bio"] = "Long biography line. " * 200
    bridge.artistLoaded.emit(with_bio)
    q("root.bioExpanded = true")
    settle(300)  # the expanded bio's layout pass, so its height is real
    q("root._artistRestoreState = ({ id: 'artist-1', ex: {}, bio: true })")
    q("artistView.pendingRestoreKey = 'artist-1'")
    q("artistView.pendingRestoreY = 3000")
    bridge.artistLoaded.emit(with_bio)
    # The bio pushes the sections down, so the same scroll offset lands on
    # an EARLIER albums row: the window start moves up, not down.
    check(
        q("root._artistSyncFromAlbums") < from_without_bio,
        "the plan ignored the expanded bio above the restore spot",
    )
    spot = q(_ALBUM_AT_Y % 3000)
    check(
        spot >= 0 and q(f"artistAlbumsRep.itemAt({spot}).item !== null") is True,
        "an expanded bio left the row at the landing spot unbuilt",
    )
    q("artistView.contentHeight")
    wait("artistAlbumsRep.itemAt(119).item !== null", "the expanded-bio page's rows never filled in")

    # A saved spot past the page's own end clamps to the bottom screen
    # instead of planning every window past its section.
    q("root.artistAlbumsExpanded = true")
    q("root._artistRestoreState = ({ id: 'artist-1', ex: {}, bio: false })")
    q("artistView.pendingRestoreKey = 'artist-1'")
    q("artistView.pendingRestoreY = 1000000")
    bridge.artistLoaded.emit(_payload())
    check(
        q("artistAlbumsRep.itemAt(0).item === null") is True,
        "a restore past the page's end built the rows at the top",
    )
    check(
        q("artistVideosRep.itemAt(0).item !== null") is True,
        "a restore past the page's end did not land on the bottom screen",
    )

    if failures:
        for f in failures:
            print("REGRESSED:", f, file=sys.stderr)
        return 1
    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_scenario())
