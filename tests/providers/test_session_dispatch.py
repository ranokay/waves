"""Real socket requests are applied only on the Qt owner thread."""

from __future__ import annotations

import sys
import threading
import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, Qt
from support.bridge_stub import BridgeStub

from waves.desktop.providers.profile_owner import ProfileOwner
from waves.desktop.providers.session_dispatch import SessionDispatcher
from waves.desktop.providers.session_ipc import SessionServer, request

pytestmark = pytest.mark.skipif(sys.platform != "darwin" and not sys.platform.startswith("linux"), reason="Unix IPC")


@pytest.fixture
def app():
    return QCoreApplication.instance() or QCoreApplication([])


@pytest.fixture
def bridge():
    return BridgeStub(
        settings=SimpleNamespace(data=SimpleNamespace(apple_enabled=True)),
        _provider_login_attempts={},
        _provider_cleanup_events={},
        _session_resolved=True,
        _logged_in=False,
        _apple_wrapper_auth_cache={
            "at": time.time(),
            "result": {"reachable": True, "state": "logged_out", "logged_in": False},
        },
    )


def call_while_pumping(app, profile, message):
    result = []
    thread = threading.Thread(target=lambda: result.append(request(profile, message, timeout=2)))
    thread.start()
    end = time.monotonic() + 3
    while thread.is_alive() and time.monotonic() < end:
        app.processEvents()
        thread.join(0.005)
    assert not thread.is_alive()
    return result[0]


def test_socket_dispatch_uses_qt_thread_and_no_duplicate_handoff(app, bridge, tmp_path):
    activations = []
    adapter = SessionDispatcher(bridge, lambda: activations.append(threading.get_ident()))
    with ProfileOwner.acquire(tmp_path) as owner, SessionServer(owner, adapter.dispatch, on_close=adapter.close):
        message = {"version": 1, "op": "ensure", "provider": "tidal"}
        first = call_while_pumping(app, tmp_path, message)
        second = call_while_pumping(app, tmp_path, message)
        assert first == second
        assert first["state"] == "unavailable_unknown" and first["action"] == "open_waves"
        assert first["result"] == "action_required"
        assert bridge.signInRequested.emits == ["tidal"]
        assert activations == [threading.get_ident(), threading.get_ident()]
        assert bridge._provider_login_attempts == {}
        assert call_while_pumping(app, tmp_path, {"version": 1, "op": "activate"})["result"] == "activated"


@pytest.mark.parametrize(
    "message", [{"version": 1, "op": "activate"}, {"version": 1, "op": "ensure", "provider": "tidal"}]
)
def test_expired_request_never_applies_queued_gui_effect(app, bridge, tmp_path, message):
    activations = []
    entered = threading.Event()
    adapter = SessionDispatcher(bridge, lambda: activations.append(True))

    adapter._queued.connect(lambda _job: entered.set(), Qt.ConnectionType.DirectConnection)

    def queued(message, deadline):
        return adapter.dispatch(message, deadline)

    with ProfileOwner.acquire(tmp_path) as owner, SessionServer(owner, queued, timeout=0.1, on_close=adapter.close):
        reply = []
        worker = threading.Thread(target=lambda: reply.append(request(tmp_path, message, timeout=1)))
        worker.start()
        assert entered.wait(1)
        worker.join(2)
        assert not worker.is_alive()
        assert reply[0]["error"] in {"timeout", "unavailable"}
        app.processEvents()
        assert activations == [] and bridge.signInRequested.emits == []


def test_server_close_invalidates_queued_requests_before_owner_release(app, bridge, tmp_path):
    activations = []
    entered = threading.Event()
    adapter = SessionDispatcher(bridge, lambda: activations.append(True))

    adapter._queued.connect(lambda _job: entered.set(), Qt.ConnectionType.DirectConnection)

    def queued(message, deadline):
        return adapter.dispatch(message, deadline)

    with ProfileOwner.acquire(tmp_path) as owner:
        server = SessionServer(owner, queued, timeout=1, on_close=adapter.close)
        worker = threading.Thread(target=lambda: request(tmp_path, {"version": 1, "op": "activate"}, timeout=2))
        worker.start()
        assert entered.wait(1)
        server.close()
        worker.join(2)
        assert not worker.is_alive()
        app.processEvents()
        assert activations == []


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"reachable": True, "state": "awaiting_2fa", "logged_in": False}, "awaiting_verification"),
        ({"reachable": True, "state": "not_logged_out", "logged_in": False}, "unavailable_unknown"),
        ({"reachable": False, "state": "", "logged_in": False}, "unavailable_unknown"),
        ({"reachable": True, "state": "authenticated", "logged_in": True}, "authenticated"),
        ({"reachable": True, "state": "logged_out", "logged_in": False}, "signed_out"),
    ],
)
def test_apple_cached_account_states_remain_distinct(app, bridge, tmp_path, payload, expected):
    bridge._apple_wrapper_auth_cache = {"at": time.time(), "result": payload}
    adapter = SessionDispatcher(bridge, lambda: None)
    with ProfileOwner.acquire(tmp_path) as owner, SessionServer(owner, adapter.dispatch, on_close=adapter.close):
        answer = call_while_pumping(app, tmp_path, {"version": 1, "op": "status", "provider": "apple"})
        assert answer["state"] == expected
        assert answer["facts"] == dict.fromkeys(("catalog", "runtime", "identity", "storefront", "delivery"), "unknown")
        assert not bridge.appleSetupRequested.emits


def test_disabled_and_stopped_apple_never_restart_or_login(app, bridge, tmp_path):
    activations = []
    adapter = SessionDispatcher(bridge, lambda: activations.append(True))
    with ProfileOwner.acquire(tmp_path) as owner, SessionServer(owner, adapter.dispatch, on_close=adapter.close):
        message = {"version": 1, "op": "ensure", "provider": "apple"}
        bridge.settings.data.apple_enabled = False
        answer = call_while_pumping(app, tmp_path, message)
        assert answer["action"] == "enable_provider"
        bridge.settings.data.apple_enabled = True
        bridge._apple_runtime_sessions = SimpleNamespace(choices_restored=True, is_stopped=lambda _id: True)
        answer = call_while_pumping(app, tmp_path, message)
        assert answer["action"] == "start_runtime" and answer["facts"]["runtime"] == "not_ready"
        assert bridge.appleSetupRequested.emits == ["setup", "setup"]
        assert len(activations) == 2


@pytest.mark.parametrize(("credential", "expected"), [("cookies", "authenticated"), ("wrapper", "expired_rejected")])
def test_cookie_expiry_does_not_reject_authenticated_wrapper(app, bridge, tmp_path, credential, expected):
    bridge._apple_session_expired = True
    bridge._apple_session_credential = credential
    bridge._apple_wrapper_auth_cache = {
        "at": time.time(),
        "result": {"reachable": True, "state": "authenticated", "logged_in": True},
    }
    adapter = SessionDispatcher(bridge, lambda: None)
    with ProfileOwner.acquire(tmp_path) as owner, SessionServer(owner, adapter.dispatch, on_close=adapter.close):
        answer = call_while_pumping(app, tmp_path, {"version": 1, "op": "status", "provider": "apple"})
        assert answer["state"] == expected


def test_pending_tidal_resume_does_not_restart_or_open_handoff(app, bridge, tmp_path):
    bridge._provider_login_attempts["tidal"] = SimpleNamespace(resume=True)
    activated = []
    adapter = SessionDispatcher(bridge, lambda: activated.append(True))
    with ProfileOwner.acquire(tmp_path) as owner, SessionServer(owner, adapter.dispatch, on_close=adapter.close):
        message = {"version": 1, "op": "ensure", "provider": "tidal"}
        for _ in range(2):
            assert call_while_pumping(app, tmp_path, message)["state"] == "checking"
        assert activated == [] and bridge.signInRequested.emits == []


def test_concurrent_ensures_share_single_pending_handoff(app, bridge, tmp_path):
    adapter = SessionDispatcher(bridge, lambda: None)
    barrier = threading.Barrier(3)
    replies = []
    message = {"version": 1, "op": "ensure", "provider": "tidal"}

    def client():
        barrier.wait()
        replies.append(request(tmp_path, message, timeout=2))

    with ProfileOwner.acquire(tmp_path) as owner, SessionServer(owner, adapter.dispatch, on_close=adapter.close):
        threads = [threading.Thread(target=client) for _ in range(2)]
        for worker in threads:
            worker.start()
        barrier.wait()
        end = time.monotonic() + 3
        while any(worker.is_alive() for worker in threads) and time.monotonic() < end:
            app.processEvents()
            for worker in threads:
                worker.join(0.005)
        assert all(not worker.is_alive() for worker in threads)
        assert len(replies) == 2 and all(reply["action"] == "open_waves" for reply in replies)
        assert bridge.signInRequested.emits == ["tidal"]
        assert bridge._provider_login_attempts == {}


def test_pending_fresh_tidal_login_is_not_restarted(app, bridge, tmp_path):
    bridge._provider_login_attempts["tidal"] = SimpleNamespace(resume=False, submitted=False)
    adapter = SessionDispatcher(bridge, lambda: None)
    with ProfileOwner.acquire(tmp_path) as owner, SessionServer(owner, adapter.dispatch, on_close=adapter.close):
        message = {"version": 1, "op": "ensure", "provider": "tidal"}
        result = call_while_pumping(app, tmp_path, message)
        assert result["state"] == "authenticating" and result["action"] == "open_waves"
        assert bridge.signInRequested.emits == ["tidal"]
        assert not bridge._provider_login_attempts["tidal"].submitted


def test_gui_callback_failure_has_only_fixed_error(app, bridge, tmp_path, capsys):
    def fail():
        raise RuntimeError("private callback detail")

    adapter = SessionDispatcher(bridge, fail)
    with ProfileOwner.acquire(tmp_path) as owner, SessionServer(owner, adapter.dispatch, on_close=adapter.close):
        reply = call_while_pumping(app, tmp_path, {"version": 1, "op": "activate"})
        assert reply == {"version": 1, "error": "unavailable"}
    assert "private callback detail" not in capsys.readouterr().err


def test_ensure_resumes_saved_tidal_once_and_respects_signout(app, bridge, tmp_path):
    calls = []
    bridge.providers = {"tidal": SimpleNamespace(has_resumable_session=lambda: True)}

    def resume():
        calls.append("resume")
        bridge._provider_login_attempts["tidal"] = SimpleNamespace(resume=True)

    bridge._try_token_login = resume
    adapter = SessionDispatcher(bridge, lambda: None)
    with ProfileOwner.acquire(tmp_path) as owner, SessionServer(owner, adapter.dispatch, on_close=adapter.close):
        msg = {"version": 1, "op": "ensure", "provider": "tidal"}
        assert call_while_pumping(app, tmp_path, msg)["state"] == "checking"
        assert call_while_pumping(app, tmp_path, msg)["state"] == "checking"
        assert calls == ["resume"]
        bridge._provider_login_attempts.clear()
        bridge._provider_cleanup_events["tidal"] = threading.Event()
        assert call_while_pumping(app, tmp_path, msg)["state"] == "signed_out"
        assert calls == ["resume"]


def test_stale_apple_refresh_is_scheduled_once_and_stopped_runtime_never_refreshes(app, bridge, tmp_path):
    calls = []
    bridge._apple_wrapper_auth_cache = {
        "at": time.time() - 60,
        "result": {"reachable": True, "state": "authenticated", "logged_in": True},
    }
    bridge._schedule_apple_wrapper_auth_refresh = lambda: calls.append(True) or True
    bridge._apple_runtime_sessions = SimpleNamespace(choices_restored=True, is_stopped=lambda _id: False)
    adapter = SessionDispatcher(bridge, lambda: None)
    with ProfileOwner.acquire(tmp_path) as owner, SessionServer(owner, adapter.dispatch, on_close=adapter.close):
        msg = {"version": 1, "op": "ensure", "provider": "apple"}
        status = call_while_pumping(app, tmp_path, {**msg, "op": "status"})
        assert status["state"] == "unavailable_unknown" and calls == []
        assert call_while_pumping(app, tmp_path, msg)["state"] == "checking"
        assert call_while_pumping(app, tmp_path, msg)["state"] == "checking"
        assert calls == [True]
        bridge._apple_runtime_sessions.is_stopped = lambda _id: True
        assert call_while_pumping(app, tmp_path, msg)["action"] == "start_runtime"
        assert calls == [True]
