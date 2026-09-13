"""Disabling Apple Music stops its work and leaves it retryable.

The switch means "stop using Apple", so its queued and running rows stop with
it; rows that keep fetching behind a vanished search group mislead. Nothing is
lost: the rows stay in Stopped with the reason, RETRY / RETRY ALL picks them
up after the switch is back on, and a retry attempted while it is still off is
refused with the row left in place. No TIDAL work (including TIDAL work held
for the download folder to return) is touched. The running row's worker
settles itself as cancelled, so the stop's words must survive that wordless
settle without leaking into ordinary settles.
"""

from __future__ import annotations

from collections import deque
from threading import Event, Lock
from types import SimpleNamespace

from waves.constants import CTX_APPLE
from waves.waves_ui.backend import WavesBridge

_REASON = "Apple Music was disabled"


def _stop_stub() -> SimpleNamespace:
    stub = SimpleNamespace()
    stub._queue_lock = Lock()
    stub._pending_lock = Lock()
    stub._queue = [
        {"qid": 1, "media_id": "apple:album:a", "status": "queued", "reason": ""},
        {"qid": 2, "media_id": "tidal:album:t", "status": "queued", "reason": ""},
        {"qid": 3, "media_id": "apple:track:x", "status": "running", "reason": ""},
    ]
    stub._queue_index = {row["qid"]: row for row in stub._queue}
    stub._qdirty_changed = {}
    stub._job_specs = {1: "apple-spec", 2: "tidal-spec"}
    stub._pending_qids = deque([1, 2])
    stub._job_aborts = {3: Event()}
    stub._pending_downloads = [("apple:album:held", lambda: None), ("tidal:album:held", lambda: None)]
    stub.stopped_poll = []
    stub._recovery_poll = SimpleNamespace(stop=lambda: stub.stopped_poll.append("stop"))
    stub.released = []
    stub._release_abandoned_hold = lambda mids: stub.released.extend(mids)
    stub.emitted = []
    stub.downloadState = SimpleNamespace(emit=lambda mid, state: stub.emitted.append((mid, state)))
    stub.queue_emits = 0
    stub._emit_queue = lambda: setattr(stub, "queue_emits", stub.queue_emits + 1)
    stub._stop_provider_downloads = WavesBridge._stop_provider_downloads.__get__(stub, SimpleNamespace)
    return stub


def test_disabling_apple_stops_only_apple_work_and_keeps_it_retryable():
    stub = _stop_stub()

    count = stub._stop_provider_downloads(CTX_APPLE, _REASON)

    assert count == 2
    apple_queued = stub._queue_index[1]
    apple_running = stub._queue_index[3]
    tidal = stub._queue_index[2]
    assert apple_queued["status"] == "cancelled" and apple_queued["reason"] == _REASON
    assert apple_running["status"] == "cancelled" and apple_running["reason"] == _REASON
    assert tidal["status"] == "queued" and tidal["reason"] == ""
    # A queued row's spec must go with it, or its turn starts it anyway;
    # the running row's abort ends the fetch in place.
    assert 1 not in stub._job_specs and 2 in stub._job_specs
    assert list(stub._pending_qids) == [2]
    assert stub._job_aborts[3].is_set()
    assert [mid for mid, _fn in stub._pending_downloads] == ["tidal:album:held"]
    assert stub.released == ["apple:album:held"]
    assert ("apple:album:a", "") in stub.emitted
    assert stub.queue_emits == 1
    # Work still held for TIDAL keeps the recovery watch alive.
    assert stub.stopped_poll == []


def test_an_empty_provider_queue_stops_nothing_and_emits_nothing():
    stub = _stop_stub()
    stub._queue = [row for row in stub._queue if not str(row["media_id"]).startswith("apple:")]
    stub._queue_index = {row["qid"]: row for row in stub._queue}
    stub._job_specs = {2: "tidal-spec"}
    stub._pending_qids = deque([2])
    stub._job_aborts = {}
    stub._pending_downloads = [("tidal:album:held", lambda: None)]

    assert stub._stop_provider_downloads(CTX_APPLE, _REASON) == 0
    assert stub._queue_index[2]["status"] == "queued"
    assert stub.queue_emits == 0


def _retry_stub(item: dict) -> SimpleNamespace:
    stub = SimpleNamespace()
    stub._queue_index = {item["qid"]: item}
    stub._merge_plans = {}
    stub.removed = []
    stub._queue_item = WavesBridge._queue_item.__get__(stub, SimpleNamespace)
    stub._row_object = lambda it: object()
    stub._download_apple = lambda *a, **k: False
    stub._remove_row = lambda qid, withdrawn=None: stub.removed.append(qid) or True
    stub._emit_queue = lambda: None
    stub._start_retry = WavesBridge._start_retry.__get__(stub, SimpleNamespace)
    stub.retryQueueItem = WavesBridge.retryQueueItem.__get__(stub, SimpleNamespace)
    return stub


def test_a_refused_retry_keeps_the_stopped_row():
    item = {
        "qid": 1,
        "media_id": "apple:album:a",
        "status": "cancelled",
        "reason": _REASON,
        "type": "album",
        "name": "A",
        "template": "T",
        "collection": True,
        "quality": "HIGH",
        "askQuality": "HIGH",
    }
    stub = _retry_stub(item)

    stub.retryQueueItem(1)

    assert stub.removed == []
    assert stub._queue_index[1]["status"] == "cancelled"
    assert stub._queue_index[1]["reason"] == _REASON


def test_retry_all_keeps_rows_a_refused_provider_did_not_requeue():
    rows = [
        {"qid": 1, "media_id": "apple:album:a", "status": "cancelled", "reason": _REASON, "type": "album"},
        {"qid": 2, "media_id": "apple:album:b", "status": "cancelled", "reason": _REASON, "type": "album"},
    ]
    stub = SimpleNamespace(
        _queue=rows,
        _queue_index={row["qid"]: row for row in rows},
        _queue_lock=Lock(),
        _queue_emit_suspended=False,
        _merge_plans={},
        _redownload_overrides=set(),
        _library_claim_overrides=set(),
        _pending_lock=Lock(),
        _pending_downloads=[],
        _qdirty_removed=[],
        _row_object=lambda item: object(),
        _start_retry=lambda item, obj: False,
        _emit_queue=lambda: None,
    )
    stub._reindex_queue = lambda: None
    stub._remove_rows_where = WavesBridge._remove_rows_where.__get__(stub, SimpleNamespace)
    stub._queue_batch = WavesBridge._queue_batch.__get__(stub, SimpleNamespace)
    stub._retry_all_with_status = WavesBridge._retry_all_with_status.__get__(stub, SimpleNamespace)

    stub._retry_all_with_status("cancelled")

    assert [row["status"] for row in rows] == ["cancelled", "cancelled"]


def _status_stub(item: dict) -> SimpleNamespace:
    stub = SimpleNamespace()
    stub._queue_index = {item["qid"]: item}
    stub._queue_lock = Lock()
    stub.marked = []
    stub._queue_item = lambda qid: stub._queue_index.get(int(qid))
    stub._queue_mark_changed = lambda qid: stub.marked.append(int(qid))
    stub._emit_queue = lambda: None
    stub._set_queue_status = WavesBridge._set_queue_status.__get__(stub, SimpleNamespace)
    return stub


def test_a_wordless_cancel_settle_keeps_the_stop_words():
    item = {"qid": 3, "status": "cancelled", "reason": _REASON}
    stub = _status_stub(item)

    stub._set_queue_status(3, "cancelled")

    assert item["status"] == "cancelled"
    assert item["reason"] == _REASON


def test_a_running_presentation_is_cleared_by_a_cancel_settle():
    # The preserve rule is only for a row a stop already worded; a running
    # row's held/throttled presentation must not survive its own cancel.
    item = {"qid": 3, "status": "running", "reason": "Throttled: Apple is rate-limiting. Retrying in 30s."}
    stub = _status_stub(item)

    stub._set_queue_status(3, "cancelled")

    assert item["status"] == "cancelled"
    assert item["reason"] == ""


def test_a_settle_that_carries_words_still_replaces_them():
    item = {"qid": 3, "status": "cancelled", "reason": _REASON}
    stub = _status_stub(item)

    stub._set_queue_status(3, "failed", "3 of 4 tracks failed")

    assert item["status"] == "failed"
    assert item["reason"] == "3 of 4 tracks failed"
