"""Exercise the local transport with real Unix sockets and profile locks."""

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time

import pytest

from waves.desktop.providers.profile_owner import OwnerBusy, ProfileOwner
from waves.desktop.providers.session_ipc import MAX_MESSAGE, IPCUnavailable, SessionServer, request

pytestmark = pytest.mark.skipif(sys.platform != "darwin" and not sys.platform.startswith("linux"), reason="Unix IPC")


def dispatch(message, deadline):
    assert deadline > time.monotonic()
    if message["op"] == "activate":
        return {"result": "activated", "secret": "not sent"}
    return {
        "state": "awaiting_verification",
        "action": "complete_verification",
        "facts": dict.fromkeys(("catalog", "runtime", "identity", "storefront", "delivery"), "unknown"),
        "account_id": "must not escape",
    }


def raw(path, data, timeout=2):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout)
        client.connect(str(path))
        client.sendall(data)
        return json.loads(client.recv(8192))


def test_real_roundtrip_sanitizes_and_activates(tmp_path):
    with ProfileOwner.acquire(tmp_path) as owner, SessionServer(owner, dispatch):
        answer = request(tmp_path, {"version": 1, "op": "ensure", "provider": "apple"})
        assert answer["state"] == "awaiting_verification"
        assert answer["action"] == "complete_verification"
        assert "account_id" not in answer
        assert request(tmp_path, {"version": 1, "op": "activate"}) == {"version": 1, "result": "activated"}


@pytest.mark.parametrize("version", [None, True, 2])
def test_client_rejects_bad_response_version(tmp_path, monkeypatch, version):
    from waves.desktop.providers import session_ipc

    original = session_ipc._receive
    client_thread = threading.get_ident()

    def receive(conn, deadline):
        result = original(conn, deadline)
        if threading.get_ident() == client_thread:
            if version is None:
                result.pop("version")
            else:
                result["version"] = version
        return result

    monkeypatch.setattr(session_ipc, "_receive", receive)
    with ProfileOwner.acquire(tmp_path) as owner, SessionServer(owner, dispatch):
        assert request(tmp_path, {"version": 1, "op": "activate"}) == {"version": 1, "error": "unavailable"}


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        (b'{"version":1,"version":1,"op":"activate"}\n', "invalid_request"),
        (b'{"version":true,"op":"activate"}\n', "invalid_request"),
        (b'{"version":2,"op":"activate"}\n', "unsupported_version"),
        (b'{"version":1,"op":"delete"}\n', "unsupported_operation"),
        (b'{"version":1,"op":"status","provider":"other"}\n', "unsupported_provider"),
        (b'{"version":1,"op":"activate","secret":"x"}\n', "invalid_request"),
        (b"x" * (MAX_MESSAGE + 1), "too_large"),
    ],
)
def test_protocol_rejects_invalid_requests(tmp_path, payload, error):
    with ProfileOwner.acquire(tmp_path) as owner, SessionServer(owner, dispatch) as server:
        assert raw(server.path, payload) == {"version": 1, "error": error}


def test_slow_client_does_not_block_other_clients(tmp_path):
    with (
        ProfileOwner.acquire(tmp_path) as owner,
        SessionServer(owner, dispatch, timeout=0.2) as server,
        socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as slow,
    ):
        slow.settimeout(2)
        slow.connect(str(server.path))
        slow.sendall(b'{"version":')
        assert (
            request(tmp_path, {"version": 1, "op": "status", "provider": "tidal"})["state"] == "awaiting_verification"
        )
        assert json.loads(slow.recv(4096))["error"] == "timeout"


def test_dispatch_timeout_is_bounded_and_results_are_sanitized(tmp_path):
    event = threading.Event()

    def slow(_request, _deadline):
        event.wait(2)
        return {"secret": "never"}

    try:
        with ProfileOwner.acquire(tmp_path) as owner, SessionServer(owner, slow, timeout=0.1) as server:
            start = time.monotonic()
            reply = raw(server.path, b'{"version":1,"op":"status","provider":"tidal"}\n')
            assert reply == {"version": 1, "error": "timeout"}
            assert time.monotonic() - start < 1
    finally:
        event.set()


def test_closed_owner_refused_and_active_server_keeps_lock(tmp_path):
    owner = ProfileOwner.acquire(tmp_path)
    server = SessionServer(owner, dispatch)
    try:
        with pytest.raises(IPCUnavailable):
            SessionServer(owner, dispatch)
        owner.close()
        with pytest.raises(OwnerBusy):
            ProfileOwner.acquire(tmp_path)
        assert request(tmp_path, {"version": 1, "op": "activate"})["result"] == "activated"
    finally:
        server.close()
    with pytest.raises(IPCUnavailable):
        SessionServer(owner, dispatch)
    with ProfileOwner.acquire(tmp_path):
        pass


def test_simultaneous_servers_share_one_owner_endpoint(tmp_path, monkeypatch):
    from waves.desktop.providers import session_ipc

    original = session_ipc.tempfile.mkdtemp

    def slow_create(*args, **kwargs):
        time.sleep(0.05)
        return original(*args, **kwargs)

    monkeypatch.setattr(session_ipc.tempfile, "mkdtemp", slow_create)
    barrier = threading.Barrier(2)
    servers = []
    errors = []
    with ProfileOwner.acquire(tmp_path) as owner:

        def start():
            barrier.wait()
            try:
                servers.append(SessionServer(owner, dispatch))
            except IPCUnavailable:
                errors.append(True)

        workers = [threading.Thread(target=start) for _ in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(2)
        try:
            assert all(not worker.is_alive() for worker in workers)
            assert len(servers) == 1 and len(errors) == 1
        finally:
            for server in servers:
                server.close()


def test_unsafe_existing_endpoint_not_removed(tmp_path):
    with ProfileOwner.acquire(tmp_path) as owner:
        from waves.desktop.providers.session_ipc import _endpoint

        path = _endpoint(tmp_path, create=True)
        path.write_text("keep")
        try:
            with pytest.raises(IPCUnavailable):
                SessionServer(owner, dispatch)
            assert path.read_text() == "keep"
        finally:
            path.unlink()


@pytest.mark.integration
def test_crash_recovery_replaces_stale_socket(tmp_path):
    code = (
        "import os,sys\n"
        "from pathlib import Path\n"
        "from waves.desktop.providers.profile_owner import ProfileOwner\n"
        "from waves.desktop.providers.session_ipc import SessionServer\n"
        "o=ProfileOwner.acquire(Path(sys.argv[1]))\n"
        "s=SessionServer(o,lambda r,d: {})\n"
        "print('ready',flush=True)\n"
        "os._exit(0)\n"
    )
    proc = subprocess.run(  # noqa: S603 - fixed interpreter and fixture script
        [sys.executable, "-c", code, str(tmp_path)], capture_output=True, text=True, timeout=5, check=False
    )
    assert proc.returncode == 0 and proc.stdout.strip() == "ready"
    with ProfileOwner.acquire(tmp_path) as owner, SessionServer(owner, dispatch):
        assert request(tmp_path, {"version": 1, "op": "activate"})["result"] == "activated"


def test_long_profile_path_and_peer_rejection(tmp_path, monkeypatch):
    from waves.desktop.providers import session_ipc

    profile = tmp_path
    for _ in range(5):
        profile = profile / ("long-profile-" * 10)
        profile.mkdir()
    with ProfileOwner.acquire(profile) as owner, SessionServer(owner, dispatch) as server:
        assert len(os.fsencode(server.path)) < 104
        assert request(profile, {"version": 1, "op": "activate"})["result"] == "activated"
        monkeypatch.setattr(session_ipc, "_peer_uid", lambda _conn: os.getuid() + 1)
        assert request(profile, {"version": 1, "op": "activate"})["error"] == "unavailable"


def test_socket_path_does_not_depend_on_uid_length(tmp_path):
    with ProfileOwner.acquire(tmp_path) as owner, SessionServer(owner, dispatch) as server:
        assert len(os.fsencode(server.path)) < 104
        assert "waves-provider-" not in str(server.path)
        assert request(tmp_path, {"version": 1, "op": "activate"})["result"] == "activated"


def test_removed_temporary_namespace_is_recreated(tmp_path):
    with ProfileOwner.acquire(tmp_path) as owner:
        with SessionServer(owner, dispatch) as server:
            old_namespace = server.path.parent
        if old_namespace.exists():
            old_namespace.rmdir()
        with SessionServer(owner, dispatch) as server:
            assert server.path.parent != old_namespace
            assert request(tmp_path, {"version": 1, "op": "activate"})["result"] == "activated"


def test_preempted_namespace_is_replaced_without_removing_file(tmp_path):
    with ProfileOwner.acquire(tmp_path) as owner:
        with SessionServer(owner, dispatch) as server:
            root = server.path.parent.parent
        with tempfile.NamedTemporaryFile(prefix="w-", dir=root) as other:
            (owner.control_dir / "namespace").write_text(os.path.basename(other.name))
            with SessionServer(owner, dispatch) as server:
                assert str(server.path.parent) != other.name
                assert os.path.isfile(other.name)
                assert request(tmp_path, {"version": 1, "op": "activate"})["result"] == "activated"


@pytest.mark.integration
def test_separate_process_can_use_client(tmp_path):
    code = (
        "import json,sys\n"
        "from pathlib import Path\n"
        "from waves.desktop.providers.session_ipc import request\n"
        "print(json.dumps(request(Path(sys.argv[1]), {'version':1,'op':'activate'})))\n"
    )
    with ProfileOwner.acquire(tmp_path) as owner, SessionServer(owner, dispatch):
        proc = subprocess.run(  # noqa: S603 - fixed interpreter and fixture script
            [sys.executable, "-c", code, str(tmp_path)], capture_output=True, text=True, timeout=5, check=False
        )
    assert proc.returncode == 0
    assert json.loads(proc.stdout) == {"version": 1, "result": "activated"}


def test_server_rejects_wrong_peer_before_dispatch(tmp_path, monkeypatch):
    from waves.desktop.providers import session_ipc

    called = threading.Event()

    def record(message, deadline):
        called.set()
        return dispatch(message, deadline)

    with ProfileOwner.acquire(tmp_path) as owner, SessionServer(owner, record) as server:
        monkeypatch.setattr(session_ipc, "_peer_uid", lambda _conn: os.getuid() + 1)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(2)
            client.connect(str(server.path))
            client.sendall(b'{"version":1,"op":"activate"}\n')
            try:
                response = client.recv(1024)
            except ConnectionResetError:
                response = b""
        assert response == b""
        assert not called.is_set()


def test_dispatch_exception_is_not_returned(tmp_path):
    def fail(_message, _deadline):
        raise ValueError("sensitive exception")

    with ProfileOwner.acquire(tmp_path) as owner, SessionServer(owner, fail):
        assert request(tmp_path, {"version": 1, "op": "activate"}) == {"version": 1, "error": "unavailable"}
