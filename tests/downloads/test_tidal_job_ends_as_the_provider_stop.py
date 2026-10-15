"""A TIDAL job that a provider stop overtakes ends as that stop.

Signing out of TIDAL words the provider's rows cancelled under the queue lock,
then cleans up before it sets the jobs' aborts. A job that read its abort
clear can still start, resolve its target, finish or fail in that window. The
queue refuses each of those writes, so the row keeps the stop's words, and the
job hands its button back idle instead of lighting it running, done or failed.
"""

from __future__ import annotations

from threading import Event, Lock
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from support.bridge_stub import BridgeStub
from support.dispatch_stub import arm_dispatch

from waves.desktop import backend
from waves.desktop.backend import WavesBridge, _JobSpec
from waves.desktop.queue.bridge import QueueMixin
from waves.errors import DownloadIncomplete

_WORDS = "Signed out of TIDAL"


class _Signal:
    def __init__(self) -> None:
        self.emits: list = []

    def emit(self, *args) -> None:
        self.emits.append(args)


class _InlinePool:
    def start(self, worker) -> None:
        worker.run()


class _Download:
    path_base = ""
    unavailable_count = 0

    def __init__(self, stub: _Stub) -> None:
        self._stub = stub
        self.settings = stub.settings

    def item(self, **kwargs):
        self._stub.stop_if("finish", "fail")
        if self._stub.stop_lands == "fail":
            raise RuntimeError("synthetic engine failure")
        return True, "/tmp/waves-out/Track.flac"


class _Stub(BridgeStub, QueueMixin):
    """One TIDAL track job with the real queue status rules, and a provider
    stop that rewrites the row (its abort still to come) where the test says."""

    def __init__(self, stop_lands: str) -> None:
        self.stop_lands = stop_lands
        self._logged_in = True
        self.providers = {
            "tidal": SimpleNamespace(
                get_object=self._resolve, classify_refusal=lambda exc: SimpleNamespace(kind=None, message="")
            )
        }
        self._queue = [{"qid": 1, "media_id": "m1", "status": "queued", "reason": "", "type": "track", "name": "Track"}]
        self._queue_lock = Lock()
        self._merge_plans: dict = {}
        self._redownload_overrides: set = set()
        self._library_claim_overrides: set = set()
        self.settings = SimpleNamespace(
            data=SimpleNamespace(download_base_path="/tmp/waves-out", download_delay=False, downloads_concurrent_max=2)
        )
        self.dl_pool = _InlinePool()
        self.downloadState = _Signal()
        self.downloadProgress = _Signal()
        self.statuses: list[str] = []
        self._track_poll = SimpleNamespace(isActive=lambda: True, start=lambda *a: None)
        self.dl = _Download(self)
        arm_dispatch(self)
        self._jobs.aborts[1] = Event()

    def stop_if(self, *moments: str) -> None:
        if self.stop_lands in moments:
            with self._queue_lock:
                self._queue[0]["status"], self._queue[0]["reason"] = "cancelled", _WORDS

    def _resolve(self, kind, raw_id):
        self.stop_if("resolve")
        if self.stop_lands == "resolve":
            raise RuntimeError("synthetic catalog failure")
        return SimpleNamespace(id="m1", name="Track", artist=SimpleNamespace(name="Artist"), artists=[], duration=200)

    def _gate_reachability(self, retry, media_id) -> bool:
        self.stop_if("probe", "probe raises")
        if self.stop_lands == "probe raises":
            raise DownloadIncomplete("The original download folder is unavailable. Retry after reconnecting it.")
        return True

    def _emit_queue(self) -> None:
        pass

    def _set_status(self, msg) -> None:
        self.statuses.append(msg)

    def _set_queue_progress(self, qid, pct) -> None:
        pass

    def _job_library_skip(self, qid: int) -> bool:
        return False

    def _row_ask(self, qid):
        return None

    def _job_quality(self, qid):
        return None

    def _build_download(self, signals, **kwargs):
        return self.dl

    def _release_job_signals(self, qid) -> None:
        self._jobs.signals.pop(qid, None)

    def _download_failed_with_folder(self, *args) -> bool:
        return False  # the folder answers: the track itself failed


def _run(stop_lands: str) -> _Stub:
    stub = _Stub(stop_lands)
    spec = _JobSpec("tidal", "track", "tidal:m1", "Track", "{title}", False, "m1", None)
    with patch.object(backend, "_ProgressSignals", lambda *a, **k: object()):
        WavesBridge._start_job(stub, 1, spec)
    return stub


@pytest.mark.parametrize("stop_lands", ["resolve", "probe", "probe raises", "finish", "fail"])
def test_a_tidal_job_overtaken_by_a_provider_stop_keeps_its_words(stop_lands):
    stub = _run(stop_lands)

    row = stub._queue[0]
    assert (row["status"], row["reason"]) == ("cancelled", _WORDS)
    assert stub.downloadState.emits[-1] == ("m1", ""), "the button is handed back idle"


@pytest.mark.parametrize("stop_lands", ["resolve", "probe", "probe raises"])
def test_a_tidal_job_stopped_before_it_starts_never_lights_its_button(stop_lands):
    stub = _run(stop_lands)

    assert ("m1", "running") not in stub.downloadState.emits
    assert stub.downloadProgress.emits == []


@pytest.mark.parametrize("stop_lands", ["finish", "fail"])
def test_a_tidal_run_that_ends_inside_the_stop_reads_cancelled(stop_lands):
    stub = _run(stop_lands)

    assert stub.statuses[-1] == "Cancelled Track"


def test_a_tidal_job_nobody_stopped_still_finishes():
    stub = _run("nowhere")

    assert stub._queue[0]["status"] == "done"
    assert stub.downloadState.emits[-1] == ("m1", "done")
    assert stub.statuses[-1].startswith("Finished Track")
