from __future__ import annotations

from threading import Lock
from types import SimpleNamespace

from waves.providers.apple import AppleProvider
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


def _song(song_id="song-1", preview=True):
    attrs = {
        "name": "Xtal",
        "artistName": "Aphex Twin",
        "albumName": "Selected Ambient Works 85-92",
        "artwork": {"url": "https://img/song/{w}x{h}bb.jpg"},
        "releaseDate": "1992-02-12",
        "durationInMillis": 293000,
        "trackNumber": 1,
        "discNumber": 1,
        "audioTraits": ["hi-res-lossless"],
    }
    if preview:
        attrs["previews"] = [{"url": "https://audio-preview/song-1.m4a"}]
    return {
        "id": song_id,
        "type": "songs",
        "attributes": attrs,
        "relationships": {"artists": {"data": [{"id": "artist-1"}]}},
    }


def _album():
    return {
        "id": "album-1",
        "type": "albums",
        "attributes": {
            "name": "Selected Ambient Works 85-92",
            "artistName": "Aphex Twin",
            "artwork": {"url": "https://img/album/{w}x{h}bb.jpg"},
            "releaseDate": "1992-02-12",
            "trackCount": 13,
            "durationInMillis": 4455000,
            "audioTraits": ["lossless"],
        },
        "relationships": {"tracks": {"data": [_song()]}},
    }


class _Catalog:
    def __init__(self, album=None, artist=None, playlist=None, song=None):
        self._album = album
        self._artist = artist
        self._playlist = playlist
        self._song = song

    async def get_album(self, album_id):
        return {"data": [self._album]}

    async def get_artist(self, artist_id):
        return {"data": [self._artist]}

    async def get_playlist(self, playlist_id):
        return {"data": [self._playlist]}

    async def get_song(self, song_id):
        return {"data": [self._song]}


def _apple_provider(**resources):
    return AppleProvider(catalog=_Catalog(**resources))


def test_apple_link_payload_carries_the_single_row_in_the_apple_group():
    stub = SimpleNamespace(providers={"apple": _apple_provider(album=_album())})
    provider = stub.providers["apple"]
    resolved = {"kind": "album", "item": provider.get_object("album", "album-1")}

    payload = WavesBridge._apple_link_payload(stub, resolved)

    assert [row["id"] for row in payload["apple"]["albums"]] == ["apple:album-1"]
    assert payload["albums"] == [] and payload["tracks"] == []
    assert WavesBridge._apple_link_payload(stub, {"kind": "nope", "item": {}}) is None
    assert WavesBridge._apple_link_payload(stub, "not-a-dict") is None


def test_apple_album_expansion_rows_map_track_rows():
    stub = SimpleNamespace(providers={"apple": _apple_provider(album=_album())})

    rows = WavesBridge._apple_album_expansion_rows(stub, "apple:album-1")

    assert [(r["id"], r["title"], r["num"]) for r in rows] == [("apple:song-1", "Xtal", 1)]
    empty = SimpleNamespace(providers={"apple": _apple_provider()})
    assert WavesBridge._apple_album_expansion_rows(empty, "apple:gone") == []


def test_apple_playlist_expansion_rows_number_by_position():
    playlist = {
        "id": "playlist-1",
        "type": "playlists",
        "attributes": {
            "name": "Essentials",
            "curatorName": "Apple",
            "artwork": {"url": "https://img/pl/{w}x{h}bb.jpg"},
        },
        "relationships": {"tracks": {"data": [_song("song-1"), _song("song-2")]}},
    }
    stub = SimpleNamespace(providers={"apple": _apple_provider(playlist=playlist)})

    rows = WavesBridge._apple_playlist_expansion_rows(stub, "apple:playlist-1")

    assert [(r["id"], r["num"], r["kind"]) for r in rows] == [
        ("apple:song-1", 1, "track"),
        ("apple:song-2", 2, "track"),
    ]


def test_apple_browse_item_matches_the_tidal_payload_shape():
    stub = SimpleNamespace(
        providers={"apple": _apple_provider(album=_album())},
        _ownership=SimpleNamespace(record_members_replace=lambda *a: None),
        collectionMembershipChanged=_Signal(),
    )
    stub._record_page_members = lambda payload: WavesBridge._record_page_members(stub, payload)

    payload = WavesBridge._build_apple_browse_item(stub, "album", "apple:album-1", "item:album:apple:album-1")

    assert payload["title"] == "Selected Ambient Works 85-92"
    assert payload["header"]["id"] == "apple:album-1"
    assert payload["header"]["art"] == "https://img/album/320x320bb.jpg"
    assert payload["sections"][0]["items"][0]["id"] == "apple:song-1"
    assert payload["error"] is False


def test_apple_preview_track_emits_the_clip_url_directly():
    apple = _apple_provider(song=_song())
    stub = SimpleNamespace(
        providers={"apple": apple},
        threadpool=_InlinePool(),
        previewReady=_Signal(),
        previewState=_Signal(),
        previewMeta=_Signal(),
    )
    stub._emit_apple_preview_meta = lambda *a: WavesBridge._emit_apple_preview_meta(stub, *a)
    stub.previewTrack = lambda track_id: WavesBridge.previewTrack(stub, track_id)

    stub.previewTrack("apple:song-1")

    assert ("track", "apple:song-1", "loading") in stub.previewState.emits
    assert stub.previewReady.emits == [("track", "apple:song-1", "https://audio-preview/song-1.m4a")]
    kind, ident, title, _artist, *_ = stub.previewMeta.emits[0]
    assert (kind, ident, title) == ("track", "apple:song-1", "Xtal")


def test_apple_preview_track_without_a_clip_reports_error():
    apple = _apple_provider(song=_song(preview=False))
    stub = SimpleNamespace(
        providers={"apple": apple},
        threadpool=_InlinePool(),
        previewReady=_Signal(),
        previewState=_Signal(),
        previewMeta=_Signal(),
    )
    stub._emit_apple_preview_meta = lambda *a: WavesBridge._emit_apple_preview_meta(stub, *a)

    WavesBridge.previewTrack(stub, "apple:song-1")

    assert stub.previewReady.emits == []
    assert ("track", "apple:song-1", "error") in stub.previewState.emits


def test_apple_album_preview_plays_for_a_signed_out_user():
    """Apple previews need no session (spec §7.4): a signed-out TIDAL bridge
    must not gate an Apple album preview, which used to return silently and
    leave the button buffering forever (issue #217)."""
    apple = _apple_provider(album=_album(), song=_song())
    stub = SimpleNamespace(
        providers={"apple": apple},
        _logged_in=False,
        threadpool=_InlinePool(),
        previewReady=_Signal(),
        previewState=_Signal(),
        previewMeta=_Signal(),
    )
    stub._emit_apple_preview_meta = lambda *a: WavesBridge._emit_apple_preview_meta(stub, *a)
    stub.previewMedia = lambda kind, ident: WavesBridge.previewMedia(stub, kind, ident)

    stub.previewMedia("album", "apple:album-1")

    assert ("album", "apple:album-1", "loading") in stub.previewState.emits
    assert stub.previewReady.emits == [("album", "apple:album-1", "https://audio-preview/song-1.m4a")]
    kind, ident, title, *_ = stub.previewMeta.emits[0]
    assert (kind, ident, title) == ("album", "apple:album-1", "Xtal")


def test_apple_album_preview_without_a_clip_reports_error():
    """No preview URL is a visible failure, never a silent return."""
    track = _song(preview=False)
    album = _album()
    album["relationships"]["tracks"]["data"] = [track]
    stub = SimpleNamespace(
        providers={"apple": _apple_provider(album=album, song=track)},
        _logged_in=False,
        threadpool=_InlinePool(),
        previewReady=_Signal(),
        previewState=_Signal(),
        previewMeta=_Signal(),
    )
    stub._emit_apple_preview_meta = lambda *a: WavesBridge._emit_apple_preview_meta(stub, *a)

    WavesBridge.previewMedia(stub, "album", "apple:album-1")

    assert stub.previewReady.emits == []
    assert ("album", "apple:album-1", "error") in stub.previewState.emits


def test_tidal_album_preview_stays_gated_on_the_session():
    """The fix is Apple's; a signed-out TIDAL preview still does nothing."""
    stub = SimpleNamespace(
        providers={"apple": _apple_provider(album=_album(), song=_song())},
        _logged_in=False,
        threadpool=_InlinePool(),
        previewReady=_Signal(),
        previewState=_Signal(),
    )

    WavesBridge.previewMedia(stub, "album", "tidal:album-1")

    assert stub.previewState.emits == [] and stub.previewReady.emits == []


def test_apple_artist_page_loads_albums_and_top_tracks():
    artist = {
        "id": "artist-1",
        "type": "artists",
        "attributes": {"name": "Aphex Twin", "artwork": {"url": "https://img/{w}x{h}bb.jpg"}},
        "relationships": {
            "albums": {"data": [_album()]},
            "top-songs": {"data": [_song()]},
        },
    }
    stub = _prefetch_stub(providers={"apple": _apple_provider(artist=artist, song=_song())})

    WavesBridge._load_apple_artist(stub, "apple:artist-1")

    (payload,) = stub.artistLoaded.emits
    assert payload["name"] == "Aphex Twin"
    assert [a["id"] for a in payload["albums"]] == ["apple:album-1"]
    assert [t["id"] for t in payload["tracks"]] == ["apple:song-1"]


def test_standalone_apple_artist_ignores_a_cached_summary():
    """The LYRICS/COVER standalone path must not build an artist page from a
    cached search summary: its album entries are reference stubs, so the
    canonical artist is fetched instead (issue #216)."""
    summary = {
        "id": "artist-1",
        "type": "artists",
        "attributes": {"name": "Aphex Twin"},
        "relationships": {
            "albums": {"data": [{"id": "album-1", "type": "albums", "href": "/v1/catalog/us/albums/album-1"}]}
        },
    }
    canonical = {
        "id": "artist-1",
        "type": "artists",
        "attributes": {"name": "Aphex Twin"},
        "relationships": {"albums": {"data": [_album()]}},
        "views": {"top-songs": {"data": [_song()]}},
    }

    class _StrictCatalog(_Catalog):
        """The shared fake answers any id; the resolver walks kinds and must
        only hit the one the id names."""

        def _one(self, wanted, ident, resource):
            if ident != wanted:
                raise KeyError(ident)
            return {"data": [resource]}

        async def get_album(self, album_id):
            return self._one("album-1", album_id, self._album)

        async def get_artist(self, artist_id):
            return self._one("artist-1", artist_id, self._artist)

        async def get_playlist(self, playlist_id):
            raise KeyError(playlist_id)

        async def get_song(self, song_id):
            return self._one("song-1", song_id, self._song)

    provider = AppleProvider(catalog=_StrictCatalog(album=_album(), artist=canonical, song=_song()))
    provider._remember("artist", summary)
    stub = SimpleNamespace(providers={"apple": provider})

    rows = WavesBridge._standalone_apple_tracks(stub, "apple:artist-1")

    assert rows, "the standalone path served nothing from a cached summary"
    assert any(row[0]["title"] == "Xtal" for row in rows)
    assert any(row[1] is not None and row[1]["title"] == "Selected Ambient Works 85-92" for row in rows)


def _apple_artist_catalog():
    artist = {
        "id": "artist-1",
        "type": "artists",
        "attributes": {"name": "Aphex Twin", "artwork": {"url": "https://img/{w}x{h}bb.jpg"}},
        "relationships": {
            "albums": {"data": []},
            "top-songs": {"data": [_song()]},
        },
    }
    return _Catalog(artist=artist, song=_song())


def _prefetch_stub(**overrides):
    stub = SimpleNamespace(
        _logged_in=True,
        providers={"apple": AppleProvider(catalog=_apple_artist_catalog())},
        threadpool=_InlinePool(),
        _artist_cache={},
        _artist_loading=set(),
        _artist_prefetch=None,
        _artist_prefetch_claimed=False,
        _prefetch_lock=Lock(),
        _browse_gen=0,
        artistLoaded=_Signal(),
        artistLoadFailed=_Signal(),
        statuses=[],
        busy=[],
    )
    stub._set_status = stub.statuses.append
    stub._set_busy = lambda on: stub.busy.append(bool(on))
    stub._remember_artist_page = lambda aid, payload: stub._artist_cache.__setitem__(aid, payload)
    stub._start_apple_artist_build = lambda *a, **k: WavesBridge._start_apple_artist_build(stub, *a, **k)
    for key, value in overrides.items():
        setattr(stub, key, value)
    return stub


def test_apple_hover_prefetch_warms_the_page_silently():
    stub = _prefetch_stub()

    WavesBridge.prefetchArtist(stub, "apple:artist-1")

    assert stub.artistLoaded.emits == []
    assert stub.busy == [] and stub.statuses == []
    assert stub._artist_cache["apple:artist-1"]["name"] == "Aphex Twin"
    assert stub._artist_loading == set() and stub._artist_prefetch is None


def test_apple_click_claims_an_in_flight_hover_prefetch():
    stub = _prefetch_stub(
        _artist_loading={"apple:artist-1"},
        _artist_prefetch="apple:artist-1",
    )

    WavesBridge._load_apple_artist(stub, "apple:artist-1")

    assert stub._artist_prefetch_claimed is True
    assert stub.busy == [True] and stub.statuses == ["Loading artist…"]
    assert stub.artistLoaded.emits == []  # the worker finishes as the click


def test_apple_click_after_a_prefetch_serves_the_warmed_cache():
    stub = _prefetch_stub()
    WavesBridge.prefetchArtist(stub, "apple:artist-1")

    WavesBridge._load_apple_artist(stub, "apple:artist-1")

    (payload,) = stub.artistLoaded.emits
    assert payload["name"] == "Aphex Twin"
    assert stub.statuses[-1] == "Aphex Twin"


class _FailingArtistCatalog:
    async def get_artist(self, artist_id):
        raise RuntimeError("network died")


def test_apple_silent_prefetch_failure_stays_silent():
    stub = _prefetch_stub(providers={"apple": AppleProvider(catalog=_FailingArtistCatalog())})

    WavesBridge.prefetchArtist(stub, "apple:artist-1")

    assert stub.artistLoaded.emits == []
    assert stub.statuses == [] and stub.busy == []
    assert stub._artist_cache == {}
    assert stub._artist_loading == set() and stub._artist_prefetch is None


def test_apple_click_failure_reports_and_releases_the_load():
    stub = _prefetch_stub(providers={"apple": AppleProvider(catalog=_FailingArtistCatalog())})

    WavesBridge._load_apple_artist(stub, "apple:artist-1")

    assert stub.artistLoaded.emits == []
    assert stub.statuses == ["Loading artist…", "Could not open that artist"]
    assert stub.busy == [True, False]
    assert stub.artistLoadFailed.emits == ["apple:artist-1"]


class _DeferredPool:
    def __init__(self):
        self.fns: list = []

    def start(self, worker, priority: int = 0):
        self.fns.append(worker.fn)


def test_apple_click_serves_cache_even_with_a_stale_loading_mark():
    stub = _prefetch_stub(providers={"apple": AppleProvider(catalog=_FailingArtistCatalog())})
    stub._artist_cache["apple:artist-1"] = {"id": "apple:artist-1", "name": "Aphex Twin"}
    stub._artist_loading.add("apple:artist-1")

    WavesBridge._load_apple_artist(stub, "apple:artist-1")

    (payload,) = stub.artistLoaded.emits
    assert payload["name"] == "Aphex Twin"
    assert stub._artist_prefetch_claimed is False  # served, not claimed


def test_apple_stale_worker_keeps_the_next_generations_prefetch():
    pool = _DeferredPool()
    stub = _prefetch_stub(threadpool=pool)
    WavesBridge.prefetchArtist(stub, "apple:artist-1")
    assert len(pool.fns) == 1

    # Logout clears the markers and bumps the generation; the next account
    # hovers the same artist before the old request finishes.
    stub._browse_gen = 1
    stub._artist_loading = set()
    stub._artist_prefetch = None
    stub._artist_cache = {}
    WavesBridge.prefetchArtist(stub, "apple:artist-1")
    assert len(pool.fns) == 2

    pool.fns[0]()  # the stale worker lands: touches nothing new

    assert stub._artist_loading == {"apple:artist-1"}
    assert stub._artist_prefetch == "apple:artist-1"
    assert stub._artist_cache == {}
    assert stub.artistLoaded.emits == []

    pool.fns[1]()  # the current worker warms the page quietly

    assert stub._artist_cache["apple:artist-1"]["name"] == "Aphex Twin"
    assert stub.artistLoaded.emits == []
