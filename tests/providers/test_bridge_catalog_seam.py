"""The bridge's catalog reads route through the Provider seam.

Search, pasted-link resolution, the
album/artist/playlist page re-fetches, the My Tidal sweep and favorites
windows, and the favorite-id sets read through ``self.providers`` instead of
reaching the TIDAL session/helper directly. The row-dict schema is the
contract; the payloads QML consumes are byte-identical.

HOW THE SEAM STAYS CLOSED
-------------------------
Every test here drives the real bridge method on a stub whose provider is a
recording fake and whose ``tidal.session`` is a guard that fails the test on
ANY touch: a catalog read that reaches past the seam cannot pass. The canned
builder answers double as the byte-identical expectation -- the emitted
payload must equal exactly what the builders were handed to build.
"""

from __future__ import annotations

from threading import Barrier, Lock
from types import SimpleNamespace

import pytest
from providers.fakes import BareProvider
from tidalapi.album import Album
from tidalapi.artist import Artist

from waves.constants import CTX_APPLE, CTX_TIDAL
from waves.desktop import backend
from waves.desktop.backend import WavesBridge
from waves.providers import Capability, ProviderDescriptor, TidalProvider
from waves.providers.apple import AppleCatalogUnavailable, AppleProvider


class _Signal:
    def __init__(self):
        self.emits: list = []

    def emit(self, *args):
        self.emits.append(args[0] if len(args) == 1 else args)


class _InlinePool:
    @staticmethod
    def start(worker, priority: int = 0):
        worker.fn()


class _GuardSession:
    """Any attribute touch fails: the seam is the only road."""

    def __getattr__(self, name):
        raise AssertionError(f"the bridge reached the TIDAL session directly: .{name}")


class _FakeProvider(BareProvider):
    """Records the seam calls the bridge makes; answers with canned objects."""

    capabilities = frozenset(Capability)

    def __init__(self, provider_id="tidal", **answers):
        self.id = provider_id
        self.name = provider_id.title()
        self._logged_in = answers.pop("signed_in", True)
        self._row_builders = {}
        self.calls: list[tuple] = []
        # What the provider declares about its search surface:
        # the neutral answer is every section in the flow layout, which the
        # per-test declarations override where they stand for TIDAL or Apple.
        self.search_sections = answers.pop(
            "search_sections", ("artists", "albums", "tracks", "videos", "playlists", "mixes")
        )
        self._answers = answers

    @property
    def is_logged_in(self):
        return self._logged_in

    def descriptor(self):
        return ProviderDescriptor(id=self.id, name=self.name, link_hosts=(f"{self.id}.com",))

    # The SDK interpretation belongs to its provider, as in production.
    resolve_link = TidalProvider.resolve_link
    row_for = TidalProvider.row_for

    def classify_failure(self, exc):
        if self.id == CTX_APPLE:
            return AppleProvider.__new__(AppleProvider).classify_failure(exc)
        return super().classify_failure(exc)

    def search(self, needle):
        self.calls.append(("search", needle))
        if isinstance(self._answers.get("search"), Exception):
            raise self._answers["search"]
        return self._answers.get("search", {})

    def open_url(self, url):
        self.calls.append(("open_url", url))
        answer = self._answers.get("open_url")
        if isinstance(answer, Exception):
            raise answer
        return answer

    def get_object(self, kind, raw_id):
        self.calls.append(("get_object", kind, raw_id))
        answer = self._answers.get("get_object")
        if isinstance(answer, Exception):
            raise answer
        return answer

    def user_collections(self):
        self.calls.append(("user_collections",))
        return self._answers.get("user_collections", {})

    def favorites_page(self, kind, offset, limit, order=None):
        self.calls.append(("favorites_page", kind, offset, limit, order))
        return self._answers.get("favorites_page", ([], False))

    def favorite_ids(self, kind):
        self.calls.append(("favorite_ids", kind))
        answer = self._answers.get("favorite_ids")
        if isinstance(answer, Exception):
            raise answer
        return answer


def _provider(**answers) -> _FakeProvider:
    return _FakeProvider(**answers)


def _stub_base(providers: dict) -> SimpleNamespace:
    return SimpleNamespace(
        threadpool=_InlinePool(),
        statuses=[],
        busy=[],
        _search_gen=0,
        _browse_gen=0,
        tidal=SimpleNamespace(session=_GuardSession()),
        providers=providers,
    )


_ALL_SECTIONS = ("artists", "albums", "tracks", "videos", "playlists", "mixes")
# Apple's catalog answers four kinds; its group carries no video/mix buckets.
_APPLE_SECTIONS = ("artists", "albums", "tracks", "playlists")


def _group(provider, rows=None, *, top=None, error="", sections=_ALL_SECTIONS) -> dict:
    """One search group, shaped like the bridge's own builder."""
    source = rows or {}
    group = {"provider": provider}
    for section in sections:
        group[section] = list(source.get(section) or [])
    group["top"] = top
    group["error"] = error
    return group


def _payload(*groups) -> dict:
    return {"groups": list(groups)}


# --------------------------------------------------------------------------- #
# search
# --------------------------------------------------------------------------- #
class _SearchStub:
    search = WavesBridge.search
    dropSearchSource = WavesBridge.dropSearchSource
    _absorb_search_group = WavesBridge._absorb_search_group
    _search_display_payload = WavesBridge._search_display_payload
    _paint_search_display = WavesBridge._paint_search_display
    _settle_search = WavesBridge._settle_search
    _enrich_search_artists = WavesBridge._enrich_search_artists
    _search_total = staticmethod(WavesBridge._search_total)
    _search_artist_meters = staticmethod(WavesBridge._search_artist_meters)
    _remember_search = WavesBridge._remember_search
    _save_page_cache = lambda self: None
    _top_hit_dict = WavesBridge._top_hit_dict
    _SEARCH_CACHE_MAX = 20
    _SEARCH_TTL = 90.0

    def __init__(self, provider):
        self._logged_in = True
        self._search_cache: dict = {}
        self._objs_lock = Lock()
        self._objs: dict = {"artist": {}, "album": {}, "track": {}, "video": {}, "playlist": {}, "mix": {}}
        base = _stub_base({"tidal": provider})
        self.__dict__.update(base.__dict__)
        self.searchResults = _Signal()
        self.artistMetaLoaded = _Signal()
        # The gates the real bridge registers where the providers are wired:
        # TIDAL's session, Apple's enable switch.
        self._provider_search_gates = {
            "tidal": lambda: bool(self._logged_in),
            "apple": lambda: bool(
                getattr(getattr(self, "settings", None), "data", None) and self.settings.data.apple_enabled
            ),
        }

    def _set_status(self, text):
        self.statuses.append(text)

    def _set_busy(self, on):
        self.busy.append(bool(on))

    def _remember(self, kind, key, obj):
        self._objs[kind][key] = obj

    def _dedup_albums(self, albums):
        return list(albums)

    def _dedup_tracks(self, tracks):
        return list(tracks)

    def _dedup_videos(self, videos):
        return list(videos)

    def _album_dict(self, a):
        return {"id": "al1", "title": "A"}

    def _track_dict(self, t):
        return {"id": "tr1", "title": "T"}

    def _video_dict(self, v):
        return {"id": "vi1", "title": "V"}

    def _playlist_dict(self, p):
        return {"id": "pl1", "title": "P"}

    def _mix_dict(self, m):
        return {"id": "mx1", "title": "M"}


def test_search_reads_the_provider_and_the_payload_is_the_built_rows():
    provider = _provider(
        search={
            "albums": [object()],
            "tracks": [object()],
            "videos": [object()],
            "playlists": [object()],
            "mixes": [object()],
            "top_hit": None,
        },
    )
    stub = _SearchStub(provider)

    stub.search("aphex twin")

    assert provider.calls == [("search", "aphex twin")]
    # The display folds the provider group into sections; each row exposes
    # its source, and the provider's own buckets survive untouched.
    assert stub.searchResults.emits == [
        {
            "sources": [{"provider": "tidal", "state": "ready", "error": ""}],
            "sections": {
                "artists": [],
                "albums": [{"id": "al1", "title": "A", "sources": [{"provider": "tidal", "id": "al1"}]}],
                "tracks": [{"id": "tr1", "title": "T", "sources": [{"provider": "tidal", "id": "tr1"}]}],
                "videos": [{"id": "vi1", "title": "V", "sources": [{"provider": "tidal", "id": "vi1"}]}],
                "playlists": [{"id": "pl1", "title": "P", "sources": [{"provider": "tidal", "id": "pl1"}]}],
                "mixes": [{"id": "mx1", "title": "M", "sources": [{"provider": "tidal", "id": "mx1"}]}],
            },
            "top": None,
        }
    ]
    assert stub.statuses[-1] == "5 results"
    assert stub.busy == [True, False]


def test_a_cached_search_never_reaches_the_provider_twice():
    provider = _provider(search={"albums": [object()], "top_hit": None})
    stub = _SearchStub(provider)

    stub.search("aphex")
    stub.search("aphex")

    assert provider.calls == [("search", "aphex")]  # the second came from cache
    assert stub.busy[-1] is False


def test_a_lone_failed_provider_names_itself():
    # A LONE enabled provider's failure names its source with the owner's safe
    # words: no second provider can carry them, so a blank
    # page would be the only answer. The status repeats them, nothing is
    # cached, and busy is never latched. A BUILD failure is the other
    # "Search failed" road (tests/downloads/test_worker_latch_and_logout.py).
    provider = _provider(search=RuntimeError("network died"))
    stub = _SearchStub(provider)

    stub.search("aphex")

    assert stub.busy == [True, False]
    (payload,) = stub.searchResults.emits
    assert payload["sources"] == [
        {
            "provider": "tidal",
            "state": "failed",
            "error": "The operation could not finish. Try again or open the logs.",
        }
    ]
    assert payload["sections"] == {}
    assert stub.statuses[-1] == "The operation could not finish. Try again or open the logs."
    assert stub._search_cache == {}


def test_a_partial_tidal_failure_names_the_tidal_source():
    # One provider failed while the other answered: the failure's words ride
    # ITS source (never the successful one's), and the status names it.
    tidal = _provider(search=RuntimeError("network died"))
    apple = _provider(
        search={"tracks": [{"id": "apple:song-1", "title": "Xtal"}], "top_hit": None},
        search_sections=_APPLE_SECTIONS,
    )
    stub = _SearchStub(tidal)
    apple.id, apple.name = "apple", "Apple Music"
    stub.providers["apple"] = apple
    stub.settings = SimpleNamespace(data=SimpleNamespace(apple_enabled=True))

    stub.search("aphex")

    payload = stub.searchResults.emits[-1]
    sources = {source["provider"]: source for source in payload["sources"]}
    assert sources["tidal"]["state"] == "failed"
    assert sources["tidal"]["error"] == "The operation could not finish. Try again or open the logs."
    assert sources["apple"]["state"] == "ready" and sources["apple"]["error"] == ""
    assert [row["title"] for row in payload["sections"]["tracks"]] == ["Xtal"]
    assert stub.statuses[-1] == "The operation could not finish. Try again or open the logs."
    assert stub._search_cache == {}


def test_search_enabled_reads_every_registered_provider_and_its_gate():
    # The search row's generic gate: a registered SEARCH provider
    # with a gate that says on, or declared live readiness, keeps it live; a provider
    # without SEARCH, or with a gate that says off, does not.
    bridge = SimpleNamespace(providers={}, _provider_search_gates={"tidal": lambda: False}, _logged_in=False)
    assert WavesBridge.searchEnabled(bridge) is False

    bridge.providers["tidal"] = _provider()
    assert WavesBridge.searchEnabled(bridge) is False, "a gated-off provider is not on"
    bridge._provider_search_gates["tidal"] = lambda: True
    assert WavesBridge.searchEnabled(bridge) is True

    # No bridge gate: a third provider contributes its own account facts.
    bridge.providers["fake"] = _provider(provider_id="fake")
    bridge._provider_search_gates["tidal"] = lambda: False
    assert WavesBridge.searchEnabled(bridge) is True
    bridge.providers["fake"]._logged_in = False
    assert WavesBridge.searchEnabled(bridge) is False, "absence of a bridge gate does not grant a session"

    # A provider that cannot search never keeps the row live.
    bridge.providers.clear()
    bridge.providers["catalog"] = SimpleNamespace(capabilities=frozenset({Capability.CATALOG}))
    assert WavesBridge.searchEnabled(bridge) is False


def test_search_group_carries_only_the_sections_its_provider_declares():
    # The declaration is consumed through the group builder: a provider that
    # names a subset carries exactly those buckets, and one that names nothing
    # answers everything by default. A name the
    # page does not render contributes no bucket.
    provider = SimpleNamespace(
        search_sections=("artists", "albums", "songs"),
    )
    group = backend._search_group("fake", provider, {"artists": [1], "albums": [2], "videos": [3], "mixes": [4]})
    assert group["artists"] == [1] and group["albums"] == [2]
    assert "videos" not in group and "mixes" not in group

    undeclared = backend._search_group("fake", SimpleNamespace(), {})
    assert set(_ALL_SECTIONS) <= set(undeclared), "an undeclared provider answers them all"


def test_search_enabled_answers_the_bridge_slot_through_the_real_seam():
    # The QML calls waves.searchEnabled(); the real bridge answers it over its
    # own registry and gates.
    tidal = _provider()
    stub = _SearchStub(tidal)
    assert WavesBridge.searchEnabled(stub) is True, "a signed-in TIDAL keeps the row live"
    stub._logged_in = False
    assert WavesBridge.searchEnabled(stub) is False
    stub.providers["fake"] = _provider(provider_id="fake")
    assert WavesBridge.searchEnabled(stub) is True, "a ready third provider joins the gate"


class _FanoutProvider(_FakeProvider):
    def __init__(self, barrier: Barrier, result: dict):
        super().__init__()
        self._barrier = barrier
        self._result = result

    def search(self, needle):
        self.calls.append(("search", needle))
        self._barrier.wait(timeout=2)
        return self._result


def test_search_fans_out_over_enabled_providers_and_folds_their_sources():
    barrier = Barrier(2)
    tidal = _FanoutProvider(barrier, {"albums": [object()], "top_hit": None})
    apple_payload = {
        "artists": [],
        "albums": [],
        "tracks": [{"id": "apple:song-1", "title": "Xtal"}],
        "videos": [{"id": "apple:video-must-not-cross", "title": "No"}],
        "playlists": [],
        "mixes": [],
        "top": None,
    }
    apple = _FanoutProvider(barrier, apple_payload)
    # Apple's catalog answers no videos or mixes: its group carries just its
    # own sections, whatever the reply's key set.
    apple.search_sections = _APPLE_SECTIONS
    stub = _SearchStub(tidal)
    apple.id, apple.name = "apple", "Apple Music"
    stub.providers["apple"] = apple
    stub.settings = SimpleNamespace(data=SimpleNamespace(apple_enabled=True))

    stub.search("aphex twin")

    assert tidal.calls == [("search", "aphex twin")]
    assert apple.calls == [("search", "aphex twin")]
    payload = stub.searchResults.emits[-1]
    assert [(s["provider"], s["state"]) for s in payload["sources"]] == [("tidal", "ready"), ("apple", "ready")]
    # TIDAL's built rows and Apple's own row dicts both reach the page, each
    # labelled with its source; Apple's stray video row never crosses.
    assert [row["id"] for row in payload["sections"]["albums"]] == ["al1"]
    assert [row["title"] for row in payload["sections"]["tracks"]] == ["Xtal"]
    assert payload["sections"]["videos"] == [] and payload["sections"]["mixes"] == []
    assert stub.statuses[-1] == "2 results"


def test_search_with_apple_disabled_keeps_the_old_page_unchanged():
    tidal = _provider(
        search={"albums": [object()], "top_hit": None},
    )
    apple = _provider(search=AssertionError("disabled Apple search ran"))
    stub = _SearchStub(tidal)
    apple.id, apple.name = "apple", "Apple Music"
    stub.providers["apple"] = apple
    stub.settings = SimpleNamespace(data=SimpleNamespace(apple_enabled=False))

    stub.search("aphex twin")

    assert apple.calls == []
    # Apple contributes no source at all while it is off: the page keeps the
    # exact TIDAL-only structure.
    (payload,) = stub.searchResults.emits
    assert [s["provider"] for s in payload["sources"]] == ["tidal"]
    assert [row["id"] for row in payload["sections"]["albums"]] == ["al1"]


def test_search_with_tidal_signed_out_and_apple_enabled_asks_only_apple():
    # The picker's "Search works with no account" promise. The signed-out
    # TIDAL provider is never touched; the page carries exactly the Apple
    # source and sections.
    tidal = _provider(search=AssertionError("TIDAL search ran without a session"))
    apple_payload = {
        "artists": [],
        "albums": [{"id": "apple:album-1", "title": "A"}],
        "tracks": [],
        "videos": [],
        "playlists": [],
        "mixes": [],
        "top": None,
    }
    apple = _provider(search=apple_payload, search_sections=_APPLE_SECTIONS)
    stub = _SearchStub(tidal)
    apple.id, apple.name = "apple", "Apple Music"
    stub.providers["apple"] = apple
    stub.settings = SimpleNamespace(data=SimpleNamespace(apple_enabled=True))
    stub._logged_in = False

    stub.search("aphex twin")

    assert tidal.calls == []
    assert apple.calls == [("search", "aphex twin")]
    (payload,) = stub.searchResults.emits
    assert [s["provider"] for s in payload["sources"]] == ["apple"]
    assert set(payload["sections"]) == set(_APPLE_SECTIONS)
    assert [row["id"] for row in payload["sections"]["albums"]] == ["apple:album-1"]
    assert stub.statuses[-1] == "1 results"
    assert stub.busy == [True, False]


def test_an_apple_only_failure_names_its_source():
    """When Apple is the only provider and its fetch fails,
    the honest words reach the Apple source so the page can show them with a
    RETRY -- not a silent "Search failed" with a blank page. Nothing is cached
    from a failure."""
    tidal = _provider(search=AssertionError("TIDAL search ran without a session"))
    apple = _provider(search=AppleCatalogUnavailable(), search_sections=_APPLE_SECTIONS)
    stub = _SearchStub(tidal)
    apple.id, apple.name = "apple", "Apple Music"
    stub.providers["apple"] = apple
    stub.settings = SimpleNamespace(data=SimpleNamespace(apple_enabled=True))
    stub._logged_in = False

    stub.search("aphex twin")

    payload = stub.searchResults.emits[-1]
    assert payload["sources"] == [
        {
            "provider": "apple",
            "state": "failed",
            "error": "Apple's catalog format has changed. Check for a Waves update.",
        }
    ]
    assert payload["sections"] == {}
    assert stub.statuses[-1] == payload["sources"][0]["error"]
    assert stub._search_cache == {}


def test_a_two_provider_failure_stays_a_plain_search_failure():
    """The per-source words belong to the one failure no second provider can
    carry: with TIDAL in the fan-out, both fetches failing
    is a plain failure status -- no single provider's words are put in the
    other's mouth -- and nothing is cached."""
    tidal = _provider(search=RuntimeError("network died"))
    apple = _provider(search=AppleCatalogUnavailable())
    stub = _SearchStub(tidal)
    apple.id, apple.name = "apple", "Apple Music"
    stub.providers["apple"] = apple
    stub.settings = SimpleNamespace(data=SimpleNamespace(apple_enabled=True))

    stub.search("aphex twin")

    assert stub.statuses[-1] == "Search failed"
    payload = stub.searchResults.emits[-1]
    assert [(s["provider"], s["state"]) for s in payload["sources"]] == [("tidal", "failed"), ("apple", "failed")]
    assert payload["sections"] == {}
    assert stub._search_cache == {}


def test_search_with_no_provider_available_refuses_unchanged():
    tidal = _provider(search=AssertionError("TIDAL search ran without a session"))
    apple = _provider(search=AssertionError("Apple search ran while disabled"))
    stub = _SearchStub(tidal)
    apple.id, apple.name = "apple", "Apple Music"
    stub.providers["apple"] = apple
    stub.settings = SimpleNamespace(data=SimpleNamespace(apple_enabled=False))
    stub._logged_in = False

    stub.search("aphex twin")

    assert tidal.calls == [] and apple.calls == []
    assert stub.statuses == ["Sign in to search"]
    assert stub.searchResults.emits == []
    assert stub.busy == []


def test_an_apple_only_page_never_serves_a_signed_in_search():
    # The enabled set is part of the cache key: a page built with no TIDAL
    # rows must not paint over a later signed-in search with the same needle.
    tidal = _provider(search={"albums": [object()], "top_hit": None})
    apple = _provider(search={"tracks": [{"id": "apple:song-1", "title": "Xtal"}], "top_hit": None})
    stub = _SearchStub(tidal)
    apple.id, apple.name = "apple", "Apple Music"
    stub.providers["apple"] = apple
    stub.settings = SimpleNamespace(data=SimpleNamespace(apple_enabled=True))
    stub._logged_in = False

    stub.search("aphex twin")
    stub._logged_in = True
    stub.search("aphex twin")

    assert tidal.calls == [("search", "aphex twin")]
    first = stub.searchResults.emits[0]
    second = stub.searchResults.emits[-1]
    assert [s["provider"] for s in first["sources"]] == [CTX_APPLE], "TIDAL is not on an Apple-only page"
    assert first["sections"]["tracks"] == [
        {"id": "apple:song-1", "title": "Xtal", "sources": [{"provider": CTX_APPLE, "id": "apple:song-1"}]}
    ]
    assert [s["provider"] for s in second["sources"]] == [CTX_TIDAL, CTX_APPLE]
    assert [row["id"] for row in second["sections"]["albums"]] == ["al1"]


def test_an_apple_catalog_failure_is_visible_and_is_not_cached():
    tidal = _provider(search={"albums": [object()], "top_hit": None})
    apple = _provider(search=AppleCatalogUnavailable(), search_sections=_APPLE_SECTIONS)
    stub = _SearchStub(tidal)
    apple.id, apple.name = "apple", "Apple Music"
    stub.providers["apple"] = apple
    stub.settings = SimpleNamespace(data=SimpleNamespace(apple_enabled=True))

    stub.search("aphex twin")

    assert stub.statuses[-1] == "Apple's catalog format has changed. Check for a Waves update."
    assert stub._search_cache == {}
    payload = stub.searchResults.emits[-1]
    apple_source = next(s for s in payload["sources"] if s["provider"] == CTX_APPLE)
    # The honest words ride the Apple source itself, so the page cannot paint
    # "0 results" as if the catalog were empty.
    assert apple_source["state"] == "failed" and apple_source["error"] == stub.statuses[-1]


# --------------------------------------------------------------------------- #
# _open_url
# --------------------------------------------------------------------------- #
class _OpenUrlStub:
    _open_url = WavesBridge._open_url
    _absorb_search_group = WavesBridge._absorb_search_group
    _search_display_payload = WavesBridge._search_display_payload
    _paint_search_display = WavesBridge._paint_search_display
    _settle_search = WavesBridge._settle_search
    _fav_artist_dict = WavesBridge._fav_artist_dict

    def __init__(self, provider):
        self._objs_lock = Lock()
        self._objs: dict = {"artist": {}, "album": {}, "track": {}, "video": {}, "playlist": {}, "mix": {}}
        base = _stub_base({"tidal": provider})
        self.__dict__.update(base.__dict__)
        self.searchResults = _Signal()

        provider._row_builders = {"album": self._album_dict, "artist": self._fav_artist_dict}

    def _set_status(self, text):
        self.statuses.append(text)

    def _set_busy(self, on):
        self.busy.append(bool(on))

    def _remember(self, kind, key, obj):
        self._objs[kind][key] = obj

    def _album_dict(self, a):
        self._remember("album", "al1", a)
        return {"id": "al1", "title": "Pasted"}


def test_a_pasted_album_link_resolves_through_the_seam():
    album = Album.__new__(Album)
    provider = _provider(open_url=album)
    stub = _OpenUrlStub(provider)

    stub._open_url("https://tidal.com/browse/album/42?u")

    assert provider.calls == [("open_url", "https://tidal.com/browse/album/42?u")]
    (payload,) = stub.searchResults.emits
    assert payload["sources"] == [{"provider": "tidal", "state": "ready", "error": ""}]
    assert payload["sections"]["albums"] == [
        {"id": "al1", "title": "Pasted", "sources": [{"provider": "tidal", "id": "al1"}]}
    ]
    assert stub.statuses[-1] == "Opened link"
    assert stub._objs["album"]["al1"] is album  # remembered, as ever


def test_a_link_the_provider_cannot_resolve_reports_failure():
    # None covers every "cannot show this" case: not this provider's grammar,
    # a gone item, a failed lookup.
    provider = _provider(open_url=None)
    stub = _OpenUrlStub(provider)

    stub._open_url("https://tidal.com/browse/album/gone")

    assert stub.statuses[-1] == "Could not open that link"
    assert stub.busy == [True, False]
    assert stub.searchResults.emits == []


@pytest.mark.qml
def test_link_failure_is_redacted_and_success_resolves_its_event():
    import json

    from PySide6.QtCore import QCoreApplication

    from waves.desktop.diagnostics.events import ApplicationEvents

    app = QCoreApplication.instance() or QCoreApplication([])
    provider = _provider(open_url=RuntimeError("Authorization: Basic dXNlcjpwYXNz /Users/private/link.json"))
    stub = _OpenUrlStub(provider)
    stub._events = ApplicationEvents()
    seen = []
    stub._events.changed.connect(seen.append)
    stub._open_url("https://tidal.com/browse/album/42")
    app.processEvents()
    failure = seen[-1]
    assert failure["domain"] == "search"
    assert failure["scope"] == "unknown"
    assert "dXNlcjpwYXNz" not in json.dumps(seen)
    assert "link.json" not in json.dumps(seen)
    assert "RuntimeError" not in failure["summary"]
    assert "RuntimeError" in failure["diagnostics"]
    provider._answers["open_url"] = Album.__new__(Album)
    stub._open_url("https://tidal.com/browse/album/42")
    app.processEvents()
    assert stub.statuses[-1] == "Opened link"
    assert seen[-1]["id"] == failure["id"]
    assert seen[-1]["lifecycle"] == "resolved"
    assert stub._events.action(failure["id"], "open_logs") is None


def test_a_pasted_artist_link_lands_in_the_artists_bucket():
    artist = Artist.__new__(Artist)
    artist.id = "99"
    artist.name = "Aphex Twin"
    provider = _provider(open_url=artist)
    stub = _OpenUrlStub(provider)

    stub._open_url("https://tidal.com/browse/artist/99")

    (payload,) = stub.searchResults.emits
    assert payload["sections"]["artists"] == [
        {
            "id": "99",
            "name": "Aphex Twin",
            "art": "",
            "roles": "Artist",
            "popularity": -1,
            "sources": [{"provider": "tidal", "id": "99"}],
        }
    ]
    assert stub._objs["artist"]["99"] is artist


# --------------------------------------------------------------------------- #
# _get_artist (the artist page's id resolution)
# --------------------------------------------------------------------------- #
class _GetArtistStub:
    _get_artist = WavesBridge._get_artist

    def __init__(self, provider, artist=None):
        self._objs_lock = Lock()
        self._objs = {"artist": {}}
        base = _stub_base({"tidal": provider})
        self.__dict__.update(base.__dict__)
        self._remembered: list = []
        if artist is not None:
            self._objs["artist"]["a1"] = artist

    def _remember(self, kind, key, obj):
        self._remembered.append((kind, key, obj))


def test_an_artist_page_miss_resolves_through_the_seam():
    artist = Artist.__new__(Artist)
    provider = _provider(get_object=artist)
    stub = _GetArtistStub(provider)

    assert stub._get_artist("a1") is artist
    assert provider.calls == [("get_object", "artist", "a1")]
    assert stub._remembered == [("artist", "a1", artist)]


def test_an_artist_page_hit_never_reaches_the_provider():
    artist = Artist.__new__(Artist)
    provider = _provider()
    stub = _GetArtistStub(provider, artist=artist)

    assert stub._get_artist("a1") is artist
    assert provider.calls == []


def test_a_failed_artist_resolution_answers_none():
    provider = _provider(get_object=RuntimeError("gone"))
    stub = _GetArtistStub(provider)

    assert stub._get_artist("a1") is None


# --------------------------------------------------------------------------- #
# the album/playlist page re-fetches
# --------------------------------------------------------------------------- #
class _AlbumTracksStub:
    _start_album_tracks_fetch = WavesBridge._start_album_tracks_fetch
    _dress_panel_rows = WavesBridge._dress_panel_rows
    _dress_library_row = WavesBridge._dress_library_row

    def __init__(self, provider):
        base = _stub_base({"tidal": provider})
        self.__dict__.update(base.__dict__)
        self._objs = {"album": {}, "track": {}}
        self._prefetch_lock = Lock()
        self._album_tracks_inflight: dict = {"9": True}
        self._album_tracks_unrecorded: set = set()
        self.albumTracksLoaded = _Signal()
        self.cached: list = []
        self.members: list = []

    def _remember(self, kind, key, obj):
        self._objs[kind][key] = obj

    def _remember_album_tracks(self, album_id, rows):
        self.cached.append(album_id)

    def _record_album_members(self, album_id, rows):
        self.members.append(album_id)


def test_an_album_tracks_miss_resolves_through_the_seam():
    album = SimpleNamespace(
        id=9, tracks=lambda: [SimpleNamespace(id="t1", name="T", duration=1, popularity=1, explicit=False)]
    )
    provider = _provider(get_object=album)
    stub = _AlbumTracksStub(provider)

    stub._start_album_tracks_fetch("9")

    assert provider.calls == [("get_object", "album", "9")]
    assert stub.albumTracksLoaded.emits == [
        ("9", [{"id": "t1", "num": 1, "title": "T", "duration": "0:01", "popularity": 1, "explicit": False}])
    ]
    assert stub.cached == ["9"]


def test_a_failed_album_refetch_emits_no_rows():
    provider = _provider(get_object=RuntimeError("gone"))
    stub = _AlbumTracksStub(provider)

    stub._start_album_tracks_fetch("9")

    assert stub.albumTracksLoaded.emits == [("9", [])]
    assert stub.cached == []


class _PlaylistTracksStub:
    loadPlaylistTracks = WavesBridge.loadPlaylistTracks
    _dress_panel_rows = WavesBridge._dress_panel_rows
    _dress_library_row = WavesBridge._dress_library_row

    def __init__(self, provider):
        base = _stub_base({"tidal": provider})
        self.__dict__.update(base.__dict__)
        self._objs = {"playlist": {}, "track": {}, "video": {}}
        self.playlistTracksLoaded = _Signal()

    def _remember(self, kind, key, obj):
        self._objs[kind][key] = obj


def test_a_playlist_tracks_miss_resolves_through_the_seam(monkeypatch):
    playlist = SimpleNamespace(id="p1")
    provider = _provider(get_object=playlist)
    stub = _PlaylistTracksStub(provider)
    monkeypatch.setattr(
        backend,
        "_all_playlist_items",
        lambda obj: ([SimpleNamespace(id="t1", name="T", artists=[], duration=5, popularity=2, explicit=False)], True),
    )

    stub.loadPlaylistTracks("p1")

    assert provider.calls == [("get_object", "playlist", "p1")]
    ((pid, rows),) = stub.playlistTracksLoaded.emits
    assert pid == "p1"
    assert rows[0]["id"] == "t1" and rows[0]["kind"] == "track"


def test_a_failed_playlist_refetch_emits_no_rows():
    provider = _provider(get_object=RuntimeError("gone"))
    stub = _PlaylistTracksStub(provider)

    stub.loadPlaylistTracks("p1")

    assert stub.playlistTracksLoaded.emits == [("p1", [])]


# --------------------------------------------------------------------------- #
# the My Tidal sweep and favorites windows
# --------------------------------------------------------------------------- #
def test_the_media_lists_sweep_reads_the_provider(monkeypatch):
    # walk=False: the listing sweep only, no folder walk (its own read).
    provider = _provider(user_collections={"playlists": [], "mixes": []})
    stub = SimpleNamespace(
        tidal=SimpleNamespace(session=_GuardSession()),
        providers={"tidal": provider},
        _media_lists_lock=Lock(),
        _media_lists_cache={},
        _MEDIA_LISTS_TTL=60.0,
        _folder_tree={},
    )

    fresh, tree = WavesBridge._media_lists(stub, "tidal", refresh=True, walk=False)

    assert provider.calls == [("user_collections",)]
    assert fresh == {"playlists": [], "mixes": []}
    assert tree is None
    assert stub._media_lists_cache["tidal"][1] is fresh  # cached, as ever


def test_a_fresh_sweep_within_the_ttl_never_reaches_the_provider_twice(monkeypatch):
    import time

    provider = _provider(user_collections={"playlists": [], "mixes": []})
    stub = SimpleNamespace(
        tidal=SimpleNamespace(session=_GuardSession()),
        providers={"tidal": provider},
        _media_lists_lock=Lock(),
        _media_lists_cache={"tidal": (time.monotonic(), {"playlists": ["kept"]}, None)},
        _MEDIA_LISTS_TTL=60.0,
        _folder_tree={},
    )

    fresh, _tree = WavesBridge._media_lists(stub, "tidal", refresh=True, walk=False)

    assert fresh == {"playlists": ["kept"]}  # the TTL copy
    assert provider.calls == []


def test_the_library_favorites_window_reads_the_provider():
    # The pane's window: the source's favourites page, with the rows in the
    # SOURCE's own row vocabulary (row_for), never a bridge branch on who it
    # is. An item the provider cannot render (an empty row) is dropped.
    o1, o2 = object(), object()

    class _RowProvider(_FakeProvider):
        def row_for(self, kind, item):
            self.calls.append(("row_for", kind))
            return {"id": f"row{int(item is o2)}"}

    provider = _RowProvider(favorites_page=([o1, o2], True))
    # The source lookup and the row build are module-level helpers reading
    # ``providers`` / the provider itself, so the stub carries only those.
    stub = SimpleNamespace(providers={"tidal": provider}, _lib_sort={})

    rows, more = WavesBridge._library_page(stub, "tidal", "tracks", 0, 10, order_override=("date", "desc"))

    assert provider.calls == [
        ("favorites_page", "tracks", 0, 10, ("date", "desc")),
        ("row_for", "track"),
        ("row_for", "track"),
    ]
    assert rows == [{"id": "row0"}, {"id": "row1"}]
    assert more is True


def test_the_library_window_drops_rows_a_provider_cannot_render():
    o1, o2 = object(), object()

    class _RowProvider(_FakeProvider):
        def row_for(self, kind, item):
            return {"id": "row1"} if item is o2 else {}

    provider = _RowProvider(favorites_page=([o1, o2], False))
    stub = SimpleNamespace(providers={"tidal": provider}, _lib_sort={})

    rows, more = WavesBridge._library_page(stub, "tidal", "tracks", 0, 10)

    assert rows == [{"id": "row1"}]
    assert more is False


def test_a_source_with_no_provider_loads_nothing():
    stub = SimpleNamespace(providers={}, _lib_sort={})

    assert WavesBridge._library_page(stub, "gone", "tracks", 0, 10) == ([], False)


# --------------------------------------------------------------------------- #
# the favorite-id sets
# --------------------------------------------------------------------------- #
def test_the_favorite_id_set_reads_the_provider_and_caches():
    provider = _provider(favorite_ids={"1", "2"})
    stub = SimpleNamespace(providers={"tidal": provider}, _fav_ids={}, _FAV_IDS_TTL=600.0)

    assert WavesBridge._favorite_ids(stub, "albums") == {"1", "2"}
    assert WavesBridge._favorite_ids(stub, "albums") == {"1", "2"}
    assert provider.calls == [("favorite_ids", "albums")]  # second read: the TTL cache


def test_a_failed_favorite_id_read_serves_stale_or_the_partial_set():
    provider = _provider(favorite_ids=RuntimeError("rate limited"))
    stub = SimpleNamespace(providers={"tidal": provider}, _fav_ids={"albums": (0.0, {"old"})}, _FAV_IDS_TTL=600.0)

    assert WavesBridge._favorite_ids(stub, "albums") == {"old"}
    assert stub._fav_ids["albums"] == (0.0, {"old"})  # not re-stamped

    # With nothing cached, the partial set the provider gathered before the
    # failure is what the badges get (the old path's rule), never a blank.
    from waves.providers.base import FavoritesUnavailable

    partial = FavoritesUnavailable({"half"})
    stub = SimpleNamespace(providers={"tidal": provider}, _fav_ids={}, _FAV_IDS_TTL=600.0)
    provider._answers["favorite_ids"] = partial
    assert WavesBridge._favorite_ids(stub, "albums") == {"half"}

    # A failure that carries no partial set at all reads as empty.
    provider._answers["favorite_ids"] = RuntimeError("no ids gathered")
    empty = SimpleNamespace(providers={"tidal": provider}, _fav_ids={}, _FAV_IDS_TTL=600.0)
    assert WavesBridge._favorite_ids(empty, "albums") == set()


# --------------------------------------------------------------------------- #
# the wiring
# --------------------------------------------------------------------------- #
def test_the_bridge_builds_its_provider_map_in_init():
    # The seam lives on the instance, keyed by the provider-id constant (the
    # same key every lookup reads), built around the session wrapper it
    # delegates to (pinned at the source: constructing a real bridge here
    # would drag the whole config stack in).
    source = __import__("inspect").getsource(WavesBridge.__init__)
    assert "CTX_TIDAL: TidalProvider(self.tidal)" in source
    assert "CTX_APPLE: AppleProvider()" in source
