"""STOP sticks even when it lands while the folder is being probed.

A job checks its abort gate once, as its worker picks it up, and then runs the
reachability probe of the download folder. That probe is the slow part of
starting a job: against a stale network mount (an SMB share this app's users
live on) it costs seconds, remounts, and probes again. Nothing looked at the
abort gate afterwards.

So STOP pressed in that window marks the row cancelled, clears the button and
says "Downloads stopped", and then the job comes out of the probe and sets the
very same row back to running: the button re-lights at 0% and the status line
reads "Downloading ..." again, for as long as it takes to enumerate the whole
collection (much longer under rate limiting). Only then does the job notice the
abort and fall back to Stopped. To the user, STOP simply does not stick.

The job looks at the gate again on the way out of the probe and settles exactly
as it does when the abort was already set on the way in.
"""

from __future__ import annotations

from threading import Event, Lock
from types import SimpleNamespace
from unittest.mock import patch

from support.dispatch_stub import arm_dispatch

from waves.desktop import backend
from waves.desktop.backend import WavesBridge, _JobSpec
from waves.desktop.job_runtime import JobRuntime


class _Signal:
    def __init__(self):
        self._jobs = JobRuntime()
        self.emits: list = []

    def emit(self, *args) -> None:
        self.emits.append(args)


class _InlinePool:
    def start(self, worker) -> None:
        worker.run()


class _Download:
    path_base = ""
    write_count = ok_count = fail_count = unavailable_count = 0
    list_unavailable = False

    def items(self, **kwargs):
        raise AssertionError("a stopped job must never reach the engine")

    def item(self, **kwargs):
        raise AssertionError("a stopped job must never reach the engine")


class _Stub:
    """Enough bridge for one job body, with the gate under the test's control."""

    def __init__(self, stop_during_the_probe: bool) -> None:
        self._jobs = JobRuntime()
        self._stop_during_the_probe = stop_during_the_probe
        self._logged_in = True
        self.providers = {"tidal": SimpleNamespace(get_object=lambda kind, raw_id: _media())}
        self._jobs.aborts: dict[int, Event] = {}
        self._jobs.signals: dict = {}
        self._jobs.dls: dict = {}
        self._jobs.tracks: dict = {}
        self._merge_plans: dict = {}
        self._redownload_overrides: set = set()
        self._library_claim_overrides: set = set()
        self._queue = [{"qid": 1, "media_id": "m1", "status": "queued", "type": "album", "name": "Album"}]
        self._queue_index = {1: self._queue[0]}
        self._queue_lock = Lock()
        self.settings = SimpleNamespace(
            data=SimpleNamespace(download_base_path="/tmp/waves-out", download_delay=False, downloads_concurrent_max=2)
        )
        self.dl = _Download()
        self.dl_pool = _InlinePool()
        self.downloadState = _Signal()
        self.downloadProgress = _Signal()
        self.statuses: list[str] = []
        self._track_poll = SimpleNamespace(isActive=lambda: True, start=lambda *a: None)
        arm_dispatch(self)

    # The row's status, recorded rather than delivered.
    def _set_queue_status(self, qid, status, reason: str = "") -> None:
        self._queue[0]["status"] = status
        self.statuses.append(status)

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
        self._jobs.signals.pop(qid, None)

    def _gate_reachability(self, retry, media_id) -> bool:
        """The probe. STOP lands while it is running, exactly as stopAll
        does: every row is marked cancelled and every job's abort is set."""
        if self._stop_during_the_probe:
            self._queue[0]["status"] = "cancelled"
            self._jobs.aborts[1].set()
        return True  # the mount answered in the end


def _media():
    return SimpleNamespace(
        id="m1", name="Album", artist=SimpleNamespace(name="Artist"), artists=[], audio_quality=None, duration=200
    )


def _run(*, stop_during_the_probe: bool) -> _Stub:
    stub = _Stub(stop_during_the_probe)
    spec = _JobSpec("tidal", "album", "tidal:m1", "Album", "{title}", True, "m1", None)
    with patch.object(backend, "_ProgressSignals", lambda *a, **k: object()):
        WavesBridge._start_job(stub, 1, spec)
    return stub


def test_a_stop_during_the_probe_leaves_the_row_stopped():
    stub = _run(stop_during_the_probe=True)

    assert stub._queue[0]["status"] == "cancelled"
    assert "running" not in stub.statuses, "the stopped row went back to running"


def test_a_stop_during_the_probe_never_re_lights_the_button():
    stub = _run(stop_during_the_probe=True)

    assert ("m1", "running") not in stub.downloadState.emits
    assert ("m1", "") in stub.downloadState.emits, "the button is handed back, idle"
    assert stub.downloadProgress.emits == [], "and nothing re-opens its progress bar at 0%"


def test_a_stopped_job_lets_go_of_everything_it_was_holding():
    stub = _run(stop_during_the_probe=True)

    assert stub._jobs.aborts == {}
    assert stub._jobs.signals == {}
    assert stub._jobs.dls == {}, "the per-track poll keeps ticking on a job it can still see"


def test_a_job_nobody_stopped_still_starts():
    stub = _run(stop_during_the_probe=False)

    assert stub.statuses == ["running"]
    assert ("m1", "running") in stub.downloadState.emits
