"""The queue's clear, remove and stop slots withdraw the job they drop.

A clear or removal aborts the job whose row it withdraws and spares one that
has reached running; STOP drops held downloads; a dismissal settles the rollups.
"""

from __future__ import annotations

from threading import Event, Lock
from types import SimpleNamespace
from unittest.mock import patch

from support.dispatch_stub import _queue_stub, arm_dispatch

from waves.desktop import backend
from waves.desktop.backend import WavesBridge, _JobSpec


class _Sig:
    def __init__(self):
        self.emits: list = []

    def emit(self, *a):
        self.emits.append(a)


def _bind(stub, name):
    return getattr(WavesBridge, name).__get__(stub, type(stub))


# --------------------------------------------------------------------------- #
# Queue teardown: F, G, I, J, K.
# --------------------------------------------------------------------------- #
# --- I. A bulk clear aborts the job it withdraws ---------------------------- #
#
# _pump_queue hands a row to the pool while it still reads "queued": the status
# only flips to "running" AFTER the folder reachability probe, which on a
# sleeping share is seconds of probe, remount and probe again. Both bulk clears
# select on that status, so the row of a job already downloading was withdrawn
# with nothing left to stop it. The album ran to completion with no row, no
# progress and no control, and with the queue reading idle the drawer hides
# STOP entirely.
def test_clear_all_aborts_the_job_whose_row_it_withdraws():
    s = _queue_stub(["queued", "queued"], running_qid=1)
    abort = Event()
    s._job_aborts[1] = abort

    s.clearQueue()

    assert abort.is_set(), "the album kept downloading with no row left to show or stop it"


def test_clear_queued_section_aborts_it_too():
    s = _queue_stub(["queued", "queued"], running_qid=1)
    abort = Event()
    s._job_aborts[1] = abort

    s.clearQueued()

    assert abort.is_set()


def test_removing_one_row_aborts_it_too():
    s = _queue_stub(["queued", "queued"], running_qid=1)
    abort = Event()
    s._job_aborts[1] = abort

    s.removeQueueItem(1)

    assert abort.is_set()


def test_a_clear_that_spares_the_running_row_aborts_nothing():
    """The other half of the contract: CLEAR ALL spares a row that has reached
    "running" and it must keep downloading, so nothing may set its abort."""
    s = _queue_stub(["running", "queued"], running_qid=1)
    abort = Event()
    s._job_aborts[1] = abort

    s.clearQueue()

    assert not abort.is_set(), "a row still writing bytes was killed by a bulk clear"
    assert [it["qid"] for it in s._queue] == [1]


def test_clearing_rows_behind_the_running_one_leaves_it_alone():
    """And a clear that touches only other rows must not abort the job either."""
    s = _queue_stub(["queued", "failed"], running_qid=1)
    abort = Event()
    s._job_aborts[1] = abort

    s.clearFailed()

    assert not abort.is_set()


# --- J. STOP ends held downloads too ---------------------------------------- #
#
# A download held for an unreachable folder is neither running nor queued: the
# gate withdrew its row, so STOP's sweep cannot see it and nothing holds its
# abort. Left in the stash it was not stopped, only postponed: the recovery
# watch kept polling and started the albums again by itself minutes later, into
# rollups the same press had already deleted.
def test_stop_drops_downloads_held_for_the_folder_to_come_back():
    s = _queue_stub(["running"])
    s._pending_downloads = [("m9", lambda: None)]
    stopped: list = []
    s._recovery_poll = SimpleNamespace(stop=lambda: stopped.append(True), start=lambda: None, isActive=lambda: True)

    s.stopAll()

    assert s._pending_downloads == [], "STOP left downloads for the recovery watch to start again"
    assert stopped == [True], "the recovery watch kept polling after STOP"
    # A held download can carry a lit button, and the row sweep cannot see it
    # (a hold has no row): a button left lit refuses every click for the rest
    # of the session.
    assert ("m9", "") in s.downloadState.emits, "the held download's button was left lit and dead"


# --- K. A withdrawn row gives up its merge plan ----------------------------- #
#
# downloadAlbum PEEKS the stashed best-of-both plan (it must survive a RETRY),
# so a plan left behind by a withdrawn row was consumed by the next PLAIN click
# on that album: with the preference since turned off, the click still built a
# cross-edition copy, and the "Best of both:" line that would have said so is
# only written on the explicit path.
def test_clearing_a_failed_row_releases_its_merge_plan():
    s = _queue_stub(["failed"])
    s._merge_plans["m1"] = ["a plan the scan stashed"]

    s.clearFailed()

    assert "m1" not in s._merge_plans, "the next plain click on this album would silently merge editions"


def test_clearing_a_stopped_row_releases_it_too():
    s = _queue_stub(["cancelled"])
    s._merge_plans["m1"] = ["a plan the scan stashed"]

    s.clearStopped()

    assert "m1" not in s._merge_plans


# --- F. Dismissing the folder gate settles the rollups ---------------------- #
#
# Held downloads have no row, so no worker will ever credit them. Dropping them
# without crediting left a discography short of its own key set for good: the
# artist button stayed "running" and refused every tap, with an idle queue and
# no STOP on screen to end it.
def test_dismissing_the_folder_nudge_settles_the_rollup():
    s = _queue_stub(["done"])
    # A discography of three: one landed, and two are held behind the folder
    # that went away, with their rows already withdrawn by the gate.
    s._artist_groups["art1"]["keys"] |= {"m2", "m3"}
    s._bump_download_groups("m1", 100.0, "done")
    assert "art1" in s._artist_groups, "the group must still be open with two members outstanding"
    s._pending_downloads = [("m2", lambda: None), ("m3", lambda: None)]

    s.dismissDownloadFolderNudge()

    assert s._artist_groups == {}, "the artist button would stay running and refuse every tap"
    assert ("art1", "failed") in s.downloadState.emits


def test_dismissing_with_nothing_held_settles_nothing():
    """The slot is also the dialog's click-away, so it fires with an empty
    stash all the time. It must not sweep live rollups when it does."""
    s = _queue_stub(["queued"])

    s.dismissDownloadFolderNudge()

    assert "art1" in s._artist_groups


# --- G. Held work is not credited as failed --------------------------------- #
#
# Every False from the reachability gate has stashed the download for automatic
# replay (one of them tells the user "the download starts by itself"). Crediting
# it as failed deleted the rollup before the replay could report into it, so a
# discography whose folder slept between albums finished RED with every one of
# its albums present on disk.
class _InlinePool:
    def start(self, worker) -> None:
        worker.run()


class _GateStub:
    """One job body, with the gate blocking and the rollup under observation."""

    def __init__(self) -> None:
        self._logged_in = True
        self.providers = {"tidal": SimpleNamespace(get_object=lambda kind, raw_id: _media())}
        self._job_aborts: dict[int, Event] = {}
        self._job_signals: dict = {}
        self._job_dls: dict = {}
        self._job_tracks: dict = {}
        self._merge_plans: dict = {}
        self._redownload_overrides: set = set()
        self._library_claim_overrides: set = set()
        self._queue = [{"qid": 1, "media_id": "m1", "status": "queued", "type": "album", "name": "Album"}]
        self._queue_index = {1: self._queue[0]}
        self._queue_lock = Lock()
        self.settings = SimpleNamespace(
            data=SimpleNamespace(download_base_path="/tmp/waves-out", download_delay=False, downloads_concurrent_max=2)
        )
        self.dl = SimpleNamespace(path_base="")
        self.dl_pool = _InlinePool()
        self.downloadState = _Sig()
        self.downloadProgress = _Sig()
        self.bumps: list = []
        self._track_poll = SimpleNamespace(isActive=lambda: True, start=lambda *a: None)
        arm_dispatch(self)
        self._emit_queue = lambda: None
        for n in ("_remove_rows_where", "_remove_row", "_reindex_queue"):
            setattr(self, n, _bind(self, n))

    def _set_queue_status(self, qid, status, reason: str = "") -> None:
        self._queue[0]["status"] = status

    def _set_queue_progress(self, qid, pct) -> None:
        pass

    def _set_status(self, msg) -> None:
        pass

    def _job_library_skip(self, qid: int) -> bool:
        return False

    def _row_ask(self, qid):
        return None  # a held retry asks at what its row asked; no row ask here

    def _job_quality(self, qid):
        return None

    def _build_download(self, signals, **kwargs):
        return self.dl

    def _release_job_signals(self, qid) -> None:
        self._job_signals.pop(qid, None)

    def _bump_download_groups(self, media_id, pct, state) -> None:
        self.bumps.append((media_id, pct, state))

    def _gate_reachability(self, retry, media_id) -> bool:
        """The folder is asleep: the gate stashes the replay and blocks."""
        return False


def _media():
    return SimpleNamespace(
        id="m1", name="Album", artist=SimpleNamespace(name="Artist"), artists=[], audio_quality=None, duration=200
    )


def test_a_download_held_at_the_gate_is_not_credited_as_failed():
    stub = _GateStub()
    spec = _JobSpec("tidal", "album", "tidal:m1", "Album", "{title}", True, "m1", None)

    with patch.object(backend, "_ProgressSignals", lambda *a, **k: object()):
        WavesBridge._start_job(stub, 1, spec)

    assert stub.bumps == [], "the rollup was deleted before the automatic replay could report into it"


def test_a_merge_held_at_the_gate_keeps_its_plan_even_if_a_clear_beat_the_stash():
    """A bulk clear runs on the GUI thread and can take the row away while the
    worker is still inside the probe, which is BEFORE the stash exists, so the
    withdrawal's held-work check cannot see this download and releases its
    plan. The replay survives (the closure carries the plan by value), but a
    later RETRY reads this dict and would save a plain album over the tracks
    the merge had borrowed."""
    stub = _GateStub()
    plan = ["a plan the scan stashed"]
    spec = _JobSpec("tidal", "album", "tidal:m1", "Album", "{title}", True, "m1", plan)
    # The clear already landed: the row is gone and the plan went with it.
    stub._queue.clear()
    stub._queue_index.clear()
    stub._merge_plans.pop("m1", None)

    with patch.object(backend, "_ProgressSignals", lambda *a, **k: object()):
        WavesBridge._start_job(stub, 1, spec)

    assert stub._merge_plans.get("m1") == plan, "a retried merge would have come back a plain album"


def test_a_plain_album_held_at_the_gate_invents_no_plan():
    """The guard is only for a job that really carries one: a plain download
    must not acquire a merge plan by passing through the gate."""
    stub = _GateStub()
    spec = _JobSpec("tidal", "album", "tidal:m1", "Album", "{title}", True, "m1", None)

    with patch.object(backend, "_ProgressSignals", lambda *a, **k: object()):
        WavesBridge._start_job(stub, 1, spec)

    assert stub._merge_plans == {}


def test_a_download_held_at_the_gate_still_withdraws_its_row():
    """The rest of the gate-block contract is unchanged: the queue reads as if
    the download never started, so only the CREDIT was wrong."""
    stub = _GateStub()
    spec = _JobSpec("tidal", "album", "tidal:m1", "Album", "{title}", True, "m1", None)

    with patch.object(backend, "_ProgressSignals", lambda *a, **k: object()):
        WavesBridge._start_job(stub, 1, spec)

    assert stub._queue == []
    assert ("m1", "") in stub.downloadState.emits
