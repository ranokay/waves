"""Busy-latch discipline in the browse/search workers, and sign-out fences.

* loadArtist, search, _open_url and loadArtistLibrary must build their result
  payloads INSIDE the try: the dict builders can choke on a partial tidalapi
  object (the code's own _top_hit_dict guard concedes as much), Worker.run only
  logs an escape, and nothing else clears busy or the status line. loadArtist
  is worst: an artist id left in _artist_loading makes the dedup guard silently
  refuse every later click on that artist for the whole session.

* logout must supersede the in-flight fetch workers. A search still running
  when the user signs out would emit after "Signed out" and refill the caches
  logout just cleared with objects bound to the dead session; the album-tracks
  and playlist-tracks workers need their own generation guard.
"""

from __future__ import annotations

from threading import Lock
from types import SimpleNamespace

from providers.fakes import StubProvider
from support.bridge_stub import BridgeStub

from waves.desktop import backend
from waves.desktop.backend import WavesBridge
from waves.desktop.providers.lifecycle import provider_contexts
from waves.providers import Capability, ProviderDescriptor


class _Signal:
    def __init__(self):
        self.emits: list = []

    def emit(self, *args):
        self.emits.append(args)


class _InlinePool:
    @staticmethod
    def start(worker, priority: int = 0):
        worker.fn()


class _StubBase(BridgeStub):
    """The attributes every slot under test shares."""

    def __init__(self):
        self._logged_in = True
        self.providers = {
            "tidal": StubProvider(
                "tidal", "TIDAL", capabilities={Capability.CATALOG, Capability.FAVORITES}, logged_in=True
            )
        }
        self.threadpool = _InlinePool()
        self.statuses: list[str] = []
        self.busy: list[bool] = []
        self._browse_gen = 0
        self._search_gen = 0

    def _set_status(self, text):
        self.statuses.append(text)

    def _set_busy(self, on):
        self.busy.append(bool(on))


class _Artist:
    name = "Art"

    def get_bio(self):
        return ""

    def get_albums(self):
        return []

    def get_ep_singles(self):
        return []

    def get_top_tracks(self, limit=10):
        return [SimpleNamespace(id="t1")]

    def get_videos(self, limit=None):
        return []


# --------------------------------------------------------------------------- #
# loadArtist: a choking builder must not strand the artist or latch busy
# --------------------------------------------------------------------------- #
class _LoadArtistStub(_StubBase):
    loadArtist = WavesBridge.loadArtist
    _start_artist_build = WavesBridge._start_artist_build

    _artist_art_summary = staticmethod(WavesBridge._artist_art_summary)

    def __init__(self, artist):
        super().__init__()
        self._artist = artist
        self._artist_cache: dict = {}
        self._artist_loading: set = set()
        self._artist_prefetch = None
        self._artist_prefetch_claimed = False
        self._prefetch_lock = Lock()
        self.artistLoaded = _Signal()
        self.artistLoadFailed = _Signal()
        self.artistPagePrefetched = _Signal()

    def _get_artist(self, artist_id):
        return self._artist

    def _dedup_albums(self, albums):
        return albums

    def _artist_page_collapses_editions(self):
        return False

    def _dedup_tracks(self, tracks):
        return tracks

    def _dedup_videos(self, videos):
        return videos

    def _album_dict(self, a):
        return {"id": a.id}

    def _track_dict(self, t):
        raise RuntimeError("partial payload: the builder chokes")


def test_a_choking_builder_never_strands_the_artist():
    stub = _LoadArtistStub(_Artist())

    stub.loadArtist("a1")

    # The failure is REPORTED (status, busy released, QML told), and the
    # dedup set is released so the next click on this artist tries again.
    assert stub._artist_loading == set()
    assert stub.busy == [True, False]
    assert stub.statuses[-1] == "Could not load artist"
    assert stub.artistLoadFailed.emits == [("a1",)]
    assert stub.artistLoaded.emits == []

    # And the retry is actually accepted, not refused by a stale entry.
    stub.loadArtist("a1")
    assert stub.busy == [True, False, True, False]


def test_an_unresolvable_artist_still_reports_failure():
    stub = _LoadArtistStub(_Artist())
    stub._get_artist = lambda artist_id: None

    stub.loadArtist("a1")

    assert stub._artist_loading == set()
    assert stub.busy == [True, False]
    assert stub.statuses[-1] == "Could not load artist"
    assert stub.artistLoadFailed.emits == [("a1",)]


# --------------------------------------------------------------------------- #
# search: a choking builder fails THIS search visibly
# --------------------------------------------------------------------------- #
class _SearchStub(_StubBase):
    search = WavesBridge.search
    dropSearchSource = WavesBridge.dropSearchSource
    _absorb_search_group = WavesBridge._absorb_search_group
    _search_display_payload = WavesBridge._search_display_payload
    _paint_search_display = WavesBridge._paint_search_display
    _settle_search = WavesBridge._settle_search
    _show_search_display = WavesBridge._show_search_display
    _enrich_search_artists = WavesBridge._enrich_search_artists
    _search_total = staticmethod(WavesBridge._search_total)
    _search_artist_meters = staticmethod(WavesBridge._search_artist_meters)

    def __init__(self):
        super().__init__()
        self._logged_in = True
        self._search_cache: dict = {}
        self._objs_lock = Lock()
        self._objs: dict = {"artist": {}, "album": {}, "track": {}, "video": {}, "playlist": {}, "mix": {}}
        self.tidal = SimpleNamespace(session=object())
        self.searchResults = _Signal()
        self.artistMetaLoaded = _Signal()
        self._provider_search_gates = {"tidal": lambda: bool(self._logged_in)}

    def _remember(self, kind, key, obj):
        self._objs[kind][key] = obj

    def _dedup_albums(self, albums):
        return list(albums)

    def _dedup_tracks(self, tracks):
        return list(tracks)

    def _dedup_videos(self, videos):
        return list(videos)

    def _album_dict(self, a):
        raise RuntimeError("partial payload: the builder chokes")


def test_a_choking_search_build_clears_busy_and_says_so(monkeypatch):
    stub = _SearchStub()
    stub.providers = {
        "tidal": SimpleNamespace(
            capabilities=frozenset({Capability.SEARCH}), search=lambda needle: {"albums": [SimpleNamespace(id="x")]}
        )
    }

    stub.search("aphex")

    assert stub.busy == [True, False]
    assert stub.statuses[-1] == "Search results could not be displayed. Try again or open the logs."
    (payload,) = stub.searchResults.emits[0]
    assert payload["sources"][0]["state"] == "failed"
    assert payload["sources"][0]["error"] == stub.statuses[-1]
    assert stub._search_cache == {}


# --------------------------------------------------------------------------- #
# _open_url: same discipline for the pasted-link resolver
# --------------------------------------------------------------------------- #
class _OpenUrlStub(_StubBase):
    _open_url = WavesBridge._open_url

    def __init__(self):
        super().__init__()
        self._objs: dict = {"artist": {}, "album": {}}
        self._objs_lock = Lock()
        self.tidal = SimpleNamespace(session=object())
        self.searchResults = _Signal()

    def _album_dict(self, a):
        raise RuntimeError("partial payload: the builder chokes")


def test_a_choking_link_payload_clears_busy(monkeypatch):
    stub = _OpenUrlStub()
    # The seam resolves the link to the engine object it names (an album, so
    # the payload lands in the albums bucket); the builder then chokes.
    from tidalapi.album import Album

    provider = stub.providers["tidal"]
    provider.capabilities |= {Capability.OPEN_URL}
    provider.open_url = lambda url: {"kind": "album", "item": Album.__new__(Album)}
    provider.row_for = lambda kind, item: stub._album_dict(item)
    provider.descriptor = lambda: ProviderDescriptor(id="tidal", name="TIDAL", link_hosts=("tidal.com",))

    stub._open_url("https://tidal.com/album/42")

    assert stub.busy == [True, False]
    assert stub.statuses[-1] == "Could not open that link"
    assert stub.searchResults.emits == []


# --------------------------------------------------------------------------- #
# loadArtistLibrary: same discipline for the library-scoped page
# --------------------------------------------------------------------------- #
class _LibraryArtistStub(_StubBase):
    loadArtistLibrary = WavesBridge.loadArtistLibrary

    def __init__(self):
        super().__init__()
        self.artistLoaded = _Signal()
        self.artistLoadFailed = _Signal()

    def _get_artist(self, artist_id):
        artist = _Artist()
        artist.get_albums = lambda: [SimpleNamespace(id="al1")]
        return artist

    def _favorite_ids(self, kind):
        return {"al1"}

    def _dedup_albums(self, albums):
        return list(albums)

    def _dedup_tracks(self, tracks):
        return list(tracks)

    def _album_dict(self, a):
        raise RuntimeError("partial payload: the builder chokes")


def test_a_choking_library_page_clears_busy():
    stub = _LibraryArtistStub()

    stub.loadArtistLibrary("a1")

    assert stub.busy == [True, False]
    assert stub.statuses[-1] == "Could not load artist"
    assert stub.artistLoaded.emits == []
    # A Back onto the scoped page waits on artistLoaded to clear its history
    # latch; a silent failure left navPush dead until logout. Both failure
    # exits now tell the QML.
    assert stub.artistLoadFailed.emits == [("a1",)]


def test_an_unresolvable_library_artist_still_reports_failure():
    stub = _LibraryArtistStub()
    stub._get_artist = lambda artist_id: None

    stub.loadArtistLibrary("a1")

    assert stub.busy == [True, False]
    assert stub.statuses[-1] == "Could not load artist"
    assert stub.artistLoadFailed.emits == [("a1",)]


# --------------------------------------------------------------------------- #
# Sign-out fences
# --------------------------------------------------------------------------- #
def test_logout_supersedes_every_inflight_search():
    bridge = _SearchStub()
    provider = StubProvider("tidal", "TIDAL", capabilities={Capability.SEARCH}, logged_in=True)
    provider.search = lambda needle: {"albums": [SimpleNamespace(id="42")]}
    bridge.providers = {"tidal": provider}
    bridge._album_dict = lambda album: {"id": album.id}
    bridge._top_hit_dict = lambda hit: None
    bridge._searchEvent = _Signal()
    bridge._SEARCH_CACHE_MAX = WavesBridge._SEARCH_CACHE_MAX
    bridge._remember_search = WavesBridge._remember_search.__get__(bridge)
    bridge._save_page_cache = lambda: None
    bridge._absorb_search_group = WavesBridge._absorb_search_group.__get__(bridge)
    bridge._search_display_payload = WavesBridge._search_display_payload.__get__(bridge)
    bridge._paint_search_display = WavesBridge._paint_search_display.__get__(bridge)
    bridge._settle_search = WavesBridge._settle_search.__get__(bridge)
    bridge._show_search_display = WavesBridge._show_search_display.__get__(bridge)
    bridge.logout = WavesBridge.logout.__get__(bridge)
    bridge._end_provider_context = WavesBridge._end_provider_context.__get__(bridge)
    bridge._stop_provider_downloads = lambda provider_id, reason: 0
    bridge._schedule_provider_cache_clear = lambda provider_id: None
    bridge._start_provider_logout = lambda provider_id: None
    bridge._set_login_busy = lambda provider_id, busy: None
    bridge._set_logged_in = lambda value: setattr(bridge, "_logged_in", value)
    bridge.providerStateChanged = _Signal()

    # First prove this result can paint and populate the actual search cache.
    bridge.search("first")
    first = bridge._searchEvent.emits.pop()[0]
    WavesBridge._on_search_event(bridge, first)
    assert bridge.searchResults.emits[-1][0]["sections"]["albums"] == [
        {"id": "42", "sources": [{"provider": "tidal", "id": "42"}]}
    ]
    assert "tidal:first" in bridge._search_cache
    bridge.searchResults.emits.clear()

    # Hold the next completed worker result at the GUI relay across logout.
    bridge.search("second")
    late = bridge._searchEvent.emits.pop()[0]
    bridge.logout()
    WavesBridge._on_search_event(bridge, late)

    assert bridge.searchResults.emits == []
    assert bridge._search_cache == {}
    assert bridge.statuses[-1] == "Signed out"
    assert bridge.busy[-1] is False


class _AlbumTracksStub(_StubBase):
    _start_album_tracks_fetch = WavesBridge._start_album_tracks_fetch

    def __init__(self, album):
        super().__init__()
        self._objs = {"album": {"al1": album}}
        self._prefetch_lock = Lock()
        self._album_tracks_inflight: dict = {"al1": True}
        self._album_tracks_unrecorded: set = set()
        self.albumTracksLoaded = _Signal()
        self.cached: list = []
        self.members: list = []

    def _remember(self, kind, key, obj):
        pass

    def _remember_album_tracks(self, album_id, rows):
        self.cached.append(album_id)

    def _record_album_members(self, album_id, rows):
        self.members.append(album_id)


def test_album_tracks_landing_after_logout_are_dropped():
    stub_holder: list = []

    class _Album:
        def tracks(self):
            # Logout lands mid-fetch: it clears the inflight registrations.
            stub_holder[0]._album_tracks_inflight.clear()
            return [SimpleNamespace(id="t1", name="T", duration=1)]

    stub = _AlbumTracksStub(_Album())
    stub_holder.append(stub)

    stub._start_album_tracks_fetch("al1")

    # Nothing built on the dead session may be cached, recorded, or emitted.
    assert stub.cached == [] and stub.members == []
    assert stub.albumTracksLoaded.emits == []


class _PlaylistTracksStub(_StubBase):
    loadPlaylistTracks = WavesBridge.loadPlaylistTracks

    def __init__(self):
        super().__init__()
        self._objs = {"playlist": {"p1": object()}}
        self.playlistTracksLoaded = _Signal()

    def _remember(self, kind, key, obj):
        pass


def test_playlist_tracks_landing_after_logout_are_dropped(monkeypatch):
    stub = _PlaylistTracksStub()

    def fetch(obj):
        provider_contexts(stub).revoke("tidal")
        return [], True

    monkeypatch.setattr(backend, "_all_playlist_items", fetch)

    stub.loadPlaylistTracks("p1")

    assert stub.playlistTracksLoaded.emits == []
