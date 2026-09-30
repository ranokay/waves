"""A long artist track list only mounts the five rows in its folded preview."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from support.qml import EXIT_OK, boot_main_qml, run_scenario


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
    settle(250)
    folded = (
        q("artistTracksModel.count") == 242
        and q("artistTopTracksRep.count") == 5
        and q("artistTracksPreviewModel.get(4).id") == "track-4"
    )
    q("root.toggleArtistExpand('tracks')")
    settle(250)
    expanded = q("artistTopTracksRep.count") == 242
    q("root.toggleArtistExpand('tracks')")
    settle(250)
    folded_again = q("artistTopTracksRep.count") == 5
    if not (folded and expanded and folded_again):
        print(f"folded={folded}, expanded={expanded}, folded_again={folded_again}", file=sys.stderr)
        return 1
    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_scenario())
