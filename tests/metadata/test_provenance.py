"""Origin descriptive facts, delivered technical facts.

ADR 0011: descriptive metadata defaults to origin; a missing origin field is
filled from the delivered item only for a consistent match. Item/artist ids,
ISRC, UPC, codec and quality always describe the delivered file.
"""

from __future__ import annotations

from waves.metadata.catalog_identity import CatalogIdentity
from waves.metadata.provenance import album_path_facts, origin_facts, path_facts, resolve_track_facts


def _track_identity(**changes) -> CatalogIdentity:
    values = {
        "media_id": "tidal:1",
        "kind": "track",
        "title": "Origin Title",
        "artist": "Origin Artist",
        "identifier": "USSM1000001",
        "duration_ms": 200000,
        "explicit": False,
        "version": None,
        "release_title": "Origin Album",
        "release_artist": "Origin Album Artist",
        "release_date": "1999-01-02",
        "track_number": 2,
        "disc_number": 1,
        "track_count": 10,
    }
    values.update(changes)
    return CatalogIdentity(**values)


def _delivered() -> dict:
    return {
        "item_id": "apple:42",
        "artist_ids": ["apple:artist"],
        "album_artist_ids": ["apple:album-artist"],
        "artists": [("apple:artist", "Delivered Artist")],
        "album_artists": ["Delivered Album Artist"],
        "copyright": "Delivered Copyright",
        "isrc": "GBAAA0000001",
        "explicit": True,
        "bpm": 120,
        "key": "C",
        "key_scale": "major",
        "share_url": "https://delivered/42",
        "volume_num": 1,
        "track_num": 2,
        "release_date": "2024-05-06",
        "release_type": "album",
        "album": {
            "name": "Delivered Album",
            "num_tracks": 12,
            "num_volumes": 1,
            "upc": "123456789012",
            "type": "ALBUM",
        },
    }


def test_origin_descriptive_facts_win_but_delivered_technical_facts_stay():
    resolved = resolve_track_facts(
        _delivered(),
        origin_facts(_track_identity()),
        "origin",
        True,
        delivered_title="Delivered Title",
    )

    assert resolved["title"] == "Origin Title"
    assert resolved["artists"] == [("apple:artist", "Origin Artist")]
    assert resolved["album"]["name"] == "Origin Album"
    assert resolved["album_artists"] == ["Origin Album Artist"]
    assert resolved["release_date"] == "1999-01-02"
    assert resolved["track_num"] == 2
    # Technical / delivered facts are never taken from origin.
    assert resolved["item_id"] == "apple:42"
    assert resolved["isrc"] == "GBAAA0000001"
    assert resolved["album"]["upc"] == "123456789012"
    assert resolved["album"]["num_volumes"] == 1


def test_fulfillment_source_uses_the_delivered_facts_untouched():
    delivered = _delivered()

    resolved = resolve_track_facts(
        delivered,
        origin_facts(_track_identity()),
        "fulfillment",
        True,
        delivered_title="Delivered Title",
    )

    assert resolved == delivered


def test_a_missing_origin_field_fills_only_for_a_consistent_match():
    origin = origin_facts(_track_identity(artist=""))
    consistent = resolve_track_facts(_delivered(), origin, "origin", True, delivered_title="Delivered Title")
    inconsistent = resolve_track_facts(_delivered(), origin, "origin", False, delivered_title="Delivered Title")

    assert consistent["artists"] == [("apple:artist", "Delivered Artist")]
    assert inconsistent["artists"] == []


def test_an_album_offer_matches_its_ordered_track_list_by_position():
    album = CatalogIdentity(
        media_id="tidal:album",
        kind="album",
        title="Origin Album",
        artist="Origin Album Artist",
        identifier="123456789012",
        release_title="Origin Album",
        release_artist="Origin Album Artist",
        release_date="1999-01-02",
        track_count=2,
        tracks=(
            _track_identity(media_id="tidal:1", title="One", track_number=1),
            _track_identity(media_id="tidal:2", title="Two", track_number=2),
        ),
        tracks_complete=True,
    )
    delivered = _delivered()

    resolved = resolve_track_facts(delivered, origin_facts(album), "origin", True, delivered_title="Two")

    assert resolved["title"] == "Two"
    assert resolved["album"]["name"] == "Origin Album"


def test_an_album_entry_that_cannot_be_matched_keeps_delivered_facts():
    album = CatalogIdentity(
        media_id="tidal:album",
        kind="album",
        title="Origin Album",
        artist="Origin Album Artist",
        release_title="Origin Album",
        release_artist="Origin Album Artist",
        release_date="1999-01-02",
        track_count=1,
        tracks=(_track_identity(media_id="tidal:1", title="One", track_number=1),),
        tracks_complete=False,
    )

    resolved = resolve_track_facts(_delivered(), origin_facts(album), "origin", True, delivered_title="Delivered")

    assert resolved["title"] == "Delivered"
    assert resolved["album"]["name"] == "Delivered Album"


def test_path_facts_describe_the_resolved_track_and_leave_ordering_alone():
    resolved = resolve_track_facts(_delivered(), origin_facts(_track_identity()), "origin", True)
    values = path_facts(resolved)

    assert values["track_title"] == "Origin Title"
    assert values["artist_name"] == "Origin Artist"
    assert values["album_title"] == "Origin Album"
    assert values["album_year"] == "1999"
    assert "list_pos" not in values
    assert "album_track_num" not in values


def test_album_path_facts_name_the_origin_release():
    album = CatalogIdentity(
        media_id="tidal:album",
        kind="album",
        title="Origin Album",
        artist="Origin Album Artist",
        release_title="Origin Album",
        release_artist="Origin Album Artist",
        release_date="1999-01-02",
        track_count=2,
    )

    values = album_path_facts(origin_facts(album))

    assert values["album_title"] == "Origin Album"
    assert values["album_artist"] == "Origin Album Artist"
    assert values["album_year"] == "1999"
