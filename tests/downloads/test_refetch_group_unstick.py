"""A failed re-fetch must not strand a discography group at "running".

_refetch_for_download is the fallback when a download is requested for an id
whose live object was evicted from _objs (a new search clears every bucket; a
discography video scan can even fill a whole bucket by itself, evicting its
own earliest members). When that re-fetch fails, the item never enters the
queue, yet its id stays in the artist group's key set. Without a "failed"
bump on the failure exits, len(done) can never reach len(keys): the artist
button spins forever and the group dict leaks for the session.

These tests bind the REAL _refetch_for_download and the real group bump
helpers over an inline pool, and require both failure exits (fetch failed,
and account switched mid-fetch) to settle the group.
"""

from __future__ import annotations

from collections import deque
from threading import Lock
from types import SimpleNamespace

from providers.fakes import StubProvider

from waves.constants import CTX_TIDAL
from waves.desktop.backend import WavesBridge
from waves.desktop.queue.bridge import QueueMixin
from waves.desktop.queue.runtime import JobRuntime
from waves.providers import Capability


class _Stub(QueueMixin):
    """Bare object the real methods get bound onto."""


def _bind(stub, name):
    return getattr(WavesBridge, name).__get__(stub, type(stub))


class _Sig:
    def __init__(self):
        self.emits: list = []

    def emit(self, *args):
        self.emits.append(args)


class _InlinePool:
    def start(self, worker):
        worker.fn()


def _stub(session_video):
    stub = _Stub()
    stub._refetch_inflight = set()
    stub._logged_in = True
    stub._browse_gen = 1
    stub._browse_lock = Lock()
    stub.tidal = SimpleNamespace(session=SimpleNamespace(video=session_video))
    # The Provider seam (and the Chooser's parked-click drop) are the only
    # roads the real method travels now: route get_object through the same
    # session callable, looked up late so the account-switch test's
    # reassignment still takes effect, and bind the real drop (a no-op
    # without parked pins).
    provider = StubProvider(CTX_TIDAL, "TIDAL", capabilities={Capability.CATALOG}, logged_in=True)
    provider.get_object = lambda bucket, media_id: stub.tidal.session.video(media_id)
    stub.providers = {CTX_TIDAL: provider}
    stub._queue = []
    stub._queue_lock = Lock()
    stub._reindex_queue()
    stub._jobs = JobRuntime()
    stub._pending_qids = deque()
    stub._pending_lock = Lock()
    stub._pending_downloads = []
    stub._merge_plans = {}
    stub._redownload_overrides = set()
    stub._library_claim_overrides = set()
    stub._search_gen = 0
    stub._set_busy = lambda busy: None
    stub._set_login_busy = lambda provider_id, busy: None
    stub.providerStateChanged = _Sig()
    stub._schedule_provider_cache_clear = lambda provider_id: None
    stub._end_provider_context = _bind(stub, "_end_provider_context")
    stub._stop_provider_downloads = _bind(stub, "_stop_provider_downloads")
    stub._release_abandoned_hold = _bind(stub, "_release_abandoned_hold")
    stub._chooser_drop_refetch = _bind(stub, "_chooser_drop_refetch")
    stub.threadpool = _InlinePool()
    stub.downloadState = _Sig()
    stub.downloadProgress = _Sig()
    stub.statuses: list = []
    stub._set_status = stub.statuses.append
    # A one-member discography group: the strand is visible immediately.
    stub._artist_groups = {"art1": {"keys": {"9"}, "done": set(), "failed": set(), "prog": {}}}
    stub._artist_lock = Lock()
    stub._folder_groups = {}
    stub._folder_lock = Lock()
    stub._scan_gen = 0
    stub._bump_download_groups = _bind(stub, "_bump_download_groups")
    stub._bump_artist_group = _bind(stub, "_bump_artist_group")
    stub._bump_folder_group = _bind(stub, "_bump_folder_group")
    stub._refetch_for_download = _bind(stub, "_refetch_for_download")
    return stub


def test_a_failed_refetch_settles_its_group_as_failed():
    def _raise(_vid):
        raise RuntimeError("429")

    stub = _stub(_raise)
    stub._refetch_for_download("video", "9")
    assert stub._artist_groups == {}, "the finished group must be deleted, not leak"
    assert ("art1", "failed") in stub.downloadState.emits, "the artist button must leave 'running'"
    assert ("9", "failed") in stub.downloadState.emits
    assert stub._refetch_inflight == set()


def test_an_account_switch_mid_fetch_settles_the_group_too():
    stub = _stub(lambda _vid: SimpleNamespace(id=9))

    # The fetch succeeds, but the account generation moved on underneath it:
    # the download must not start, and the group must still settle.
    real_video = stub.tidal.session.video

    def _switch(vid):
        stub._end_provider_context(CTX_TIDAL, "Account changed")
        return real_video(vid)

    stub.tidal.session.video = _switch
    stub._refetch_for_download("video", "9")
    assert stub._artist_groups == {}, "the finished group must be deleted, not leak"
    assert ("art1", "") in stub.downloadState.emits
    assert stub._refetch_inflight == set()
