"""With "Skip existing" off, a download fetches every track (#693).

WHAT THIS FENCES OFF
--------------------
Turn "Skip existing" off and download a playlist into a new folder, to have
every song of it in one place: every song Waves had already downloaded into an
album folder was skipped anyway, and the row read IN LIBRARY (upstream
iamprivacy/Waves#53). The setting was only ever read at the destination path;
the gate that runs before the engine, the ownership ledger followed by the
library scan's tag claim, never asked it. Now a job queued with the setting off
consults neither gate and fetches every track. With it on, nothing changed.

The setting is pinned on the queue row the way askLibrarySkip is, so the run's
gate and the expanded row's prediction answer alike however Settings moves
while the queue works through.
"""

from __future__ import annotations

from threading import Lock
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from support.bridge_stub import BridgeStub
from support.dispatch_stub import arm_dispatch

from waves.desktop import backend
from waves.desktop.backend import WavesBridge, _TrackedDownload
from waves.desktop.queue.runtime import JobRuntime

# An owned copy at the quality every job here asks for (LOSSLESS), so with the
# gate armed it is current and skips.
_OWNED = {"path": "/music/Album Folder/01 Song.flac", "quality_rank": 2, "quality_tier": "LOSSLESS"}


# ---- the run's own gate ------------------------------------------------------


def _gate(*, skip_existing: bool, owned=_OWNED, claim=None) -> _TrackedDownload:
    """A real _TrackedDownload without Download.__init__ (which needs a live
    session), wired for the pre-fetch gate alone."""
    dl = _TrackedDownload.__new__(_TrackedDownload)
    dl._ownership_of = (lambda tid: dict(owned)) if owned else (lambda tid: None)
    dl._target_rank = 2  # LOSSLESS
    dl._skip_existing_base = skip_existing
    dl._library_claim = claim
    dl._force_redownload = False
    dl.settings = SimpleNamespace(data=SimpleNamespace(default_audio_type="stereo"))
    return dl


def _track(tid=42):
    return SimpleNamespace(id=tid, track_num=1, volume_num=1, duration=180, waves_identity_id=None)


def test_off_fetches_a_track_owned_in_another_folder():
    """The report itself: the copy an album download left elsewhere no longer
    stops the playlist's own copy from landing."""
    assert _gate(skip_existing=False)._claim_decision(_track())[0] is None


def test_on_still_skips_a_track_owned_in_another_folder():
    assert _gate(skip_existing=True)._claim_decision(_track())[0] == "skip"


def test_off_never_asks_the_library_claim():
    asked: list = []

    def claim(media):
        asked.append(media.id)
        return {"local_class": "LOSSLESS"}

    assert _gate(skip_existing=False, owned=None, claim=claim)._claim_decision(_track())[0] is None
    assert asked == []


def test_on_still_honors_the_library_claim():
    dl = _gate(skip_existing=True, owned=None, claim=lambda media: {"local_class": "LOSSLESS"})
    assert dl._claim_decision(_track())[0] == "skip"


def test_off_fetches_a_merge_member_too():
    member = _track()
    member.waves_identity_id = "7"
    assert _gate(skip_existing=False)._claim_decision(member, "{album}/{title}")[0] is None


def test_a_redownload_still_forces_with_the_setting_off():
    dl = _gate(skip_existing=False)
    dl._force_redownload = True
    assert dl._claim_decision(_track())[0] == "force"


# ---- the queue row pins the setting ------------------------------------------


class _Signal:
    def emit(self, *args) -> None:
        pass


class _HoldingPool:
    def start(self, worker) -> None:
        pass


class _Stub(BridgeStub):
    """Just what _enqueue, _job_skip_existing, _predict_skips and _download
    touch, with the real methods bound wherever the answer is under test."""

    _enqueue = WavesBridge._enqueue
    _queue_item = WavesBridge._queue_item
    _set_queue_status = WavesBridge._set_queue_status
    _job_library_skip = WavesBridge._job_library_skip
    _job_skip_existing = WavesBridge._job_skip_existing
    _skip_existing_on = WavesBridge._skip_existing_on
    _job_quality = WavesBridge._job_quality
    _queued_quality_value = WavesBridge._queued_quality_value
    _target_tier = WavesBridge._target_tier
    _target_quality_rank = WavesBridge._target_quality_rank
    _predict_skips = WavesBridge._predict_skips
    _download = WavesBridge._download
    _ask_quality_for = WavesBridge._ask_quality_for
    _quality_override_key = WavesBridge._quality_override_key
    _row_ask = WavesBridge._row_ask

    def __init__(self, skip_existing: bool) -> None:
        self._jobs = JobRuntime()
        self._logged_in = True
        self._queue_seq = 0
        self._queue: list = []
        self._queue_index: dict = {}
        self._queue_lock = Lock()
        self._merge_plans: dict = {}
        self._redownload_overrides: set = set()
        self._library_claim_overrides: set = set()
        self._objs = {"album": {}}
        # Every track is owned in some other folder, at the job's quality.
        self._ownership = SimpleNamespace(ownership_of=lambda tid: dict(_OWNED))
        self.settings = SimpleNamespace(
            data=SimpleNamespace(
                tidal_quality_audio="LOSSLESS",
                default_audio_type="stereo",
                download_base_path="/tmp/waves-out",
                download_delay=False,
                downloads_concurrent_max=2,
                skip_existing=skip_existing,
            )
        )
        self.dl_pool = _HoldingPool()
        self.downloadState = _Signal()
        self.downloadProgress = _Signal()
        self._track_poll = SimpleNamespace(isActive=lambda: True, start=lambda *a: None)
        arm_dispatch(self)
        self.built: list[dict] = []

    def _library_bulk_skip_on(self) -> bool:
        return False

    def _library_claim_media(self, media, album=None):
        return None

    def _emit_queue(self) -> None:
        pass

    def _download_gate(self) -> str:
        return "ok"

    def _ffmpeg_gate_holds(self, media_id, retry) -> bool:
        return False

    def _build_download(self, signals, **kwargs):
        self.built.append(kwargs)
        return SimpleNamespace(path_base="")

    def _set_status(self, msg) -> None:
        pass


def _playlist():
    return SimpleNamespace(
        id="pl-1",
        name="DJ Set",
        artist=None,
        artists=[],
        audio_quality=None,
        album=None,
        duration=200,
    )


def _tracks(*ids):
    return [SimpleNamespace(id=i, name=f"t{i}", duration=200) for i in ids]


def _queue_playlist(stub) -> int:
    return stub._enqueue("DJ Set", "playlist", "pl-1", collection=True)


def _dispatch(stub) -> dict:
    with patch.object(backend, "_ProgressSignals", lambda *a, **k: object()):
        stub._download(_playlist(), "playlist", "DJ Set", "{title}", True, "pl-1")
    assert len(stub.built) == 1, stub.built
    return stub.built[0]


@pytest.mark.parametrize("setting_on", [True, False])
def test_the_row_records_the_setting_it_was_queued_with(setting_on):
    stub = _Stub(setting_on)
    qid = _queue_playlist(stub)
    assert stub._queue_index[qid]["askSkipExisting"] is setting_on


@pytest.mark.parametrize("pinned", [True, False])
def test_a_captured_request_pins_its_own_setting(pinned):
    """A request captured at click time carries its own copy of the setting;
    the row pins that, whatever the live setting says at queue time."""
    stub = _Stub(not pinned)
    qid = stub._enqueue("DJ Set", "playlist", "pl-1", collection=True, skip_existing=pinned)
    assert stub._job_skip_existing(qid) is pinned


@pytest.mark.parametrize("pinned", [True, False])
def test_changing_the_setting_afterwards_does_not_reach_a_queued_row(pinned):
    stub = _Stub(pinned)
    qid = _queue_playlist(stub)
    stub.settings.data.skip_existing = not pinned
    assert stub._job_skip_existing(qid) is pinned


def test_a_row_from_before_the_field_reads_the_setting():
    stub = _Stub(False)
    qid = _queue_playlist(stub)
    del stub._queue_index[qid]["askSkipExisting"]
    assert stub._job_skip_existing(qid) is False


@pytest.mark.parametrize("pinned", [True, False])
def test_the_run_is_built_with_the_rows_pin(pinned):
    """The job's download is built with what the row says: the setting moves
    the moment the row is created, so a build that read Settings instead would
    land on the opposite."""
    stub = _Stub(pinned)
    enqueue = stub._enqueue

    def enqueue_then_flip(*a, **k):
        qid = enqueue(*a, **k)
        stub.settings.data.skip_existing = not pinned
        return qid

    stub._enqueue = enqueue_then_flip
    assert _dispatch(stub)["skip_existing"] is pinned


def test_a_row_queued_off_promises_no_skips():
    """The drawer must not paint IN LIBRARY on a track the run will fetch."""
    stub = _Stub(False)
    qid = _queue_playlist(stub)
    stub.settings.data.skip_existing = True  # moved after queueing: no effect
    assert stub._predict_skips(qid, stub._queue_index[qid], _tracks("1", "2")) == {}


def test_a_row_queued_on_still_predicts_the_owned_skips():
    stub = _Stub(True)
    qid = _queue_playlist(stub)
    marks = stub._predict_skips(qid, stub._queue_index[qid], _tracks("1"))
    assert set(marks) == {"1"} and marks["1"]["kind"] == "own", marks


@pytest.mark.parametrize("pinned", [True, False])
def test_the_run_and_the_expanded_row_answer_alike(pinned):
    stub = _Stub(pinned)
    built = _dispatch(stub)
    stub.settings.data.skip_existing = not pinned
    qid = stub._queue[0]["qid"]
    marks = stub._predict_skips(qid, stub._queue_index[qid], _tracks("1"))
    assert built["skip_existing"] is pinned
    assert bool(marks) is pinned, marks


@pytest.mark.parametrize("setting_on", [True, False])
def test_a_captured_request_carries_the_setting_it_was_made_with(setting_on):
    """The click-time snapshot holds Skip existing, so a request's row pins the
    setting as it stood when the person clicked."""
    from waves.model.cfg import Settings
    from waves.model.download_policy import capture_intent

    data = Settings()
    data.skip_existing = setting_on
    intent = capture_intent(data, "tidal", "album", "tidal:1", tier="LOSSLESS", audio_type=None, toggles={})
    data.skip_existing = not setting_on
    assert intent.skip_existing is setting_on
