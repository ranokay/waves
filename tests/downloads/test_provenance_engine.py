"""The engine's tag and path seams read the captured provenance policy."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from downloads.fakes import make_download
from tidalapi import Album, Track

from waves.constants import MediaType, QualityTier
from waves.metadata.provenance import origin_facts


def _artist(name="Delivered Artist"):
    return SimpleNamespace(name=name, id=7, roles=None)


def _album():
    album = Album.__new__(Album)
    album.id = 10
    album.name = "Delivered Album"
    album.artists = [_artist()]
    album.artist = _artist()
    album.num_tracks = 2
    album.num_volumes = 1
    album.explicit = False
    album.release_date = datetime(2024, 5, 6)
    album.type = "ALBUM"
    return album


def _track(title="Delivered Title"):
    track = Track.__new__(Track)
    track.id = 1
    track.name = title
    track.full_name = title
    track.version = None
    track.explicit = False
    track.track_num = 2
    track.volume_num = 1
    track.duration = 200
    track.isrc = "GBAAA0000001"
    track.media_metadata_tags = []
    track.artists = [_artist()]
    track.artist = _artist()
    track.album = _album()
    return track


def _delivered_facts() -> dict:
    return {
        "item_id": "apple:42",
        "artist_ids": ["apple:artist"],
        "album_artist_ids": ["apple:album-artist"],
        "artists": [("apple:artist", "Delivered Artist")],
        "album_artists": ["Delivered Album Artist"],
        "copyright": "Delivered Copyright",
        "isrc": "GBAAA0000001",
        "explicit": False,
        "bpm": 0,
        "key": None,
        "key_scale": None,
        "share_url": "",
        "volume_num": 1,
        "track_num": 2,
        "release_date": "2024-05-06",
        "release_type": "album",
        "album": {
            "name": "Delivered Album",
            "num_tracks": 2,
            "num_volumes": 1,
            "upc": "123456789012",
            "type": "ALBUM",
        },
    }


def _origin() -> dict:
    return origin_facts(
        SimpleNamespace(
            kind="track",
            media_id="tidal:1",
            title="Origin Title",
            artist="Origin Artist",
            identifier="USSM1000001",
            duration_ms=200000,
            explicit=False,
            version=None,
            release_title="Origin Album",
            release_version=None,
            release_artist="Origin Album Artist",
            release_date="1999-01-02",
            track_number=2,
            disc_number=1,
            track_count=10,
            tracks=(),
            tracks_complete=False,
        )
    )


def _prepare(tmp_path, *, organization="origin", metadata="origin"):
    dl = make_download(tmp_path)
    dl._organization_source = organization
    dl._metadata_source = metadata
    dl._origin_facts = _origin()
    dl._origin_consistent = True
    dl._pinned_audio_type = "stereo"
    dl._pinned_tier = QualityTier.LOSSLESS
    dl.provider = SimpleNamespace(
        id="tidal",
        media_kind=lambda _item: MediaType.TRACK,
        track_facts=lambda _track: _delivered_facts(),
    )
    dl.extension_guess = lambda *_args, **_kwargs: ".flac"
    dl._psetting = lambda key, default=None: False
    dl.settings.data.metadata_target_upc = "UPC"
    dl.settings.data.mark_explicit = False
    dl.settings.data.metadata_write_url = False
    dl.settings.data.metadata_replay_gain = False
    dl.settings.data.initial_key_format = "standard"
    return dl


def test_origin_policy_drives_the_path(tmp_path):
    dl = _prepare(tmp_path)

    destination, _extension = dl._destination_path(
        _track(), "{provider_name}/{quality}/{audio_type}/{album_title}/{track_title}", None
    )

    assert destination.parent.name == "Origin Album"
    assert destination.name.startswith("Origin Title")
    assert "Tidal/LOSSLESS/stereo" in str(destination)


def test_fulfillment_policy_leaves_the_delivered_path(tmp_path):
    dl = _prepare(tmp_path, organization="fulfillment")

    destination, _extension = dl._destination_path(_track(), "{album_title}/{track_title}", None)

    assert destination.parent.name == "Delivered Album"
    assert destination.name.startswith("Delivered Title")


def test_origin_policy_drives_the_tag_writer_but_not_delivered_ids(tmp_path, monkeypatch):
    import waves.download as download_module

    captured: dict = {}

    class FakeMetadata:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def save(self):
            return True

    monkeypatch.setattr(download_module, "Metadata", FakeMetadata)
    dl = _prepare(tmp_path)

    ok, *_ = dl.metadata_write(_track(), tmp_path / "Song.flac", False)

    assert ok
    assert captured["title"] == "Origin Title"
    assert captured["album"] == "Origin Album"
    assert captured["artists"] == ["Origin Artist"]
    assert captured["item_id"] == "apple:42"
    assert captured["upc"] == "123456789012"
