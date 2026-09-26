"""PRV-01: the provider row-dict runtime contract.

``validate_row`` in waves.providers.base owns the required keys per row
kind plus value type checks. Tests/CI raise naming the missing key;
shipped runtime logs once per kind and never alters the row.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

import waves.download
from waves.constants import CTX_TIDAL
from waves.desktop.backend import WavesBridge
from waves.providers.apple.provider import AppleProvider
from waves.providers.base import RowValidationError, validate_row


def _good_track() -> dict:
    return {
        "id": "7",
        "title": "Xtal",
        "artist": "Aphex Twin",
        "artist_id": "1",
        "artists": [{"id": "1", "name": "Aphex Twin", "roles": []}],
        "album": "Selected Ambient Works",
        "album_id": "2",
        "num": 1,
        "vol": 1,
        "art": "",
        "year": "1992",
        "date": "1992-02-12",
        "duration": "4:54",
        "duration_sec": 294,
        "quality": "LOSSLESS",
        "popularity": -1,
        "explicit": False,
        "added": "",
    }


def test_a_key_dropped_row_fails_naming_the_missing_key():
    row = _good_track()
    del row["title"]
    with pytest.raises(RowValidationError, match="missing key 'title'"):
        validate_row("track", row)


def test_a_mistyped_value_fails_naming_the_key_and_type():
    row = _good_track()
    row["popularity"] = "high"
    with pytest.raises(RowValidationError, match=r"key 'popularity' must be int"):
        validate_row("track", row)


def test_bool_is_not_an_int_and_int_is_not_a_bool():
    row = _good_track()
    row["popularity"] = True
    with pytest.raises(RowValidationError, match="popularity"):
        validate_row("track", row)
    row = _good_track()
    row["explicit"] = 1
    with pytest.raises(RowValidationError, match="explicit"):
        validate_row("track", row)


def test_unknown_kind_and_non_dict_rows_fail():
    with pytest.raises(RowValidationError, match="unknown row kind 'nope'"):
        validate_row("nope", {})
    with pytest.raises(RowValidationError, match="not a dict"):
        validate_row("track", ["id"])


def test_extra_keys_and_both_artists_spellings_pass():
    row = _good_track()
    row["listed"] = "2024-01-01"  # the album row's documented extra
    assert validate_row("track", row) is row
    row["artists"] = [{"name": "Aphex Twin", "id": "1"}]  # TIDAL's {name, id} shape
    assert validate_row("track", row) is row
    bad = _good_track()
    bad["artists"] = [{"name": "nameless"}]
    with pytest.raises(RowValidationError, match="artists"):
        validate_row("track", bad)


def test_runtime_logs_once_per_kind_and_never_alters_the_row(caplog):
    base = __import__("waves.providers.base", fromlist=["_warned_kinds"])
    base._warned_kinds.clear()
    row = _good_track()
    del row["title"]
    with caplog.at_level(logging.WARNING, logger="waves.providers.base"):
        assert validate_row("track", row, strict=False) is row
        assert validate_row("track", row, strict=False) is row
    warnings = [r for r in caplog.records if "invalid track row" in r.getMessage()]
    assert len(warnings) == 1
    assert "missing key 'title'" in warnings[0].getMessage()


def test_apple_rows_pass_unchanged():
    provider = AppleProvider(catalog=None)
    artist = {"id": "ar1", "type": "artists", "attributes": {"name": "Aphex Twin"}}
    album = {
        "id": "al1",
        "type": "albums",
        "attributes": {
            "name": "SAW",
            "artistName": "Aphex Twin",
            "releaseDate": "1992-02-12",
            "trackCount": 13,
        },
    }
    track = {
        "id": "so1",
        "type": "songs",
        "attributes": {
            "name": "Xtal",
            "artistName": "Aphex Twin",
            "albumName": "SAW",
            "trackNumber": 1,
            "discNumber": 1,
            "durationInMillis": 294000,
        },
    }
    playlist = {"id": "pl1", "type": "playlists", "attributes": {"name": "Mix", "curatorName": "Me"}}
    before = [dict(artist), dict(album), dict(track), dict(playlist)]
    rows = {
        "artist": provider.row_for("artist", artist),
        "album": provider.row_for("album", album),
        "track": provider.row_for("track", track),
        "playlist": provider.row_for("playlist", playlist),
    }
    assert all(rows.values())
    assert [artist, album, track, playlist] == before  # inputs untouched, rows new dicts


def _tidal_self():
    return SimpleNamespace(
        _remember=lambda *args: None,
        providers={CTX_TIDAL: SimpleNamespace(advertised_tier=lambda obj: None)},
    )


def test_tidal_rows_pass_unchanged():
    tidal_self = _tidal_self()
    album = SimpleNamespace(id="11", name="SAW", duration=3600, explicit=False, artists=[])
    track = SimpleNamespace(
        id="7", name="Xtal", track_num=1, volume_num=1, duration=294, explicit=False, album=album, artists=[]
    )
    video = SimpleNamespace(id="9", name="Clip", duration=180, explicit=False, artists=[])
    playlist = SimpleNamespace(id="5", name="Mix")
    mix = SimpleNamespace(id="3", name="Daily Mix", title="Daily Mix", sub_title="Made for you")
    rows = {
        "album": WavesBridge._album_dict(tidal_self, album),
        "track": WavesBridge._track_dict(tidal_self, track),
        "video": WavesBridge._video_dict(tidal_self, video),
        "playlist": WavesBridge._playlist_dict(tidal_self, playlist),
        "mix": WavesBridge._mix_dict(tidal_self, mix),
        "artist": WavesBridge._fav_artist_dict(tidal_self, SimpleNamespace(id="1", name="Aphex Twin")),
    }
    assert all(rows.values())
    assert rows["track"]["title"] == "Xtal"  # built, hence validated, unchanged


def test_the_download_engine_does_not_import_the_validator():
    assert "validate_row" not in vars(waves.download)
    assert "RowValidationError" not in vars(waves.download)
