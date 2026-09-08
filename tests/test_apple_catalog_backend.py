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
