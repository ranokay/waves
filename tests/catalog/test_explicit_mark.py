"""A track's own explicit flag wears the E mark, and only that flag does.

WHAT THIS FENCES OFF
--------------------
A song TIDAL carries both explicit and clean as two rows with the same title,
artist, album, date, duration and quality, and nothing told them apart but a
sticker the cover may or may not carry. Every list that shows a track now
wears the same "E" the video cells already did - the search, browse and saved
rows (TrackRow), an album's inline expand (AlbumBlock) and a playlist's
(PlaylistBlock) - read off the row payload's own flag, never a suffix matched
out of a title, so an explicit release and its clean twin never read the same.

The mark also has to lay out like a data mark, not a decoration: it rides
after the rendered title, inside the title's own box (its room is reserved in
the title's rightPadding, so an elided title leaves it visible), and it stays
clear of the NEW tag that shares that tail.

Runs in a SUBPROCESS like the other Main.qml scenarios: building the bridge
installs process-global handlers that must not leak into the suite.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from support.paths import QML_MAIN
from support.qml import (
    EXIT_OK,
    EXIT_PRECONDITION,
    EXIT_REGRESSED,
    boot_main_qml,
    run_scenario,
    wait_until,
)

# ----- structure ------------------------------------------------------------------

_QML = {path.name: path.read_text(encoding="utf-8") for path in sorted(QML_MAIN.parent.rglob("*.qml"))}

# Every track list, and the row-owned flag its mark reads.
_WEARERS = {
    "VideoCell.qml": "vcell.vcExplicit",
    "TrackRow.qml": "trow.explicit",
    "AlbumBlock.qml": "modelData.explicit === true",
    "PlaylistBlock.qml": "modelData.explicit === true",
}


def test_the_mark_uses_the_lighter_ink() -> None:
    mark = _QML["ExplicitMark.qml"]
    assert 'objectName: "explicitMark"' in mark, "the mark keeps no objectName for the rendered check"
    assert "#a8acb4" in mark, "the mark's ink is a copy of Main.qml's textLo (a step above the dim grey)"
    assert "Palette.textDim" not in mark, "at the dim grey the mark sinks into the row background"


def test_every_track_list_wears_exactly_one_mark() -> None:
    counted = {name: len(re.findall(r"(?<![\w.])ExplicitMark\s*\{", source)) for name, source in _QML.items()}
    got = {name: count for name, count in counted.items() if count}
    assert got == dict.fromkeys(_WEARERS, 1), (
        f"the explicit mark is placed on {got}, expected exactly one on each of {sorted(_WEARERS)}"
    )


def test_each_mark_reads_its_rows_own_flag() -> None:
    for name, flag in _WEARERS.items():
        block = re.search(r"(?<![\w.])ExplicitMark\s*\{([^}]*)\}", _QML[name], re.DOTALL)
        assert block, f"{name} places no ExplicitMark instance"
        assert f"visible: {flag}" in block.group(1), (
            f"{name}'s mark does not read its row's flag ({flag}); a title-matching rule would fold twins apart"
        )


def test_every_track_title_carries_the_test_handle() -> None:
    for name in ("TrackRow.qml", "AlbumBlock.qml", "PlaylistBlock.qml"):
        found = _QML[name].count('objectName: "trackTitle"')
        assert found == 1, f"{name} has {found} trackTitle handles, expected exactly 1"


# ----- the live UI ----------------------------------------------------------------


# The heaviest QML boot: excluded from the quick QML pass.
@pytest.mark.qml
@pytest.mark.slow
def test_the_mark_follows_the_flag_on_every_track_list() -> None:
    run_scenario(
        Path(__file__),
        "--run-scenario",
        timeout=240,
        sandbox_prefix="waves-explicit-mark-",
        failure_message="the explicit mark is wrong on screen",
    )


# Every visible track title, with its box, rendered text width and the scene
# x of its explicit mark and NEW tag (null when absent). Walking by
# objectName reaches the search rows and both inline expands through the one
# shape. JSON, because a QML object comes back from QQmlExpression as an
# opaque QJSValue.
_TITLES = """
JSON.stringify((function() {
    var out = []
    function find(it, name) {
        if (!it) return null
        if (it.objectName === name && it.visible && it.width > 0) return it
        var kids = it.children || []
        for (var i = 0; i < kids.length; i++) { var f = find(kids[i], name); if (f) return f }
        return null
    }
    function walk(it) {
        if (!it) return
        if (it.objectName === "trackTitle" && it.visible && it.width > 0) {
            var e = find(it, "explicitMark")
            var n = find(it, "newTag")
            out.push({
                title: "" + it.text,
                tx: it.mapToItem(null, 0, 0).x, tw: it.width, tcw: it.contentWidth, elided: it.truncated,
                ex: e ? e.mapToItem(null, 0, 0).x : null, ew: e ? e.width : 0,
                nx: n ? n.mapToItem(null, 0, 0).x : null
            })
        }
        var kids = it.children || []
        for (var i = 0; i < kids.length; i++) walk(kids[i])
    }
    walk(root.contentItem)
    return out
})())
"""


def _track(tid: str, title: str, explicit: bool, when: str = "2019-05-03") -> dict:
    return {
        "id": tid,
        "kind": "track",
        "title": title,
        "artist": "Some Artist",
        "artist_id": "ar0",
        "album": "Some Album",
        "album_id": "al" + tid,
        "num": 1,
        "vol": 1,
        "art": "",
        "year": when[:4],
        "date": when,
        "duration": "3:20",
        "duration_sec": 200,
        "quality": "LOSSLESS",
        "popularity": 50,
        "explicit": explicit,
        "added": "",
    }


def _run_scenario() -> int:
    booted = boot_main_qml()
    if isinstance(booted, int):
        return booted
    _root, q, settle, bridge = booted
    # The expands must render from the seeded caches, never the network.
    type(bridge).loadAlbumTracks = lambda self, album_id: None  # type: ignore[method-assign]
    type(bridge).loadPlaylistTracks = lambda self, playlist_id: None  # type: ignore[method-assign]

    failures: list[str] = []

    def check(cond, what: str) -> None:
        if not cond:
            failures.append(what)

    def titles() -> dict[str, dict]:
        return {row["title"]: row for row in json.loads(q(_TITLES))}

    def geometry(row: dict) -> str | None:
        """Why the mark is misplaced on this row, or None when it lays out."""
        if row["ex"] is None:
            return "wears no mark"
        text_end = row["tx"] + row["tcw"]
        if row["ex"] < text_end + 2:
            return f"the mark overlaps the title text ({row['ex']} < {text_end})"
        if row["ex"] + row["ew"] > row["tx"] + row["tw"] + 0.5:
            return f"the mark spills past the title's box ({row['ex']} + {row['ew']} > {row['tx']} + {row['tw']})"
        return None

    fresh = (date.today() - timedelta(days=2)).isoformat()
    long_title = "A Very Long Song Title That Keeps Going " * 6

    q("openSearch()")
    settle(150)
    q("_searchSeq = _navSeq")
    from search.fakes import qml_search_payload

    bridge.searchResults.emit(
        qml_search_payload(
            albums=[
                {
                    "id": "alxp",
                    "title": "Expand Album",
                    "artist": "Some Artist",
                    "artist_id": "ar0",
                    "art": "",
                    "year": "2019",
                    "date": "2019-05-03",
                    "tracks": 2,
                    "duration_sec": 400,
                    "quality": "LOSSLESS",
                    "popularity": 50,
                    "explicit": False,
                    "added": "",
                }
            ],
            playlists=[
                {
                    "id": "plxp",
                    "title": "Expand Playlist",
                    "creator": "Some Artist",
                    "art": "",
                    "tracks": 2,
                }
            ],
            tracks=[
                _track("t1", "Something I Need", True),
                _track("t2", "Something I Need ", False),
                _track("t3", long_title, True, when=fresh),
                _track("t4", "Fresh Explicit", True, when=fresh),
            ],
        )
    )
    wait_until(
        lambda: not q("searchBuilding"),
        timeout_ms=10000,
        message="search results finished building",
    )
    settle(500)

    # The inline expands render from the caches the fetch would have filled.
    q(
        "root.trackCache = ({'alxp': "
        + json.dumps([_track("at1", "Album Explicit", True), _track("at2", "Album Clean", False)])
        + "})"
    )
    q(
        "root.playlistTrackCache = ({'plxp': "
        + json.dumps([_track("pt1", "List Explicit", True), _track("pt2", "List Clean", False)])
        + "})"
    )
    q("root.expandedAlbums = ({'alxp': true})")
    q("root.expandedPlaylists = ({'plxp': true})")
    needed = {
        "Something I Need",
        "Something I Need ",
        long_title,
        "Fresh Explicit",
        "Album Explicit",
        "Album Clean",
        "List Explicit",
        "List Clean",
    }
    try:
        wait_until(
            lambda: needed <= set(titles()),
            timeout_ms=10000,
            message="every search row and both expands rendered",
        )
    except AssertionError:
        print(f"did not render every seeded row; missing {sorted(needed - set(titles()))}", file=sys.stderr)
        return EXIT_PRECONDITION
    settle(800)
    rows = titles()

    # The twin pair: the flag decides, not the title.
    if rows["Something I Need"]["ex"] is None:
        failures.append("the explicit twin wears no mark")
    if rows["Something I Need "]["ex"] is not None:
        failures.append("the clean twin wears the explicit mark")

    # The mark rides after the rendered title, inside the title's box, and
    # the NEW tag sharing that tail never overlaps it.
    for title in ("Something I Need", "Fresh Explicit", long_title):
        row = rows[title]
        why = geometry(row)
        if why:
            failures.append(f"{title[:24]!r}: {why}")
            continue
        if row["nx"] is not None and row["nx"] < row["ex"] + row["ew"] + 4:
            failures.append(f"{title[:24]!r}: the NEW tag overlaps the mark ({row['nx']} vs {row['ex']} + {row['ew']})")

    # These are what the rows must do on screen, so they fail rather than skip.
    if not rows[long_title]["elided"]:
        failures.append("the long title did not elide, so its mark's room is not under test")
    if rows[long_title]["nx"] is None or rows["Fresh Explicit"]["nx"] is None:
        failures.append("a fresh row wears no NEW tag")

    # The album and playlist expands wear the same mark, same geometry.
    for title in ("Album Explicit", "List Explicit"):
        why = geometry(rows[title])
        if why:
            failures.append(f"{title!r}: the expand's explicit row {why}")
    failures.extend(
        f"{title!r}: the expand's clean row wears the mark"
        for title in ("Album Clean", "List Clean")
        if rows[title]["ex"] is not None
    )

    if failures:
        print("\n".join(failures), file=sys.stderr)
        return EXIT_REGRESSED
    print("explicit mark follows the flag on every track list: OK")
    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_run_scenario())
