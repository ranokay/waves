"""Issue #259: a second saved-shelf source renders with zero QML edits.

WHAT THIS FENCES OFF
--------------------
My Music's shelves were TIDAL-shaped end to end: seven hardcoded category
lists gated on the TIDAL session and refreshed through TIDAL-only loaders. A
provider that later declared FAVORITES could contribute a descriptor and a
session and still render nothing.

This is the paper test, on the real pane: a second provider is registered on
the live bridge (a descriptor, a session, FAVORITES) and the pane grows its
own group -- label, category strip, keep-alive panes -- from that descriptor
alone, with its rows built by its own ``row_for`` and fetched through its own
``favorites_page``. Nothing in Main.qml names it. TIDAL is present and
signed in too, so both groups render, each under its source label.

Runs in a SUBPROCESS like the other Main.qml scenarios: building the bridge
installs process-global handlers that must not leak into the suite.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from support.qml import EXIT_OK, EXIT_REGRESSED, boot_main_qml, run_scenario

_ALBUM_ROWS = [
    {
        "id": "fake:1",
        "title": "Alpha",
        "artist": "Fake Artist",
        "artist_id": "fake:a1",
        "art": "",
        "year": "2024",
        "date": "2024-03-01",
        "listed": "",
        "tracks": 9,
        "duration_sec": 2000,
        "quality": "LOSSLESS",
        "popularity": 40,
    },
    {
        "id": "fake:2",
        "title": "Beta",
        "artist": "Fake Artist",
        "artist_id": "fake:a1",
        "art": "",
        "year": "2023",
        "date": "2023-01-01",
        "listed": "",
        "tracks": 7,
        "duration_sec": 1700,
        "quality": "HIGH",
        "popularity": 30,
    },
]


def _fake_provider():
    """A second provider: descriptor + session + FAVORITES, nothing else.

    It names itself; the pane must render it from the descriptor and route
    every page through the two seam calls a favourites shelf needs.
    """
    from waves.providers import Capability, ProviderDescriptor, StatusKind

    class _FakeProvider:
        id = "fake"
        name = "Fake Music"
        capabilities = frozenset({Capability.FAVORITES})
        is_logged_in = True

        def descriptor(self):
            return ProviderDescriptor(id=self.id, name=self.name, status_kind=StatusKind.SESSION)

        def favorites_page(self, kind, offset, limit, order=None):
            if kind != "albums":
                return [], False
            return [("obj", "1"), ("obj", "2")], False

        def row_for(self, kind, item):
            if kind != "album":
                return {}
            index = int(item[1]) - 1
            return dict(_ALBUM_ROWS[index])

        def user_collections(self):
            return None

        def folder_tree(self, root_folders=None):
            return None

    return _FakeProvider()


def _run_scenario() -> int:  # noqa: C901 (one straight scenario)
    booted = boot_main_qml()
    if isinstance(booted, int):
        return booted
    _root, q, settle, bridge = booted

    # A live TIDAL session plus the fake: two sources, so both groups render
    # and the labels are source-qualified (issue #221's rule).
    bridge._logged_in = True
    bridge.providers["fake"] = _fake_provider()
    q("root.refreshProviderSurfaces()")
    q("root.libraryOpen = true")
    settle(200)

    failures: list[str] = []
    sources = q("root.myMusicSources.length")
    if sources != 2:
        failures.append(f"the pane did not pick up the second source ({sources} sources)")
    groups = q("root.libGroupList().length")
    if groups != 2:
        failures.append(f"the pane rendered {groups} source groups, expected 2")

    fake = 'root.libGroupFor("fake")'
    tidal = 'root.libGroupFor("tidal")'
    if q(fake + " ? String(" + fake + ".sourceLabel) : ''") != "Saved from Fake Music":
        failures.append("the fake source's group carried no source label")
    if q(tidal + " ? String(" + tidal + ".sourceLabel) : ''") != "Saved from TIDAL":
        failures.append("TIDAL's group was not source-qualified beside a second source")
    # Its strip is its own: the categories its capability can fill, nothing
    # the pane hardcoded (no Mixes/Videos/Playlists tabs for a FAVORITES-only
    # provider).
    if q(fake + '.categories.map(function (c) { return c.id }).join(",")') != "home,albums,tracks,artists":
        failures.append("the fake source's category strip is not its own capability's")

    # Select one of its shelves: the load rides the SOURCE's provider
    # (favorites_page) and the rows come back through its row_for.
    q(fake + '.select("albums")')
    settle(700)
    count = q(fake + '.modelFor("albums").count')
    if count != 2:
        failures.append(f"the fake source's albums pane holds {count} rows, expected 2")
    else:
        first = q(fake + '.modelFor("albums").get(0).title')
        if first != "Alpha":
            failures.append(f"the fake source's first row is {first!r}, expected its own vocabulary")
    if q(fake + '.viewFor("albums") ? ' + fake + '.viewFor("albums").visible : false') is not True:
        failures.append("the fake source's albums pane is not the visible one")

    # TIDAL's own group is untouched by the second source: its strip is still
    # the seven shelves, and its panes hold no fake rows.
    if q(tidal + ".categories.length") != 7:
        failures.append("the TIDAL group lost its category strip")
    if q(fake + '.modelFor("albums").count') != 2 and q(tidal + '.modelFor("albums").count') > 0:
        failures.append("rows landed in the wrong source's pane")

    # One vocabulary per source: TIDAL's pane rows are the bridge's own row
    # dicts (the same keys search, Browse and the artist pages carry, so the
    # badges, ownership and identity reads agree), bound where the providers
    # are wired.
    from waves.waves_ui.backend import WavesBridge

    builders = bridge.providers["tidal"]._row_builders
    for kind, method in (
        ("album", WavesBridge._album_dict),
        ("track", WavesBridge._track_dict),
        ("video", WavesBridge._video_dict),
        ("playlist", WavesBridge._playlist_dict),
        ("mix", WavesBridge._mix_dict),
        ("artist", WavesBridge._fav_artist_dict),
    ):
        if builders.get(kind) is None or builders[kind].__func__ is not method:
            failures.append(f"TIDAL's {kind} rows do not ride the bridge's own {method.__name__}")

    for line in failures:
        print(f"REGRESSED: {line}", file=sys.stderr)
    return EXIT_REGRESSED if failures else EXIT_OK


@pytest.mark.qml
def test_a_second_source_renders_its_own_group_with_no_qml_edits():
    run_scenario(
        Path(__file__),
        "--run-scenario",
        timeout=180,
        sandbox_prefix="waves-my-music-second-source-",
        failure_message="the second saved-shelf source did not render its own group",
    )


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_run_scenario())
