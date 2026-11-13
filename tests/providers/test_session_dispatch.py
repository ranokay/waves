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

pytestmark = [
    pytest.mark.qml,
    pytest.mark.skipif(sys.platform != "darwin" and not sys.platform.startswith("linux"), reason="Unix IPC"),
]


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


def test_socket_dispatch_uses_qt_thread_and_reopens_handoff(app, bridge, tmp_path):
    activations = []
    adapter = SessionDispatcher(bridge, lambda: activations.append(threading.get_ident()))
    with ProfileOwner.acquire(tmp_path) as owner, SessionServer(owner, adapter.dispatch, on_close=adapter.close):
        message = {"version": 1, "op": "ensure", "provider": "tidal"}
        first = call_while_pumping(app, tmp_path, message)
        second = call_while_pumping(app, tmp_path, message)
        assert first == second
        assert first["state"] == "unavailable_unknown" and first["action"] == "open_waves"
        assert first["result"] == "action_required"
        assert bridge.signInRequested.emits == ["tidal", "tidal"]
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
        assert bridge.signInRequested.emits == ["tidal", "tidal"]
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
        assert call_while_pumping(app, tmp_path, msg)["state"] == "checking"
        assert calls == ["resume", "resume"]
        bridge._provider_login_attempts.clear()
        bridge._provider_cleanup_events["tidal"] = threading.Event()
        assert call_while_pumping(app, tmp_path, msg)["state"] == "signed_out"
        assert calls == ["resume", "resume"]


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
        adapter._apple_refresh_started -= 11
        assert call_while_pumping(app, tmp_path, msg)["state"] == "checking"
        assert calls == [True, True]
        bridge._apple_runtime_sessions.is_stopped = lambda _id: True
        assert call_while_pumping(app, tmp_path, msg)["action"] == "start_runtime"
        assert calls == [True, True]


def test_verified_cookies_account_survives_stopped_wrapper(app, bridge, tmp_path):
    from waves.desktop.providers.lifecycle import provider_contexts
    from waves.file_integrity import sha256_file
    from waves.providers.apple.engines import EngineFacts
    from waves.providers.apple.runtime import verify_cookies_file

    cookies = tmp_path / "fixture-cookies.txt"
    cookies.write_text(".apple.com\tTRUE\t/\tTRUE\t0\tmedia-user-token\tfixture-only\n")
    assert verify_cookies_file(str(cookies))["has_token"]
    bridge.settings.data.apple_cookies_path = str(cookies)
    bridge.providers = {"apple": SimpleNamespace(cookies_path=str(cookies))}
    bridge._apple_engine_facts_gen = 1
    bridge._apple_runtime_sessions = SimpleNamespace(
        choices_restored=True, is_stopped=lambda _id: True, revision=lambda _id: (1, 2)
    )
    bridge._apple_engine_facts_cache = (
        provider_contexts(bridge).capture("apple"),
        time.time(),
        EngineFacts(cookies_ready=True),
        [],
        1,
        (1, 2),
        (str(cookies), sha256_file(cookies), 0),
    )
    adapter = SessionDispatcher(bridge, lambda: pytest.fail("valid cookies need no handoff"))
    with ProfileOwner.acquire(tmp_path) as owner, SessionServer(owner, adapter.dispatch, on_close=adapter.close):
        for op in ("status", "ensure"):
            result = call_while_pumping(app, tmp_path, {"version": 1, "op": op, "provider": "apple"})
            assert result["state"] == "authenticated"
            assert result["facts"]["runtime"] == "not_ready"
            assert result["facts"]["delivery"] == "unknown"


@pytest.mark.parametrize("valid", [True, False, "expired", "empty", "bad_expiry", "negative_expiry"])
@pytest.mark.parametrize("stopped", [False, True])
def test_cookie_evidence_is_refreshed_once_on_worker_without_gui_file_reads(
    app, bridge, tmp_path, monkeypatch, valid, stopped
):
    from waves.desktop.backend import WavesBridge
    from waves.providers.apple import runtime
    from waves.providers.apple.provider import AppleProvider

    cookies = tmp_path / "fixture-cookies.txt"
    name = "other-cookie" if valid is False else "media-user-token"
    expiry = {"expired": "1", "bad_expiry": "invalid", "negative_expiry": "-1"}.get(valid, "0")
    value = "" if valid == "empty" else "fixture-only"
    cookies.write_text(f".apple.com\tTRUE\t/\tTRUE\t{expiry}\t{name}\t{value}\n")
    provider = AppleProvider()
    provider.cookies_path = str(cookies)
    bridge.providers = {"apple": provider}
    bridge.settings.data.apple_cookies_path = str(cookies)
    bridge._apple_engine_facts_gen = 1
    bridge._apple_engine_facts_cache = None
    if stopped:
        bridge._apple_runtime_sessions = SimpleNamespace(
            choices_restored=True,
            is_stopped=lambda _id: True,
            revision=lambda _id: (0, 0),
            readiness=lambda _id: "stopped",
            observe_current=lambda *_args: ("stopped", (0, 0)),
        )
        monkeypatch.setattr(
            WavesBridge, "_apple_observe_wrapper_identity", lambda _bridge: SimpleNamespace(revision="", verified=None)
        )
    bridge._apple_cookies_ready = lambda: True
    bridge._apple_runtime_ready = lambda: False
    bridge._apple_needs_attention = lambda: False
    bridge._apple_fetch_binary_ready = lambda: False
    bridge._apple_wrapper_signed_in = lambda: False
    bridge._apple_container_serves = lambda: False
    bridge._apple_live_flags = WavesBridge._apple_live_flags.__get__(bridge)
    bridge._apple_engine_facts = WavesBridge._apple_engine_facts.__get__(bridge)
    bridge._apple_engine_details = WavesBridge._apple_engine_details.__get__(bridge)
    workers, deliveries, probes = [], [], []
    bridge.threadpool = SimpleNamespace(start=workers.append)
    bridge._catalogEvent = SimpleNamespace(emit=deliveries.append)
    original = runtime.verify_cookies_file

    def verify_on_worker(*args, **kwargs):
        probes.append(threading.get_ident())
        assert threading.get_ident() != threading.main_thread().ident
        return original(*args, **kwargs)

    monkeypatch.setattr(runtime, "verify_cookies_file", verify_on_worker)
    adapter = SessionDispatcher(bridge, lambda: pytest.fail("no sign-in handoff while checking cookies"))
    with ProfileOwner.acquire(tmp_path) as owner, SessionServer(owner, adapter.dispatch, on_close=adapter.close):
        message = {"version": 1, "op": "ensure", "provider": "apple"}
        for _ in range(2):
            assert call_while_pumping(app, tmp_path, message)["state"] == "checking"
        assert len(workers) == 1 and probes == []
        worker = threading.Thread(target=workers.pop().run)
        worker.start()
        worker.join(5)
        assert not worker.is_alive() and probes and len(deliveries) == 1
        deliveries.pop().deliver()
        status = call_while_pumping(app, tmp_path, {**message, "op": "status"})
        assert (status["state"] == "authenticated") is (valid is True)
        if valid is True:
            assert call_while_pumping(app, tmp_path, message)["state"] == "authenticated"
        assert len(probes) == 2


@pytest.mark.parametrize("change", ["provider_epoch", "generation", "cookie_path", "account_revision", "age", "expiry"])
def test_changed_cookie_evidence_never_authenticates(app, bridge, tmp_path, change):
    from waves.desktop.providers.lifecycle import provider_contexts
    from waves.providers.apple.engines import EngineFacts

    path = str(tmp_path / "fixture-cookies.txt")
    bridge.settings.data.apple_cookies_path = path
    bridge.providers = {"apple": SimpleNamespace(cookies_path=path)}
    bridge._apple_engine_facts_gen = 1
    bridge._apple_runtime_sessions = SimpleNamespace(
        choices_restored=True, is_stopped=lambda _id: True, revision=lambda _id: (1, 2)
    )
    contexts = provider_contexts(bridge)
    evidence = (path, "fixture-digest", time.time() - 1 if change == "expiry" else 0)
    bridge._apple_engine_facts_cache = (
        contexts.capture("apple"),
        time.time() - 31 if change == "age" else time.time(),
        EngineFacts(cookies_ready=True),
        [],
        1,
        (1, 2),
        evidence,
    )
    if change == "provider_epoch":
        contexts.revoke("apple")
    elif change == "generation":
        bridge._apple_engine_facts_gen += 1
    elif change == "cookie_path":
        bridge.settings.data.apple_cookies_path = path + ".new"
        bridge.providers["apple"].cookies_path = path + ".new"
    elif change == "account_revision":
        bridge._apple_runtime_sessions.revision = lambda _id: (2, 2)
    adapter = SessionDispatcher(bridge, lambda: None)
    with ProfileOwner.acquire(tmp_path) as owner, SessionServer(owner, adapter.dispatch, on_close=adapter.close):
        answer = call_while_pumping(app, tmp_path, {"version": 1, "op": "status", "provider": "apple"})
        assert answer["state"] != "authenticated"
        assert answer["facts"]["runtime"] == "not_ready"


def test_wrapper_expiry_does_not_reject_current_cookie_evidence(app, bridge, tmp_path):
    from waves.desktop.providers.lifecycle import provider_contexts
    from waves.providers.apple.engines import EngineFacts

    path = str(tmp_path / "fixture-cookies.txt")
    bridge.settings.data.apple_cookies_path = path
    bridge.providers = {"apple": SimpleNamespace(cookies_path=path)}
    bridge._apple_engine_facts_gen = 1
    bridge._apple_session_expired = True
    bridge._apple_session_credential = "wrapper"
    bridge._apple_engine_facts_cache = (
        provider_contexts(bridge).capture("apple"),
        time.time(),
        EngineFacts(cookies_ready=True),
        [],
        1,
        (0, 0),
        (path, "fixture-digest", 0),
    )
    adapter = SessionDispatcher(bridge, lambda: pytest.fail("cookies need no wrapper handoff"))
    with ProfileOwner.acquire(tmp_path) as owner, SessionServer(owner, adapter.dispatch, on_close=adapter.close):
        result = call_while_pumping(app, tmp_path, {"version": 1, "op": "ensure", "provider": "apple"})
        assert result["state"] == "authenticated" and result["facts"]["delivery"] == "unknown"
        assert bridge._apple_session_expired and bridge._apple_session_credential == "wrapper"


def test_good_wrapper_does_not_clear_cookie_expiry(app, bridge, tmp_path):
    from waves.desktop.providers.lifecycle import provider_contexts
    from waves.providers.apple.engines import EngineFacts

    path = str(tmp_path / "fixture-cookies.txt")
    bridge.settings.data.apple_cookies_path = path
    bridge.providers = {"apple": SimpleNamespace(cookies_path=path)}
    bridge._apple_engine_facts_gen = 1
    bridge._apple_session_expired = True
    bridge._apple_session_credential = "cookies"
    bridge._apple_engine_facts_cache = (
        provider_contexts(bridge).capture("apple"),
        time.time(),
        EngineFacts(cookies_ready=True),
        [],
        1,
        (0, 0),
        (path, "fixture-digest", 0),
    )
    bridge._apple_wrapper_auth_cache = {
        "at": time.time(),
        "result": {"reachable": True, "state": "authenticated", "logged_in": True},
    }
    adapter = SessionDispatcher(bridge, lambda: pytest.fail("wrapper needs no handoff"))
    with ProfileOwner.acquire(tmp_path) as owner, SessionServer(owner, adapter.dispatch, on_close=adapter.close):
        result = call_while_pumping(app, tmp_path, {"version": 1, "op": "ensure", "provider": "apple"})
        assert result["state"] == "authenticated" and result["facts"]["delivery"] == "unknown"
        assert bridge._apple_session_expired and bridge._apple_session_credential == "cookies"
