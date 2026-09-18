"""Issue #292: a third provider's search group renders with zero QML edits.

WHAT THIS FENCES OFF
--------------------
The search payload used to build TIDAL's ungrouped buckets plus one ``apple``
block, and Main.qml held one fixed model set and section layout per provider.
A provider registered with ``Capability.SEARCH`` could render badges (#278)
but had nowhere to put its results.

This is the paper test, on the real page: a third provider is registered on
the live bridge (a descriptor, a session, SEARCH) and the results page grows
its own group -- head name and mark from its descriptor, its rows in the
sections its payload declares, its own fold -- driven end to end through the
bridge's real fan-out and the real QML payload handler. TIDAL and Apple are
present too, so all three groups render in the payload's own order.

Runs in a SUBPROCESS like the other Main.qml scenarios: building the bridge
installs process-global handlers that must not leak into the suite.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from support.qml import EXIT_OK, EXIT_REGRESSED, boot_main_qml, run_scenario

_LOGO = "assets/providers/apple-music.png"

_FAKE_ALBUM = {
    "id": "fake:al1",
    "title": "Fake Album",
    "artist": "Fake Artist",
    "artist_id": "fake:ar1",
    "artists": [],
    "art": "",
    "year": "2026",
    "date": "2026-01-01",
    "listed": "",
    "tracks": 4,
    "duration_sec": 1200,
    "quality": "LOSSLESS",
    "popularity": 44,
    "explicit": False,
    "added": "",
}
_FAKE_ARTIST = {"id": "fake:ar1", "name": "Fake Artist", "art": "", "roles": "Artist", "popularity": 30}
_FAKE_TRACKS = [
    {
        "id": f"fake:tr{n}",
        "title": f"Fake Track {n}",
        "artist": "Fake Artist",
        "artist_id": "fake:ar1",
        "artists": [],
        "album": "Fake Album",
        "album_id": "fake:al1",
        "num": n,
        "vol": 1,
        "art": "",
        "year": "2026",
        "date": "2026-01-01",
        "duration": "3:0" + str(n),
        "duration_sec": 180,
        "quality": "LOSSLESS",
        "popularity": 10,
        "explicit": False,
        "added": "",
    }
    for n in (1, 2)
]
_APPLE_ALBUM = {
    "id": "apple:al1",
    "title": "Apple Album",
    "artist": "Apple Artist",
    "artist_id": "apple:ar1",
    "artists": [],
    "art": "",
    "year": "2026",
    "date": "2026-01-01",
    "tracks": 2,
    "duration_sec": 600,
    "quality": "LOSSLESS",
    "popularity": -1,
    "explicit": False,
    "added": "",
}


def _fake_provider():
    """A third provider: descriptor + session + SEARCH, nothing else.

    It names itself; the page must render its group from the payload and the
    descriptor alone, with no wiring registered for it anywhere (no search
    gate, no QML branch).
    """
    from waves.providers import Capability, ProviderDescriptor, StatusKind

    class _FakeProvider:
        id = "fake"
        name = "Fake Music"
        capabilities = frozenset({Capability.SEARCH, Capability.CATALOG})
        is_logged_in = True
        search_artists_layout = "flow"

        def descriptor(self):
            return ProviderDescriptor(
                id=self.id,
                name=self.name,
                logo=_LOGO,
                status_kind=StatusKind.SESSION,
            )

        def search(self, needle):
            return {
                "artists": [dict(_FAKE_ARTIST)],
                "albums": [dict(_FAKE_ALBUM)],
                "tracks": [dict(row) for row in _FAKE_TRACKS],
                "videos": [],
                "playlists": [],
                "mixes": [],
                "top": None,
            }

    return _FakeProvider()


def _walk_expression(group: str, body: str) -> str:
    """Run ``body`` with ``g`` bound to the provider group's item."""
    return (
        "(function(){ var g = " + group + "; if (!g) return JSON.stringify(null);"
        " function walk(o, out) { if (!o) return; out.push(o);"
        "  if (o.contentItem) walk(o.contentItem, out);"
        "  if (o.item) walk(o.item, out);"
        "  var kids = o.children || []; for (var i = 0; i < kids.length; i++) walk(kids[i], out); }"
        " var all = []; walk(g, all); var out = []; " + body + " return JSON.stringify(out); })()"
    )


def _settle_until(q, settle, predicate, *, timeout_ms: int = 8000, step_ms: int = 25) -> bool:
    waited = 0
    while not predicate():
        if waited >= timeout_ms:
            return False
        settle(step_ms)
        waited += max(step_ms, 1)
    return True


def _run_scenario() -> int:  # noqa: C901 (one straight scenario)
    booted = boot_main_qml()
    if isinstance(booted, int):
        return booted
    _root, q, settle, bridge = booted

    # TIDAL signed in, Apple enabled: the page must show all three providers.
    bridge._logged_in = True
    bridge.loggedInChanged.emit()
    bridge.settings.data.apple_enabled = True
    bridge.appleStatusChanged.emit()
    settle(300)

    # TIDAL's reply still carries engine objects; the bridge builds its rows.
    # The row translation is stubbed at the builder (the seam this scenario is
    # not about), the fan-out and grouping are the real ones.
    class _TidalAlbum:
        id = "tidal:al1"
        name = "Tidal Album"

    bridge.providers["tidal"].search = lambda needle: {"albums": [_TidalAlbum()], "top_hit": None}
    bridge._album_dict = lambda album: {
        "id": str(album.id),
        "title": str(album.name),
        "artist": "Tidal Artist",
        "artist_id": "",
        "artists": [],
        "art": "",
        "year": "2026",
        "date": "2026-01-01",
        "listed": "",
        "tracks": 3,
        "duration_sec": 900,
        "quality": "LOSSLESS",
        "popularity": -1,
        "explicit": False,
        "added": "",
    }
    bridge.providers["apple"].search = lambda needle: {
        "artists": [],
        "albums": [dict(_APPLE_ALBUM)],
        "tracks": [],
        "videos": [],
        "playlists": [],
        "mixes": [],
        "top": None,
    }
    bridge.providers["fake"] = _fake_provider()

    failures: list[str] = []
    q("root.submitSearch('fabric')")
    landed = _settle_until(q, settle, lambda: q("root.searchGroupList().length") == 3)
    if not landed:
        print(
            f"the third provider's search never landed ({q('root.searchGroupList().length')} groups)", file=sys.stderr
        )
        return EXIT_REGRESSED

    tidal = "root.searchGroupFor('tidal')"
    apple = "root.searchGroupFor('apple')"
    fake = "root.searchGroupFor('fake')"
    order = q("root.searchGroupList().map(function (g) { return g.providerId }).join(',')")
    if order != "tidal,apple,fake":
        failures.append(f"the groups did not render in payload order ({order!r})")

    # The third group's own head: name and mark from its descriptor.
    if not q(fake + ".headVisible"):
        failures.append("the third provider's group head is not visible")
    name_hit = json.loads(
        q(
            _walk_expression(
                fake,
                "for (var i = 0; i < all.length; i++)"
                " if (all[i].text !== undefined && all[i].text === 'FAKE MUSIC'"
                "     && all[i].visible && all[i].width > 0)"
                "  out.push(['name', all[i].text]);",
            )
        )
    )
    if name_hit != [["name", "FAKE MUSIC"]]:
        failures.append(f"the head did not render the descriptor's name ({name_hit})")
    marks = json.loads(
        q(
            _walk_expression(
                fake,
                "for (var i = 0; i < all.length; i++)"
                " if (all[i].source !== undefined && ('' + all[i].source).indexOf('" + _LOGO + "') !== -1)"
                "  out.push([all[i].visible, all[i].width, all[i].height]);",
            )
        )
    )
    if not marks or not any(m[0] and m[1] > 0 and m[2] > 0 for m in marks):
        failures.append(f"the head did not render the descriptor's mark ({marks})")

    # Its rows, on its own models, with its own counts.
    counts = (
        q(fake + ".modelFor('artists').count"),
        q(fake + ".modelFor('albums').count"),
        q(fake + ".modelFor('tracks').count"),
    )
    if counts != (1, 1, 2):
        failures.append(f"the third provider's rows did not land ({counts})")
    if q(fake + ".modelFor('albums').get(0).title") != "Fake Album":
        failures.append("the third provider's album row lost its title")
    if q(fake + ".rowCount") != 4:
        failures.append(f"the third provider's count reads {q(fake + '.rowCount')}, expected 4")

    # Sections are driven by its own rows: it declares no videos, so the
    # filter can never host its head, and its videos section stays empty.
    if q(fake + ".hostable('videos')") is not True:
        failures.append("the third provider's payload did not carry its videos bucket")
    if q(fake + ".sectionVisible('videos')"):
        failures.append("an empty videos section rendered for the third provider")
    q("root.filterType = 'tracks'")
    settle(50)
    # Only the provider with track rows keeps a head under the tracks filter;
    # the other two have none, and Apple's group carries no videos/mixes
    # bucket at all (so that filter can never host it).
    if not q(fake + ".headVisible") or q(tidal + ".headVisible") or q(apple + ".headVisible"):
        failures.append("the tracks filter did not keep exactly the providers with tracks")
    q("root.filterType = 'all'")
    settle(50)

    # Its own fold: collapsing the third group hides its rows, leaves the
    # shipped two alone, and persists under its own provider-keyed pref.
    if not q(tidal + ".headVisible") or not q(apple + ".headVisible"):
        failures.append("the first two providers' groups are not on the page")
    q(fake + ".toggleCollapsed()")
    settle(100)
    if not q(fake + ".collapsed"):
        failures.append("the third provider's group did not collapse")
    if q(fake + ".sectionVisible('albums')"):
        failures.append("a collapsed group still showed its rows")
    if not q(fake + ".headVisible"):
        failures.append("the collapsed group lost its own head")
    if not q(tidal + ".sectionVisible('albums')") or not q(apple + ".sectionVisible('albums')"):
        failures.append("collapsing the third group moved the shipped two")
    bridge._config_writer.flush()
    settle(100)
    if not bridge._waves_prefs.get("search_provider_fake_collapsed"):
        failures.append("the third provider's fold did not reach its provider-keyed pref")

    # The shipped two are unchanged: heads in order, rows and counts as ever.
    if q(tidal + ".modelFor('albums').count") != 1 or q(apple + ".modelFor('albums').count") != 1:
        failures.append("the shipped providers' rows changed beside the third group")

    # Removing the middle group shifts the third provider onto its delegate
    # (the Repeater reuses items by index). Its own fold must survive the
    # shift, not inherit the departed provider's state.
    bridge.settings.data.apple_enabled = False
    bridge.appleStatusChanged.emit()
    settle(300)
    if q("root.searchGroupFor('apple')") is not None:
        failures.append("the switched-off provider's group stayed on the page")
    if not bool(q(fake)):
        failures.append("the third provider's group went with the switched-off one")
    elif not q(fake + ".collapsed"):
        failures.append("a group delegate reuse dropped the third provider's fold")
    if q(fake + ".sectionVisible('albums')"):
        failures.append("the shifted group rendered rows while collapsed")

    q(fake + ".toggleCollapsed()")
    settle(100)
    if not q(fake + ".sectionVisible('albums')") or q(fake + ".modelFor('albums').count") != 1:
        failures.append("the shifted group did not come back with its own rows")

    for line in failures:
        print(f"REGRESSED: {line}", file=sys.stderr)
    return EXIT_REGRESSED if failures else EXIT_OK


@pytest.mark.qml
def test_a_third_search_provider_renders_its_own_group_with_no_qml_edits():
    run_scenario(
        Path(__file__),
        "--run-scenario",
        timeout=180,
        sandbox_prefix="waves-search-third-provider-",
        failure_message="the third search provider did not render its own group",
    )


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_run_scenario())
