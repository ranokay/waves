"""When a stashed best-of-both merge plan survives and when it is released.

A stale batch drops it, a live batch and a held withdrawal keep it for the
replay, and only a really abandoned row releases it.
"""

from __future__ import annotations

import contextlib

from conftest import _Signal
from support.dispatch_stub import _queue_stub

from waves.desktop.backend import WavesBridge


class _EnqueueStub:
    _enqueue_albums = WavesBridge._enqueue_albums

    def __init__(self):
        self._scan_gen = 1
        self._merge_scanned: set[str] = set()
        self._merge_plans: dict[str, list] = {}
        self.downloadState = _Signal()
        self.queued: list[str] = []

    def downloadAlbum(self, key):
        self.queued.append(key)

    @contextlib.contextmanager
    def _queue_batch(self):
        yield


def test_a_stale_album_batch_drops_the_merge_plan_too():
    """STOP between the edition scan stashing its plan and the batch being
    delivered. The refusal already releases the scan exemption for exactly this
    reason; the plan needs the same treatment, or the next PLAIN click on that
    album silently downloads a cross-edition assembly with no "Best of both:"
    line anywhere to say so."""
    stub = _EnqueueStub()
    stub._merge_scanned.add("al1")
    stub._merge_plans["al1"] = ["a plan"]

    stub._enqueue_albums(0, ["al1"])  # gen 0 != _scan_gen 1: STOP landed

    assert stub.queued == [], "a stale batch queues nothing"
    assert stub._merge_scanned == set()
    assert stub._merge_plans == {}, "the plan outlived the batch that would have consumed it"


def test_a_live_album_batch_keeps_its_merge_plan():
    stub = _EnqueueStub()
    stub._merge_plans["al1"] = ["a plan"]

    stub._enqueue_albums(1, ["al1"])

    assert stub.queued == ["al1"]
    assert stub._merge_plans == {"al1": ["a plan"]}, "the download about to run needs it"


def test_a_plan_survives_a_row_withdrawn_because_the_download_is_only_HELD():
    """The folder gate withdraws the row precisely BECAUSE it stashed a replay,
    so that withdrawal is a hold, not a give-up. Popping the plan there means
    the share comes back, the merge replays from the closure, and a later RETRY
    of it re-downloads the album PLAIN, writing the identity edition's own
    lower-quality tracks over the ones the merge had borrowed."""
    s = _queue_stub(["queued"])
    s._merge_plans["m1"] = ["a plan the scan stashed"]
    s._pending_downloads = [("m1", lambda: None)]

    s._remove_row(1)

    assert s._merge_plans["m1"] == ["a plan the scan stashed"], "a held merge came back as a plain album"


def test_a_plan_is_still_released_when_the_row_is_really_abandoned():
    """The other side: nothing held, so the withdrawal is a give-up and the
    plan goes with it. Without this the hold check would disable the release it
    exists for."""
    s = _queue_stub(["queued"])
    s._merge_plans["m1"] = ["a plan the scan stashed"]
    s._pending_downloads = []

    s._remove_row(1)

    assert "m1" not in s._merge_plans


def test_a_plan_is_kept_while_a_live_row_still_holds_it():
    """RETRY re-queues the item BEFORE the old row is dropped, which is the
    whole reason the plan is peeked and not popped: a retried merge must stay a
    merge. The release rides the same liveness test as the REDOWNLOAD force."""
    s = _queue_stub(["failed", "queued"])
    s._queue[1]["media_id"] = "m1"  # the retry's new row for the same album
    s._merge_plans["m1"] = ["a plan the scan stashed"]

    s.clearFailed()

    assert s._merge_plans["m1"] == ["a plan the scan stashed"], "a retried merge was degraded to a plain download"
