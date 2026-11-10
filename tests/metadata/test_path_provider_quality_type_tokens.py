"""Provider, quality and audio-type path tokens.

The tokens are optional: an existing template renders byte-identically, and
the ordering tokens keep the source collection's order. New values still go
through the same cross-platform sanitizer.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from tidalapi import Album, Track

from waves.paths import format_path_media


def _artist() -> SimpleNamespace:
    return SimpleNamespace(name="Bright Eyes", id=99, roles=None)


def _album() -> Album:
    album = Album.__new__(Album)
    album.id = 10
    album.name = "The Better Life / Dead Love"
    album.artists = [_artist()]
    album.artist = _artist()
    album.num_tracks = 2
    album.num_volumes = 1
    album.explicit = False
    album.release_date = datetime(2011, 5, 3)
    album.type = "ALBUM"
    return album


def _track(num: int = 1, title: str = "One") -> Track:
    track = Track.__new__(Track)
    track.id = num
    track.name = title
    track.full_name = title
    track.version = None
    track.explicit = False
    track.track_num = num
    track.volume_num = 1
    track.duration = 150
    track.isrc = "USSM1000001"
    track.media_metadata_tags = []
    track.artists = [_artist()]
    track.artist = _artist()
    track.album = _album()
    return track


def test_new_tokens_render_the_delivery_provenance():
    rendered = format_path_media(
        "{provider_name}/{quality}/{audio_type}/{track_title}",
        _track(),
        provider_name="Tidal",
        quality="HI_RES_LOSSLESS",
        audio_type="atmos",
    )

    assert rendered == "Tidal/HI_RES_LOSSLESS/atmos/One"


def test_an_existing_template_renders_byte_identically():
    legacy = "{provider_name}/{artist_name}/[{album_year}] {album_title}/{album_track_num} {track_title}"

    assert format_path_media(legacy, _track(), provider_name="Tidal") == (
        "Tidal/Bright Eyes/[2011] The Better Life Dead Love/1 One"
    )


def test_ordering_tokens_keep_the_source_order():
    first = format_path_media("{list_pos}. {track_title}", _track(1, "One"), list_pos=1, list_total=2)
    second = format_path_media("{list_pos}. {track_title}", _track(2, "Two"), list_pos=2, list_total=2)

    assert (first, second) == ("1. One", "2. Two")


def test_a_facts_overlay_changes_descriptive_tokens_but_not_ordering_or_ids():
    rendered = format_path_media(
        "{list_pos}/{track_id}/{track_title}/{album_title}",
        _track(1, "Delivered"),
        list_pos=3,
        facts={"track_title": "Origin", "album_title": "Origin Album"},
    )

    assert rendered == "3/1/Origin/Origin Album"


def test_new_token_values_are_sanitized_for_every_platform():
    rendered = format_path_media(
        "{quality}/{audio_type}/{track_title}",
        _track(title="Song"),
        quality="HI/RES: LOSSLESS?",
        audio_type="atmos|stereo",
    )

    # The template's own separators stay; the values introduce none.
    assert rendered.count("/") == 2
    assert ":" not in rendered
    assert "?" not in rendered
    assert "|" not in rendered


def test_a_literal_token_in_a_new_value_stays_literal():
    rendered = format_path_media(
        "{track_title}",
        _track(title="Song"),
        facts={"track_title": "Ode to {artist_name}"},
    )

    assert rendered == "Ode to (artist_name)"
