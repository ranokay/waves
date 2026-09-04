from __future__ import annotations

from waves.providers.apple import AppleProvider


class _Catalog:
    def __init__(self):
        self.terms: list[str] = []

    async def get_search_results(self, term: str) -> dict:
        self.terms.append(term)
        return {
            "results": {
                "artists": {
                    "data": [
                        {
                            "id": "artist-1",
                            "attributes": {
                                "name": "Aphex Twin",
                                "artwork": {"url": "https://img/{w}x{h}bb.{f}"},
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
                                "trackCount": 13,
                                "durationInMillis": 4455000,
                                "audioTraits": ["lossless"],
                                "contentRating": "explicit",
                            },
                        }
                    ]
                },
                "songs": {
                    "data": [
                        {
                            "id": "song-1",
                            "attributes": {
                                "name": "Xtal",
                                "artistName": "Aphex Twin",
                                "albumName": "Selected Ambient Works 85-92",
                                "url": "https://music.apple.com/us/album/selected-ambient-works/album-1?i=song-1",
                                "artwork": {"url": "https://img/song/{w}x{h}bb.jpg"},
                                "releaseDate": "1992-02-12",
                                "durationInMillis": 293000,
                                "trackNumber": 1,
                                "discNumber": 1,
                                "audioTraits": ["hi-res-lossless", "lossless"],
                            },
                            "relationships": {"artists": {"data": [{"id": "artist-1"}]}},
                        }
                    ]
                },
                "music-videos": {
                    "data": [
                        {
                            "id": "video-1",
                            "attributes": {
                                "name": "T69 Collapse",
                                "artistName": "Aphex Twin",
                                "artwork": {"url": "https://img/video/{w}x{h}bb.jpg"},
                                "releaseDate": "2018-08-07",
                                "durationInMillis": 310000,
                                "videoTraits": ["4K"],
                            },
                        }
                    ]
                },
                "playlists": {
                    "data": [
                        {
                            "id": "playlist-1",
                            "attributes": {
                                "name": "Aphex Twin Essentials",
                                "curatorName": "Apple Music Electronic",
                                "artwork": {"url": "https://img/playlist/{w}x{h}bb.jpg"},
                                "lastModifiedDate": "2026-08-01T12:00:00Z",
                            },
                            "relationships": {"tracks": {"meta": {"total": 25}}},
                        }
                    ]
                },
            }
        }


def test_search_converts_the_public_catalog_to_waves_rows_without_account_setup():
    provider = AppleProvider(catalog=_Catalog())

    result = provider.search("aphex twin")

    assert result == {
        "artists": [
            {
                "id": "apple:artist-1",
                "name": "Aphex Twin",
                "art": "https://img/320x320bb.jpg",
                "roles": "Artist",
                "popularity": -1,
            }
        ],
        "albums": [
            {
                "id": "apple:album-1",
                "title": "Selected Ambient Works 85-92",
                "artist": "Aphex Twin",
                "artist_id": "apple:artist-1",
                "artists": [{"id": "apple:artist-1", "name": "Aphex Twin", "roles": []}],
                "art": "https://img/album/320x320bb.jpg",
                "year": "1992",
                "date": "1992-02-12",
                "tracks": 13,
                "duration_sec": 4455,
                "quality": "LOSSLESS",
                "popularity": -1,
                "explicit": True,
                "added": "",
            }
        ],
        "tracks": [
            {
                "id": "apple:song-1",
                "title": "Xtal",
                "artist": "Aphex Twin",
                "artist_id": "apple:artist-1",
                "artists": [{"id": "apple:artist-1", "name": "Aphex Twin", "roles": []}],
                "album": "Selected Ambient Works 85-92",
                "album_id": "apple:album-1",
                "num": 1,
                "vol": 1,
                "art": "https://img/song/160x160bb.jpg",
                "year": "1992",
                "date": "1992-02-12",
                "duration": "4:53",
                "duration_sec": 293,
                "quality": "HI-RES",
                "popularity": -1,
                "explicit": False,
                "added": "",
            }
        ],
        "videos": [
            {
                "id": "apple:video-1",
                "title": "T69 Collapse",
                "artist": "Aphex Twin",
                "artists": [{"id": "apple:artist-1", "name": "Aphex Twin", "roles": []}],
                "art": "https://img/video/160x107bb.jpg",
                "art_big": "https://img/video/750x500bb.jpg",
                "duration": "5:10",
                "explicit": False,
                "added": "",
                "date": "2018-08-07",
                "quality": "4K",
            }
        ],
        "playlists": [
            {
                "id": "apple:playlist-1",
                "title": "Aphex Twin Essentials",
                "art": "https://img/playlist/320x320bb.jpg",
                "tracks": 25,
                "creator": "Apple Music Electronic",
                "added": "",
                "kind": "playlist",
                "sub": "",
                "path": "",
                "plCount": 0,
            }
        ],
        "mixes": [],
        "top": None,
    }


def test_catalog_client_is_created_lazily_without_account_or_runtime_arguments():
    catalog = _Catalog()
    calls = 0

    async def create_catalog():
        nonlocal calls
        calls += 1
        return catalog

    provider = AppleProvider(catalog_factory=create_catalog)

    provider.search("first")
    provider.search("second")

    assert calls == 1
    assert catalog.terms == ["first", "second"]
