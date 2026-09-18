from __future__ import annotations

from threading import Lock
from types import SimpleNamespace

import pytest

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


def _summary_artist() -> dict:
    """Apple's search summary for artist-1: a named artist whose album
    relationship lists reference stubs (id/type/href, no attributes) and which
    carries no views -- the captured live shape behind audit F-02 (issue #216).
    A fresh dict per call, so a caller may remember or mutate it freely."""
    return {
        "id": "artist-1",
        "type": "artists",
        "attributes": {"name": "Aphex Twin", "artwork": {"url": "https://img/{w}x{h}bb.jpg"}},
        "relationships": {
            "albums": {"data": [{"id": "album-1", "type": "albums", "href": "/v1/catalog/us/albums/album-1"}]}
        },
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

    group = payload["groups"][0]
    assert group["provider"] == "apple"
    assert [row["id"] for row in group["albums"]] == ["apple:album-1"]
    assert "videos" not in group and "mixes" not in group, "Apple's group carries only the sections its search answers"
    assert group["tracks"] == []
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


def _preview_stub(**resources):
    """A signed-out bridge stub for the preview slots: signals, an inline pool,
    the meta helper and every preview entry point bound for direct calls.
    Signed out on purpose: Apple previews must not need the TIDAL session."""
    stub = SimpleNamespace(
        providers={"apple": _apple_provider(**resources)},
        _logged_in=False,
        threadpool=_InlinePool(),
        previewReady=_Signal(),
        previewState=_Signal(),
        previewMeta=_Signal(),
    )
    stub._emit_apple_preview_meta = lambda *a, **k: WavesBridge._emit_apple_preview_meta(stub, *a, **k)
    stub.previewMedia = lambda kind, ident: WavesBridge.previewMedia(stub, kind, ident)
    stub.previewTrack = lambda ident: WavesBridge.previewTrack(stub, ident)
    stub.previewArtist = lambda ident: WavesBridge.previewArtist(stub, ident)
    return stub


def _playlist_resource(*songs):
    return {
        "id": "playlist-1",
        "type": "playlists",
        "attributes": {
            "name": "Essentials",
            "curatorName": "Apple",
            "artwork": {"url": "https://img/pl/{w}x{h}bb.jpg"},
        },
        "relationships": {"tracks": {"data": list(songs)}},
    }


def _artist_with_top_songs(*songs):
    return {
        "id": "artist-1",
        "type": "artists",
        "attributes": {"name": "Aphex Twin"},
        "views": {"top-songs": {"data": list(songs)}},
    }


def test_apple_preview_track_emits_the_clip_url_directly():
    stub = _preview_stub(song=_song())

    stub.previewTrack("apple:song-1")

    assert ("track", "apple:song-1", "loading") in stub.previewState.emits
    assert stub.previewReady.emits == [("track", "apple:song-1", "https://audio-preview/song-1.m4a")]
    kind, ident, title, *_ = stub.previewMeta.emits[0]
    assert (kind, ident, title) == ("track", "apple:song-1", "Xtal")


def test_apple_preview_track_without_a_clip_reports_error():
    stub = _preview_stub(song=_song(preview=False))

    stub.previewTrack("apple:song-1")

    assert stub.previewReady.emits == []
    assert ("track", "apple:song-1", "error") in stub.previewState.emits


def _collection_stub(kind, *songs):
    """(stub, media_id) for an Apple album or playlist holding the songs."""
    dead = songs[0]
    if kind == "album":
        album = _album()
        album["relationships"]["tracks"]["data"] = list(songs)
        return _preview_stub(album=album, song=dead), "apple:album-1"
    return _preview_stub(playlist=_playlist_resource(*songs), song=dead), "apple:playlist-1"


@pytest.mark.parametrize("kind", ["album", "playlist"])
def test_apple_collection_preview_plays_for_a_signed_out_user(kind):
    """Apple previews need no session (spec §7.4): a signed-out TIDAL bridge
    must not gate them, which used to return silently and leave the button
    buffering forever (issue #217)."""
    stub, media_id = _collection_stub(kind, _song())

    stub.previewMedia(kind, media_id)

    assert (kind, media_id, "loading") in stub.previewState.emits
    assert stub.previewReady.emits == [(kind, media_id, "https://audio-preview/song-1.m4a")]
    assert stub.previewMeta.emits[0][2] == "Xtal"


@pytest.mark.parametrize("kind", ["album", "playlist"])
def test_apple_collection_preview_without_a_clip_reports_error(kind):
    """No preview URL is a visible failure, never a silent return."""
    stub, media_id = _collection_stub(kind, _song(preview=False))

    stub.previewMedia(kind, media_id)

    assert stub.previewReady.emits == []
    assert (kind, media_id, "error") in stub.previewState.emits


def test_apple_artist_preview_plays_and_reports_a_missing_clip():
    stub = _preview_stub(artist=_artist_with_top_songs(_song()), song=_song())

    stub.previewArtist("apple:artist-1")

    assert stub.previewReady.emits == [("artist", "apple:artist-1", "https://audio-preview/song-1.m4a")]

    dead = _song(preview=False)
    stub2 = _preview_stub(artist=_artist_with_top_songs(dead), song=dead)

    stub2.previewArtist("apple:artist-1")

    assert stub2.previewReady.emits == []
    assert ("artist", "apple:artist-1", "error") in stub2.previewState.emits


def test_tidal_album_preview_stays_gated_on_the_session():
    """The fix is Apple's; a signed-out TIDAL preview still does nothing."""
    stub = _preview_stub(album=_album(), song=_song())

    stub.previewMedia("album", "tidal:album-1")

    assert stub.previewState.emits == [] and stub.previewReady.emits == []


def test_standalone_apple_artist_ignores_a_cached_summary():
    """The LYRICS/COVER standalone path must not build an artist page from a
    cached search summary: its album entries are reference stubs, so the
    canonical artist is fetched instead (issue #216)."""
    summary = _summary_artist()
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


def _summary_artist_catalog():
    """A catalog whose search answers with Apple's attribute-less artist
    summary (``_summary_artist``) and whose canonical fetch returns the
    attributed artist, so only a bridge that refetches projects a populated
    page. Returns ``(catalog, fetch_calls)``."""

    calls: list = []

    class _SummaryCatalog(_Catalog):
        async def get_search_results(self, term, types):
            return {
                "results": {
                    "artists": {"data": [_summary_artist()]},
                    "albums": {"data": []},
                    "songs": {"data": []},
                    "playlists": {"data": []},
                }
            }

        async def get_artist(self, artist_id):
            calls.append(("artist", artist_id))
            return {"data": [self._artist]}

    canonical = {
        "id": "artist-1",
        "type": "artists",
        "attributes": {"name": "Aphex Twin", "artwork": {"url": "https://img/{w}x{h}bb.jpg"}},
        "relationships": {"albums": {"data": [_album()]}},
        "views": {"top-songs": {"data": [_song()]}},
    }
    return _SummaryCatalog(album=_album(), artist=canonical, song=_song()), calls


def test_apple_artist_payload_projects_named_rows_and_top_tracks():
    """R-11's acceptance at the bridge's own seam (issue #247): the payload the
    artist page renders carries a named album row with art, a track count and
    a date, plus the top-tracks section. The pre-fix bridge projected Apple's
    attribute-less search summary into blank rows (audit F-02)."""
    catalog, calls = _summary_artist_catalog()
    provider = AppleProvider(catalog=catalog)
    provider.search("aphex")  # the summary copy a click would see
    stub = _prefetch_stub(providers={"apple": provider})

    WavesBridge._load_apple_artist(stub, "apple:artist-1")

    (payload,) = stub.artistLoaded.emits
    assert payload["name"] == "Aphex Twin"
    (album,) = payload["albums"]
    assert album["title"] == "Selected Ambient Works 85-92"
    assert album["artist"] == "Aphex Twin"
    assert album["art"] == "https://img/album/320x320bb.jpg"
    assert album["tracks"] == 13
    assert (album["date"], album["year"]) == ("1992-02-12", "1992")
    assert [row["title"] for row in payload["tracks"]] == ["Xtal"]
    assert ("artist", "artist-1") in calls, "the summary was never refetched"


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
