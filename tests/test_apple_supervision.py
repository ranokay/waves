"""Session supervision + pacing (issue #33, spec §3)."""

from __future__ import annotations

from pathlib import Path
from threading import Event
from types import SimpleNamespace

from waves.apple_supervision import (
    HELD_POLL_SEC,
    IDLE_TIMEOUT_DEFAULT,
    PACING_BATCH_DEFAULT,
    PACING_DELAY_DEFAULT,
    THROTTLE_CAP_SEC,
    WRAPPER_CONTAINER_NAME,
    SidecarSupervisor,
    container_run_args,
    container_start_args,
    container_stop_args,
    health_url,
    held_message,
    is_health_ok,
    is_wrapper_down_error,
    pacing_due,
    pacing_policy,
    parse_retry_after,
    probe_health,
    throttle_delay,
    throttled_message,
)
from waves.model.cfg import HelpSettings, Settings
from waves.waves_ui.backend import WavesBridge


def test_settings_carry_the_supervision_defaults():
    data = Settings()
    assert (data.apple_pacing_batch_size, data.apple_pacing_delay_sec) == (25, 30.0)
    assert data.apple_wrapper_idle_sec == 300.0
    assert PACING_BATCH_DEFAULT == 25 and PACING_DELAY_DEFAULT == 30.0
    assert IDLE_TIMEOUT_DEFAULT == 300.0
    help_text = HelpSettings()
    assert "Apple" in help_text.apple_pacing_batch_size
    assert "Apple" in help_text.apple_pacing_delay_sec
    assert "idle" in help_text.apple_wrapper_idle_sec.lower()


def test_pacing_policy_sanitizes_and_due_marks_batch_boundaries():
    assert pacing_policy(25, 30.0) == (25, 30.0)
    assert pacing_policy(0, 30.0) == (0, 30.0)
    assert pacing_policy(25, 0) == (25, 0.0)
    assert pacing_policy("many", 30.0) == (0, 0.0)
    assert pacing_policy(25, None) == (25, 0.0)
    assert pacing_due(1, 25) is False
    assert pacing_due(26, 25) is True
    assert pacing_due(51, 25) is True
    assert pacing_due(27, 25) is False
    assert pacing_due(2, 0) is False


def test_throttle_delay_is_exponential_then_capped_and_retry_after_wins():
    assert throttle_delay(0) == 5.0
    assert throttle_delay(1) == 10.0
    assert throttle_delay(2) == 20.0
    assert throttle_delay(10) == THROTTLE_CAP_SEC
    assert throttle_delay(0, 42.0) == 42.0
    assert throttle_delay(3, 500.0) == THROTTLE_CAP_SEC
    assert throttle_delay(0, None) == 5.0


def test_parse_retry_after_reads_headers_attrs_and_words():
    assert parse_retry_after(SimpleNamespace(headers={"Retry-After": "120"})) == 120.0
    assert parse_retry_after(SimpleNamespace(headers={"retry-after": "30"})) == 30.0
    assert parse_retry_after(SimpleNamespace(headers={"Retry-after": "44"})) == 44.0
    assert parse_retry_after(SimpleNamespace(response=SimpleNamespace(headers={"Retry-After": "7"}))) == 7.0
    assert parse_retry_after(SimpleNamespace(retry_after=17)) == 17.0
    assert parse_retry_after(RuntimeError("HTTP 429 Retry-After: 45")) == 45.0
    assert parse_retry_after(RuntimeError("rate limited, retry in 12s")) == 12.0
    assert parse_retry_after(RuntimeError("boom")) is None


def test_parse_retry_after_accepts_an_http_date():
    import datetime
    from email.utils import format_datetime

    future = datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=120)
    headers = {"Retry-After": format_datetime(future, usegmt=True)}
    wait = parse_retry_after(SimpleNamespace(headers=headers))
    assert wait is not None and 0.0 < wait <= 120.0


def test_presentations_carry_one_clear_message_with_countdown():
    held = held_message()
    assert "Held" in held and "runtime" in held.lower()
    assert "Apple" in throttled_message(20) and "20s" in throttled_message(20)
    assert "Retrying now" in throttled_message(0)


def test_wrapper_down_means_held_never_credentials_or_integrity():
    from waves.apple_engine import AppleCredentialsError, AppleDownloadError, AppleIntegrityError, AppleWrapperDown

    assert is_wrapper_down_error(AppleWrapperDown("Apple wrapper is unreachable at x: refused")) is True
    assert is_wrapper_down_error(AppleCredentialsError("need cookies")) is False
    assert is_wrapper_down_error(AppleIntegrityError("integrity check")) is False
    assert is_wrapper_down_error(AppleDownloadError("Apple wrapper is unreachable: connection refused")) is True
    assert is_wrapper_down_error(RuntimeError("boom")) is False


def test_held_hierarchy_is_single_and_catchable_as_a_download_error():
    import waves.apple_engine as engine
    import waves.apple_supervision as supervision

    assert supervision.AppleHeld is engine.AppleHeld
    assert supervision.AppleWrapperDown is engine.AppleWrapperDown
    assert issubclass(engine.AppleWrapperDown, engine.AppleDownloadError)
    assert issubclass(engine.AppleWrapperDown, engine.AppleHeld)


def test_classify_maps_a_dead_sidecar_to_retryable_failure_never_unavailable():
    from waves.apple_engine import AppleWrapperDown
    from waves.providers.apple import AppleProvider
    from waves.providers.base import RefusalKind

    verdict = AppleProvider.classify_refusal(AppleProvider(), AppleWrapperDown("Apple wrapper is unreachable"))
    assert verdict.kind is RefusalKind.FAILURE


def test_container_run_args_map_high_ports_and_mount_the_session():
    args = container_run_args(image="img:1", http_port=51234, decrypt_port=51235, data_dir="/tmp/wd")
    assert args[:3] == ["docker", "run", "-d"]
    assert "--name" in args and WRAPPER_CONTAINER_NAME in args
    assert "51234:80" in args and "51235:10020" in args
    assert "/tmp/wd:/app/rootfs/data/data/com.apple.android.music/files" in args
    assert args[-1] == "img:1"
    assert "SYS_ADMIN" in args
    assert container_start_args() == ["docker", "start", WRAPPER_CONTAINER_NAME]
    assert container_stop_args() == ["docker", "stop", WRAPPER_CONTAINER_NAME]


def test_health_probe_shape():
    assert health_url(51234) == "http://127.0.0.1:51234/health"
    assert is_health_ok({"status": "ok", "runtime": {"playback_ready": True}}) is True
    assert is_health_ok({"status": "ok", "runtime": {"playback_ready": False}}) is False
    assert is_health_ok({"status": "error"}) is False
    assert is_health_ok(None) is False

    class _Resp:
        status_code = 200

        def json(self):
            return {"status": "ok", "version": "1"}

    assert probe_health(1, http_get=lambda url, timeout=5: _Resp()) == {"status": "ok", "version": "1"}

    def _boom(url, timeout=5):
        raise ConnectionError("down")

    assert probe_health(1, http_get=_boom) is None


def test_supervisor_idles_and_stops_only_when_truly_idle():
    now = [1000.0]
    sup = SidecarSupervisor(runner=lambda *a, **k: SimpleNamespace(returncode=0), monotonic=lambda: now[0])
    assert sup.idle_seconds() == 0.0
    sup.note_activity()
    assert sup.should_stop(300.0) is False
    assert sup.should_stop(300.0, apple_busy=True) is False
    now[0] += 301.0
    assert sup.should_stop(300.0) is True
    assert sup.should_stop(0) is False


def test_supervisor_zero_monotonic_reading_is_real_activity_not_never():
    sup = SidecarSupervisor(runner=lambda *a, **k: SimpleNamespace(returncode=0), monotonic=lambda: 0.0)
    assert sup._last_activity is None
    sup.note_activity()
    assert sup._last_activity == 0.0
    assert sup.should_stop(300.0, apple_busy=False) is False
    sup._monotonic = lambda: 301.0
    assert sup.should_stop(300.0, apple_busy=False) is True


def test_supervisor_ready_and_ensure_paths():
    ok_probe = lambda url, timeout=5: SimpleNamespace(status_code=200, json=lambda: {"status": "ok"})
    sup = SidecarSupervisor(
        runner=lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""),
        http_get=ok_probe,
        monotonic=lambda: 0.0,
    )
    assert sup.is_ready(1) is True

    # Healthy already: no subprocess at all.
    calls: list = []
    sup2 = SidecarSupervisor(
        runner=lambda *a, **k: (calls.append(a[0]), SimpleNamespace(returncode=0))[1],
        http_get=ok_probe,
    )
    assert sup2.ensure_started(http_port=1, image="img:1", data_dir="/tmp/nowhere-supervision") is True
    assert calls == []

    # Down then started: lists containers (none), runs fresh, then healthy.
    probes = {"n": 0}

    def _flapping(url, timeout=5):
        probes["n"] += 1
        payload = {"status": "ok"} if probes["n"] > 1 else None
        if payload is None:
            raise ConnectionError("down")
        return SimpleNamespace(status_code=200, json=lambda: payload)

    seen: list = []
    tmp = Path("/tmp/waves-supervision-ensure")
    sup3 = SidecarSupervisor(
        manager=SimpleNamespace(app_dir="/tmp/waves-supervision-app"),
        runner=lambda *a, **k: (seen.append(a[0]), SimpleNamespace(returncode=0, stdout="", stderr=""))[1],
        http_get=_flapping,
    )
    assert sup3.ensure_started(http_port=51234, image="img:1", data_dir=str(tmp)) is True
    assert any(cmd[:2] == ["docker", "run"] for cmd in seen)
    assert sup3.stop() is True


def test_supervisor_recreates_a_running_but_unhealthy_container(tmp_path):
    from waves.apple_supervision import container_states

    assert container_states("waves-wrapper-v2 running\nother exited") == {
        "waves-wrapper-v2": "running",
        "other": "exited",
    }
    probes = {"n": 0}

    def _never_healthy(url, timeout=5):
        probes["n"] += 1
        raise ConnectionError("down")

    seen: list = []

    def _runner(args, **kwargs):
        seen.append(list(args))
        if args[:2] == ["docker", "ps"]:
            return SimpleNamespace(returncode=0, stdout="waves-wrapper-v2 running\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    sup = SidecarSupervisor(runner=_runner, http_get=_never_healthy, monotonic=lambda: 0.0)
    assert sup.ensure_started(http_port=51234, image="img:1", data_dir=str(tmp_path / "wd")) is False
    kinds = [cmd[:2] for cmd in seen]
    assert ["docker", "ps"] in kinds
    # Running-but-unhealthy is never plain-started; it is removed and rerun.
    assert ["docker", "start"] not in kinds
    assert ["docker", "rm"] in kinds
    assert ["docker", "run"] in kinds


def _bridge_stub(**settings_overrides):
    data = SimpleNamespace(apple_pacing_batch_size=0, apple_pacing_delay_sec=0.0, apple_wrapper_idle_sec=0.0)
    for key, value in settings_overrides.items():
        setattr(data, key, value)
    stub = SimpleNamespace(settings=SimpleNamespace(data=data), _apple_runtime=None, _apple_supervisor=None)
    for name in (
        "_apple_setting",
        "_apple_effective_wrapper_port",
        "_apple_pacing_policy",
        "_apple_pace_if_due",
        "_apple_throttle_delay",
        "_apple_throttle_wait",
        "_apple_set_held",
        "_apple_needs_wrapper",
        "_apple_supervisor_for_job",
        "_apple_wrapper_port_for_job",
        "_apple_ensure_sidecar",
        "_apple_note_activity",
        "_apple_idle_timeout",
        "_apple_sleep_abortable",
    ):
        setattr(stub, name, getattr(WavesBridge, name).__get__(stub, SimpleNamespace))
    stub._queue_index = {}
    stub._queue_item = lambda qid: stub._queue_index.get(qid)
    stub._set_queue_status = lambda qid, status, reason="": (
        stub._queue_index.setdefault(int(qid), {}).__setitem__("status", status)
        or stub._queue_index[int(qid)].__setitem__("reason", reason)
    )
    stub._set_status = lambda msg: setattr(stub, "last_status", msg)
    return stub


def test_backend_pacing_reads_settings_and_never_pauses_without_them():
    stub = _bridge_stub(apple_pacing_batch_size=25, apple_pacing_delay_sec=30.0)
    assert stub._apple_pacing_policy() == (25, 30.0)
    stub_plain = _bridge_stub()
    assert stub_plain._apple_pacing_policy() == (0, 0.0)
    # No pause configured: due check passes through without sleeping.
    assert stub_plain._apple_pace_if_due(26, Event()) is True


def test_backend_proactive_pause_sleeps_once_per_batch(tmp_path):
    stub = _bridge_stub(apple_pacing_batch_size=25, apple_pacing_delay_sec=30.0)
    slept: list = []
    stub._apple_sleep_abortable = lambda secs, abort: slept.append(secs) or True
    assert stub._apple_pace_if_due(26, Event(), 1) is True
    assert slept == [30.0]
    assert stub._apple_pace_if_due(27, Event(), 1) is True
    assert slept == [30.0]


def test_backend_throttle_wait_counts_down_and_respects_stop():
    stub = _bridge_stub()
    abort = Event()
    assert stub._apple_throttle_wait(7, 0.05, abort) is True
    row = stub._queue_index[7]
    assert row["status"] == "running" and "Throttled" in row["reason"]
    abort2 = Event()
    abort2.set()
    assert stub._apple_throttle_wait(8, 30.0, abort2) is False


def test_backend_held_keeps_the_row_queued_with_its_reason():
    stub = _bridge_stub()
    stub._queue_index[3] = {"status": "running", "reason": ""}
    stub._apple_set_held(3)
    assert stub._queue_index[3]["status"] == "queued"
    assert "Held" in stub._queue_index[3]["reason"]


def test_backend_needs_wrapper_only_for_lossless_and_up():
    from waves.constants import QualityTier, quality_rank

    stub = _bridge_stub()
    assert stub._apple_needs_wrapper(quality_rank(QualityTier.HIGH)) is False
    assert stub._apple_needs_wrapper(quality_rank(QualityTier.LOSSLESS)) is True
    assert stub._apple_needs_wrapper(quality_rank(QualityTier.HI_RES_LOSSLESS)) is True


def test_backend_ensure_skips_cookies_tier_and_holds_a_dead_sidecar(tmp_path):
    from waves.constants import QualityTier, quality_rank

    # Cookies-tier ask: no sidecar, no hold, even with no manager at all.
    stub = _bridge_stub()
    assert stub._apple_ensure_sidecar(1, Event(), need_wrapper=False) is True

    # Wrapper-tier ask with no tier set up: the cookies path serves alone.
    stub2 = _bridge_stub()
    stub2._apple_runtime = SimpleNamespace(read_port=lambda: 0)
    stub2.providers = {__import__("waves.constants", fromlist=["CTX_APPLE"]).CTX_APPLE: SimpleNamespace(wrapper_url="")}
    assert stub2._apple_ensure_sidecar(1, Event(), need_wrapper=True) is True

    # Wrapper-tier ask with a configured but dead sidecar: held, then resume.
    # The first start attempt fails while the row visibly waits; the sleep
    # callback asserts the held presentation mid-wait, then the retry heals.
    states = {"ready": False, "starts": 0}

    class _Sup:
        def is_ready(self, port):
            return states["ready"]

        def ensure_started(self, **kwargs):
            states["starts"] += 1
            if states["starts"] < 2:
                return False
            states["ready"] = True
            return True

        def note_activity(self):
            return None

    stub3 = _bridge_stub()
    stub3._apple_runtime = SimpleNamespace(read_port=lambda: 51234, app_dir=str(tmp_path))
    stub3.providers = {
        __import__("waves.constants", fromlist=["CTX_APPLE"]).CTX_APPLE: SimpleNamespace(
            wrapper_url="http://127.0.0.1:51234"
        )
    }
    stub3._apple_supervisor = _Sup()

    def _sleep_once(secs, abort):
        row = stub3._queue_index[9]
        assert row["status"] == "queued" and "Held" in row["reason"]
        return True

    stub3._apple_sleep_abortable = _sleep_once
    stub3._queue_index[9] = {"status": "running", "reason": ""}
    assert stub3._apple_ensure_sidecar(9, Event(), need_wrapper=True) is True
    assert states["ready"] is True
    assert stub3._queue_index[9]["status"] == "running"
    assert stub3._queue_index[9]["reason"] == ""

    # STOP while held: the wait ends promptly as a stop, for RETRY ALL.
    stub4 = _bridge_stub()
    stub4._apple_runtime = SimpleNamespace(read_port=lambda: 51234, app_dir=str(tmp_path))
    stub4.providers = {
        __import__("waves.constants", fromlist=["CTX_APPLE"]).CTX_APPLE: SimpleNamespace(
            wrapper_url="http://127.0.0.1:51234"
        )
    }
    stub4._apple_supervisor = SimpleNamespace(
        is_ready=lambda port: False, ensure_started=lambda **k: False, note_activity=lambda: None
    )
    abort = Event()
    abort.set()
    assert stub4._apple_ensure_sidecar(11, abort, need_wrapper=True) is False
    _ = quality_rank(QualityTier.HIGH)


def test_queue_drawer_shows_held_and_throttled_presentations():
    qml = Path("waves/waves_ui/qml/Main.qml").read_text(encoding="utf-8")
    assert 'if (qrow.st === "queued") return a + (model.reason ? model.reason : "Queued")' in qml
    assert 'if (qrow.st === "running" && model.reason) return a + model.reason' in qml


def test_held_poll_tick_is_sane():
    assert 1.0 <= float(HELD_POLL_SEC) <= 30.0
