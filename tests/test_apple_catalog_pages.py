from __future__ import annotations

from waves.providers.apple import AppleProvider


def _song_resource(song_id="song-1", with_preview=True):
    attrs = {
        "name": "Xtal",
        "artistName": "Aphex Twin",
        "albumName": "Selected Ambient Works 85-92",
        "url": "https://music.apple.com/us/album/selected-ambient-works/album-1?i=song-1",
        "artwork": {"url": "https://img/song/{w}x{h}bb.jpg"},
        "releaseDate": "1992-02-12",
        "durationInMillis": 293000,
        "trackNumber": 1,
        "discNumber": 1,
        "audioTraits": ["hi-res-lossless"],
    }
    if with_preview:
        attrs["previews"] = [{"url": "https://audio-preview/song-1.m4a"}]
    return {
        "id": song_id,
        "type": "songs",
        "attributes": attrs,
        "relationships": {"artists": {"data": [{"id": "artist-1"}]}},
    }


def _album_resource():
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
        "relationships": {"tracks": {"data": [_song_resource()]}},
    }


class _Catalog:
    def __init__(self, album=None, artist=None, playlist=None, song=None):
        self._album = album
        self._artist = artist
        self._playlist = playlist
        self._song = song
        self.calls: list = []

    async def get_album(self, album_id):
        self.calls.append(("album", album_id))
        return {"data": [self._album]}

    async def get_artist(self, artist_id):
        self.calls.append(("artist", artist_id))
        return {"data": [self._artist]}

    async def get_playlist(self, playlist_id):
        self.calls.append(("playlist", playlist_id))
        return {"data": [self._playlist]}

    async def get_song(self, song_id):
        self.calls.append(("song", song_id))
        return {"data": [self._song]}


def test_parse_apple_url_covers_albums_artists_playlists_and_songs():
    assert AppleProvider.parse_apple_url("https://music.apple.com/us/album/nevermind/1440783617") == (
        "album",
        "1440783617",
        None,
    )
    assert AppleProvider.parse_apple_url("https://music.apple.com/us/artist/nirvana/666398") == (
        "artist",
        "666398",
        None,
    )
    assert AppleProvider.parse_apple_url("https://music.apple.com/us/playlist/todays-hits/pl.abc123") == (
        "playlist",
        "pl.abc123",
        None,
    )
    assert AppleProvider.parse_apple_url("https://music.apple.com/us/album/nevermind/1440783617?i=1440783620") == (
        "track",
        "1440783620",
        None,
    )
    assert AppleProvider.parse_apple_url("https://tidal.com/browse/album/42") is None
    assert AppleProvider.parse_apple_url("not a url") is None


def test_open_url_resolves_through_the_catalog():
    provider = AppleProvider(catalog=_Catalog(album=_album_resource()))

    resolved = provider.open_url("https://music.apple.com/us/album/whatever/album-1")

    assert resolved["kind"] == "album"
    assert resolved["item"]["id"] == "album-1"


def test_open_url_answers_none_for_foreign_links_and_missing_items():
    provider = AppleProvider(catalog=_Catalog())

    assert provider.open_url("https://tidal.com/browse/album/42") is None
    assert provider.open_url("https://music.apple.com/us/album/whatever/gone") is None


def test_get_object_caches_by_namespaced_id():
    provider = AppleProvider(catalog=_Catalog(album=_album_resource()))

    first = provider.get_object("album", "apple:album-1")
    second = provider.get_object("album", "album-1")

    assert first is second
    assert provider._catalog.calls == [("album", "album-1")]


def test_collection_items_builds_track_rows_from_the_album_resource():
    provider = AppleProvider(catalog=_Catalog())

    rows = provider.collection_items(_album_resource())

    assert [(row["id"], row["title"], row["num"]) for row in rows] == [("apple:song-1", "Xtal", 1)]


def test_artist_page_splits_albums_and_top_songs():
    artist = {
        "id": "artist-1",
        "type": "artists",
        "attributes": {"name": "Aphex Twin", "artwork": {"url": "https://img/{w}x{h}bb.jpg"}},
        "relationships": {
            "albums": {
                "data": [
                    {
                        "id": "album-1",
                        "type": "albums",
                        "attributes": {
                            "name": "Selected Ambient Works 85-92",
                            "artistName": "Aphex Twin",
                            "artwork": {"url": "https://img/album/{w}x{h}bb.jpg"},
                            "releaseDate": "1992-02-12",
                        },
                    }
                ]
            },
            "top-songs": {"data": [_song_resource()]},
        },
    }
    provider = AppleProvider(catalog=_Catalog())

    page = provider.artist_page(artist)

    assert page["name"] == "Aphex Twin"
    assert [a["id"] for a in page["albums"]] == ["apple:album-1"]
    assert [t["id"] for t in page["tracks"]] == ["apple:song-1"]


def test_preview_url_returns_the_documented_30_second_clip():
    provider = AppleProvider(catalog=_Catalog())

    assert provider.preview_url(_song_resource()) == "https://audio-preview/song-1.m4a"
    assert provider.preview_url(_song_resource(with_preview=False)) is None


def test_cover_url_uses_the_documented_template():
    provider = AppleProvider(catalog=_Catalog())

    assert provider.cover_url(_album_resource(), 500) == "https://img/album/500x500bb.jpg"
    assert provider.cover_url({}, 500) == ""


def _search_summary_catalog():
    """A catalog whose search answers are summaries and whose fetches are full."""

    class _SearchCatalog(_Catalog):
        async def get_search_results(self, term, types):
            return {
                "results": {
                    "artists": {
                        "data": [
                            {
                                "id": "artist-1",
                                "attributes": {
                                    "name": "Aphex Twin",
                                    "artwork": {"url": "https://img/{w}x{h}bb.jpg"},
                                },
                            }
                        ]
                    },
                    "albums": {
                        "data": [
                            {
                                "id": "album-1",
                                "attributes": {
                                    "name": "Selected Ambient Works 85-92",
                                    "artistName": "Aphex Twin",
                                    "artwork": {"url": "https://img/album/{w}x{h}bb.jpg"},
                                    "releaseDate": "1992-02-12",
                                },
                            }
                        ]
                    },
                    "songs": {"data": [_song_resource()]},
                    "playlists": {"data": []},
                }
            }

    return _SearchCatalog(album=_album_resource(), song=_song_resource(), artist=_full_artist_resource())


def _full_artist_resource():
    return {
        "id": "artist-1",
        "type": "artists",
        "attributes": {"name": "Aphex Twin", "artwork": {"url": "https://img/{w}x{h}bb.jpg"}},
        "relationships": {
            "albums": {"data": [_album_resource()]},
            "top-songs": {"data": [_song_resource()]},
        },
    }


def test_get_object_refetches_a_search_summary_album_before_building_pages():
    provider = AppleProvider(catalog=_search_summary_catalog())
    provider.search("aphex")

    assert provider._catalog.calls == []
    album = provider.get_object("album", "apple:album-1")

    assert provider._catalog.calls == [("album", "album-1")]
    assert album["relationships"]["tracks"]["data"][0]["id"] == "song-1"
    assert provider.get_object("album", "album-1") is album
    assert provider._catalog.calls == [("album", "album-1")]


def test_get_object_reuses_a_named_search_track_without_refetching():
    provider = AppleProvider(catalog=_search_summary_catalog())
    provider.search("aphex")

    track = provider.get_object("track", "apple:song-1")

    assert track["id"] == "song-1"
    assert provider._catalog.calls == []


def test_get_object_refetches_a_search_summary_artist_before_building_pages():
    provider = AppleProvider(catalog=_search_summary_catalog())
    provider.search("aphex")

    provider.get_object("artist", "apple:artist-1")

    assert ("artist", "artist-1") in provider._catalog.calls


def test_a_later_search_summary_invalidates_a_fetched_album():
    provider = AppleProvider(catalog=_search_summary_catalog())
    provider.get_object("album", "album-1")
    provider.search("aphex")

    provider.get_object("album", "apple:album-1")

    assert provider._catalog.calls == [("album", "album-1"), ("album", "album-1")]


def test_rendering_a_fetched_empty_album_preserves_completeness():
    empty_album = {
        "id": "album-9",
        "type": "albums",
        "attributes": {
            "name": "Silence",
            "artistName": "Aphex Twin",
            "artwork": {"url": "https://img/album/{w}x{h}bb.jpg"},
            "releaseDate": "1992-02-12",
        },
    }

    class _EmptyCatalog:
        def __init__(self):
            self.calls: list = []

        async def get_album(self, album_id):
            self.calls.append(("album", album_id))
            return {"data": [empty_album]}

    provider = AppleProvider(catalog=_EmptyCatalog())
    fetched = provider.get_object("album", "album-9")
    provider.row_for("album", fetched)

    assert provider.get_object("album", "apple:album-9") is fetched
    assert provider._catalog.calls == [("album", "album-9")]
