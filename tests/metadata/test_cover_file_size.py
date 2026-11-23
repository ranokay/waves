"""Cover-sidecar size and reuse of embedded artwork."""

from __future__ import annotations

from unittest.mock import MagicMock

from waves.constants import CoverDimensions, cover_file_dimension
from waves.download import Download

# ----- separate cover.jpg size ---------------------------------------------


def test_want_cover_file_scope_matrix():
    # Master toggle off -> never write cover.jpg, whatever the scope.
    assert Download._want_cover_file(False, True, True) is False
    # Album/collection download always writes when saving is on (today's behaviour).
    assert Download._want_cover_file(True, True, False) is True
    # A lone single track: off by default, on only when the user opts in.
    assert Download._want_cover_file(True, False, False) is False
    assert Download._want_cover_file(True, False, True) is True


def test_cover_file_dimension_follow_matches_embedded():
    assert cover_file_dimension(CoverDimensions.Px320, "follow") is CoverDimensions.Px320


def test_cover_file_dimension_explicit_and_invalid():
    assert cover_file_dimension(CoverDimensions.Px320, "Px640") is CoverDimensions.Px640
    # An unknown value never crashes; it falls back to the embedded size.
    assert cover_file_dimension(CoverDimensions.Px320, "not-a-size") is CoverDimensions.Px320


def _cover_fixture():
    dl = MagicMock(spec=Download)
    dl.cover_data_cached = MagicMock(return_value=b"fetched")
    track = MagicMock()
    track.album.image = MagicMock(side_effect=lambda d: f"url:{d}")
    return dl, track


def test_cover_file_data_reuses_embedded_when_sizes_match():
    dl, track = _cover_fixture()
    out = Download._album_cover_file_data(dl, track, b"embedded", CoverDimensions.Px320, CoverDimensions.Px320)
    assert out == b"embedded"
    dl.cover_data_cached.assert_not_called()  # no second download when sizes match


def test_cover_file_data_refetches_for_a_different_size():
    dl, track = _cover_fixture()
    out = Download._album_cover_file_data(dl, track, b"embedded", CoverDimensions.Px320, CoverDimensions.Px640)
    assert out == b"fetched"
    track.album.image.assert_called_once_with(int(CoverDimensions.Px640))


def test_cover_file_data_origin_fetches_original():
    dl, track = _cover_fixture()
    out = Download._album_cover_file_data(dl, track, b"embedded", CoverDimensions.Px320, CoverDimensions.PxORIGIN)
    assert out == b"fetched"
    track.album.image.assert_called_once_with(CoverDimensions.PxORIGIN)
