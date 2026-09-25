"""Arm a partial WavesBridge stand-in with the queue dispatcher's state.

``_pump_queue`` builds a queued ``_JobSpec`` when the pool is free, one at a
time, so stubs that bind the real ``_download`` need the dispatcher's fields.
Their inline pools keep their synchronous behavior through a ``_jobFinished``
stand-in that calls the real ``_on_job_finished`` directly: the Worker's
``finally`` emits it, the next queued spec starts, and a multi-download test
still sees every job run in order within the ``_download`` call it drove.
"""

from __future__ import annotations

from collections import deque
from threading import Event, Lock
from types import SimpleNamespace

from waves.desktop.backend import WavesBridge
from waves.desktop.job_runtime import JobRuntime
from waves.providers import Refusal, RefusalKind


class _RecordingSignal:
    """Minimal stand-in for a Qt signal: records every emit."""

    def __init__(self):
        self.emits: list = []

    def emit(self, *args):
        self.emits.append(args if len(args) != 1 else args[0])


def arm_queue(stub) -> None:
    """The queue's dirty marks (what QML has not been told yet) and the
    per-row stores the remove path prunes: any stand-in that binds the real
    _enqueue / _remove_rows_where / _flush_queue_changes family needs them.

    Defaults are only filled in where the stand-in has not set its own, so a
    test that wants a populated queue, a live abort or a running job says so
    and this leaves it alone."""
    stub._qdirty_added = getattr(stub, "_qdirty_added", [])
    stub._qdirty_changed = getattr(stub, "_qdirty_changed", {})
    stub._qdirty_removed = getattr(stub, "_qdirty_removed", [])
    stub._qdirty_full = getattr(stub, "_qdirty_full", False)
    stub._qflush_posted = getattr(stub, "_qflush_posted", False)
    # name -> factory for the state the real queue methods read. Each line says
    # which path needs it, because a missing one fails as an AttributeError
    # deep inside a bound method rather than at the stand-in.
    defaults = (
        # The per-row stores the remove path prunes, on the job runtime
        # (constructed here, so stub builds must stay on the main thread).
        ("_jobs", JobRuntime),
        ("_job_owned", dict),
        ("_job_fetched", dict),
        ("_queue_lock", Lock),
        # A withdrawn row gives up its REDOWNLOAD force on the way out, and the
        # library-claim override it registered alongside that force: both marks
        # live only as long as a live row holds them.
        ("_redownload_overrides", set),
        ("_library_claim_overrides", set),
        # And the best-of-both plan the scan stashed for the row, the third
        # piece of the same per-row state: a plan left behind is picked up by
        # the next plain click on that album.
        ("_merge_plans", dict),
        # The job in flight, so a clear that drops its row can abort it: a row
        # is handed to the pool while it still reads "queued", so the bulk
        # clears can select one that is already downloading.
        ("_running_qid", lambda: None),
        # The watch that replays downloads held for an unreachable folder, and
        # which STOP stops (the held downloads themselves are armed with
        # the rest of the rollup state, below).
        ("_recovery_poll", lambda: SimpleNamespace(stop=lambda: None, start=lambda: None, isActive=lambda: False)),
        # The provider a job resolves its object through at dispatch (the
        # spec carries a name, not an object). A test that wants a specific
        # object or refusal sets its own before driving the job.
        (
            "providers",
            lambda: {
                "tidal": SimpleNamespace(
                    get_object=lambda kind, raw_id: SimpleNamespace(id=raw_id),
                    classify_refusal=lambda exc: Refusal(RefusalKind.FAILURE, str(exc)),
                )
            },
        ),
    )
    for name, make in defaults:
        if not hasattr(stub, name):
            setattr(stub, name, make())
    # Real bridge methods the queue family calls on itself. _queue_batch is the
    # context manager a batched enqueue (a discography, a folder, RETRY ALL)
    # holds the queue's delivery open through.
    # _discard_pending_downloads and _release_abandoned_hold are what a press
    # reaches a HELD download through: every withdrawal slot calls them so a
    # download waiting for the folder to come back is stopped rather than
    # merely postponed, and the state its hold kept alive goes with it.
    for name in (
        "_queue_mark_changed",
        "_abort_if_in_flight",
        "_queue_batch",
        "_discard_pending_downloads",
        "_release_abandoned_hold",
    ):
        if not hasattr(stub, name):
            setattr(stub, name, getattr(WavesBridge, name).__get__(stub, type(stub)))
    _arm_rollups(stub)


def _arm_rollups(stub) -> None:
    """The rollup fields and methods the withdrawal slots touch: a cleared or
    cancelled queued row credits its discography/folder rollups, and every
    slot sweeps for stranded groups afterwards. Stubs with their own richer
    versions keep them."""
    from threading import Lock as _Lock

    for field, default in (
        ("_artist_groups", dict),
        ("_folder_groups", dict),
        ("_stranded_once", set),
        ("_scan_gen", int),
        ("_scans_in_flight", int),
        # A download held for recovery has no queue row, and the reaper counts
        # it as live work all the same (a held member must not strand a group).
        ("_pending_downloads", list),
    ):
        if not hasattr(stub, field):
            setattr(stub, field, default())
    for lock in ("_artist_lock", "_folder_lock", "_pending_lock"):
        if not hasattr(stub, lock):
            setattr(stub, lock, _Lock())
    for sig in ("downloadState", "downloadProgress", "folderRemaining"):
        if not hasattr(stub, sig):
            setattr(stub, sig, _RecordingSignal())
    for name in ("_bump_download_groups", "_bump_artist_group", "_bump_folder_group", "_reap_stranded_groups"):
        if not hasattr(stub, name):
            setattr(stub, name, getattr(WavesBridge, name).__get__(stub, type(stub)))
    # _download's duplicate-row refusal reads the pinned quality of a fresh row.
    if not hasattr(stub, "_queued_quality_value"):
        stub._queued_quality_value = lambda: "LOSSLESS"


def arm_dispatch(stub) -> None:
    arm_queue(stub)
    stub._jobs.specs = {}
    stub._jobs.objs = {}
    stub._pending_qids = deque()
    stub._running_qid = None
    stub._paused = getattr(stub, "_paused", False)
    stub._pct_last = getattr(stub, "_pct_last", {})
    if not hasattr(stub, "_track_poll"):
        stub._track_poll = SimpleNamespace(isActive=lambda: True, start=lambda *a: None)
    if not hasattr(stub, "_queue_item"):
        # A stand-in whose _enqueue returns a bare qid keeps no rows; the
        # pump re-validates the row, so answer "still queued" as a real row
        # would (the pre-dispatcher behavior: the job always started).
        stub._queue_item = lambda qid: {"qid": qid, "status": "queued"}
    for name in ("_pump_queue", "_start_job", "_on_job_finished"):
        setattr(stub, name, getattr(WavesBridge, name).__get__(stub, type(stub)))
    stub._jobFinished = SimpleNamespace(emit=stub._on_job_finished)


def _queue_stub(statuses, *, running_qid=None):
    """A bridge stand-in carrying one queue row per status, with the real
    clear/remove/stop family bound.

    ``statuses`` are the row statuses in qid order (qid ``n`` has media id
    ``m<n>``) and ``running_qid`` names the job already in flight. The stub
    also carries the per-row stores and the discography rollup those slots
    sweep, so a test reads what a withdrawal aborted, released or emitted.
    """
    s = SimpleNamespace()
    s._queue = [
        {"qid": n, "media_id": f"m{n}", "status": st, "type": "album", "name": f"r{n}"}
        for n, st in enumerate(statuses, 1)
    ]
    s._queue_lock = Lock()
    s._queue_index = {it["qid"]: it for it in s._queue}
    s._queue_emit_suspended = False
    s._jobs = JobRuntime()
    s._jobs.specs = {it["qid"]: object() for it in s._queue}
    s._jobs.aborts = {}
    s._pending_qids = deque(it["qid"] for it in s._queue)
    s._event_run = Event()
    s._paused = False
    s.pausedChanged = _RecordingSignal()
    s._scan_gen = 0
    s._scans_in_flight = 0
    s._scan_count_lock = Lock()
    s.scanningChanged = _RecordingSignal()
    s.downloadState = _RecordingSignal()
    s.downloadProgress = _RecordingSignal()
    s.folderRemaining = _RecordingSignal()
    s.statuses = []
    s._set_status = s.statuses.append
    s._jobs.objs = {}
    s._artist_groups = {
        "art1": {"keys": {it["media_id"] for it in s._queue}, "done": set(), "failed": set(), "prog": {}}
    }
    s._artist_lock = Lock()
    s._folder_groups = {}
    s._folder_lock = Lock()
    s._stranded_once = set()
    arm_queue(s)
    s._running_qid = running_qid
    s._emit_queue = lambda: None
    for n in (
        "_reindex_queue",
        "_queue_item",
        "_remove_rows_where",
        "_remove_row",
        "_abort_if_in_flight",
        "clearQueue",
        "clearQueued",
        "clearFailed",
        "clearStopped",
        "cancelQueueItem",
        "removeQueueItem",
        "stopAll",
        "dismissDownloadFolderNudge",
        "_bump_download_groups",
        "_bump_artist_group",
        "_bump_folder_group",
        "_reap_stranded_groups",
    ):
        setattr(s, n, getattr(WavesBridge, n).__get__(s, type(s)))
    return s
