"""The bridge's catalog reads route through the Provider seam (ticket #20).

THE MIGRATION
-------------
Batch 1 of the call-site migration: search, pasted-link resolution, the
album/artist/playlist page re-fetches, the My Tidal sweep and favorites
windows, and the favorite-id sets read through ``self.providers`` instead of
reaching the TIDAL session/helper directly. The row-dict schema is the
contract; the payloads QML consumes are byte-identical.

HOW THIS STAYS FIXED
--------------------
Every test here drives the real bridge method on a stub whose provider is a
recording fake and whose ``tidal.session`` is a guard that fails the test on
ANY touch: a catalog read that reaches past the seam cannot pass. The canned
builder answers double as the byte-identical expectation -- the emitted
payload must equal exactly what the builders were handed to build.
"""

from __future__ import annotations

from threading import Barrier, Lock
from types import SimpleNamespace

from tidalapi.album import Album
from tidalapi.artist import Artist

from waves.providers.apple import AppleCatalogUnavailable
from waves.waves_ui import backend
from waves.waves_ui.backend import WavesBridge


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


class _FakeProvider:
    """Records the seam calls the bridge makes; answers with canned objects."""

    def __init__(self, **answers):
        self.calls: list[tuple] = []
        self._answers = answers

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


# --------------------------------------------------------------------------- #
# search
# --------------------------------------------------------------------------- #
class _SearchStub:
    search = WavesBridge.search
    _search_total = staticmethod(WavesBridge._search_total)
    _remember_search = WavesBridge._remember_search
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
        }
    )
    stub = _SearchStub(provider)

    stub.search("aphex twin")

    assert provider.calls == [("search", "aphex twin")]
    assert stub.searchResults.emits == [
        {
            "artists": [],
            "albums": [{"id": "al1", "title": "A"}],
            "tracks": [{"id": "tr1", "title": "T"}],
            "videos": [{"id": "vi1", "title": "V"}],
            "playlists": [{"id": "pl1", "title": "P"}],
            "mixes": [{"id": "mx1", "title": "M"}],
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


def test_a_failed_provider_search_degrades_to_an_empty_payload():
    # The old fetch-failure semantics, byte-identical: results = {} builds an
    # all-empty payload, the status reads 0 results, and nothing is cached
    # (an all-empty payload is more likely a failed fetch than an empty
    # catalog). A BUILD failure is the path that says "Search failed".
    provider = _provider(search=RuntimeError("network died"))
    stub = _SearchStub(provider)

    stub.search("aphex")

    assert stub.busy == [True, False]
    assert stub.statuses[-1] == "0 results"
    (payload,) = stub.searchResults.emits
    assert payload["albums"] == [] and payload["tracks"] == []
    assert stub._search_cache == {}


class _FanoutProvider(_FakeProvider):
    def __init__(self, barrier: Barrier, result: dict):
        super().__init__()
        self._barrier = barrier
        self._result = result

    def search(self, needle):
        self.calls.append(("search", needle))
        self._barrier.wait(timeout=2)
        return self._result


def test_search_fans_out_over_enabled_providers_and_emits_separate_groups():
    barrier = Barrier(2)
    tidal = _FanoutProvider(barrier, {"albums": [object()], "top_hit": None})
    apple_payload = {
        "artists": [],
        "albums": [],
        "tracks": [{"id": "apple:song-1", "title": "Xtal"}],
        "videos": [],
        "playlists": [],
        "mixes": [],
        "top": None,
    }
    apple = _FanoutProvider(barrier, apple_payload)
    stub = _SearchStub(tidal)
    stub.providers["apple"] = apple
    stub.settings = SimpleNamespace(data=SimpleNamespace(apple_enabled=True))

    stub.search("aphex twin")

    assert tidal.calls == [("search", "aphex twin")]
    assert apple.calls == [("search", "aphex twin")]
    assert stub.searchResults.emits == [
        {
            "artists": [],
            "albums": [{"id": "al1", "title": "A"}],
            "tracks": [],
            "videos": [],
            "playlists": [],
            "mixes": [],
            "top": None,
            "apple": apple_payload,
        }
    ]
    assert stub.statuses[-1] == "2 results"


def test_search_with_apple_disabled_keeps_the_tidal_payload_unchanged():
    tidal = _provider(search={"albums": [object()], "top_hit": None})
    apple = _provider(search=AssertionError("disabled Apple search ran"))
    stub = _SearchStub(tidal)
    stub.providers["apple"] = apple
    stub.settings = SimpleNamespace(data=SimpleNamespace(apple_enabled=False))

    stub.search("aphex twin")

    assert apple.calls == []
    assert stub.searchResults.emits == [
        {
            "artists": [],
            "albums": [{"id": "al1", "title": "A"}],
            "tracks": [],
            "videos": [],
            "playlists": [],
            "mixes": [],
            "top": None,
        }
    ]


def test_an_apple_catalog_failure_is_visible_and_is_not_cached():
    tidal = _provider(search={"albums": [object()], "top_hit": None})
    apple = _provider(search=AppleCatalogUnavailable())
    stub = _SearchStub(tidal)
    stub.providers["apple"] = apple
    stub.settings = SimpleNamespace(data=SimpleNamespace(apple_enabled=True))

    stub.search("aphex twin")

    assert stub.statuses[-1] == "Apple changed its web app. A Waves update is needed."
    assert stub._search_cache == {}
    assert stub.searchResults.emits[0]["apple"]["tracks"] == []


# --------------------------------------------------------------------------- #
# _open_url
# --------------------------------------------------------------------------- #
class _OpenUrlStub:
    _open_url = WavesBridge._open_url

    def __init__(self, provider):
        self._objs_lock = Lock()
        self._objs: dict = {"artist": {}, "album": {}, "track": {}, "video": {}, "playlist": {}, "mix": {}}
        base = _stub_base({"tidal": provider})
        self.__dict__.update(base.__dict__)
        self.searchResults = _Signal()

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
    assert stub.searchResults.emits == [
        {
            "artists": [],
            "albums": [{"id": "al1", "title": "Pasted"}],
            "tracks": [],
            "videos": [],
            "playlists": [],
            "mixes": [],
            "top": None,
        }
    ]
    assert stub.statuses[-1] == "Opened link"
    assert stub._objs["album"]["al1"] is album  # remembered, as ever


def test_a_link_the_provider_cannot_resolve_reports_failure():
    # None covers every "cannot show this" case: not this provider's grammar,
    # a gone item, a failed lookup.
    provider = _provider(open_url=None)
    stub = _OpenUrlStub(provider)

    stub._open_url("https://example.com/nothing")

    assert stub.statuses[-1] == "Could not open that link"
    assert stub.busy == [True, False]
    assert stub.searchResults.emits == []


def test_a_pasted_artist_link_lands_in_the_artists_bucket():
    artist = Artist.__new__(Artist)
    artist.id = "99"
    artist.name = "Aphex Twin"
    provider = _provider(open_url=artist)
    stub = _OpenUrlStub(provider)

    stub._open_url("https://tidal.com/browse/artist/99")

    (payload,) = stub.searchResults.emits
    assert payload["artists"] == [{"id": "99", "name": "Aphex Twin", "art": "", "roles": "Artist", "popularity": -1}]
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
        _media_lists_cache=None,
        _MEDIA_LISTS_TTL=60.0,
        _folder_tree=None,
    )

    fresh, tree = WavesBridge._media_lists(stub, refresh=True, walk=False)

    assert provider.calls == [("user_collections",)]
    assert fresh == {"playlists": [], "mixes": []}
    assert tree is None
    assert stub._media_lists_cache[1] is fresh  # cached, as ever


def test_a_fresh_sweep_within_the_ttl_never_reaches_the_provider_twice(monkeypatch):
    import time

    provider = _provider(user_collections={"playlists": [], "mixes": []})
    stub = SimpleNamespace(
        tidal=SimpleNamespace(session=_GuardSession()),
        providers={"tidal": provider},
        _media_lists_lock=Lock(),
        _media_lists_cache=(time.monotonic(), {"playlists": ["kept"]}, None),
        _MEDIA_LISTS_TTL=60.0,
        _folder_tree=None,
    )

    fresh, _tree = WavesBridge._media_lists(stub, refresh=True, walk=False)

    assert fresh == {"playlists": ["kept"]}  # the TTL copy
    assert provider.calls == []


def test_the_library_favorites_window_reads_the_provider():
    o1, o2 = object(), object()
    provider = _provider(favorites_page=([o1, o2], True))
    stub = SimpleNamespace(
        providers={"tidal": provider},
        _lib_sort={},
        _track_dict=lambda o: {"id": f"row{int(o is o2)}"},
        _album_dict=lambda o: {},
        _fav_artist_dict=lambda o: {},
        _video_dict=lambda o: {},
    )

    rows, more = WavesBridge._library_page(stub, "tracks", 0, 10, order_override=("date", "desc"))

    assert provider.calls == [("favorites_page", "tracks", 0, 10, ("date", "desc"))]
    assert rows == [{"id": "row0"}, {"id": "row1"}]
    assert more is True


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
