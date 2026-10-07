"""Merge equivalence for search rows: only fully evidenced pairs fold.

The rule is deliberately narrower than display matching: a track folds only
when a valid ISRC, an exact edition-key title, one canonical artist, a
precise (within one second) duration and consistent explicitness all agree.
Anything less stays a separate row, labelled with its own source.
"""

from __future__ import annotations

from waves.providers.search_merge import fold_search_groups


def _track(row_id: str, **overrides) -> dict:
    row = {
        "id": row_id,
        "title": "Northern Grain",
        "artist": "Midnight Choir",
        "artist_id": "",
        "artists": [],
        "album": "Northern Grain",
        "album_id": "",
        "num": 1,
        "vol": 1,
        "art": "",
        "year": "2024",
        "date": "2024-01-01",
        "duration": "3:48",
        "duration_sec": 228,
        "quality": "LOSSLESS",
        "popularity": -1,
        "explicit": False,
        "added": "",
        "isrc": "USRC17607839",
    }
    row.update(overrides)
    return row


def _album(row_id: str, **overrides) -> dict:
    row = {
        "id": row_id,
        "title": "Northern Grain",
        "artist": "Midnight Choir",
        "artist_id": "",
        "artists": [],
        "art": "",
        "year": "2024",
        "date": "2024-01-01",
        "tracks": 10,
        "duration_sec": 2400,
        "quality": "LOSSLESS",
        "popularity": -1,
        "explicit": False,
        "added": "",
        # 4006381333931 is the canonical EAN-13 example: its checksum is valid.
        "upc": "4006381333931",
    }
    row.update(overrides)
    return row


def _artist(row_id: str, name: str = "Midnight Choir") -> dict:
    return {"id": row_id, "name": name, "art": "", "roles": "Artist", "popularity": -1}


def _group(provider: str, **buckets) -> dict:
    group = {"provider": provider}
    group.update(buckets)
    return group


def _sources(row: dict) -> list[dict]:
    return row["sources"]


def test_two_tracks_with_one_isrc_fold_to_the_earlier_groups_row() -> None:
    tidal = _track("tidal:t1")
    apple = _track("apple:a1", quality="HI_RES_LOSSLESS")
    folded = fold_search_groups([_group("tidal", tracks=[tidal]), _group("apple", tracks=[apple])])

    assert [row["id"] for row in folded["sections"]["tracks"]] == ["tidal:t1"]
    merged = folded["sections"]["tracks"][0]
    assert _sources(merged) == [
        {"provider": "tidal", "id": "tidal:t1"},
        {"provider": "apple", "id": "apple:a1"},
    ]


def test_a_duration_gap_over_one_second_keeps_tracks_separate() -> None:
    folded = fold_search_groups(
        [
            _group("tidal", tracks=[_track("tidal:t1", duration_sec=228)]),
            _group("apple", tracks=[_track("apple:a1", duration_sec=230)]),
        ]
    )
    rows = folded["sections"]["tracks"]
    assert [row["id"] for row in rows] == ["tidal:t1", "apple:a1"]
    assert [_sources(row) for row in rows] == [
        [{"provider": "tidal", "id": "tidal:t1"}],
        [{"provider": "apple", "id": "apple:a1"}],
    ]


def test_one_isrc_with_conflicting_titles_never_folds() -> None:
    folded = fold_search_groups(
        [
            _group("tidal", tracks=[_track("tidal:t1", title="Northern Grain")]),
            _group("apple", tracks=[_track("apple:a1", title="Paper Ferry")]),
        ]
    )
    assert [row["id"] for row in folded["sections"]["tracks"]] == ["tidal:t1", "apple:a1"]


def test_an_edition_qualifier_keeps_the_same_isrc_apart() -> None:
    folded = fold_search_groups(
        [
            _group("tidal", tracks=[_track("tidal:t1", title="Northern Grain")]),
            _group("apple", tracks=[_track("apple:a1", title="Northern Grain (Remastered)")]),
        ]
    )
    assert [row["id"] for row in folded["sections"]["tracks"]] == ["tidal:t1", "apple:a1"]


def test_an_unknown_or_invalid_isrc_stays_separately_labelled() -> None:
    folded = fold_search_groups(
        [
            _group("tidal", tracks=[_track("tidal:t1", isrc="")]),
            _group("apple", tracks=[_track("apple:a1", isrc="")]),
        ]
    )
    rows = folded["sections"]["tracks"]
    assert [row["id"] for row in rows] == ["tidal:t1", "apple:a1"]
    assert rows[0]["sources"] != rows[1]["sources"]


def test_an_explicitness_conflict_keeps_tracks_separate() -> None:
    folded = fold_search_groups(
        [
            _group("tidal", tracks=[_track("tidal:t1", explicit=False)]),
            _group("apple", tracks=[_track("apple:a1", explicit=True)]),
        ]
    )
    assert [row["id"] for row in folded["sections"]["tracks"]] == ["tidal:t1", "apple:a1"]


def test_an_artist_spelled_with_a_different_canonical_form_still_folds() -> None:
    folded = fold_search_groups(
        [
            _group("tidal", tracks=[_track("tidal:t1", artist="Bjork")]),
            _group("apple", tracks=[_track("apple:a1", artist="Björk")]),
        ]
    )
    assert [row["sources"] for row in folded["sections"]["tracks"]] == [
        [{"provider": "tidal", "id": "tidal:t1"}, {"provider": "apple", "id": "apple:a1"}]
    ]


def test_an_album_with_one_upc_and_track_count_folds() -> None:
    folded = fold_search_groups(
        [
            _group("tidal", albums=[_album("tidal:al1")]),
            _group("apple", albums=[_album("apple:al2")]),
        ]
    )
    rows = folded["sections"]["albums"]
    assert [row["id"] for row in rows] == ["tidal:al1"]
    assert _sources(rows[0]) == [
        {"provider": "tidal", "id": "tidal:al1"},
        {"provider": "apple", "id": "apple:al2"},
    ]


def test_an_album_without_a_upc_stays_separate() -> None:
    folded = fold_search_groups(
        [
            _group("tidal", albums=[_album("tidal:al1", upc="")]),
            _group("apple", albums=[_album("apple:al2", upc="")]),
        ]
    )
    assert [row["id"] for row in folded["sections"]["albums"]] == ["tidal:al1", "apple:al2"]


def test_an_album_track_count_conflict_keeps_releases_apart() -> None:
    folded = fold_search_groups(
        [
            _group("tidal", albums=[_album("tidal:al1", tracks=10)]),
            _group("apple", albums=[_album("apple:al2", tracks=12)]),
        ]
    )
    assert [row["id"] for row in folded["sections"]["albums"]] == ["tidal:al1", "apple:al2"]


def test_artists_and_playlists_never_fold_but_carry_their_source() -> None:
    folded = fold_search_groups(
        [
            _group("tidal", artists=[_artist("tidal:r1")], playlists=[{"id": "tidal:p1"}]),
            _group("apple", artists=[_artist("apple:r2", name="Midnight Choir")], playlists=[{"id": "apple:p2"}]),
        ]
    )
    assert [row["id"] for row in folded["sections"]["artists"]] == ["tidal:r1", "apple:r2"]
    assert [row["sources"] for row in folded["sections"]["artists"]] == [
        [{"provider": "tidal", "id": "tidal:r1"}],
        [{"provider": "apple", "id": "apple:r2"}],
    ]
    assert [row["id"] for row in folded["sections"]["playlists"]] == ["tidal:p1", "apple:p2"]


def test_a_bucket_no_arrived_provider_answers_is_absent() -> None:
    folded = fold_search_groups([_group("apple", artists=[_artist("apple:r2")], albums=[])])
    assert "mixes" not in folded["sections"] and "videos" not in folded["sections"]
    assert folded["sections"]["artists"][0]["id"] == "apple:r2"


def test_two_rows_from_one_provider_never_fold_together() -> None:
    # A provider's own duplicate reply is not a cross-provider equivalent:
    # both rows stay, each labelled with its own source.
    folded = fold_search_groups([_group("tidal", tracks=[_track("tidal:t1"), _track("tidal:t2")])])
    rows = folded["sections"]["tracks"]
    assert [row["id"] for row in rows] == ["tidal:t1", "tidal:t2"]
    assert [_sources(row) for row in rows] == [
        [{"provider": "tidal", "id": "tidal:t1"}],
        [{"provider": "tidal", "id": "tidal:t2"}],
    ]


def test_the_first_groups_pin_is_the_top_and_folds_like_a_row() -> None:
    top = {"kind": "track", **_track("tidal:t1")}
    folded = fold_search_groups(
        [
            _group("tidal", tracks=[_track("tidal:t1")], top=top),
            _group("apple", tracks=[_track("apple:a1")]),
        ]
    )
    assert folded["top"]["id"] == "tidal:t1"
    assert _sources(folded["top"]) == [
        {"provider": "tidal", "id": "tidal:t1"},
        {"provider": "apple", "id": "apple:a1"},
    ]


def test_folding_never_mutates_the_provider_groups() -> None:
    tidal = _track("tidal:t1")
    apple = _track("apple:a1")
    groups = [_group("tidal", tracks=[tidal]), _group("apple", tracks=[apple])]
    fold_search_groups(groups)
    assert tidal == _track("tidal:t1") and apple == _track("apple:a1")
