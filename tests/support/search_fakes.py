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

from waves.desktop import backend
from waves.desktop.backend import WavesBridge
from waves.providers import Capability


class SearchStub:
    search = WavesBridge.search
    _fav_artist_dict = WavesBridge._fav_artist_dict
    _search_total = staticmethod(WavesBridge._search_total)
    _search_artist_meters = staticmethod(WavesBridge._search_artist_meters)
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
        # The real bridge registers TIDAL's session and Apple's switch as its
        # search gates; a stub that only carries TIDAL wires the session one
        # (an un-gated provider is taken at its word).
        self._provider_search_gates = {"tidal": lambda: bool(self._logged_in)}

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


def search_group(provider="tidal", album_ids=("al1",), pop=-1) -> dict:
    """One provider's group, shaped like the bridge's own builder."""
    return {
        "provider": provider,
        "artists_layout": "strip" if provider == "tidal" else "flow",
        "head_when_alone": provider != "tidal",
        "artists": [{"id": "a1", "name": "Artist 1", "art": "", "roles": "", "popularity": pop}],
        "albums": [{"id": i} for i in album_ids],
        "tracks": [],
        "videos": [],
        "playlists": [],
        "mixes": [],
        "top": None,
        "error": "",
    }


def search_payload(album_ids=("al1",), pop=-1) -> dict:
    return {"groups": [search_group(album_ids=album_ids, pop=pop)]}


def group_of(payload, provider="tidal") -> dict:
    """The payload's group for one provider (the pipeline's own order)."""
    for group in payload.get("groups") or []:
        if group.get("provider") == provider:
            return group
    return {}


#: Apple's search answers four result kinds; its group carries no video/mix
#: buckets. The QML scenario payloads below mirror the bridge's own builder,
#: so a seeded page has the shape a real search produces.
_APPLE_SECTIONS = ("artists", "albums", "tracks", "playlists")


def qml_search_payload(
    *,
    provider="tidal",
    artists=(),
    albums=(),
    tracks=(),
    videos=(),
    playlists=(),
    mixes=(),
    top=None,
    error="",
    layout=None,
) -> dict:
    """A one-provider search payload for QML scenarios.

    Row dicts go in untouched; only the buckets the provider's search answers
    are carried, exactly as the bridge composes them.
    """
    rows = {
        "artists": list(artists),
        "albums": list(albums),
        "tracks": list(tracks),
        "videos": list(videos),
        "playlists": list(playlists),
        "mixes": list(mixes),
    }
    names = _APPLE_SECTIONS if provider == "apple" else tuple(rows)
    group = {
        "provider": provider,
        "artists_layout": layout or ("strip" if provider == "tidal" else "flow"),
        # A lone TIDAL group is the page's own shape and stays headless; any
        # other provider's head says whose rows these are.
        "head_when_alone": provider != "tidal",
    }
    for name in names:
        group[name] = rows[name]
    group["top"] = top
    group["error"] = error
    return {"groups": [group]}


def wire_search(monkeypatch, stub, album_ids=("al1",), pop=50):
    """The catalog behind a search: a fake TIDAL provider serving the
    engine-object shape, plus the meter helpers. The search pipeline reads the
    wire exclusively through the Provider seam, so the fake lives on the
    stub's providers dict, where the real TidalProvider would sit."""
    artist = SimpleNamespace(id="a1", name="Artist 1")
    monkeypatch.setattr(backend, "_image", lambda obj, dimension=320: "")
    monkeypatch.setattr(backend, "_artist_roles", lambda a: "")
    monkeypatch.setattr(backend, "_artist_popularity", lambda a: pop)
    stub.providers = {
        "tidal": SimpleNamespace(
            name="TIDAL",
            capabilities=frozenset({Capability.SEARCH}),
            search_artists_layout="strip",
            search_head_when_alone=False,
            search=lambda needle: {
                "artists": [artist],
                "albums": [SimpleNamespace(id=i) for i in album_ids],
            },
        )
    }
