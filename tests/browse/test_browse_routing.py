"""Browse routing: every fetch goes through the row's owning provider (#600).

The combined landing stamps each section and chip link with its owner; the
drill-down, the playlists leaf grid, the endless-scroll window and the tile
mosaics all route back through that provider, guarded by capability and
readiness rather than a global TIDAL session. Legacy unqualified keys
(cached pages, nav snapshots) still read as TIDAL's.
"""

from __future__ import annotations

from threading import Lock
from types import SimpleNamespace

from browse.fakes import LandingProvider
from conftest import _InlinePool, _Signal
from providers.fakes import StubProvider, stub_bridge

from waves.desktop.backend import WavesBridge
from waves.desktop.bridge_surfaces import browse_owner
from waves.desktop.providers.lifecycle import page_provider
from waves.providers import BrowseWindow
from waves.providers.base import Capability


def _page(rows):
    return SimpleNamespace(rows=rows)


def _slot_bridge(providers) -> WavesBridge:
    """A bare bridge with the signals and inline pool the page slots touch."""
    b = WavesBridge.__new__(WavesBridge)
    b.providers = dict(providers)
    b._tracked_sessions = set()
    b._provider_readiness_probes = {}
    b._browse_pages = {}
    b._browse_loading = set()
    b._browse_gen = 0
    b._evict_lock = Lock()
    b.threadpool = _InlinePool()
    b.browsePageLoaded = _Signal()
    b.browseSectionMore = _Signal()
    b.browseTileArt = _Signal()
    b._catalogEvent = SimpleNamespace(emit=lambda event: WavesBridge._on_catalog_event(b, event))
    b.busy_log = []
    b.status_log = []
    b._set_busy = lambda v: b.busy_log.append(v)
    b._set_status = lambda v: b.status_log.append(v)
    b._save_page_cache = lambda: None
    b._page_rows = lambda page: [dict(r) for r in page.rows]
    b._browse_card = lambda obj: {"id": str(getattr(obj, "id", ""))}
    return b


def test_open_browse_page_routes_to_the_rows_owner() -> None:
    stub = LandingProvider(
        "stub",
        "Stub",
        pages={"pages/x": _page([{"rowKind": "tracks", "title": "T", "items": [{"id": "t1"}]}])},
    )
    b = _slot_bridge({"stub": stub})
    b.openBrowsePage("pages/x", "X", "stub")

    assert stub.calls == [("browse_page", "X", "pages/x")]
    (payload,) = b.browsePageLoaded.emits
    assert payload["key"] == "pages/x"
    assert payload["provider_id"] == "stub"
    assert payload["sections"] == [{"rowKind": "tracks", "title": "T", "items": [{"id": "t1"}], "provider_id": "stub"}]

    # A cached revisit re-emits the page immediately, then revalidates
    # silently; the unchanged payload re-emits nothing on top.
    b.openBrowsePage("pages/x", "X", "stub")
    assert len(b.browsePageLoaded.emits) == 2
    assert len(stub.calls) == 2


def test_open_browse_page_defaults_to_tidal_for_legacy_calls() -> None:
    tidal = LandingProvider(
        "tidal", "TIDAL", pages={"pages/x": _page([{"rowKind": "tracks", "title": "T", "items": []}])}
    )
    b = _slot_bridge({"tidal": tidal})
    b.openBrowsePage("pages/x", "X")  # a nav snapshot / retry from before owners

    assert tidal.calls == [("browse_page", "X", "pages/x")]
    assert b.browsePageLoaded.emits[0]["provider_id"] == "tidal"


def test_open_browse_page_refuses_ids_the_owner_guard_rejects() -> None:
    catalog_only = LandingProvider(
        "catalog",
        "C",
        pages={"pages/x": _page([{"rowKind": "tracks", "title": "T", "items": []}])},
        capabilities=frozenset({Capability.CATALOG}),
    )
    signed_out = LandingProvider(
        "stub", "S", pages={"pages/x": _page([{"rowKind": "tracks", "title": "T", "items": []}])}, logged_in=False
    )
    b = _slot_bridge({"catalog": catalog_only, "stub": signed_out})

    b.openBrowsePage("pages/x", "X", "catalog")
    b.openBrowsePage("pages/x", "X", "stub")
    b.openBrowsePage("pages/x", "X", "ghost")

    assert catalog_only.calls == [] and signed_out.calls == []
    # Each refusal lands as that page's own error: the QML clears its
    # loading state and offers RETRY instead of a spinner that never ends.
    assert [p["key"] for p in b.browsePageLoaded.emits] == ["pages/x", "pages/x", "pages/x"]
    assert all(p["error"] for p in b.browsePageLoaded.emits)
    assert b._browse_loading == set()


def test_open_browse_playlists_keeps_its_qml_key_and_routes() -> None:
    stub = LandingProvider(
        "stub",
        "Stub",
        pages={
            "pages/p": _page(
                [
                    {
                        "rowKind": "cards",
                        "title": "Playlists here",
                        "items": [{"kind": "playlist", "id": "p1"}, {"kind": "album", "id": "a1"}],
                    }
                ]
            )
        },
    )
    b = _slot_bridge({"stub": stub})
    b.openBrowsePlaylists("pages/p", "P", "stub")

    assert stub.calls == [("browse_page", "P", "pages/p")]
    (payload,) = b.browsePageLoaded.emits
    assert payload["key"] == "pl:pages/p"
    assert payload["provider_id"] == "stub"
    (section,) = payload["sections"]
    assert section["items"] == [{"kind": "playlist", "id": "p1"}]
    assert section["provider_id"] == "stub"
    # The lone section's headline blanks: the back bar names the page.
    assert section["title"] == ""


def test_section_more_routes_through_the_owning_provider_and_grows_its_rows() -> None:
    stub = LandingProvider(
        "stub",
        "Stub",
        window=BrowseWindow(category=SimpleNamespace(items=[SimpleNamespace(id="c1")]), n=1, total=3),
    )
    b = _slot_bridge({"stub": stub})
    b._browse_root_cache = {
        "sections": [{"data": "pages/data/9", "offset": 0, "items": [], "provider_id": "stub"}],
        "sources": [{"provider_id": "stub", "name": "Stub"}],
    }

    b.loadBrowseSectionMore("local:Row", "pages/data/9", 0, "ALBUM_LIST", "Row", "stub")

    assert stub.calls == [("browse_window", "Row", "pages/data/9", "ALBUM_LIST", 0, 50)]
    (payload,) = b.browseSectionMore.emits
    assert payload["provider_id"] == "stub"
    assert payload["offset"] == 1 and payload["more"] is True
    assert b._browse_root_cache["sections"][0]["items"] == [{"id": "c1"}]
    assert b._browse_root_cache["sections"][0]["offset"] == 1


def test_section_more_refuses_unready_owner_and_off_service_paths() -> None:
    stub = LandingProvider(
        "stub", "Stub", window=BrowseWindow(category=SimpleNamespace(items=[]), n=0, total=0), logged_in=False
    )
    b = _slot_bridge({"stub": stub})
    b.loadBrowseSectionMore("local:Row", "pages/data/9", 0, "ALBUM_LIST", "Row", "stub")
    b.loadBrowseSectionMore("local:Row", "pages/data/9", 0, "ALBUM_LIST", "Row", "ghost")
    assert stub.calls == []
    assert all(p["error"] for p in b.browseSectionMore.emits)

    ready = LandingProvider("ready", "R", window=BrowseWindow(category=SimpleNamespace(items=[]), n=0, total=0))
    c = _slot_bridge({"ready": ready})
    c.loadBrowseSectionMore("local:Row", "https://evil.test/pages/data/9", 0, "ALBUM_LIST", "Row", "ready")
    assert ready.calls == [], "a window path may never leave the provider's API"
    assert c.browseSectionMore.emits[-1]["error"] is True


def test_tile_art_keys_namespace_non_tidal_owners() -> None:
    assert WavesBridge._tile_art_key("tidal", "pages/genres/pop") == "pages/genres/pop"
    assert WavesBridge._tile_art_key("stub", "pages/genres/pop") == "stub|pages/genres/pop"


def test_growth_matches_only_rows_with_the_same_owner() -> None:
    b = _slot_bridge({})
    b._browse_root_cache = {
        "sections": [
            {"data": "pages/data/9", "offset": 0, "items": [], "provider_id": "stub"},
            {"data": "pages/data/9", "offset": 0, "items": [], "provider_id": "other"},
        ]
    }
    b._browse_grow_cached("pages/data/9", 0, [{"id": "c1"}], 1, True, "stub")
    rows = b._browse_root_cache["sections"]
    assert rows[0]["items"] == [{"id": "c1"}]
    assert rows[1]["items"] == []


def test_page_provider_parses_qualified_and_legacy_keys() -> None:
    assert page_provider("browse:stub:pages/x") == "stub"
    assert page_provider("browse:tidal:pages/x") == "tidal"
    assert page_provider("browse:pages/x") == "tidal"  # legacy editorial path
    assert page_provider("pl:stub:pages/x") == "stub"
    assert page_provider("pl:pages/x") == "tidal"  # legacy playlists grid
    assert page_provider("item:album:stub:7") == "stub"


def test_browse_root_sources_reads_the_composing_providers() -> None:
    assert WavesBridge._browse_root_sources({"sources": [{"provider_id": "stub"}, {"provider_id": "tidal"}]}) == {
        "stub",
        "tidal",
    }
    assert WavesBridge._browse_root_sources({"sections": [{"provider_id": "stub"}]}) == {"stub"}
    # A payload cached before rows carried owners was TIDAL's.
    assert WavesBridge._browse_root_sources({"sections": [{"rowKind": "cards"}]}) == {"tidal"}
    assert WavesBridge._browse_root_sources({}) == {"tidal"}


def test_browse_owner_guards_on_capability_and_readiness() -> None:
    ready = StubProvider("tidal", "TIDAL", capabilities={Capability.BROWSE}, logged_in=True)
    signed_out = StubProvider("stub", "Stub", capabilities={Capability.BROWSE}, logged_in=False)
    incapable = StubProvider("apple", "Apple Music", capabilities={Capability.SEARCH})
    bridge = stub_bridge(
        {"tidal": ready, "stub": signed_out, "apple": incapable}, tracked=frozenset({"tidal"}), logged_in=True
    )

    assert browse_owner(bridge, "tidal") is ready
    assert browse_owner(bridge, "stub") is None
    assert browse_owner(bridge, "apple") is None
    assert browse_owner(bridge, "ghost") is None
