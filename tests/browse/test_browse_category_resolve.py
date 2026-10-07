"""Browse category resolve: a failure must never be pinned for the session.

WHAT THIS FENCES OFF
--------------------
``resolvePlaylistCategory`` gathers every playlist in one editorial category so
the DOWNLOAD ALL confirm can state a real count. An ``except`` branch that
falls through into the normal path writes its empty list into ``_category_pl``
and clears the status line. ``_category_pl`` has no TTL and is cleared only at
logout, and the fast path treats any non-None entry as authoritative, so a
single network blip leaves that tile's DOWNLOAD ALL and PREVIEW as silent
no-ops until the user signs out. The QML handler drops a zero count without a
word (`if (count <= 0) return   // backend already set the status line`), so
the click produces no dialog, no error and no status either.
"""

from __future__ import annotations

from threading import Lock
from types import SimpleNamespace

from providers.fakes import StubProvider

from waves.desktop.backend import WavesBridge
from waves.providers.base import Capability


class _Signal:
    def __init__(self):
        self.emits: list = []

    def emit(self, *args):
        self.emits.append(args)


class _InlinePool:
    """Runs the resolve worker on the calling thread, so the test can assert
    on what it left behind without a wait."""

    @staticmethod
    def start(worker):
        worker.fn()


class _ResolveStub:
    resolvePlaylistCategory = WavesBridge.resolvePlaylistCategory
    _browse_page_for = WavesBridge._browse_page_for
    _cached_category = WavesBridge._cached_category
    _cache_category = WavesBridge._cache_category
    _CATEGORY_PL_TTL = WavesBridge._CATEGORY_PL_TTL
    _CATEGORY_PL_MAX = WavesBridge._CATEGORY_PL_MAX

    def __init__(self, page, provider_id="tidal"):
        self._page = page
        self._provider_id = provider_id
        self._logged_in = True
        self._category_pl: dict[str, tuple[float, list]] = {}
        self._browse_loading: set[str] = set()
        self._browse_gen = 0
        self._objs = {"playlist": {}}
        self._lock = Lock()
        self.threadpool = _InlinePool()
        self.statuses: list = []
        self.playlistCategoryResolved = _Signal()
        # The resolve rides the named provider's own seam (issue #600).
        own = StubProvider(provider_id, provider_id.title(), capabilities={Capability.BROWSE}, logged_in=True)
        own.calls = []
        own.browse_page = lambda title, api_path: self._answer(title, api_path)
        self.providers = {provider_id: own}

    def _answer(self, title, api_path):
        self.providers[self._provider_id].calls.append((title, api_path))
        if isinstance(self._page, Exception):
            raise self._page
        return self._page

    def _remember(self, bucket, key, obj):
        self._objs[bucket][key] = obj

    def _set_busy(self, on):
        pass

    def _set_status(self, text):
        self.statuses.append(text)


def _empty_page():
    return SimpleNamespace(categories=[])


def test_a_failed_resolve_is_not_cached_and_says_so():
    stub = _ResolveStub(RuntimeError("connection reset"))
    stub.resolvePlaylistCategory("pages/mood/chill", "Chill")

    assert stub._category_pl == {}, "a transient failure must not be pinned for the session"
    assert stub.statuses[-1] == "Could not load this category"
    assert stub.playlistCategoryResolved.emits[-1] == ("pages/mood/chill", "Chill", 0, "", "tidal")
    # The retry is a real retry, not a cache hit: it fetches again.
    stub._page = _empty_page()
    stub.resolvePlaylistCategory("pages/mood/chill", "Chill")
    assert stub.statuses[-1] == "No playlists in this category"


def test_an_empty_category_is_not_cached_either():
    """Same no-empty-cache rule the landing and the drilled grid follow: a page
    whose rows all failed to normalize must not be pinned for the session."""
    stub = _ResolveStub(_empty_page())
    stub.resolvePlaylistCategory("pages/decade/1990s", "1990s")
    assert stub._category_pl == {}
    assert stub.statuses[-1] == "No playlists in this category"


def test_a_resolved_category_is_cached_and_served_from_cache():
    from tidalapi.playlist import Playlist

    one = Playlist.__new__(Playlist)
    one.id = "pl-1"
    page = SimpleNamespace(categories=[SimpleNamespace(items=[one])])

    stub = _ResolveStub(page)
    stub.resolvePlaylistCategory("pages/mood/focus", "Focus")
    assert [str(p.id) for p in stub._category_pl["cat:tidal:pages/mood/focus"][1]] == ["pl-1"]
    assert stub.statuses[-1] == ""
    assert stub.playlistCategoryResolved.emits[-1] == ("pages/mood/focus", "Focus", 1, "pl-1", "tidal")

    # Second click: served from the cache, no refetch.
    stub._page = RuntimeError("must not be called")
    stub.resolvePlaylistCategory("pages/mood/focus", "Focus")
    assert stub.playlistCategoryResolved.emits[-1] == ("pages/mood/focus", "Focus", 1, "pl-1", "tidal")


def test_the_resolve_routes_through_the_named_provider():
    stub = _ResolveStub(_empty_page(), provider_id="stub")
    stub.resolvePlaylistCategory("pages/mood/chill", "Chill", "stub")
    assert stub.providers["stub"].calls == [("Chill", "pages/mood/chill")]
    assert stub.playlistCategoryResolved.emits[-1] == ("pages/mood/chill", "Chill", 0, "", "stub")

    # An unknown/disabled owner makes no request; it answers a zero count and
    # a status so the queued action's pending flags clear.
    stub.resolvePlaylistCategory("pages/mood/chill", "Chill", "ghost")
    assert stub.providers["stub"].calls == [("Chill", "pages/mood/chill")]
    assert stub.playlistCategoryResolved.emits[-1] == ("pages/mood/chill", "Chill", 0, "", "ghost")
    assert stub.statuses[-1] == "Could not load this category"
