"""Every My Music shelf shows DOWNLOAD ALL and confirms the count.

WHAT THIS FENCES OFF
--------------------
Each shelf tab's header carries a DOWNLOAD ALL button (``favTracksBtn``
and its five twins). On the real Main.qml, with a signed-in TIDAL source:

1. The button is on screen on its own tab and on no other tab.
2. A tap arms the shelf's pending flag and asks the backend for the count;
   when the count lands, the shared bulk confirm (``catDlGate``) opens
   titled for the shelf's kind.
3. Dismissing the confirm closes it and leaves nothing armed.
4. A count that arrives with nothing armed (a stale answer) opens nothing.
5. A failed count (-1) while armed disarms and opens nothing.
6. Albums, Artists, Playlists, Mixes and Videos behave the same, each
   titled for its kind.

The count is answered by the real ``resolveFavoriteX`` slots against a
count stubbed on the TIDAL provider, so the tap-to-confirm path is the
production one. Runs in a SUBPROCESS like the other Main.qml scenarios:
building the bridge installs process-global handlers that must not leak
into the suite.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from support.qml import (
    EXIT_OK,
    EXIT_REGRESSED,
    boot_main_qml,
    checkpoint,
    make_tidal_my_music_source,
    run_scenario,
)

_TWINS = (
    ("albums", "favAlbumsBtn", "favAlbums", 4),
    ("artists", "favArtistsBtn", "favArtists", 4),
    ("playlists", "favPlaylistsBtn", "favPlaylists", 2),
    ("mixes", "favMixesBtn", "favMixes", 1),
    ("videos", "favVideosBtn", "favVideos", 4),
)


def _run_scenario() -> int:  # noqa: C901 (one straight scenario)
    booted = boot_main_qml()
    if isinstance(booted, int):
        return booted
    root, q, settle, bridge = booted
    make_tidal_my_music_source(root, q, settle, bridge)
    q("root.libraryOpen = true")
    settle(200)

    provider = bridge.providers.get("tidal")
    if provider is None:
        print("REGRESSED: no TIDAL provider behind the shelf", flush=True)
        return EXIT_REGRESSED
    counts = {"n": 0, "fail": False}

    def fake_count(kind):
        counts["n"] += 1
        if counts["fail"]:
            raise RuntimeError("503")
        return 5

    provider.favorites_count = fake_count
    # Playlists and mixes count the collections sweep, not the favorites
    # count: serve it canned (offline), with an empty folder tree.
    from types import SimpleNamespace as _NS

    provider.user_collections = lambda: {
        "playlists": [_NS(id="p1", num_tracks=9), _NS(id="p2", num_tracks=3)],
        "mixes": [_NS(id="m1")],
    }
    provider.folder_tree = lambda root_folders=None: _NS(nodes=[], partial=False)
    g = 'root.libGroupFor("tidal")'
    if q(g + " === null"):
        print("REGRESSED: the TIDAL source rendered no group", flush=True)
        return EXIT_REGRESSED

    # Delegate items have no QObject parent, so findChildren never sees
    # them; childItems does (the shelf tests' own pattern). Match the
    # button's objectName, then require the whole parent chain visible
    # within the TIDAL group.
    def shown(btn: str) -> bool:
        stack = [root.contentItem()]
        while stack:
            it = stack.pop()
            stack.extend(it.childItems())
            if it.objectName() != btn:
                continue
            o = it
            visible, in_tidal = True, False
            while o is not None:
                if o.property("visible") is False:
                    visible = False
                    break
                if o.property("sourceId") == "tidal":
                    in_tidal = True
                o = o.parentItem()
            if visible and in_tidal:
                return True
        return False

    failures: list[str] = []

    def check(name: str, cond: bool) -> None:
        checkpoint(name, "ok" if cond else "REGRESSED")
        if not cond:
            failures.append(name)

    def gate_shown() -> bool:
        from PySide6.QtCore import QObject

        gate = root.findChild(QObject, "catDlGate")
        return bool(gate is not None and gate.property("visible"))

    # 1. The Tracks button is on its own tab only.
    q(g + '.category = "tracks"')
    settle(120)
    check("tracks-button-shown", shown("favTracksBtn"))
    q(g + '.category = "albums"')
    settle(120)
    check("tracks-button-hidden-off-tab", not shown("favTracksBtn"))

    # 2. The real tap arms the flag and asks for the count; the count
    #    opens the confirm titled for tracks.
    q(g + '.category = "tracks"')
    settle(120)
    before = counts["n"]
    q(g + '.favTap("tracks")')
    settle(150)
    check("tap-arms-and-asks", counts["n"] == before + 1)
    settle(400)
    check(
        "count-opens-confirm",
        gate_shown() and q("root.catDlPrompt.kind") == "favTracks" and q("root.catDlPrompt.count") == 5,
    )
    check("confirm-disarms", not bool(q(g + ".favTracksPending")))

    # 3. Dismiss closes it.
    q("root.catDlDismiss()")
    settle(120)
    check("dismiss-closes", not gate_shown() and q("root.catDlPrompt") is None)

    # 4. A count with nothing armed opens nothing.
    bridge.favoriteTracksResolved.emit("tidal", 9)
    settle(150)
    check("stale-count-inert", not gate_shown())

    # 5. A failed count while armed disarms and opens nothing.
    counts["fail"] = True
    q(g + '.favTap("tracks")')
    settle(400)
    check("failed-count-inert", not gate_shown() and not bool(q(g + ".favTracksPending")))
    counts["fail"] = False

    # 6. Every other shelf carries its own DOWNLOAD ALL, only on its own
    #    tab, and each count opens the confirm titled for its kind.
    provider.favorites_count = lambda kind: 4
    for cat, btn, kind, want in _TWINS:
        q(f'{g}.category = "{cat}"')
        settle(120)
        is_shown = shown(btn)
        others_hidden = not shown("favTracksBtn") if cat != "tracks" else True
        q(f'{g}.favTap("{cat}")')
        settle(400)
        asked = gate_shown() and q("root.catDlPrompt.kind") == kind and q("root.catDlPrompt.count") == want
        q("root.catDlDismiss()")
        settle(120)
        q(g + '.category = "tracks"')
        settle(120)
        hidden = not shown(btn)
        print(f"{cat}: shown={is_shown} asked={asked} hidden={hidden}", flush=True)
        check(f"{cat}-button-flow", is_shown and others_hidden and asked and hidden)

    # 7. A fresh shelf load lands at its true top: the 8px header inside
    #    the scroll area puts a list's top at originY, not contentY 0. A
    #    ListView tab (Albums) and the GridView tab (Artists), rows
    #    injected offline like the other shelf scenarios.
    albums = [
        {
            "id": str(i),
            "title": f"Album {i}",
            "artist": "A",
            "art": "",
            "year": "2020",
            "date": "",
            "listed": "",
            "tracks": 10,
            "duration_sec": 2000,
            "quality": "",
            "popularity": 0,
        }
        for i in range(60)
    ]
    artists = [{"id": str(i), "name": f"Artist {i}", "art": ""} for i in range(60)]
    for cat, view, rows in (("albums", "albums", albums), ("artists", "artists", artists)):
        q(f'{g}.category = "{cat}"')
        settle(120)
        bridge.libraryLoaded.emit("tidal", cat, rows, False)
        settle(300)
        origin = float(q(f'{g}.viewFor("{view}").originY'))
        top = float(q(f'{g}.viewFor("{view}").contentY'))
        check(f"{cat}-lands-at-true-top", origin < 0 and abs(top - origin) < 0.5)

    for line in failures:
        print(f"REGRESSED: {line}", flush=True)
    return EXIT_REGRESSED if failures else EXIT_OK


@pytest.mark.qml
def test_my_music_shelves_download_all_confirms_the_count():
    run_scenario(
        Path(__file__),
        "--run-scenario",
        timeout=180,
        sandbox_prefix="waves-my-music-download-all-",
        failure_message="My Music DOWNLOAD ALL regressed",
    )


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_run_scenario())
