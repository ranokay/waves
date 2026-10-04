"""Third-provider catalog routes and GUI results honor their provider epoch."""

from __future__ import annotations

from threading import Event, Thread

import pytest
from browse.fakes import browse_bridge
from conftest import _Signal
from providers.fakes import BareProvider

from waves.desktop.backend import WavesBridge
from waves.desktop.providers.lifecycle import ProviderContexts, clear_provider_caches
from waves.providers import Capability, ProviderDescriptor


class _DeferredPool:
    def __init__(self):
        self.workers = []

    def start(self, worker, priority=0):
        self.workers.append(worker)

    def run_next(self):
        self.workers.pop(0).fn()

    def run_all(self):
        while self.workers:
            self.run_next()


class _PaperProvider(BareProvider):
    id = "paper"
    name = "Paper Music"
    capabilities = frozenset({Capability.CATALOG, Capability.SEARCH, Capability.OPEN_URL, Capability.PREVIEW})
    public_operations = capabilities

    def __init__(self):
        self.enabled = True
        self.calls = []
        self.revision = 1
        self.before_collection = None

    @classmethod
    def descriptor(cls):
        return ProviderDescriptor(id=cls.id, name=cls.name, link_hosts=(f"{cls.id}.test",))

    @property
    def is_logged_in(self):
        return False

    def get_object(self, kind, raw_id):
        self.calls.append(("get_object", kind, raw_id))
        assert ":" not in raw_id, "the provider receives its own raw ID"
        return {"kind": kind, "id": raw_id, "revision": self.revision}

    def row_for(self, kind, item):
        return {
            "id": f"{self.id}:{item['id']}",
            "title": f"{self.name} revision {item['revision']}",
            "name": self.name,
            "artist": "Artist",
            "artist_id": f"{self.id}:artist-1",
            "album_id": f"{self.id}:album-1",
            "art": "",
            "duration": "3:00",
            "duration_sec": 180,
            "num": 1,
            "popularity": -1,
            "explicit": False,
        }

    def collection_items(self, item, include_videos=True):
        self.calls.append(("collection_items", item["kind"], item["id"]))
        if self.before_collection is not None:
            self.before_collection()
        return [{"kind": "track", "id": "track-1", "revision": item["revision"]}]

    def artist_page(self, artist):
        self.calls.append(("artist_page", artist["id"]))
        return {
            "name": self.name,
            "albums": [self.row_for("album", {**artist, "id": "album-1"})],
            "tracks": [self.row_for("track", {**artist, "id": "track-1"})],
        }

    def preview_url(self, track):
        self.calls.append(("preview_url", track["id"]))
        return f"https://{self.id}.test/clip/{track['id']}/{track['revision']}"

    def search(self, needle):
        self.calls.append(("search", needle))
        return {"albums": [self.row_for("album", {"id": "album-1", "revision": self.revision})]}

    def open_url(self, url):
        self.calls.append(("open_url", url))
        return {"kind": "album", "item": {"id": "album-1", "revision": self.revision}}


class _LinenProvider(_PaperProvider):
    id = "linen"
    name = "Linen Music"


class _TidalGuard(BareProvider):
    """A closed TIDAL seam while the real third-provider ID is exercised."""

    id = "tidal"
    name = "TIDAL"
    capabilities = _PaperProvider.capabilities

    def __init__(self):
        self.calls = []

    @property
    def is_logged_in(self):
        return False

    def get_object(self, kind, raw_id):
        self.calls.append(("get_object", kind, raw_id))
        raise AssertionError("a third-provider object was requested from TIDAL")

    def search(self, needle):
        self.calls.append(("search", needle))
        raise AssertionError("signed-out TIDAL must not join the public catalog search")

    def open_url(self, url):
        self.calls.append(("open_url", url))
        raise AssertionError("a third-provider link was requested from TIDAL")


@pytest.fixture
def bridge():
    bridge = browse_bridge(None, "album")
    paper = _PaperProvider()
    bridge.providers = {"tidal": _TidalGuard(), "paper": paper}
    bridge._logged_in = False
    bridge._provider_contexts = ProviderContexts()
    bridge._provider_readiness_probes = {"paper": lambda: paper.readiness(enabled=paper.enabled, signed_in=False)}
    bridge._provider_search_gates = {"tidal": lambda: False}
    bridge.threadpool = _DeferredPool()
    bridge._catalogEvent = _Signal()
    bridge._searchEvent = _Signal()
    for signal in (
        "albumTracksLoaded",
        "playlistTracksLoaded",
        "artistLoaded",
        "artistLoadFailed",
        "previewState",
        "previewMeta",
        "previewReady",
        "searchResults",
        "artistMetaLoaded",
        "busyChanged",
        "statusChanged",
    ):
        setattr(bridge, signal, _Signal())
    bridge._busy = False
    bridge._status = ""
    bridge._set_busy = WavesBridge._set_busy.__get__(bridge)
    bridge._set_status = WavesBridge._set_status.__get__(bridge)
    bridge._album_tracks_cache = {}
    bridge._album_tracks_inflight = {}
    bridge._album_tracks_unrecorded = set()
    bridge._artist_cache = {}
    bridge._artist_reval_ts = {}
    bridge._artist_loading = set()
    bridge._artist_prefetch = None
    bridge._artist_prefetch_claimed = False
    bridge._artist_pop_cache = {}
    bridge._search_cache = {}
    bridge._search_gen = 0
    bridge._active_search_providers = set()
    bridge._dedup_albums = lambda rows: list(rows)
    bridge._dedup_tracks = lambda rows: list(rows)
    bridge._dedup_videos = lambda rows: list(rows)
    # Library verdicts have independent behavioral tests. Keep these rows
    # unchanged so routing and epoch assertions inspect the provider output.
    bridge._dress_panel_rows = lambda rows: rows
    bridge._dress_cards = lambda payload: payload
    return bridge


def _drain_gui(bridge):
    """Drive the real queued receivers after an explicitly controlled delay."""
    catalog_events = list(bridge._catalogEvent.emits)
    bridge._catalogEvent.emits.clear()
    for event in catalog_events:
        bridge._on_catalog_event(event)
    search_events = list(bridge._searchEvent.emits)
    bridge._searchEvent.emits.clear()
    for event in search_events:
        bridge._on_search_event(event)


_REQUESTS = [
    ("loadAlbumTracks", ("paper:album-1",), "albumTracksLoaded"),
    ("loadPlaylistTracks", ("paper:playlist-1",), "playlistTracksLoaded"),
    ("loadArtist", ("paper:artist-1",), "artistLoaded"),
    ("openBrowseItem", ("album", "paper:album-1"), "browsePageLoaded"),
    ("openBrowseItem", ("playlist", "paper:playlist-1"), "browsePageLoaded"),
    ("previewTrack", ("paper:track-1",), "previewReady"),
    ("previewArtist", ("paper:artist-1",), "previewReady"),
    ("previewMedia", ("album", "paper:album-1"), "previewReady"),
    ("previewMedia", ("playlist", "paper:playlist-1"), "previewReady"),
]


@pytest.mark.parametrize(("method", "args", "signal"), _REQUESTS)
def test_public_signed_out_catalog_and_preview_route_to_the_third_owner(bridge, method, args, signal):
    getattr(bridge, method)(*args)
    bridge.threadpool.run_all()
    assert getattr(bridge, signal).emits == [], "worker results wait for the GUI receiver"
    _drain_gui(bridge)

    assert len(getattr(bridge, signal).emits) == 1
    assert bridge.providers["tidal"].calls == []
    assert bridge.providers["paper"].calls[0] == (
        "get_object",
        args[-1].split(":")[1].split("-")[0],
        args[-1].split(":")[1],
    )
    if signal == "previewReady":
        assert getattr(bridge, signal).emits[0] == (
            args[0] if method == "previewMedia" else method.removeprefix("preview").lower(),
            args[-1],
            "https://paper.test/clip/track-1/1",
        )
    elif signal == "artistLoaded":
        assert bridge.artistLoaded.emits[0]["id"] == "paper:artist-1"
        assert bridge._artist_cache["paper:artist-1"]["tracks"][0]["id"] == "paper:track-1"
    elif signal == "browsePageLoaded":
        assert bridge.browsePageLoaded.emits[0]["header"]["id"] == args[-1]
        assert bridge.browsePageLoaded.emits[0]["sections"][0]["items"][0]["id"] == "paper:track-1"
    else:
        ident, rows = getattr(bridge, signal).emits[0]
        assert ident == args[-1] and rows[0]["id"] == "paper:track-1"


@pytest.mark.parametrize(("method", "args", "signal"), _REQUESTS)
def test_provider_revoked_after_worker_finish_cannot_deliver_to_gui(bridge, method, args, signal):
    getattr(bridge, method)(*args)
    bridge.threadpool.run_all()
    assert bridge._catalogEvent.emits
    bridge._provider_contexts.revoke("paper")
    clear_provider_caches(bridge, "paper")
    bridge._status = "Current account"
    bridge._busy = True
    _drain_gui(bridge)

    assert getattr(bridge, signal).emits == []
    assert bridge.previewMeta.emits == []
    assert bridge._status == "Current account" and bridge._busy
    assert bridge._album_tracks_cache == {} and bridge._artist_cache == {} and bridge._browse_pages == {}
    assert bridge.providers["tidal"].calls == []


def test_public_album_hover_prefetch_is_claimed_without_tidal_signin(bridge):
    bridge.prefetchAlbumTracks("paper:album-1")
    assert bridge._album_tracks_inflight == {"paper:album-1": False}
    bridge.loadAlbumTracks("paper:album-1")
    assert len(bridge.threadpool.workers) == 1
    bridge.threadpool.run_all()
    _drain_gui(bridge)
    assert bridge.albumTracksLoaded.emits[0][0] == "paper:album-1"
    assert bridge.providers["tidal"].calls == []


def test_old_album_fetch_cannot_consume_same_id_reopened_after_revocation(bridge):
    paper = bridge.providers["paper"]
    entered = Event()
    release = Event()
    errors = []

    def hold_old_collection():
        entered.set()
        if not release.wait(2):
            raise RuntimeError("the old collection fetch was never released")

    paper.before_collection = hold_old_collection
    bridge.loadAlbumTracks("paper:album-1")
    old = bridge.threadpool.workers.pop(0)

    def run_old():
        try:
            old.fn()
        except Exception as exc:
            errors.append(exc)

    worker = Thread(target=run_old)
    worker.start()
    try:
        assert entered.wait(2)
        bridge._provider_contexts.revoke("paper")
        clear_provider_caches(bridge, "paper")
        paper.revision = 2
        paper.before_collection = None
        bridge.loadAlbumTracks("paper:album-1")
    finally:
        release.set()
        worker.join(2)
    assert not worker.is_alive() and not errors
    assert bridge._album_tracks_inflight == {"paper:album-1": True}
    assert bridge._album_tracks_cache == {} and bridge.recorded == []
    bridge.threadpool.run_all()
    _drain_gui(bridge)
    assert bridge.albumTracksLoaded.emits[0][1][0]["title"] == "Paper Music revision 2"
    assert bridge._album_tracks_inflight == {}
    assert bridge.providers["tidal"].calls == []


@pytest.mark.parametrize(("method", "args"), [("search", ("one",)), ("_open_url", ("https://paper.test/album/1",))])
def test_public_search_and_link_use_owned_rows_and_drop_revoked_gui_result(bridge, method, args):
    getattr(bridge, method)(*args)
    bridge.threadpool.run_all()
    assert bridge._searchEvent.emits and not bridge.searchResults.emits
    bridge._provider_contexts.revoke("paper")
    _drain_gui(bridge)
    assert not bridge.searchResults.emits and not bridge._search_cache
    assert bridge.providers["tidal"].calls == []

    getattr(bridge, method)(*args)
    bridge.threadpool.run_all()
    _drain_gui(bridge)
    assert bridge.searchResults.emits[0]["groups"][0]["provider"] == "paper"
    assert bridge.searchResults.emits[0]["groups"][0]["albums"][0]["id"] == "paper:album-1"
    assert bridge.providers["tidal"].calls == []


def test_mixed_search_gui_delivery_keeps_live_provider_and_never_caches_partial_result(bridge):
    linen = _LinenProvider()
    bridge.providers[linen.id] = linen
    bridge._provider_readiness_probes[linen.id] = lambda: linen.readiness(enabled=True, signed_in=False)
    bridge.search("one")
    bridge.threadpool.run_all()
    bridge._provider_contexts.revoke("paper")
    _drain_gui(bridge)
    assert [group["provider"] for group in bridge.searchResults.emits[0]["groups"]] == ["linen"]
    assert bridge._search_cache == {}
    assert bridge._status == "1 results" and not bridge._busy
    assert bridge.providers["tidal"].calls == []


@pytest.mark.parametrize(("method", "args", "signal"), _REQUESTS)
def test_disabled_provider_catalog_and_preview_do_not_call_the_service(bridge, method, args, signal):
    bridge.providers["paper"].enabled = False
    getattr(bridge, method)(*args)
    bridge.threadpool.run_all()
    _drain_gui(bridge)
    assert bridge.providers["paper"].calls == []
    assert getattr(bridge, signal).emits == []
    assert bridge.providers["tidal"].calls == []


def test_cached_browse_root_is_checked_again_when_the_gui_receives_it(bridge):
    bridge._logged_in = True
    cached = {"title": "Previous account", "sections": []}
    bridge._browse_root_cache = cached
    bridge._start_tile_art = lambda *args: None
    bridge._load_browse_root(emit_cached=True)
    bridge.threadpool.run_next()
    assert not bridge.browseLoaded.emits
    assert bridge._catalogEvent.emits
    bridge._provider_contexts.revoke("tidal")
    clear_provider_caches(bridge, "tidal")
    current = {"title": "Current account", "sections": []}
    bridge._browse_root_cache = current
    _drain_gui(bridge)
    assert not bridge.browseLoaded.emits
    assert bridge._browse_root_cache is current


def test_favorite_count_from_an_old_account_cannot_consume_a_new_action(bridge):
    paper = bridge.providers["paper"]
    paper.capabilities |= {Capability.FAVORITES}
    bridge._provider_readiness_probes["paper"] = lambda: paper.readiness(enabled=True, signed_in=True)
    bridge.favoriteTracksResolved = _Signal()
    gid = "fav:paper:tracks"
    WavesBridge._resolve_favorite_count(bridge, "paper", "tracks", gid, bridge.favoriteTracksResolved, lambda: 42)
    bridge.threadpool.run_next()
    assert not bridge.favoriteTracksResolved.emits
    bridge._provider_contexts.revoke("paper")
    clear_provider_caches(bridge, "paper")
    WavesBridge._resolve_favorite_count(bridge, "paper", "tracks", gid, bridge.favoriteTracksResolved, lambda: 7)
    _drain_gui(bridge)
    assert not bridge.favoriteTracksResolved.emits
    bridge.threadpool.run_all()
    _drain_gui(bridge)
    assert bridge.favoriteTracksResolved.emits == [("paper", 7)]
    assert bridge.providers["tidal"].calls == []


def test_revoked_apple_retry_cannot_release_the_next_accounts_same_item(bridge):
    from waves.desktop.backend import _AppleDownloads
    from waves.desktop.queue.bridge import QueueMixin

    apple = _PaperProvider()
    bridge.providers["apple"] = apple
    bridge._refetch_inflight = set()
    bridge._retry_refetch_tokens = {}
    bridge._queueRetryRefetched = _Signal()
    retried = []
    bridge.retryQueueItem = retried.append
    entered, release = Event(), Event()

    def hold_old(kind, raw_id):
        entered.set()
        assert release.wait(2)
        return {"id": raw_id}

    apple.get_object = hold_old
    adapter = _AppleDownloads(bridge)
    adapter.refetch_retry({"type": "track", "media_id": "apple:track-1", "qid": 3})
    old_token = bridge._provider_contexts.capture("apple")
    old = Thread(target=bridge.threadpool.workers.pop(0).fn)
    old.start()
    key = ("track", "apple:track-1")
    try:
        assert entered.wait(2)
        bridge._provider_contexts.revoke("apple")
        QueueMixin._clear_retry_refetches(bridge, "apple")
        clear_provider_caches(bridge, "apple")
        apple.get_object = lambda kind, raw_id: {"id": raw_id}
        adapter.refetch_retry({"type": "track", "media_id": "apple:track-1", "qid": 4})
    finally:
        release.set()
        old.join(2)
    assert not old.is_alive()
    new_owner = bridge._retry_refetch_tokens[key]
    assert new_owner[1] == 4 and key in bridge._refetch_inflight
    assert not bridge._queueRetryRefetched.emits
    bridge.threadpool.run_all()
    QueueMixin._on_queue_retry_refetched(bridge, "track", "apple:track-1", 3, old_token)
    assert bridge._retry_refetch_tokens[key] == new_owner and not retried
    QueueMixin._on_queue_retry_refetched(bridge, *bridge._queueRetryRefetched.emits[0])
    assert retried == [4] and key not in bridge._refetch_inflight


def test_parked_third_provider_artist_refresh_is_quiet_change_only_and_throttled(bridge):
    import time

    bridge.loadArtist("paper:artist-1")
    bridge.threadpool.run_all()
    _drain_gui(bridge)
    bridge.artistLoaded.emits.clear()
    bridge.statusChanged.emits.clear()
    bridge.busyChanged.emits.clear()
    bridge.refreshArtist("paper:artist-1")
    assert not bridge.threadpool.workers
    bridge._artist_reval_ts["paper:artist-1"] = time.monotonic() - 61
    bridge.refreshArtist("paper:artist-1")
    bridge.threadpool.run_all()
    _drain_gui(bridge)
    assert not bridge.artistLoaded.emits
    bridge.providers["paper"].revision = 2
    bridge._artist_reval_ts["paper:artist-1"] = time.monotonic() - 61
    bridge.refreshArtist("paper:artist-1")
    bridge.threadpool.run_all()
    _drain_gui(bridge)
    assert bridge.artistLoaded.emits[0]["refresh"]
    assert "revision 2" in bridge.artistLoaded.emits[0]["albums"][0]["title"]
    assert not bridge.statusChanged.emits and not bridge.busyChanged.emits
    assert bridge.providers["tidal"].calls == []


def test_signed_out_tidal_artist_entry_cannot_paint_a_cached_account_page(bridge):
    bridge._artist_cache["old-artist"] = {"id": "old-artist", "name": "Old account"}
    bridge.loadArtist("old-artist")
    assert not bridge.artistLoaded.emits and not bridge.threadpool.workers
    assert not bridge.providers["tidal"].calls


def test_old_artist_build_cannot_release_a_new_accounts_hover_claim(bridge):
    paper = bridge.providers["paper"]
    original = paper.artist_page
    entered, release = Event(), Event()

    def hold_old(artist):
        entered.set()
        assert release.wait(2)
        return original(artist)

    paper.artist_page = hold_old
    bridge.prefetchArtist("paper:artist-1")
    old = Thread(target=bridge.threadpool.workers.pop(0).fn)
    old.start()
    try:
        assert entered.wait(2)
        bridge._provider_contexts.revoke("paper")
        clear_provider_caches(bridge, "paper")
        paper.artist_page = original
        bridge.prefetchArtist("paper:artist-1")
        bridge.loadArtist("paper:artist-1")
    finally:
        release.set()
        old.join(2)
    assert not old.is_alive()
    assert bridge._artist_prefetch == "paper:artist-1" and bridge._artist_prefetch_claimed
    assert bridge._artist_loading == {"paper:artist-1"}
    bridge.threadpool.run_all()
    _drain_gui(bridge)
    assert len(bridge.artistLoaded.emits) == 1
    assert not bridge._artist_loading and bridge._artist_prefetch is None


def test_artist_cleanup_does_not_block_a_catalog_commit_behind_the_prefetch_lock(bridge):
    from waves.desktop.backend import _cache_put, _catalog_work, _release_artist_build

    attempted, committed = Event(), Event()
    lock = bridge._prefetch_lock

    class ObservedLock:
        def __enter__(self):
            attempted.set()
            lock.acquire()

        def __exit__(self, *_args):
            lock.release()

    bridge._prefetch_lock = ObservedLock()
    artist_work = _catalog_work(bridge, "paper", lambda: _release_artist_build(bridge, "paper:artist-1", silent=True))

    def finish_album():
        _cache_put(bridge, bridge._album_tracks_cache, "album-1", [])
        committed.set()

    album_work = _catalog_work(bridge, "tidal", finish_album)
    artist, album = Thread(target=artist_work), Thread(target=album_work)
    # An album/browse completion already holds the shared prefetch lock.
    lock.acquire()
    try:
        artist.start()
        assert attempted.wait(2)
        album.start()
        assert committed.wait(2), "artist cleanup must not hold epoch authority while waiting for prefetch"
    finally:
        lock.release()
        artist.join(2)
        if album.ident is not None:
            album.join(2)
    assert not artist.is_alive() and not album.is_alive()
    assert bridge._album_tracks_cache["album-1"] == []
