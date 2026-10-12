"""Public bridge runtime choices do not acquire an external service's lifecycle."""

from contextlib import nullcontext
from threading import Event, Lock
from types import SimpleNamespace

import pytest
from support.bridge_stub import BridgeStub

from waves.desktop.backend import WavesBridge
from waves.providers.apple.runtime import AppleRuntimeManager
from waves.providers.apple.runtime_sessions import AppleRuntimeSessions, RuntimeKind, RuntimeProfile, SessionEvidence
from waves.providers.apple.supervision import RuntimeIdentity, SidecarSupervisor


def bridge(tmp_path):
    workers, commands = [], []
    sessions = AppleRuntimeSessions(tmp_path)
    profile = RuntimeProfile("apple:wrapper-v2", RuntimeKind.USER_MANAGED, "wrapper-v2", "http://127.0.0.1:50100")
    supervisor = SidecarSupervisor(runner=lambda *args, **kwargs: commands.append(args))
    supervisor.configure_runtime(profile, sessions)
    host = BridgeStub(
        _apple_runtime=AppleRuntimeManager(tmp_path),
        _apple_runtime_sessions=sessions,
        _apple_supervisor=supervisor,
        _apple_runtime_abort=Event(),
        _apple_runtime_profile=profile,
        _apple_engine_facts_gen=0,
        settings=SimpleNamespace(
            data=SimpleNamespace(apple_runtime_mode="user_managed", apple_wrapper_url=profile.endpoint)
        ),
        threadpool=SimpleNamespace(start=workers.append),
        _apple_sidecar_guard=nullcontext,
        _invalidate_apple_engine_facts=lambda: None,
        _configure_apple_provider=lambda: None,
    )
    return host, sessions, workers, commands


def account_bridge(tmp_path):
    host, sessions, workers, commands = bridge(tmp_path)
    deliveries = []
    host._catalogEvent = SimpleNamespace(emit=deliveries.append)
    host._apple_wrapper_base = lambda: host._apple_runtime_profile.endpoint
    host._apple_wrapper_auth_refresh_lock = Lock()
    for name in (
        "apple_wrapper_auth_state",
        "_schedule_apple_wrapper_auth_refresh",
        "_scheduled_apple_wrapper_auth_refresh",
        "_refresh_apple_wrapper_auth",
    ):
        setattr(host, name, getattr(WavesBridge, name).__get__(host))
    return host, sessions, workers, commands, deliveries


def test_public_stop_disconnects_external_runtime_on_worker_and_can_be_explicitly_resumed(tmp_path):
    host, sessions, workers, commands = bridge(tmp_path)
    WavesBridge.stopAppleExecution(host)
    assert len(workers) == 1
    workers.pop().run()
    assert sessions.is_stopped("apple:wrapper-v2")
    assert commands == []
    WavesBridge.resumeAppleExecution(host)
    workers.pop().run()
    assert not sessions.is_stopped("apple:wrapper-v2")
    assert commands == []


def test_image_restore_uses_the_detected_container_runtime(tmp_path):
    host, _, workers, _ = bridge(tmp_path)
    restored = []
    host._apple_container_state = lambda: {"name": "podman"}
    host._apple_runtime.rollback_image = lambda **kwargs: restored.append(kwargs["binary"])
    WavesBridge.rollbackAppleImage(host)
    workers.pop().run()
    assert restored == ["podman"]


def test_saving_a_different_cookies_export_immediately_revokes_admission(tmp_path):
    from waves.model.cfg import Settings
    from waves.providers.apple.provider import AppleProvider

    host, sessions, _, _ = bridge(tmp_path)
    profile = host._apple_runtime_profile
    sessions.configure(profile)
    sessions.observe(profile.id, SessionEvidence(True, True, True, True))
    assert sessions.confirm_account(profile.id)
    revision = sessions.revision(profile.id)
    host.providers = {"apple": AppleProvider()}
    host.providers["apple"].cookies_path = "old-cookies.txt"
    host.settings.data = Settings()
    host.settings.data.apple_cookies_path = "old-cookies.txt"
    host.settings.data.apple_runtime_mode = "user_managed"
    host.settings.data.apple_wrapper_url = profile.endpoint
    host._waves_prefs = {}
    host._settings_save_lock = Lock()
    host._ffmpeg_flag_prefs = {}
    host._resolve_ffmpeg_locked = lambda: ""
    host._resolve_apple_wrapper_url = lambda: profile.endpoint
    host._configure_apple_provider = WavesBridge._configure_apple_provider.__get__(host)
    host._submit_settings_write = lambda: None
    host._ffmpeg_source_label = lambda: "missing"
    host._logged_in = False
    host._set_status = lambda message: None
    WavesBridge.applySettings(host, {"apple_cookies_path": "new-cookies.txt"})
    assert sessions.revision(profile.id)[0] != revision[0]
    assert not sessions.confirm_account(profile.id)


def test_observed_machine_account_change_revokes_admission_with_unchanged_display_label(tmp_path, monkeypatch):
    host, sessions, workers, _, deliveries = account_bridge(tmp_path)
    profile = host._apple_runtime_profile
    sessions.configure(profile)
    sessions.observe(profile.id, SessionEvidence(True, True, True, True))
    assert sessions.confirm_account(profile.id)
    revision = sessions.revision(profile.id)
    old = {
        "reachable": True,
        "state": "authenticated",
        "logged_in": True,
        "account": "same-label",
        "account_id": "first",
    }
    host._apple_wrapper_auth_cache = {"at": 0.0, "result": old}
    host._apple_supervisor.observe_identity = lambda *args: RuntimeIdentity(True, "observed-runtime")
    monkeypatch.setattr(
        "waves.providers.apple.runtime.wrapper_auth_state", lambda *args, **kwargs: {**old, "account_id": "second"}
    )
    WavesBridge.appleWrapperAuth(host)
    workers.pop().run()
    deliveries.pop().deliver()
    assert sessions.revision(profile.id) != revision
    assert not WavesBridge.appleExecutionState(host)["can_confirm"]
    assert WavesBridge.appleWrapperAuth(host)["account"] == "same-label"
    assert host.appleWrapperAuthChanged.emits


@pytest.mark.parametrize("identity_verified", [None, False])
def test_account_check_does_not_contact_an_unverified_runtime(tmp_path, monkeypatch, identity_verified):
    host, _, workers, _, deliveries = account_bridge(tmp_path)
    calls = []
    host._apple_supervisor.observe_identity = lambda *args: RuntimeIdentity(identity_verified, "runtime-1")
    monkeypatch.setattr("waves.providers.apple.runtime.wrapper_auth_state", lambda *a, **kw: calls.append(True))

    assert not WavesBridge.appleWrapperAuth(host)["logged_in"]
    workers.pop().run()
    deliveries.pop().deliver()
    result = WavesBridge.appleWrapperAuth(host)

    assert calls == []
    assert result["reachable"] is False
    assert result["logged_in"] is False
    assert "not been verified" in result["error"]
    assert not WavesBridge.appleExecutionState(host)["can_confirm"]


def test_account_check_discards_a_response_when_the_runtime_instance_changes(tmp_path, monkeypatch):
    host, _, workers, _, deliveries = account_bridge(tmp_path)
    identities = iter((RuntimeIdentity(True, "runtime-1"), RuntimeIdentity(True, "runtime-2")))
    host._apple_supervisor.observe_identity = lambda *args: next(identities)
    monkeypatch.setattr(
        "waves.providers.apple.runtime.wrapper_auth_state",
        lambda *args, **kwargs: {"reachable": True, "state": "authenticated", "logged_in": True},
    )

    WavesBridge.appleWrapperAuth(host)
    workers.pop().run()
    deliveries.pop().deliver()
    result = WavesBridge.appleWrapperAuth(host)

    assert result["reachable"] is False
    assert result["logged_in"] is False
    assert result["error"] == "Runtime changed during account check"
    assert WavesBridge.appleExecutionState(host)["state"] == "unknown"
    assert not WavesBridge.appleExecutionState(host)["can_confirm"]


def test_queued_account_result_waits_for_gui_and_is_discarded_after_stop(tmp_path, monkeypatch):
    host, _, workers, _, deliveries = account_bridge(tmp_path)
    host._apple_supervisor.observe_identity = lambda *args: RuntimeIdentity(True, "runtime-1")
    monkeypatch.setattr(
        "waves.providers.apple.runtime.wrapper_auth_state",
        lambda *args, **kwargs: {"reachable": True, "state": "authenticated", "logged_in": True},
    )
    assert not WavesBridge.appleWrapperAuth(host)["logged_in"]
    workers.pop().run()
    assert not host.appleWrapperAuthChanged.emits
    assert len(deliveries) == 1
    assert not WavesBridge.appleWrapperAuth(host)["logged_in"]

    WavesBridge.stopAppleExecution(host)
    deliveries.pop().deliver()

    assert not WavesBridge.appleWrapperAuth(host)["logged_in"]
    assert WavesBridge.appleExecutionState(host)["state"] == "stopped"
    assert not host.appleWrapperAuthChanged.emits


def test_account_check_uses_the_detected_container_runtime(tmp_path, monkeypatch):
    host, sessions, workers, commands, deliveries = account_bridge(tmp_path)
    host._apple_runtime_profile = RuntimeProfile(
        "apple:wrapper-v2",
        RuntimeKind.USER_MANAGED,
        "wrapper-v2",
        "http://127.0.0.1:50100",
        "sha256:" + "a" * 64,
        container="my-wrapper",
    )
    sessions.configure(host._apple_runtime_profile)
    host._apple_container_state = lambda: {"name": "podman"}
    monkeypatch.setattr("waves.providers.apple.runtime.wrapper_auth_state", lambda *a, **kw: {})
    WavesBridge.appleWrapperAuth(host)
    workers.pop().run()
    deliveries.pop().deliver()
    assert commands
    assert all(command[0][0] == "podman" for command in commands)
    assert not WavesBridge.appleWrapperAuth(host)["logged_in"]
    assert not WavesBridge.appleExecutionState(host)["can_confirm"]


@pytest.mark.parametrize("change", ["instance", "stop_during_probe", "stop_before_publish"])
def test_engine_presentation_does_not_admit_stale_runtime_or_stop_context(tmp_path, change):
    from waves.providers.apple.provider import AppleProvider

    host, sessions, workers, _ = bridge(tmp_path)
    pending = []
    host.providers = {"apple": AppleProvider()}
    host._apple_live_flags = lambda: {"enabled": True, "cookies_account_ready": False, "wrapper_ready": True}
    host._apple_fetch_binary_ready = lambda: True
    host._apple_container_serves = lambda: True
    host._catalogEvent = SimpleNamespace(emit=pending.append)
    host._apple_wrapper_auth_cache = {
        "result": {"reachable": True, "state": "authenticated", "logged_in": True, "storefront": "us"},
        "runtime_revision": "runtime-1",
    }
    sessions.configure(host._apple_runtime_profile)
    for name in ("_apple_engine_details", "_apple_engine_facts"):
        setattr(host, name, getattr(WavesBridge, name).__get__(host))
    host._provider_engine_probes = {"apple": host._apple_engine_details}

    def observe(*args):
        if change == "stop_during_probe":
            WavesBridge.stopAppleExecution(host)
        return RuntimeIdentity(True, "runtime-2" if change == "instance" else "runtime-1")

    host._apple_supervisor.observe_identity = observe
    initial = WavesBridge.providerEngines(host, "apple")
    wrapper = next(item for item in initial[0]["requirements"] if item["protocol"] == "wrapper-v2")
    assert wrapper["state"] == "unknown"
    workers.pop().run()
    unpublished = WavesBridge.providerEngines(host, "apple")
    wrapper = next(item for item in unpublished[0]["requirements"] if item["protocol"] == "wrapper-v2")
    assert wrapper["state"] == "unknown"
    if change == "instance":
        assert WavesBridge.appleExecutionState(host)["state"] == "unknown"
        assert not WavesBridge.appleExecutionState(host)["can_confirm"]
        assert len(pending) == 1
        pending.pop().deliver()
    elif change == "stop_during_probe":
        assert WavesBridge.appleExecutionState(host)["state"] == "stopped"
        assert pending == []
    else:
        assert WavesBridge.appleExecutionState(host)["can_confirm"]
        assert len(pending) == 1
        WavesBridge.stopAppleExecution(host)
        signals_after_stop = len(host.appleStatusChanged.emits)
        pending.pop().deliver()
        assert len(host.appleStatusChanged.emits) == signals_after_stop
        assert WavesBridge.appleExecutionState(host)["state"] == "stopped"
    details = WavesBridge.providerEngines(host, "apple")
    wrapper = next(item for item in details[0]["requirements"] if item["protocol"] == "wrapper-v2")
    assert wrapper["state"] != "ready"


@pytest.mark.parametrize(
    "automatic,busy,stopped,installs",
    [(True, False, False, 1), (False, False, False, 0), (True, True, False, 0), (True, False, True, 0)],
)
def test_automatic_approved_update_requires_opt_in_idle_and_no_deliberate_stop(
    tmp_path, automatic, busy, stopped, installs
):
    host, sessions, workers, _ = bridge(tmp_path)
    calls = []
    host._apple_runtime.update_status = lambda: {"binary": {"available": True}, "image": {"available": False}}
    host.settings.data.apple_runtime_auto_install = True
    host._waves_pref_bool = lambda key: automatic
    host._apple_busy = lambda: busy
    host.installAppleRuntime = lambda: calls.append("binary")
    if stopped:
        sessions.stop("apple:wrapper-v2")
    WavesBridge.checkAppleRuntimeUpdate(host)
    workers.pop().run()
    assert len(calls) == installs


def test_update_policy_never_installs_an_external_runtime_image(tmp_path):
    host, _, workers, _ = bridge(tmp_path)
    calls = []
    host._apple_runtime.update_status = lambda: {"binary": {"available": False}, "image": {"available": True}}
    host.settings.data.apple_runtime_auto_install = True
    host._waves_pref_bool = lambda key: True
    host._apple_busy = lambda: False
    host.installAppleImage = lambda: calls.append("image")
    WavesBridge.checkAppleRuntimeUpdate(host)
    workers.pop().run()
    assert calls == []


def test_lite_disconnect_is_immediate_independent_and_persists_without_service_commands(tmp_path):
    host, sessions, workers, commands = bridge(tmp_path)
    sessions.configure(RuntimeProfile("apple:lite", RuntimeKind.USER_MANAGED, "lite-status-v1"))
    WavesBridge.stopAppleLiteRuntime(host)
    assert WavesBridge.appleLiteRuntimeState(host)["stopped"]
    assert not sessions.is_stopped("apple:wrapper-v2")
    workers.pop().run()
    assert AppleRuntimeSessions(tmp_path).is_stopped("apple:lite")
    WavesBridge.resumeAppleLiteRuntime(host)
    workers.pop().run()
    assert WavesBridge.appleLiteRuntimeState(host)["state"] == "unknown"
    assert commands == []


def test_lite_regions_never_admit_an_unverified_account(tmp_path, monkeypatch):
    host, sessions, workers, _ = bridge(tmp_path)
    profile = RuntimeProfile(
        "apple:lite",
        RuntimeKind.USER_MANAGED,
        "lite-status-v1",
        "http://127.0.0.1:12340",
        "sha256:" + "1" * 64,
        "user-supplied",
        "external-lite",
    )
    sessions.configure(profile)
    host._apple_lite_profile = profile
    host._apple_container_state = lambda: {"name": "podman"}
    monkeypatch.setattr(
        "waves.providers.apple.lite_runtime.probe_lite_runtime",
        lambda *args, **kwargs: {
            "reachable": True,
            "protocol_compatible": True,
            "artifact_verified": True,
            "authenticated": None,
            "regions": ["us"],
            "storefront": "us",
            "qualification": "pending",
        },
    )
    WavesBridge.refreshAppleLiteRuntime(host)
    workers.pop().run()
    state = WavesBridge.appleLiteRuntimeState(host)
    assert state["reachable"] and state["protocol_compatible"]
    assert state["state"] == "unknown"
    assert not state["can_confirm"]
    WavesBridge.confirmAppleRuntimeSession(host, "apple:lite")
    assert sessions.readiness("apple:lite") != "ready"


def test_settings_runtime_restoration_waits_for_worker_instead_of_reading_on_save(tmp_path):
    from waves.model.cfg import Settings
    from waves.providers.apple.provider import AppleProvider

    host, _, workers, _ = bridge(tmp_path)
    del host._apple_runtime_sessions
    host.providers = {"apple": AppleProvider()}
    host.settings.data = Settings()
    host._waves_prefs = {}
    host._settings_save_lock = Lock()
    host._ffmpeg_flag_prefs = {}
    host._resolve_ffmpeg_locked = lambda: ""
    host._resolve_apple_wrapper_url = lambda: ""
    host._configure_apple_provider = WavesBridge._configure_apple_provider.__get__(host)
    host._submit_settings_write = lambda: None
    host._ffmpeg_source_label = lambda: "missing"
    host._logged_in = False
    host._set_status = lambda message: None
    reads = []
    host._apple_runtime.image_status = lambda: reads.append("image receipt") or {}
    WavesBridge.applySettings(host, {"apple_runtime_mode": "managed"})
    assert reads == []
    assert WavesBridge.appleExecutionState(host)["stopped"]
    assert not host.providers["apple"].runtime_stopped("apple:cookies-client")
    assert not host.providers["apple"].runtime_stopped("apple:catalog-client")
    workers.pop().run()
    assert reads == ["image receipt"]
    assert not WavesBridge.appleExecutionState(host)["stopped"]


def test_lite_probe_completion_waits_for_the_gui_relay(tmp_path, monkeypatch):
    host, sessions, workers, _ = bridge(tmp_path)
    profile = RuntimeProfile("apple:lite", RuntimeKind.USER_MANAGED, "lite-status-v1", container="isolated-lite")
    sessions.configure(profile)
    host._apple_lite_profile = profile
    host._apple_container_state = lambda: {"name": "docker"}
    deliveries = []
    host._catalogEvent = SimpleNamespace(emit=deliveries.append)
    monkeypatch.setattr("waves.providers.apple.lite_runtime.probe_lite_runtime", lambda *args, **kwargs: {})
    WavesBridge.refreshAppleLiteRuntime(host)
    workers.pop().run()
    assert WavesBridge.appleLiteRuntimeState(host)["checking"]
    for event in deliveries:
        event.deliver()
    assert not WavesBridge.appleLiteRuntimeState(host)["checking"]


def test_presentation_refresh_does_not_skip_physical_stop(tmp_path):
    host, sessions, workers, _ = bridge(tmp_path)
    stopped = []
    host._apple_supervisor.stop = lambda: stopped.append(True) or True
    WavesBridge.stopAppleExecution(host)
    host._apple_engine_facts_gen += 1
    workers.pop().run()
    assert stopped == [True]
    assert sessions.is_stopped("apple:wrapper-v2")


def test_maintenance_does_not_cancel_a_queued_deliberate_stop(tmp_path):
    host, _, workers, _ = bridge(tmp_path)
    stopped = []
    host._apple_supervisor.stop = lambda: stopped.append(True) or True
    host._apple_runtime.rollback = lambda: None
    WavesBridge.stopAppleExecution(host)
    stop_worker = workers.pop()
    WavesBridge.rollbackAppleRuntime(host)
    workers.pop().run()
    stop_worker.run()
    assert AppleRuntimeSessions(tmp_path).is_stopped("apple:wrapper-v2")
    assert stopped == [True]


@pytest.mark.parametrize("runtime_id", ["apple:wrapper-v2", "apple:lite"])
def test_latest_stop_wins_when_it_arrives_at_an_older_resume_commit(tmp_path, runtime_id):
    host, sessions, workers, _ = bridge(tmp_path)
    sessions.stop(runtime_id)
    resume = sessions.resume
    stopped = False

    def resume_after_new_stop(resource, **kwargs):
        nonlocal stopped
        if not stopped:
            stopped = True
            if resource == "apple:lite":
                WavesBridge.stopAppleLiteRuntime(host)
            else:
                WavesBridge.stopAppleExecution(host)
            workers.pop().run()
        return resume(resource, **kwargs)

    sessions.resume = resume_after_new_stop
    if runtime_id == "apple:lite":
        WavesBridge.resumeAppleLiteRuntime(host)
    else:
        WavesBridge.resumeAppleExecution(host)
    workers.pop().run()
    assert sessions.is_stopped(runtime_id)
    assert AppleRuntimeSessions(tmp_path).is_stopped(runtime_id)
