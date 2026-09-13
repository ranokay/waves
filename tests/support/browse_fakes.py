"""Tidalapi-shaped fakes for the Browse item-page builders.

A hero image that honours every requested size, an unbuilt Track row, a bare
bridge wired to the offline catalog seam, and the page-loaded payload. Shared
by the item-prefetch and NEW-mark suites so no test module imports another.
"""

from __future__ import annotations

from threading import Lock
from types import SimpleNamespace

from conftest import _InlinePool, _Signal
from tidalapi.media import Track

import waves.waves_ui.backend as backend
from waves.constants import CTX_TIDAL
from waves.providers import TidalProvider
from waves.waves_ui.backend import WavesBridge


class Cover:
    """A tidalapi-shaped media object whose image() honours EVERY size it is
    asked for, so a header that asked for 480 would actually get a 480 URL
    (tidalapi rejects 480 for albums, which used to hide the bug there)."""

    def __init__(self, kind, mid, tracks):
        self.kind = kind
        self.id = mid
        self.name = f"{kind} {mid}"
        self.full_name = self.name
        self.artist = SimpleNamespace(id=7, name="Artist", roles=None)
        self.artists = [self.artist]
        self.audio_modes = None
        self.audio_quality = None
        self.media_metadata_tags = None
        self.release_date = None
        self.creator = SimpleNamespace(name="Curator")
        self.description = ""
        self._tracks = tracks

    def image(self, dimensions=320):
        return f"https://img.test/{self.kind}/{self.id}/{dimensions}x{dimensions}.jpg"

    def tracks(self, limit=None):
        return list(self._tracks)

    def items(self, limit=100, offset=0):
        return list(self._tracks)[offset : offset + limit]


def fake_track(tid, album):
    # A real Track (the page builder keeps only Track | Video rows), unbuilt.
    t = Track.__new__(Track)
    t.id = tid
    t.duration = 200
    t.album = album
    t.name = t.full_name = f"t{tid}"
    return t


def browse_bridge(obj, kind):
    b = WavesBridge.__new__(WavesBridge)
    b._logged_in = True
    b._browse_pages = {}
    b._browse_loading = set()
    b._browse_gen = 0
    b._evict_lock = Lock()
    b._objs = {"album": {}, "playlist": {}, "mix": {}, "track": {}, "video": {}}
    b._objs_lock = Lock()
    b._objs_max = 100
    b.recorded = []
    b._ownership = SimpleNamespace(record_members_replace=lambda cid, ids: b.recorded.append((cid, list(ids))))
    b.collectionMembershipChanged = _Signal()
    b.browsePageLoaded = _Signal()
    b.browsePagePrefetched = _Signal()
    b.threadpool = _InlinePool()
    b.tidal = SimpleNamespace(session=SimpleNamespace())
    # The catalog reads ride the provider (ticket #22); the real one over the
    # offline session keeps the builders' reads (advertised tier, mix items)
    # on their production shapes.
    b.providers = {CTX_TIDAL: TidalProvider(b.tidal)}
    b.busy_log = []
    b.status_log = []
    b._set_busy = lambda v: b.busy_log.append(v)
    b._set_status = lambda v: b.status_log.append(v)
    b._save_page_cache = lambda: None
    b._prefetch_lock = Lock()
    b._prefetch_key = None
    b._prefetch_claimed = False
    b._prefetch_unrecorded = set()
    b._item_fetch_ts = {}
    if obj is not None:
        b._objs[kind][str(obj.id)] = obj
    # The row builder is not under test: a thin stand-in that still reports
    # the 160 art a real _track_dict would, so the album override is visible.
    b._track_dict = lambda t: {
        "id": str(t.id),
        "kind": "track",
        "num": 1,
        "vol": 1,
        "art": backend._image(t, 160),
        "duration": "3:20",
        "duration_sec": t.duration,
    }
    return b


def page(b):
    assert len(b.browsePageLoaded.emits) == 1, b.browsePageLoaded.emits
    payload = b.browsePageLoaded.emits[0]
    assert payload["error"] is False
    return payload
