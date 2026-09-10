"""Provider-separated download paths (issue #65).

The {provider_name} token renders the provider's library folder ("Tidal",
"Apple Music") in both template engines, so the same song saved from both
providers coexists instead of colliding. Unknown providers render "" (the
segment drops away: the pre-token layout). Fresh installs get the token in
the album/track defaults; stored old defaults migrate once, customized
templates are never rewritten.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from tidalapi import Album, Track

from waves.apple_files import format_apple_path
from waves.config import _migrate_settings
from waves.constants import provider_folder_name
from waves.helper.path import format_path_media, format_str_media
from waves.model.cfg import Settings


def test_folder_names_and_unknown_fallback():
    assert provider_folder_name("tidal") == "Tidal"
    assert provider_folder_name("apple") == "Apple Music"
    assert provider_folder_name("TIDAL") == "Tidal"
    assert provider_folder_name("nope") == ""
    assert provider_folder_name("") == ""
    assert provider_folder_name(None) == ""


def _track(title: str = "Xtal", artist: str = "Aphex Twin") -> Track:
    t = Track.__new__(Track)
    t.id = 1
    t.name = title
    t.version = None
    t.full_name = title
    t.explicit = False
    t.track_num = 1
    t.volume_num = 1
    t.artists = [SimpleNamespace(name=artist)]
    t.artist = SimpleNamespace(name=artist)
    album = Album.__new__(Album)
    album.id = 1
    album.name = "Selected Ambient Works 85-92"
    album.artists = [SimpleNamespace(name=artist, roles=None)]
    album.artist = SimpleNamespace(name=artist)
    album.num_tracks = 1
    album.num_volumes = 1
    album.release_date = datetime(1992, 2, 12)
    t.album = album
    return t


def test_tidal_token_renders_and_drops_when_unknown():
    track = _track()
    assert (
        format_path_media("{provider_name}/{artist_name} - {track_title}", track, provider_name="Tidal")
        == "Tidal/Aphex Twin - Xtal"
    )
    # No provider passed: the segment collapses away, never a literal token.
    assert format_path_media("{provider_name}/{artist_name} - {track_title}", track) == "Aphex Twin - Xtal"
    assert "{provider_name}" not in format_path_media("{provider_name}/{track_title}", track)
    # Templates without the token render exactly as before.
    assert format_path_media("{artist_name} - {track_title}", track, provider_name="Tidal") == "Aphex Twin - Xtal"


def test_format_str_media_answers_the_token_directly():
    assert format_str_media("provider_name", None, provider_name="Tidal") == "Tidal"
    assert format_str_media("provider_name", None) == ""


def _apple_row():
    return {
        "id": "apple:song-1",
        "title": "Xtal",
        "artist": "Aphex Twin",
        "artist_id": "apple:artist-1",
        "artists": [{"id": "apple:artist-1", "name": "Aphex Twin", "roles": []}],
        "album": "Selected Ambient Works 85-92",
        "album_id": "apple:album-1",
        "num": 1,
        "vol": 1,
        "year": "1992",
        "date": "1992-02-12",
        "duration_sec": 293,
        "quality": "LOSSLESS",
        "explicit": False,
    }


def test_apple_token_defaults_to_apple_music_and_drops_when_empty():
    row = _apple_row()
    assert (
        format_apple_path("{provider_name}/{artist_name} - {track_title}", track=row) == "Apple Music/Aphex Twin - Xtal"
    )
    assert format_apple_path("{provider_name}/{track_title}", track=row, provider_name="") == "Xtal"
    assert format_apple_path("{provider_name}/{track_title}", track=row, provider_name="Tidal") == "Tidal/Xtal"


def test_same_song_from_both_providers_no_longer_collides():
    tidal = format_path_media("{provider_name}/{artist_name} - {track_title}", _track(), provider_name="Tidal")
    apple = format_apple_path("{provider_name}/{artist_name} - {track_title}", track=_apple_row())
    assert tidal != apple
    assert tidal.startswith("Tidal/") and apple.startswith("Apple Music/")


def test_fresh_defaults_carry_the_token_on_songs_only():
    fresh = Settings()
    assert fresh.format_album.startswith("{provider_name}/")
    assert fresh.format_track.startswith("{provider_name}/")
    assert "{provider_name}" not in fresh.format_playlist
    assert "{provider_name}" not in fresh.format_mix
    assert "{provider_name}" not in fresh.format_video


def test_download_names_its_provider_folder():
    from waves.download import Download

    dl = Download.__new__(Download)
    dl.provider = SimpleNamespace(id="tidal")
    assert Download._provider_folder(dl) == "Tidal"
    dl.provider = SimpleNamespace(id="apple")
    assert Download._provider_folder(dl) == "Apple Music"
    dl.provider = SimpleNamespace(id="nope")
    assert Download._provider_folder(dl) == ""
    dl.provider = None
    assert Download._provider_folder(dl) == ""
    del dl.provider
    assert Download._provider_folder(dl) == ""


OLD_DEFAULT = (
    "{artist_name}/[{album_year}] {album_title}{album_explicit}/{track_volume_num_optional}"
    "{album_track_num}. {artist_name} - {track_title}{track_explicit}"
)


def _pre_segment_settings() -> Settings:
    data = Settings()
    data.replay_gain_default_migrated = True  # isolate the segment step
    data.api_rate_limit_wired_migrated = True
    data.lyrics_art_per_provider_migrated = True
    data.format_playlist_folder_migrated = True
    data.format_provider_segment_migrated = False
    return data


def test_stored_old_defaults_gain_the_segment():
    data = _pre_segment_settings()
    data.format_album = OLD_DEFAULT
    data.format_track = OLD_DEFAULT
    assert _migrate_settings(data) is True
    assert data.format_album == Settings().format_album
    assert data.format_track == Settings().format_track
    assert data.format_album.startswith("{provider_name}/")
    assert data.format_provider_segment_migrated is True


def test_customized_templates_are_never_touched():
    data = _pre_segment_settings()
    custom = "MyMusic/{artist_name} - {track_title}"
    data.format_album = custom
    data.format_track = custom
    assert _migrate_settings(data) is True  # marker write still persists
    assert data.format_album == custom
    assert data.format_track == custom
    assert data.format_provider_segment_migrated is True


def test_marker_stops_a_second_rewrite():
    # The user removed {provider_name} again after the upgrade: their choice,
    # and it happens to equal the old default. The marker keeps it.
    data = _pre_segment_settings()
    data.format_album = OLD_DEFAULT
    _migrate_settings(data)
    data.format_album = OLD_DEFAULT
    assert _migrate_settings(data) is False
    assert data.format_album == OLD_DEFAULT


def test_token_is_listed_for_discovery():
    from waves.waves_ui.backend import _TEMPLATE_TOKENS

    entries = {tok: desc for tok, _group, desc in _TEMPLATE_TOKENS}
    assert "provider_name" in entries
