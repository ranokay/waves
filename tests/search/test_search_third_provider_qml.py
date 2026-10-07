"""A third provider's search results render with zero QML edits.

WHAT THIS FENCES OFF
--------------------
A search payload must be able to carry any provider's rows: a page with one
fixed ``apple`` block and one model set per provider hardcoded in Main.qml
leaves a provider registered with ``Capability.SEARCH`` able to render badges
but with nowhere to put its results.

This is the paper test, on the real page: a third provider is registered on
the live bridge (a descriptor, a session, SEARCH) and the unified results
surface grows its rows, labelled with that provider's own source mark (name
and logo from its descriptor) -- driven end to end through the bridge's real
fan-out and the real QML payload handler. TIDAL and Apple are present too, so
all three sources render in registry order.

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
_SAFE_FAILURE = "The operation could not finish. Try again or open the logs."

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

    It names itself; the page must render its rows from the payload and the
    descriptor alone, with no wiring registered for it anywhere (no search
    gate, no QML branch).
    """
    from waves.providers import Capability, ProviderDescriptor, StatusKind

    class _FakeProvider:
        id = "fake"
        name = "Fake Music"
        capabilities = frozenset({Capability.SEARCH, Capability.CATALOG})
        is_logged_in = True

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


def _walk_expression(container: str, body: str) -> str:
    """Run ``body`` with ``all`` bound to every object under ``container``."""
    return (
        "(function(){ var g = " + container + ";"
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


def _sources(q) -> str:
    return q("(root.searchSources || []).map(function (s) { return s.provider }).join(',')")


def _ids(q, model: str) -> list:
    ref = f"searchResultsView.modelFor('{model}')"
    return [q(f"{ref}.get({i}).id") for i in range(int(q(f"{ref}.count")))]


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
    # not about), the fan-out and folding are the real ones.
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
    bridge.providerStateChanged.emit("fake")
    q("root.openSearch()")

    failures: list[str] = []
    q("root.submitSearch('fabric')")
    landed = _settle_until(q, settle, lambda: _sources(q) == "tidal,apple,fake")
    if not landed:
        print(f"the third provider's search never landed ({_sources(q)})", file=sys.stderr)
        return EXIT_REGRESSED

    # The three sources render in registry order; the third one arrives with
    # no wiring beyond its descriptor and payload.
    if _sources(q) != "tidal,apple,fake":
        failures.append(f"sources did not render in registry order ({_sources(q)!r})")

    # The third provider's rows land in the unified sections, each labelled
    # with its own source; the other two providers' rows land too.
    album_ids = _ids(q, "albums")
    if sorted(album_ids) != ["apple:al1", "fake:al1", "tidal:al1"]:
        failures.append(f"the unified sections did not carry every source's album rows ({album_ids})")
    if q("searchResultsView.countFor('artists')") != 1 or q("searchResultsView.countFor('tracks')") != 2:
        failures.append("the third provider's artist/track rows did not land")
    row_sources = json.loads(q("JSON.stringify(searchResultsView.rowSources('fake:al1'))"))
    if row_sources != [{"provider": "fake", "id": "fake:al1"}]:
        failures.append(f"the third provider's row did not carry its own source ({row_sources})")

    # The source chips row names every source (All + three providers), and
    # the third provider's own mark renders from its descriptor.
    chip_count = json.loads(
        q(
            "(function(){ var all = [];"
            " function walk(o) { if (!o) return;"
            "  if (o.objectName === 'searchSourceChip' && o.visible) all.push(true);"
            "  if (o.contentItem) walk(o.contentItem); if (o.item) walk(o.item);"
            "  var k = o.children || []; for (var i = 0; i < k.length; i++) walk(k[i]); }"
            " walk(root); return JSON.stringify(all.length); })()"
        )
    )
    if chip_count != 4:
        failures.append(f"the source chips did not list All plus three sources ({chip_count})")
    marks = json.loads(
        q(
            _walk_expression(
                "searchResultsView",
                "for (var i = 0; i < all.length; i++)"
                " if (all[i].source !== undefined && ('' + all[i].source).indexOf('" + _LOGO + "') !== -1)"
                "  out.push([all[i].visible, all[i].width > 0, all[i].height > 0]);",
            )
        )
    )
    if not marks or not any(m[0] and m[1] and m[2] for m in marks):
        failures.append(f"the third provider's rows did not render its descriptor's mark ({marks})")

    # A type filter narrows the sections without touching the sources: only
    # the third provider answers tracks.
    q("root.filterType = 'tracks'")
    settle(50)
    if q("searchResultsView.sectionVisible('albums')") or not q("searchResultsView.sectionVisible('tracks')"):
        failures.append("the tracks filter did not narrow the sections")
    if q("root.filteredResultCount") != 2:
        failures.append("the tracks filter did not count the third provider's two tracks")
    q("root.filterType = 'all'")
    settle(50)

    # The source filter is the unified page's scoping tool: choosing the
    # third provider shows exactly its rows (artist + album + two tracks).
    q("root.searchSourceFilter = 'fake'")
    settle(50)
    if q("root.filteredResultCount") != 4:
        failures.append(f"the source filter did not narrow to the third provider ({q('root.filteredResultCount')})")
    q("root.searchSourceFilter = 'all'")
    settle(50)

    # Apple switching off retires only its own rows: the bridge refolds the
    # displayed page, and the other sources (the third provider included)
    # keep theirs.
    bridge.settings.data.apple_enabled = False
    bridge.appleStatusChanged.emit()
    bridge.providerStateChanged.emit("apple")
    settle(300)
    if _sources(q) != "tidal,fake":
        failures.append(f"the switched-off source stayed on the page ({_sources(q)!r})")
    album_ids = _ids(q, "albums")
    if "apple:al1" in album_ids:
        failures.append("the switched-off provider's rows stayed on the page")
    if "fake:al1" not in album_ids or "tidal:al1" not in album_ids:
        failures.append(f"the refold dropped a surviving source's rows ({album_ids})")

    # A third provider alone keeps the search row live (the bridge's generic
    # gate) and answers its own unclassified failure with safe copy + RETRY.
    bridge._logged_in = False
    bridge.loggedInChanged.emit()
    bridge.settings.data.apple_enabled = False
    bridge.appleStatusChanged.emit()
    settle(200)
    if not q("searchAvailable") or not q("searchField.enabled"):
        failures.append("a lone search-capable provider left the search row dead")

    def _fake_is_down(needle):
        raise RuntimeError("Fake Music is down: token=private-search-token /Users/private/search.json")

    bridge.providers["fake"].search = _fake_is_down
    q("root.submitSearch('boom')")
    landed = _settle_until(q, settle, lambda: q("root.searchSourceError") == _SAFE_FAILURE, timeout_ms=4000)
    if not landed:
        failures.append(f"the third provider's lone failure did not name itself ({q('root.searchSourceError')!r})")
    else:
        states = json.loads(
            q("JSON.stringify((root.searchSources || []).map(function (s) { return [s.provider, s.state]; }))")
        )
        if states != [["fake", "failed"]]:
            failures.append(f"the failed source did not carry its own state ({states})")
        retry = json.loads(
            q(
                "(function(){ var all = [];"
                " function walk(o) { if (!o) return;"
                "  if (o.objectName === 'searchSourceRetry' && o.visible) all.push(true);"
                "  if (o.contentItem) walk(o.contentItem); if (o.item) walk(o.item);"
                "  var k = o.children || []; for (var i = 0; i < k.length; i++) walk(k[i]); }"
                " walk(root); return JSON.stringify(all.length); })()"
            )
        )
        if not retry:
            failures.append("the third provider's failed source showed no RETRY")
        if q("emptyHint.text") != "Search failed":
            failures.append("the empty line did not name the failure")

    for line in failures:
        print(f"REGRESSED: {line}", file=sys.stderr)
    return EXIT_REGRESSED if failures else EXIT_OK


@pytest.mark.qml
def test_a_third_search_provider_renders_with_no_qml_edits():
    run_scenario(
        Path(__file__),
        "--run-scenario",
        timeout=180,
        sandbox_prefix="waves-search-third-provider-",
        failure_message="the third search provider did not render its rows",
    )


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_run_scenario())
