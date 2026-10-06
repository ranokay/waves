from dataclasses import replace

import pytest

from waves.metadata.catalog_identity import CatalogIdentity, CatalogLookup, resolve_candidates


def recording(media_id="tidal:1", **changes):
    return replace(
        CatalogIdentity(
            media_id=media_id,
            kind="track",
            title="Song",
            artist="Artist",
            identifier="USABC1200001",
            duration_ms=180123,
            explicit=False,
            version="",
            release_title="Album",
        ),
        **changes,
    )


def test_consistent_recording_is_eligible_and_keeps_origin_separate():
    origin = recording()
    candidate = recording("apple:2", release_title="Another album")
    result = resolve_candidates(origin, CatalogLookup((candidate,)))
    assert result.state == "high_confidence"
    assert result.automatic_eligible
    assert result.origin_id == "tidal:1"
    assert result.candidates[0].identity.media_id == "apple:2"


def test_identifier_collision_blocks_even_the_consistent_candidate():
    origin = recording()
    result = resolve_candidates(origin, CatalogLookup((recording("apple:2"), recording("apple:3", explicit=True))))
    assert result.state == "ambiguous"
    assert not result.automatic_eligible
    assert "collision" in " ".join(result.explanations).lower()


@pytest.mark.parametrize(
    "changes",
    [
        {"duration_ms": 181124},
        {"explicit": True},
        {"version": "2011 Remaster"},
        {"title": "Song (Live)"},
        {"artist": "Other Artist"},
        {"release_title": "Album (Remastered)"},
        {"identifier": "USABC1200002"},
    ],
)
def test_conflicting_facts_never_qualify_automatically(changes):
    result = resolve_candidates(recording(), CatalogLookup((recording("apple:2", **changes),)))
    assert not result.automatic_eligible
    assert result.candidates[0].conflicts


@pytest.mark.parametrize(
    "changes",
    [
        {"identifier": ""},
        {"identifier": "broken"},
        {"duration_ms": None},
        {"duration_ms": 0},
        {"explicit": None},
        {"version": None},
        {"release_title": ""},
        {"artist": ""},
        {"title": ""},
    ],
)
def test_missing_facts_remain_unresolved(changes):
    result = resolve_candidates(recording(), CatalogLookup((recording("apple:2", **changes),)))
    assert result.state == "unresolved"
    assert result.candidates[0].missing


def test_precise_duration_compares_raw_milliseconds_with_a_one_second_bound():
    assert resolve_candidates(
        recording(), CatalogLookup((recording("apple:2", duration_ms=181123),))
    ).automatic_eligible
    assert not resolve_candidates(
        recording(), CatalogLookup((recording("apple:2", duration_ms=181124),))
    ).automatic_eligible


def test_confirmation_is_scoped_and_never_promotes_future_automatic_routing():
    result = resolve_candidates(recording(), CatalogLookup((recording("apple:2", identifier="", explicit=None),)))
    confirmed = result.confirm("apple:2")
    assert confirmed.state == "user_confirmed"
    assert confirmed.confirmed_id == "apple:2"
    assert not confirmed.automatic_eligible
    assert result.state == "unresolved"
    with pytest.raises(ValueError):
        result.confirm("apple:missing")


def test_competing_candidates_and_incomplete_lookups_require_review():
    assert (
        resolve_candidates(recording(), CatalogLookup((recording("apple:2"), recording("apple:3")))).state
        == "ambiguous"
    )
    assert not resolve_candidates(
        recording(), CatalogLookup((recording("apple:2"),), complete=False)
    ).automatic_eligible
    assert resolve_candidates(recording(), CatalogLookup()).state == "unresolved"


def test_duplicate_api_rows_do_not_create_ambiguity_but_conflicting_same_id_rows_do():
    candidate = recording("apple:2")
    assert resolve_candidates(recording(), CatalogLookup((candidate, candidate))).automatic_eligible
    assert not resolve_candidates(
        recording(), CatalogLookup((candidate, replace(candidate, explicit=True)))
    ).automatic_eligible


def release(media_id="tidal:album", **changes):
    track = recording(media_id.split(":")[0] + ":track", track_number=1, disc_number=1)
    return replace(
        CatalogIdentity(
            media_id=media_id,
            kind="album",
            title="Album",
            artist="Artist",
            identifier="123456789012",
            explicit=False,
            version="",
            release_title="Album",
            release_artist="Artist",
            release_date="2020-01-01",
            release_upc="123456789012",
            track_count=1,
            tracks=(track,),
            tracks_complete=True,
        ),
        **changes,
    )


def test_album_needs_upc_and_release_and_ordered_recording_evidence():
    assert resolve_candidates(release(), CatalogLookup((release("apple:album"),))).automatic_eligible
    for changes in (
        {"release_date": "2021-01-01"},
        {"title": "Album (Deluxe)"},
        {"tracks_complete": False},
        {"tracks": ()},
        {"release_upc": ""},
        {"tracks": (recording("apple:clean", explicit=True),)},
    ):
        assert not resolve_candidates(release(), CatalogLookup((release("apple:album", **changes),))).automatic_eligible


def test_album_repeated_entries_and_order_are_preserved_in_identity():
    first = recording(track_number=1, disc_number=1)
    second = recording("tidal:2", identifier="USABC1200002", title="Second", track_number=2, disc_number=1)
    origin = release(track_count=3, tracks=(first, second, first))
    equivalent = release("apple:album", track_count=3, tracks=(first, second, first))
    assert resolve_candidates(origin, CatalogLookup((equivalent,))).automatic_eligible
    reordered = replace(equivalent, tracks=(first, first, second))
    assert not resolve_candidates(origin, CatalogLookup((reordered,))).automatic_eligible


def test_strict_edition_uses_existing_release_policy_value():
    facts = {
        "release_artist": "Artist",
        "release_date": "2020-01-01",
        "release_upc": "123456789012",
        "track_count": 1,
        "track_number": 1,
        "disc_number": 1,
    }
    origin = recording(**facts)
    candidate = recording("apple:2", **facts)
    assert resolve_candidates(origin, CatalogLookup((candidate,)), "release").automatic_eligible
    other = replace(candidate, release_title="Compilation")
    assert resolve_candidates(origin, CatalogLookup((other,))).automatic_eligible
    assert not resolve_candidates(origin, CatalogLookup((other,)), "release").automatic_eligible


@pytest.mark.parametrize("origin_kind,candidate_kind", [("track", "video"), ("video", "track"), ("video", "video")])
def test_audio_isrc_never_establishes_video_equivalence(origin_kind, candidate_kind):
    result = resolve_candidates(
        recording(kind=origin_kind), CatalogLookup((recording("apple:2", kind=candidate_kind),))
    )
    assert not result.automatic_eligible
    assert not result.confirm("apple:2").automatic_eligible


def test_remaster_year_is_identity_evidence_even_when_isrc_is_shared():
    origin = recording(release_title="Album (2009 Remaster)")
    candidate = recording("apple:2", release_title="Album (2015 Remaster)")
    assert not resolve_candidates(origin, CatalogLookup((candidate,))).automatic_eligible


def test_candidate_bound_does_not_hide_collisions_behind_an_eligible_first_row():
    candidates = tuple(recording(f"apple:{index}") for index in range(11))
    assert not resolve_candidates(recording(), CatalogLookup(candidates)).automatic_eligible
