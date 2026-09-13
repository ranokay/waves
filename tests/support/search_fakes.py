"""A bare stand-in for the bridge's search pipeline, on an inline pool.

``SearchStub`` binds the real ``WavesBridge.search`` (and the cache/eviction
helpers it calls) onto a minimal object, so search tests can drive the real
pipeline without Qt or a session. ``wire_search`` plants the fake TIDAL
provider that the pipeline reads exclusively through the Provider seam, and
``search_payload`` documents the payload shape the tests assert on. Shared by
the stale-revalidate and query-hygiene suites so no test module imports
another.
"""

from __future__ import annotations

from threading import Lock
from types import SimpleNamespace

from conftest import _InlinePool, _Signal

from waves.providers import Capability
from waves.waves_ui import backend
from waves.waves_ui.backend import WavesBridge


class SearchStub:
    search = WavesBridge.search
    _search_total = staticmethod(WavesBridge._search_total)
    _pop_cached = WavesBridge._pop_cached
    _remember_capped = WavesBridge._remember_capped
    _remember_search = WavesBridge._remember_search
    _SEARCH_TTL = WavesBridge._SEARCH_TTL
    _SEARCH_CACHE_MAX = WavesBridge._SEARCH_CACHE_MAX
    _ARTIST_POP_TTL = WavesBridge._ARTIST_POP_TTL
    _ARTIST_POP_MAX = WavesBridge._ARTIST_POP_MAX

    def __init__(self):
        self.threadpool = _InlinePool()
        self.statuses: list[str] = []
        self.busy: list[bool] = []
        self.saves = 0
        self._logged_in = True
        self._search_gen = 0
        self._search_cache: dict = {}
        self._evict_lock = Lock()
        self._artist_pop_cache: dict = {}
        self._objs_lock = Lock()
        self._objs: dict = {"artist": {}, "album": {}, "track": {}, "video": {}, "playlist": {}, "mix": {}}
        self.tidal = SimpleNamespace(session=object())
        self.searchResults = _Signal()
        self.artistMetaLoaded = _Signal()

    def _set_status(self, text):
        self.statuses.append(text)

    def _set_busy(self, on):
        self.busy.append(bool(on))

    def _save_page_cache(self):
        self.saves += 1

    def _remember(self, kind, key, obj):
        self._objs[kind][key] = obj

    def _dedup_albums(self, albums):
        return list(albums)

    def _dedup_tracks(self, tracks):
        return list(tracks)

    def _dedup_videos(self, videos):
        return list(videos)

    def _album_dict(self, a):
        return {"id": getattr(a, "id", "")}

    def _track_dict(self, t):
        return {"id": getattr(t, "id", "")}

    def _video_dict(self, v):
        return {"id": getattr(v, "id", "")}

    def _playlist_dict(self, p):
        return {"id": getattr(p, "id", "")}

    def _mix_dict(self, m):
        return {"id": getattr(m, "id", "")}

    def _top_hit_dict(self, hit):
        return None


def search_payloads(stub):
    """The emitted payload dicts, whatever shape the signal stub keeps."""
    return [e[0] if isinstance(e, tuple) else e for e in stub.searchResults.emits]


def search_payload(album_ids=("al1",), pop=-1):
    return {
        "artists": [{"id": "a1", "name": "Artist 1", "art": "", "roles": "", "popularity": pop}],
        "albums": [{"id": i} for i in album_ids],
        "tracks": [],
        "videos": [],
        "playlists": [],
        "mixes": [],
        "top": None,
    }


def wire_search(monkeypatch, stub, album_ids=("al1",), pop=50):
    """The catalog behind a search: a fake TIDAL provider serving the old
    engine-object shape, plus the meter helpers. The search pipeline reads
    the wire exclusively through the Provider seam (it no longer calls a
    backend-module ``search_results_all``), so the fake lives on the stub's
    providers dict, where the real TidalProvider would sit."""
    artist = SimpleNamespace(id="a1", name="Artist 1")
    monkeypatch.setattr(backend, "_image", lambda obj, dimension=320: "")
    monkeypatch.setattr(backend, "_artist_roles", lambda a: "")
    monkeypatch.setattr(backend, "_artist_popularity", lambda a: pop)
    stub.providers = {
        "tidal": SimpleNamespace(
            name="TIDAL",
            capabilities=frozenset({Capability.SEARCH}),
            search=lambda needle: {
                "artists": [artist],
                "albums": [SimpleNamespace(id=i) for i in album_ids],
            },
        )
    }
