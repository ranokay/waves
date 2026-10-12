"""Public bridge runtime choices do not acquire an external service's lifecycle."""

from contextlib import nullcontext
from threading import Event
from types import SimpleNamespace

import pytest
from support.bridge_stub import BridgeStub

from waves.desktop.backend import WavesBridge
from waves.providers.apple.runtime import AppleRuntimeManager
from waves.providers.apple.runtime_sessions import AppleRuntimeSessions, RuntimeKind, RuntimeProfile
from waves.providers.apple.supervision import SidecarSupervisor


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


def test_public_setup_cancel_sets_the_installer_abort(tmp_path):
    host, _, _, _ = bridge(tmp_path)
    WavesBridge.cancelAppleRuntimeSetup(host)
    assert host._apple_runtime_abort.is_set()


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
