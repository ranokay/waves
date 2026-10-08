"""A long artist track list builds only the five rows in its folded preview.

The folded section shows five of the model's rows; the rest are empty, inactive
Loaders until SHOW ALL, which builds the screen under them in the click and
lets the rest arrive in batches from the top down. SHOW LESS keeps the built
rows, hidden.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from support.qml import EXIT_OK, boot_main_qml, run_scenario, wait_until


@pytest.mark.qml
def test_artist_top_tracks_preview_limits_rendered_rows():
    run_scenario(Path(__file__), "--run-scenario", sandbox_prefix="waves-artist-preview-test-")


def _scenario() -> int:
    booted = boot_main_qml()
    if not isinstance(booted, tuple):
        return booted
    _root, q, settle, bridge = booted
    tracks = [
        {
            "id": f"track-{i}",
            "title": f"Track {i}",
            "artist": "Long Artist",
            "album": "Album",
            "album_id": "album-1",
            "art": "",
            "year": "2026",
            "date": "2026-09-30",
            "duration": "3:00",
            "duration_sec": 180,
            "quality": "LOSSLESS",
            "popularity": 1,
        }
        for i in range(242)
    ]
    bridge.artistLoaded.emit(
        {
            "id": "artist-1",
            "name": "Long Artist",
            "art": "",
            "bio": "",
            "tracks": tracks,
            "albums": [],
            "eps": [],
            "videos": [],
        }
    )
    settle(250)  # the pane's first layout pass, before the page is read
    q("artistView.contentHeight")
    settle(300)  # a second pass, so the folded five have landed

    failures: list[str] = []

    def check(cond, what: str) -> None:
        if not cond:
            failures.append(what)

    # Folded: the model holds every track, the five shown rows are built,
    # and the rows past the cap are empty, inactive Loaders.
    check(q("artistTracksModel.count") == 242, "the tracks model lost rows")
    check(q("artistTopTracksRep.count") == 242, "the folded section no longer carries every row's delegate")
    check(q("artistTopTracksRep.itemAt(4).item !== null") is True, "a folded track row was not built")
    check(q("artistTopTracksRep.itemAt(5).item === null") is True, "a track row past the cap was built while folded")
    check(q("artistTopTracksRep.itemAt(5).active") is False, "a track row past the cap is active while folded")
    check(q("artistTopTracksRep.itemAt(4).visible") is True, "a folded track row is hidden")

    # SHOW ALL builds the screen under the five in the click; the far rows
    # incubate and arrive afterwards (the page fills from the top down).
    q("root.toggleArtistExpand('tracks')")
    check(q("artistTopTracksRep.itemAt(5).item !== null") is True, "SHOW ALL left the screen under the cap unbuilt")
    check(q("artistTopTracksRep.itemAt(241).item === null") is True, "SHOW ALL built the far rows inline")
    try:
        wait_until(
            lambda: bool(q("artistTopTracksRep.itemAt(241).item !== null")),
            timeout_ms=15000,
            message="the incubated rows never arrived",
        )
    except AssertionError:
        check(False, "the incubated rows never arrived")

    # SHOW LESS hides the built rows without destroying them.
    before = q("String(artistTopTracksRep.itemAt(241))")
    q("root.toggleArtistExpand('tracks')")
    settle(100)  # one layout pass for the visibility bindings
    check(q("artistTopTracksRep.itemAt(241).item !== null") is True, "SHOW LESS destroyed the built rows")
    check(q("artistTopTracksRep.itemAt(241).visible") is False, "a kept row stayed visible after SHOW LESS")
    check(
        q("String(artistTopTracksRep.itemAt(241))") == before, "SHOW LESS rebuilt the kept rows instead of hiding them"
    )

    if failures:
        for f in failures:
            print("REGRESSED:", f, file=sys.stderr)
        return 1
    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_scenario())
