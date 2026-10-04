"""Provider cancellation retains visible asks without retaining session work."""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from threading import Event, Lock
from types import SimpleNamespace

import pytest
from conftest import _Signal

from waves.constants import ITEM_FETCH_FAILED
from waves.desktop.backend import WavesBridge
from waves.desktop.providers.lifecycle import ProviderContexts
from waves.desktop.queue.bridge import QueueMixin
from waves.desktop.queue.runtime import JobRuntime


def _row(qid: int, media_id: str, status: str = "queued", audio_type: str = "stereo") -> dict:
    return {
        "qid": qid,
        "media_id": media_id,
        "type": "album",
        "name": "Album",
        "template": "Artist/Album",
        "collection": True,
        "status": status,
        "reason": "",
        "quality": "LOSSLESS",
        "askQuality": "LOSSLESS",
        "askLibrarySkip": False,
        "audioType": audio_type,
        "askToggles": {"lyrics": True, "artwork": False},
    }


class _Pool:
    def __init__(self) -> None:
        self.workers: list = []

    def start(self, worker) -> None:
        self.workers.append(worker)


def test_revocation_resets_only_owned_rollups_without_queue_rows():
    queue = _Queue([])
    queue._artist_groups = {"17": {}, "albums:tidal:19": {}, "apple:17": {}, "vids:paper:19": {}}
    queue._folder_groups = {"cat:pages/a": {}, "fav:tidal:tracks": {}, "fav:paper:tracks": {}}
    queue._provider_contexts.revoke("tidal")

    assert queue._stop_provider_queue("tidal", "Signed out") == 0

    assert queue._artist_groups == {"apple:17": {}, "vids:paper:19": {}}
    assert queue._folder_groups == {"fav:paper:tracks": {}}
    assert set(queue.downloadState.emits) == {
        ("17", ""),
        ("albums:tidal:19", ""),
        ("cat:pages/a", ""),
        ("fav:tidal:tracks", ""),
    }


class _Queue(QueueMixin):
    _release_abandoned_hold = WavesBridge._release_abandoned_hold
    _media_work_outstanding = WavesBridge._media_work_outstanding
    _bump_download_groups = WavesBridge._bump_download_groups
    _bump_folder_group = WavesBridge._bump_folder_group
    _bump_artist_group = WavesBridge._bump_artist_group

    def __init__(self, rows: list[dict]) -> None:
        self._queue = rows
        self._queue_lock = Lock()
        self._reindex_queue()
        self._jobs = JobRuntime()
        self._pending_qids = deque(row["qid"] for row in rows if row["status"] == "queued")
        self._pending_lock = Lock()
        self._pending_downloads: list = []
        self._provider_contexts = ProviderContexts()
        self._scan_gen = 0
        self._refetch_inflight: set = set()
        self._merge_plans: dict = {}
        self._merge_plans_unbound: dict = {}
        self._merge_scanned: set = set()
        self._redownload_overrides: set = set()
        self._library_claim_overrides: set = set()
        self._qdirty_changed: dict = {}
        self._qdirty_removed: list = []
        self._qdirty_added: list = []
        self._qdirty_full = False
        self._artist_groups: dict = {}
        self._folder_groups: dict = {}
        self._artist_lock = Lock()
        self._folder_lock = Lock()
        self._paused = True
        self.pausedChanged = _Signal()
        self._event_run = Event()
        self._objs: dict = {}
        self._logged_in = True
        self.providers: dict = {}
        self.threadpool = _Pool()
        self.downloadState = _Signal()
        self.downloadProgress = _Signal()
        self.folderRemaining = _Signal()
        self._queueRetryRefetched = _Signal()
        self.statuses: list = []
        self.retries: list = []
        self.queue_emits = 0
        self.poll_stops: list = []
        self._recovery_poll = SimpleNamespace(stop=lambda: self.poll_stops.append(True))

    def _emit_queue(self) -> None:
        self.queue_emits += 1

    def _set_status(self, status: str) -> None:
        self.statuses.append(status)

    def _remember(self, bucket, media_id, obj) -> None:
        self._objs.setdefault(bucket, {})[media_id] = obj

    def retryQueueItem(self, qid: int) -> None:
        self.retries.append(qid)


def test_stop_uses_spec_owner_and_legacy_ids_without_touching_other_jobs():
    queue = _Queue([_row(1, "17"), _row(2, "tidal:18"), _row(3, "apple:17", "running"), _row(4, "third:17")])
    # The explicit engine owner wins even when a row carries an old raw ID.
    queue._queue.append(_row(5, "legacy-third"))
    queue._reindex_queue()
    queue._jobs.specs = {
        qid: SimpleNamespace(provider_id=pid) for qid, pid in [(1, "tidal"), (4, "third"), (5, "third")]
    }
    queue._jobs.aborts = {2: Event(), 3: Event()}
    live = object()
    queue._jobs.dls[2] = live
    queue._jobs.signals[2] = live
    queue._jobs.tracks[2] = {"track": {"status": "running"}}

    assert queue._stop_provider_queue("tidal", "Signed out") == 2

    assert [row["status"] for row in queue._queue] == ["cancelled", "cancelled", "running", "queued", "queued"]
    assert queue._jobs.aborts[2].is_set() and not queue._jobs.aborts[3].is_set()
    assert set(queue._jobs.specs) == {4, 5}
    assert list(queue._pending_qids) == [4]
    assert queue._jobs.dls[2] is live and queue._jobs.signals[2] is live
    assert queue._jobs.tracks[2]["track"]["status"] == "running"
    assert queue._paused and not queue._event_run.is_set()
    assert queue._scan_gen == 0


def test_visible_hold_restores_the_plain_ask_and_keeps_retry_policy():
    ask = _row(1, "17", audio_type="atmos")
    original = deepcopy(ask)
    queue = _Queue([ask, _row(2, "apple:17"), _row(3, "third:17")])
    replays: list = []
    queue._pending_downloads = [("17", lambda: replays.append("dead session")), ("apple:17", lambda: None)]
    queue._redownload_overrides = {"17"}
    queue._library_claim_overrides = {"17"}
    queue._merge_plans = {"17": ["plan awaiting provider cache unbinding"]}
    assert queue._withdraw_queue_row_for_hold(1)
    # The archive owns its copy of the plain ask, including chooser pins.
    ask["askToggles"]["lyrics"] = False

    assert queue._stop_provider_queue("tidal", "Signed out") == 1

    restored = queue._queue_index[1]
    assert restored == {**original, "status": "cancelled", "reason": "Signed out"}
    assert [row["qid"] for row in queue._queue] == [1, 2, 3]
    assert queue._qdirty_full  # a pending withdrawal delta cannot remove the restored qid
    assert queue._held_queue_rows == {}
    assert [mid for mid, _fn in queue._pending_downloads] == ["apple:17"]
    assert queue._redownload_overrides == queue._library_claim_overrides == {"17"}
    assert queue._merge_plans["17"]
    assert not replays and not queue.poll_stops


def test_two_visible_versions_restore_as_two_independent_asks():
    queue = _Queue([_row(1, "17"), _row(2, "17", audio_type="atmos"), _row(3, "apple:17")])
    queue._pending_downloads = [("17", lambda: None)]
    assert queue._withdraw_queue_row_for_hold(1)
    assert queue._withdraw_queue_row_for_hold(2)

    assert queue._stop_provider_queue("tidal", "Signed out") == 2
    assert [(row["qid"], row["audioType"], row["status"]) for row in queue._queue[:2]] == [
        (1, "stereo", "cancelled"),
        (2, "atmos", "cancelled"),
    ]


@pytest.mark.parametrize("status,aborted", [("cancelled", False), ("running", True)])
def test_a_stop_that_won_before_withdrawal_cannot_be_archived(status, aborted):
    queue = _Queue([_row(1, "17", status)])
    queue._jobs.aborts[1] = Event()
    if aborted:
        queue._jobs.aborts[1].set()

    assert not queue._withdraw_queue_row_for_hold(1)
    assert not queue._withdraw_queue_row_for_hold(99)
    assert not getattr(queue, "_held_queue_rows", {})


def test_prequeue_and_synthetic_holds_cancel_without_inventing_rows():
    queue = _Queue([])
    mids = ["17", "tidal:18", "vids:19", "albums:20", "artist:21", "fav:tidal:albums", "cat:pages/x"]
    queue._pending_downloads = [(mid, lambda: None) for mid in [*mids, "fav:apple:albums", "third:17"]]
    queue._redownload_overrides = set(mids)

    assert queue._stop_provider_queue("tidal", "Signed out") == 0
    assert queue._queue == []
    assert [mid for mid, _fn in queue._pending_downloads] == ["fav:apple:albums", "third:17"]
    assert not queue._redownload_overrides
    assert not queue.poll_stops


def test_replay_or_dismissal_forgets_only_the_affected_archive():
    queue = _Queue([_row(1, "17"), _row(2, "apple:17")])
    assert queue._withdraw_queue_row_for_hold(1)
    assert queue._withdraw_queue_row_for_hold(2)
    queue._forget_held_queue_rows(["17"])
    assert set(queue._held_queue_rows) == {2}
    assert queue._stop_provider_queue("tidal", "Signed out") == 0
    assert queue._queue == []
    assert queue._stop_provider_queue("apple", "Disabled") == 1
    assert queue._queue_index[2]["status"] == "cancelled"


@pytest.mark.parametrize("method", ["stopAll", "dismissDownloadFolderNudge"])
def test_global_stop_or_dismissal_cannot_leave_an_archive_to_resurrect(method):
    queue = _Queue([_row(1, "17"), _row(2, "apple:17")])
    queue._pending_downloads = [("17", lambda: None), ("apple:17", lambda: None)]
    queue._redownload_overrides = {"17", "apple:17"}
    assert queue._withdraw_queue_row_for_hold(1)
    assert queue._withdraw_queue_row_for_hold(2)
    queue._reap_stranded_groups = lambda: None

    getattr(WavesBridge, method)(queue)

    assert not queue._pending_downloads and not queue._held_queue_rows
    assert not queue._redownload_overrides
    assert queue._stop_provider_queue("tidal", "Signed out") == 0
    assert queue._stop_provider_queue("apple", "Disabled") == 0
    assert queue._queue == []


def test_held_member_settles_in_a_real_mixed_group_after_replay_is_dropped():
    queue = _Queue([_row(1, "17"), _row(2, "apple:17"), _row(3, "third:17")])
    keys = {"17", "apple:17", "third:17"}
    queue._folder_groups = {
        "mixed": {
            "keys": keys,
            "done": set(),
            "failed": set(),
            "prog": {},
            "weights": dict.fromkeys(keys, 1),
            "total": 3,
        },
        "unrelated": {
            "keys": {"apple:17"},
            "done": set(),
            "failed": set(),
            "prog": {},
            "weights": {"apple:17": 1},
            "total": 1,
        },
    }
    untouched = deepcopy(queue._folder_groups["unrelated"])
    queue._pending_downloads = [("17", lambda: None), ("apple:held", lambda: None)]
    assert queue._withdraw_queue_row_for_hold(1)

    queue._stop_provider_queue("tidal", "Signed out")

    assert queue._folder_groups["mixed"]["done"] == {"17"}
    assert queue._folder_groups["mixed"]["failed"] == {"17"}
    assert queue._folder_groups["unrelated"] == untouched
    assert ("mixed", 2, 3) in queue.folderRemaining.emits
    assert queue._queue_index[2]["status"] == queue._queue_index[3]["status"] == "queued"


def test_a_prequeue_hold_settles_its_existing_group_without_adding_a_row():
    queue = _Queue([_row(1, "apple:17")])
    queue._artist_groups = {"mixed": {"keys": {"17", "apple:17"}, "done": set(), "failed": set(), "prog": {}}}
    queue._pending_downloads = [("17", lambda: None)]

    assert queue._stop_provider_queue("tidal", "Signed out") == 0
    assert queue._artist_groups["mixed"]["done"] == {"17"}
    assert queue._artist_groups["mixed"]["failed"] == {"17"}
    assert [row["media_id"] for row in queue._queue] == ["apple:17"]


def test_retry_refetch_dispatches_to_its_actual_provider_with_raw_id():
    queue = _Queue([_row(1, "third:17", "cancelled")])
    calls: list = []
    obj = object()
    queue._logged_in = False  # TIDAL sign-in does not gate another provider
    queue.providers = {"third": SimpleNamespace(get_object=lambda *args: calls.append(args) or obj)}

    queue._retry_queue_refetch(queue._queue_index[1])
    queue.threadpool.workers[0].fn()
    payload = queue._queueRetryRefetched.emits[0]
    assert calls == [("album", "17")]
    assert queue._objs["album"]["third:17"] is obj
    queue._on_queue_retry_refetched(*payload)
    assert queue.retries == [1] and not queue._refetch_inflight


def test_revoked_worker_cannot_publish_or_clear_a_new_retry_owner():
    queue = _Queue([_row(1, "17", "cancelled")])
    obj = object()
    queue.providers = {"tidal": SimpleNamespace(get_object=lambda *_: obj)}
    queue._retry_queue_refetch(queue._queue_index[1])
    old = queue.threadpool.workers[0]
    queue._provider_contexts.revoke("tidal")
    queue._stop_provider_queue("tidal", "Signed out")
    queue._retry_queue_refetch(queue._queue_index[1])
    owner = queue._retry_refetch_tokens[("album", "17")]

    old.fn()

    assert queue._retry_refetch_tokens[("album", "17")] == owner
    assert ("album", "17") in queue._refetch_inflight
    assert not queue._objs and not queue._queueRetryRefetched.emits
    queue.threadpool.workers[1].fn()
    assert queue._objs["album"]["17"] is obj


def test_revocation_during_network_fetch_discards_the_result():
    queue = _Queue([_row(1, "17", "cancelled")])

    def fetch(*_):
        queue._provider_contexts.revoke("tidal")
        queue._stop_provider_queue("tidal", "Signed out")
        return object()

    queue.providers = {"tidal": SimpleNamespace(get_object=fetch)}
    queue._retry_queue_refetch(queue._queue_index[1])
    queue.threadpool.workers[0].fn()
    assert not queue._objs and not queue._queueRetryRefetched.emits
    assert not queue._refetch_inflight and not queue.retries


def test_stale_gui_payload_cannot_retry_or_release_a_new_marker():
    queue = _Queue([_row(1, "17", "cancelled")])
    queue.providers = {"tidal": SimpleNamespace(get_object=lambda *_: object())}
    queue._retry_queue_refetch(queue._queue_index[1])
    queue.threadpool.workers[0].fn()
    old_payload = queue._queueRetryRefetched.emits[0]
    queue._provider_contexts.revoke("tidal")
    queue._stop_provider_queue("tidal", "Signed out")
    queue._retry_queue_refetch(queue._queue_index[1])

    queue._on_queue_retry_refetched(*old_payload)

    assert not queue.retries
    assert ("album", "17") in queue._refetch_inflight


def test_same_context_payload_from_another_qid_does_not_release_its_owner():
    queue = _Queue([_row(1, "17", "cancelled")])
    queue.providers = {"tidal": SimpleNamespace(get_object=lambda *_: object())}
    queue._retry_queue_refetch(queue._queue_index[1])
    token, qid = queue._retry_refetch_tokens[("album", "17")]
    queue._on_queue_retry_refetched("album", "17", qid + 1, token)
    assert not queue.retries
    assert ("album", "17") in queue._refetch_inflight


def test_failed_refetch_releases_its_marker_and_keeps_the_stopped_ask():
    queue = _Queue([_row(1, "17", "cancelled")])

    def fetch(*_):
        raise OSError("offline")

    queue.providers = {"tidal": SimpleNamespace(get_object=fetch)}
    queue._retry_queue_refetch(queue._queue_index[1])
    queue.threadpool.workers[0].fn()

    assert queue._queue_index[1]["status"] == "cancelled"
    assert queue.statuses[-1] == ITEM_FETCH_FAILED
    assert not queue._refetch_inflight and not queue._retry_refetch_tokens
    assert not queue.retries
