"""What a finished collection download reports as its outcome.

The verdict comes from the per-track counters: any failure surfaces the
shortfall, tracks TIDAL refuses to stream are footnoted rather than failed,
and an all-owned collection (only ownership skips, no failures) is still a
real success.
"""

from __future__ import annotations

import pytest

from waves.desktop.backend import _collection_incomplete_reason, _unavailable_note


@pytest.mark.parametrize(
    ("write_count", "ok_count", "fail_count", "expected"),
    [
        # write, ok, fail -> reason (None means "real success")
        (20, 20, 0, None),  # every new track downloaded
        (0, 10, 0, None),  # every track already owned (skips count as ok)
        (5, 5, 0, None),  # a small fully-successful new download
        (19, 19, 1, "1 of 20 tracks failed"),  # one failure among successes must not read as done
        (0, 3, 2, "2 of 5 tracks failed"),  # partly owned, some new tracks failed
        (0, 0, 5, "5 of 5 tracks failed"),  # every track failed
        (0, 0, 0, "no tracks were downloaded"),  # nothing handled at all
    ],
)
def test_collection_incomplete_reason(write_count, ok_count, fail_count, expected):
    assert _collection_incomplete_reason(write_count, ok_count, fail_count) == expected


def test_a_single_failure_is_surfaced_even_with_many_successes():
    # Successes must not mask a failure.
    assert _collection_incomplete_reason(99, 99, 1) == "1 of 100 tracks failed"


# --- tracks TIDAL refuses to stream ------------------------------------------
# A delisted track is not a failure of this app and no retry can turn it into a
# file, so it may not fail the album around it. What it may not do either is
# prop up a false success on an album that produced nothing.


@pytest.mark.parametrize(
    ("write_count", "ok_count", "fail_count", "unavailable_count", "expected"),
    [
        # Most of a commentary edition landed, TIDAL withheld three tracks:
        # the album is finished, and the shortfall is the status line's job.
        (12, 12, 0, 3, None),
        (14, 14, 0, 1, None),
        # Every track owned already, one delisted since: still a success.
        (0, 10, 0, 1, None),
        # Every track refused, nothing written: not "15 of 15 tracks failed",
        # and not a green done over an empty folder either.
        (0, 0, 0, 15, "not available on TIDAL anymore (15 tracks)"),
        (0, 0, 0, 1, "not available on TIDAL anymore (1 track)"),
        # A real failure still leads, and the refusals count toward the total so
        # the arithmetic matches the album the user is looking at.
        (10, 10, 2, 3, "2 of 15 tracks failed"),
    ],
)
def test_unavailable_tracks_do_not_fail_the_collection(write_count, ok_count, fail_count, unavailable_count, expected):
    assert _collection_incomplete_reason(write_count, ok_count, fail_count, unavailable_count) == expected


def test_a_refused_release_says_so_rather_than_nothing_downloaded():
    assert _collection_incomplete_reason(0, 0, 0, 0, True) == "this release is not available on TIDAL anymore"


def test_unavailable_note_is_a_footnote_not_a_failure():
    assert _unavailable_note(0) == ""
    assert _unavailable_note(1) == " (1 track no longer on TIDAL)"
    assert _unavailable_note(3) == " (3 tracks no longer on TIDAL)"
