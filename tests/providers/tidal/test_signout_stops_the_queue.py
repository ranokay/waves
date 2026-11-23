"""TIDAL sign-out revokes its context and stops its own queue before teardown."""

from __future__ import annotations

from collections import deque
from contextlib import nullcontext
from threading import Event, Lock
from types import SimpleNamespace

from conftest import _Signal
from support.bridge_stub import BridgeStub

from waves.desktop.backend import WavesBridge
from waves.desktop.providers.lifecycle import ProviderContexts
from waves.desktop.queue.bridge import QueueMixin
from waves.desktop.queue.runtime import JobRuntime


class _Pool:
    def __init__(self):
        self.workers: list = []

    def start(self, worker):
        self.workers.append(worker)


class _Bridge(BridgeStub, QueueMixin):
    logout = WavesBridge.logout
    _end_provider_context = WavesBridge._end_provider_context
    _start_provider_logout = WavesBridge._start_provider_logout
    _stop_provider_downloads = WavesBridge._stop_provider_downloads
    _release_abandoned_hold = WavesBridge._release_abandoned_hold

    def __init__(self):
        self._provider_contexts = ProviderContexts()
        self.old_context = self._provider_contexts.capture("tidal")
        self._queue_lock = Lock()
        self._pending_lock = Lock()
        self._queue = [
            {"qid": 1, "media_id": "17", "status": "running", "reason": ""},
            {"qid": 2, "media_id": "tidal:18", "status": "queued", "reason": ""},
            {"qid": 3, "media_id": "apple:17", "status": "queued", "reason": ""},
            {"qid": 4, "media_id": "third:17", "status": "queued", "reason": ""},
        ]
        self._reindex_queue()
        self._qdirty_changed = {}
        self._qdirty_removed = []
        self._qdirty_full = False
        self._jobs = JobRuntime()
        self._jobs.specs = {
            qid: SimpleNamespace(provider_id=pid) for qid, pid in [(2, "tidal"), (3, "apple"), (4, "third")]
        }
        self._jobs.aborts = {1: Event(), 3: Event()}
        self._pending_qids = deque([2, 3, 4])
        self._pending_downloads = [("apple:held", lambda: None)]
        self._refetch_inflight = set()
        self._merge_scanned = set()
        self._merge_plans = {}
        self._merge_plans_unbound = {}
        self._redownload_overrides = set()
        self._library_claim_overrides = set()
        self._objs = {"album": {}}
        self.threadpool = _Pool()
        self.downloadState = _Signal()
        self.providerStateChanged = _Signal()
        self._active_search_providers = {"tidal", "apple"}
        self._search_gen = 7
        self._paused = True
        self._scan_gen = 9
        self.events: list = []
        self.statuses: list = []
        self.credits: list = []
        self._recovery_poll = SimpleNamespace(stop=lambda: self.events.append("poll stopped"))
        self.providers = {
            "tidal": SimpleNamespace(
                invalidate_catalog_context=lambda: self.events.append("catalog invalidated"),
                session_teardown_context=nullcontext,
                logout=lambda: self.events.append(("logout", self._jobs.aborts[1].is_set())),
                reset_session=lambda: self.events.append("session reset"),
            ),
        }

    def _set_login_busy(self, provider_id, value):
        self.events.append(("login busy", provider_id, value))

    def _set_logged_in(self, value):
        self.events.append(("logged in", value))

    def _set_status(self, text):
        self.statuses.append(text)

    def _set_busy(self, value):
        self.events.append(("busy", value))

    def _schedule_provider_cache_clear(self, provider_id):
        self.events.append(("invalidate disk", provider_id))

    def _emit_queue(self):
        self.events.append("queue emitted")

    def _bump_download_groups(self, *args):
        self.credits.append(args)


def test_signing_out_stops_only_tidal_downloads_including_legacy_bare_ids():
    bridge = _Bridge()

    bridge.logout()

    assert [row["status"] for row in bridge._queue] == ["cancelled", "cancelled", "queued", "queued"]
    assert [row["reason"] for row in bridge._queue[:2]] == ["Signed out of TIDAL"] * 2
    assert bridge._jobs.aborts[1].is_set() and not bridge._jobs.aborts[3].is_set()
    assert set(bridge._jobs.specs) == {3, 4}
    assert list(bridge._pending_qids) == [3, 4]
    assert bridge._pending_downloads[0][0] == "apple:held"
    assert bridge._paused and bridge._scan_gen == 9 and bridge._search_gen == 7
    assert "poll stopped" not in bridge.events


def test_revoke_and_abort_come_before_the_session_is_torn_down():
    bridge = _Bridge()

    bridge.logout()

    assert not bridge._provider_contexts.current(bridge.old_context)
    assert bridge._jobs.aborts[1].is_set()
    assert not any(isinstance(event, tuple) and event[0] == "logout" for event in bridge.events)
    bridge.threadpool.workers[0].fn()
    assert ("logout", True) in bridge.events
    assert (
        bridge.events.index("queue emitted")
        < bridge.events.index(("logged in", False))
        < bridge.events.index(("logout", True))
    )


def test_signing_out_still_says_so():
    bridge = _Bridge()
    bridge.logout()
    assert bridge.statuses == ["Signed out"]


def test_signout_clears_only_own_objects_and_unbinds_only_own_merge_plans():
    bridge = _Bridge()
    old, apple, third = object(), object(), object()
    bridge._objs["album"] = {"17": old, "tidal:18": old, "apple:17": apple, "third:17": third}
    bridge._jobs.objs = {1: old, 2: old, 3: apple, 4: third}
    bridge._merge_scanned = {"17", "tidal:18", "apple:17", "third:17"}
    entry = SimpleNamespace(src=SimpleNamespace(id="123"), track_num=1, volume_num=1, identity_id="123")
    bridge._merge_plans = {"17": [entry], "apple:17": [entry]}

    bridge.logout()

    assert bridge._objs["album"] == {"apple:17": apple, "third:17": third}
    assert bridge._jobs.objs == {3: apple, 4: third}
    assert bridge._merge_scanned == {"apple:17", "third:17"}
    assert bridge._merge_plans == {"apple:17": [entry]}
    assert bridge._merge_plans_unbound == {"17": [("123", 1, 1, "123")]}


def test_signout_restores_a_visible_hold_as_a_stopped_ask_without_its_closure():
    bridge = _Bridge()
    row = bridge._queue_index[2]
    row.update(askQuality="LOSSLESS", quality="LOSSLESS", audioType="atmos", askToggles={"lyrics": True})
    replays: list = []
    bridge._pending_downloads.append(("tidal:18", lambda: replays.append("old session")))
    bridge._redownload_overrides.add("tidal:18")
    bridge._library_claim_overrides.add("tidal:18")
    assert bridge._withdraw_queue_row_for_hold(2)

    bridge.logout()

    restored = bridge._queue_index[2]
    assert restored["status"] == "cancelled" and restored["reason"] == "Signed out of TIDAL"
    assert (restored["askQuality"], restored["quality"], restored["audioType"], restored["askToggles"]) == (
        "LOSSLESS",
        "LOSSLESS",
        "atmos",
        {"lyrics": True},
    )
    assert bridge._redownload_overrides == bridge._library_claim_overrides == {"tidal:18"}
    assert [mid for mid, _fn in bridge._pending_downloads] == ["apple:held"]
    assert not bridge._held_queue_rows and not replays
