"""A resolved Browse category must not be trusted for the life of the process.

WHAT THIS FENCES OFF
--------------------
``_category_pl`` with no TTL, no revalidation and no eviction, cleared only at
logout, goes stale for a process designed to run for weeks (see the always-on
freshness rule):

  DOWNLOAD ALL on a category says "Download 24 playlists?", the user cancels.
  Weeks later the category holds 30: the drilled grid re-fetches and shows all
  30, but the tile still reports 24 and downloadPlaylistCategory queues exactly
  the old objects, including any TIDAL has since removed.

Contrast openBrowsePage, which revalidates its cached page on every open.
Serving stale-then-revalidating is wrong HERE specifically: the resolve emit
runs whatever action the tile queued, so a late correction arrives after the
confirm dialog has already been answered against the old count.
"""

from __future__ import annotations

from waves.desktop.backend import WavesBridge


class _CacheStub:
    _cached_category = WavesBridge._cached_category
    _cache_category = WavesBridge._cache_category
    _CATEGORY_PL_TTL = WavesBridge._CATEGORY_PL_TTL
    _CATEGORY_PL_MAX = WavesBridge._CATEGORY_PL_MAX

    def __init__(self):
        self._category_pl: dict[str, tuple[float, list]] = {}


def test_a_fresh_entry_is_served():
    stub = _CacheStub()
    stub._cache_category("pages/mood/chill", ["a", "b"])
    assert stub._cached_category("pages/mood/chill") == ["a", "b"]


def test_a_stale_entry_is_dropped_not_served():
    stub = _CacheStub()
    stub._cache_category("pages/mood/chill", ["a", "b"])
    ts, playlists = stub._category_pl["pages/mood/chill"]
    stub._category_pl["pages/mood/chill"] = (ts - WavesBridge._CATEGORY_PL_TTL - 1, playlists)

    assert stub._cached_category("pages/mood/chill") is None
    assert "pages/mood/chill" not in stub._category_pl, "the stale entry must be evicted, not just skipped"


def test_the_cache_is_bounded():
    """Probing tile after tile held a full Playlist list per api path for the
    rest of the session."""
    stub = _CacheStub()
    for i in range(WavesBridge._CATEGORY_PL_MAX + 5):
        stub._cache_category(f"pages/mood/{i}", [i])

    assert len(stub._category_pl) == WavesBridge._CATEGORY_PL_MAX
    assert stub._cached_category("pages/mood/0") is None, "oldest out first"
    newest = WavesBridge._CATEGORY_PL_MAX + 4
    assert stub._cached_category(f"pages/mood/{newest}") == [newest]


def test_the_ttl_window_is_long_enough_to_answer_a_confirm():
    """The dialog is answered in seconds; the entry that built it must still be
    there when OK is pressed. This is a guard on the constant, not the code."""
    assert WavesBridge._CATEGORY_PL_TTL >= 60.0
    assert WavesBridge._CATEGORY_PL_TTL <= 3600.0


def test_download_uses_the_ttl_checked_read():
    """downloadPlaylistCategory must not reach past _cached_category into the
    raw dict, or the whole TTL is decorative for the one path that matters."""
    stub = _CacheStub()
    stub._cache_category("pages/mood/chill", ["a"])
    ts, playlists = stub._category_pl["pages/mood/chill"]
    stub._category_pl["pages/mood/chill"] = (ts - WavesBridge._CATEGORY_PL_TTL - 1, playlists)

    seen: list = []
    stub._logged_in = True
    stub._set_status = seen.append
    WavesBridge.downloadPlaylistCategory(stub, "pages/mood/chill")

    assert seen and "open the category again" in seen[-1]
