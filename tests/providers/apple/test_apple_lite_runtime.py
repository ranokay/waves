"""Lite status exposes bounded runtime facts without asserting authentication."""

import base64
import io
import json
import platform
import subprocess
import sys
from dataclasses import replace
from threading import Event, Thread

import pytest

from waves.providers.apple.lite_runtime import probe_lite_runtime
from waves.providers.apple.runtime_sessions import RuntimeKind, RuntimeProfile

IMAGE = "sha256:" + "a" * 64


def profile():
    return RuntimeProfile(
        "apple:lite",
        RuntimeKind.USER_MANAGED,
        "lite-status-v1",
        "http://127.0.0.1:12340",
        IMAGE,
        "user-supplied",
        "my-lite",
    )


def container():
    return {
        "id": "b" * 64,
        "image": IMAGE,
        "started_at": "2026-10-12T08:00:00Z",
        "running": True,
        "ports": {},
        "bindings": {},
        "readonly": True,
        "cap_drop": ["ALL"],
        "privileged": False,
        "cap_add": None,
        "user": "501:20",
        "args": ["--base-dir", "/data", "--host", "127.0.0.1", "--port", "12340"],
        "network": "my-isolated-network",
    }


def runner(info=None, status=None, rpc=None):
    observed = container() if info is None else info
    response = {"code": 0, "msg": "SUCCESS", "data": {"regions": ["ro"]}} if status is None else status

    def run(command, **options):
        if "inspect" in command:
            output = json.dumps(observed).encode()
        else:
            request = json.loads(options["input"])
            assert request == {"port": 12340}
            body = response if isinstance(response, bytes) else json.dumps(response).encode()
            envelope = {"status": 200, "encoding": "identity", "body": base64.b64encode(body).decode()}
            reply = envelope if rpc is None else rpc
            output = reply if isinstance(reply, bytes) else json.dumps(reply).encode()
        return subprocess.CompletedProcess(command, 0, output, b"")

    return run


def test_status_regions_do_not_assert_authentication_or_qualification():
    result = probe_lite_runtime(profile(), Event(), runner=runner())
    assert result["reachable"] is True
    assert result["protocol_compatible"] is True
    assert result["artifact_verified"] is True
    assert result["regions"] == ["ro"]
    assert result["storefront"] == "ro"
    assert result["authenticated"] is None
    assert result["account_id"] == ""
    assert result["qualification"] == "pending"
    assert result["session_revision"]
    assert result["error"] == ""


def changing_runtime(changed):
    initial = container()
    inspections, executed = [], []
    status = runner()

    def run(command, **options):
        if "inspect" in command:
            observed = initial if not inspections else changed
            inspections.append(observed)
            return subprocess.CompletedProcess(command, 0, json.dumps(observed).encode(), b"")
        # The configured name has already changed at this external boundary.
        target = command[3]
        executed.append(changed["id"] if target == profile().container else target)
        return status(command, **options)

    return run, inspections, executed


def test_name_replacement_never_executes_the_replacement_and_discards_old_status():
    run, _, executed = changing_runtime({**container(), "id": "c" * 64})
    result = probe_lite_runtime(profile(), Event(), runner=run)
    assert executed == ["b" * 64]
    assert result["error"] == "runtime_context_changed"
    assert result["artifact_verified"] is None
    assert result["reachable"] is None
    assert result["protocol_compatible"] is None
    assert result["regions"] == []
    assert result["session_revision"] == ""


@pytest.mark.parametrize(
    "change",
    [
        {"started_at": "2026-10-12T09:00:00Z"},
        {"image": "sha256:" + "c" * 64},
        {"readonly": False},
    ],
)
def test_restart_or_identity_or_confinement_change_discards_probe_evidence(change):
    run, _, _ = changing_runtime({**container(), **change})
    result = probe_lite_runtime(profile(), Event(), runner=run)
    assert result["error"] == "runtime_context_changed"
    assert result["artifact_verified"] is None
    assert result["storefront"] == ""
    assert result["regions"] == []
    assert result["session_revision"] == ""
    assert result["authenticated"] is None


def test_stable_runtime_status_is_accepted_after_fresh_identity_inspection():
    run, inspections, executed = changing_runtime(container())
    result = probe_lite_runtime(profile(), Event(), runner=run)
    assert executed == ["b" * 64]
    assert len(inspections) == 2
    assert result["error"] == ""
    assert result["protocol_compatible"] is True
    assert result["regions"] == ["ro"]


def test_incomplete_confinement_inspection_never_contacts_the_status_service():
    info = container()
    del info["ports"]

    def inspect_only(command, **options):
        assert "inspect" in command
        return subprocess.CompletedProcess(command, 0, json.dumps(info).encode(), b"")

    result = probe_lite_runtime(profile(), Event(), runner=inspect_only)
    assert result["reachable"] is None
    assert result["artifact_verified"] is False
    assert result["error"] == "runtime_not_confined"


@pytest.mark.parametrize(
    "change",
    [
        {"image": "sha256:" + "c" * 64},
        {"running": False},
        {"readonly": False},
        {"user": "0:20"},
        {"user": "root"},
        {"cap_drop": []},
        {"ports": {"12340/tcp": [{"HostIp": "127.0.0.1", "HostPort": "12340"}]}},
        {"bindings": {"12340/tcp": [{"HostIp": "0.0.0.0", "HostPort": "12340"}]}},  # noqa: S104 - rejection fixture
        {"network": "host"},
        {"args": ["--host", "0.0.0.0", "--port", "12340"]},  # noqa: S104 - rejection fixture
        {"args": ["--host", "127.0.0.1", "--port", "23450"]},
    ],
)
def test_unverified_or_unconfined_runtime_is_not_contacted(change):
    info = {**container(), **change}

    def inspect_only(command, **options):
        assert "inspect" in command
        return subprocess.CompletedProcess(command, 0, json.dumps(info).encode(), b"")

    result = probe_lite_runtime(profile(), Event(), runner=inspect_only)
    assert result["artifact_verified"] is False
    assert result["reachable"] is None
    assert result["authenticated"] is None
    assert result["qualification"] == "pending"


@pytest.mark.parametrize(
    "change",
    [
        {"endpoint": "http://example.com:12340"},
        {"endpoint": "https://127.0.0.1:12340"},
        {"endpoint": "http://127.0.0.1:80"},
        {"endpoint": "http://user:secret@127.0.0.1:12340"},
        {"endpoint": "http://127.0.0.1:12340/status"},
        {"container": "--all"},
        {"artifact_digest": "mutable-tag"},
        {"kind": RuntimeKind.MANAGED},
        {"protocol": "wrapper-v2"},
    ],
)
def test_invalid_runtime_configuration_performs_no_io(change):
    def unused(*args, **options):
        pytest.fail("Invalid configuration reached the external runtime")

    result = probe_lite_runtime(replace(profile(), **change), Event(), runner=unused)
    assert result["reachable"] is None
    assert result["artifact_verified"] is None
    assert result["error"]
    assert "secret" not in str(result)


@pytest.mark.parametrize(
    "status",
    [
        b"not JSON secret-response",
        b'{"code":0,"code":0,"msg":"SUCCESS","data":{"regions":["ro"]}}',
        {"code": False, "msg": "SUCCESS", "data": {"regions": ["ro"]}},
        {"code": 500, "msg": "secret-response", "data": {"regions": ["ro"]}},
        {"code": 0, "data": {"regions": ["ro"]}},
        {"code": 0, "msg": "SUCCESS", "data": {"regions": ["RO"]}},
        {"code": 0, "msg": "SUCCESS", "data": {"regions": [7]}},
        {"code": 0, "msg": "SUCCESS", "data": {}},
        b" " * 16385,
        b'{"code":0,"msg":"SUCCESS","data":' + b"[" * 7500 + b"]" * 7500 + b"}",
    ],
)
def test_malformed_or_oversized_status_is_incompatible_without_echoing_remote_data(status):
    result = probe_lite_runtime(profile(), Event(), runner=runner(status=status))
    assert result["reachable"] is True
    assert result["protocol_compatible"] is False
    assert result["regions"] == []
    assert result["error"]
    assert "secret-response" not in str(result)


def test_excessive_json_nesting_returns_a_fixed_protocol_error():
    status = b'{"code":0,"msg":"SUCCESS","data":' + b"[" * 1500 + b"]" * 1500 + b"}"
    result = probe_lite_runtime(profile(), Event(), runner=runner(status=status))
    assert result["protocol_compatible"] is False
    assert result["error"] in ("invalid_json", "invalid_status_regions")


@pytest.mark.parametrize(
    "rpc",
    [
        {"status": 302, "encoding": "identity", "body": "secret-response"},
        {"status": True, "encoding": "identity", "body": "secret-response"},
        {"status": 200, "encoding": "gzip", "body": "secret-response"},
        {"status": 200, "encoding": "identity", "body": "not-base64!"},
        b'{"status":200,"status":200,"encoding":"identity","body":"e30="}',
        b" " * 65537,
    ],
)
def test_invalid_status_transport_reply_cannot_establish_protocol_compatibility(rpc):
    result = probe_lite_runtime(profile(), Event(), runner=runner(rpc=rpc))
    assert result["protocol_compatible"] is not True
    assert result["authenticated"] is None
    assert result["error"]
    assert "secret-response" not in str(result)


@pytest.mark.parametrize("regions,storefront", [([], ""), (["us", "ro"], ""), (["ro"], "ro")])
def test_storefront_requires_one_observed_region_and_ignores_untrusted_auth_fields(regions, storefront):
    status = {"code": 0, "msg": "SUCCESS", "data": {"regions": regions, "authenticated": True, "account_id": "secret"}}
    result = probe_lite_runtime(profile(), Event(), runner=runner(status=status))
    assert result["protocol_compatible"] is True
    assert result["storefront"] == storefront
    assert result["authenticated"] is None
    assert result["account_id"] == ""
    assert "secret" not in str(result)


@pytest.mark.parametrize("change", [{"id": "c" * 64}, {"started_at": "2026-10-12T09:00:00Z"}])
def test_runtime_replacement_or_restart_changes_the_observed_session_revision(change):
    before = probe_lite_runtime(profile(), Event(), runner=runner())
    after = probe_lite_runtime(profile(), Event(), runner=runner(info={**container(), **change}))
    assert before["session_revision"] != after["session_revision"]
    assert after["authenticated"] is None


@pytest.mark.parametrize("cancel_after_inspection", [False, True])
def test_cancelled_probe_never_contacts_the_status_service(cancel_after_inspection):
    abort = Event()
    if not cancel_after_inspection:
        abort.set()

    def inspect_only(command, **options):
        assert cancel_after_inspection and "inspect" in command
        abort.set()
        return subprocess.CompletedProcess(command, 0, json.dumps(container()).encode(), b"")

    result = probe_lite_runtime(profile(), abort, runner=inspect_only)
    assert result["error"] == "cancelled"
    assert result["reachable"] is None
    assert result["authenticated"] is None


@pytest.mark.integration
def test_native_probe_bounds_process_output_and_reaps_the_owned_command(monkeypatch):
    original = subprocess.Popen
    processes = []

    def launch(command, **options):
        code = (
            "import sys; sys.stdout.buffer.write(b'x' * 1000000)"
            if "exec" in command
            else f"import sys; sys.stdout.write({json.dumps(container())!r})"
        )
        process = original([sys.executable, "-c", code], **options)
        processes.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", launch)
    result = probe_lite_runtime(profile(), Event())
    assert result["error"] == "runtime_probe_bound"
    assert result["protocol_compatible"] is None
    assert all(process.poll() is not None for process in processes)


@pytest.mark.integration
def test_native_probe_cancellation_reaps_only_its_owned_command(monkeypatch):
    original = subprocess.Popen
    processes = []
    started, finished, abort = Event(), Event(), Event()
    results = []

    def launch(command, **options):
        waiting = "exec" in command
        code = (
            "import time; time.sleep(60)" if waiting else f"import sys; sys.stdout.write({json.dumps(container())!r})"
        )
        process = original([sys.executable, "-c", code], **options)
        processes.append(process)
        if waiting:
            started.set()
        return process

    def work():
        try:
            results.append(probe_lite_runtime(profile(), abort))
        finally:
            finished.set()

    monkeypatch.setattr(subprocess, "Popen", launch)
    thread = Thread(target=work, daemon=True)
    thread.start()
    try:
        assert started.wait(timeout=2)
    finally:
        abort.set()
    assert finished.wait(timeout=5)
    thread.join(timeout=1)
    assert results[0]["error"] == "cancelled"
    assert all(process.poll() is not None for process in processes)


def test_automatic_detection_uses_running_podman_without_retaining_host_diagnostics():
    commands = []
    execute = runner()

    def run(command, **options):
        commands.append(command)
        if command[1:] == ["info"]:
            if command[0] == "docker":
                return subprocess.CompletedProcess(command, 1, b"private-host-diagnostic", b"")
            return subprocess.CompletedProcess(command, 0, b"private-host-diagnostic", b"")
        return execute(command, **options)

    result = probe_lite_runtime(profile(), Event(), binary=None, runner=run)
    assert result["protocol_compatible"] is True
    assert commands[:2] == [["docker", "info"], ["podman", "info"]]
    assert all(command[0] == "podman" for command in commands[2:])
    assert "private-host-diagnostic" not in str(result)


@pytest.mark.integration
def test_cancellation_during_detection_reaps_its_command_without_starting_a_fallback(monkeypatch):
    original = subprocess.Popen
    processes, commands, results = [], [], []
    started, finished, abort = Event(), Event(), Event()

    def launch(command, **options):
        commands.append(command)
        process = original([sys.executable, "-c", "import time; time.sleep(60)"], **options)
        processes.append(process)
        started.set()
        return process

    def work():
        try:
            results.append(probe_lite_runtime(profile(), abort, binary=None))
        finally:
            finished.set()

    monkeypatch.setattr(subprocess, "Popen", launch)
    thread = Thread(target=work, daemon=True)
    thread.start()
    try:
        assert started.wait(timeout=2)
    finally:
        abort.set()
    assert finished.wait(timeout=5)
    thread.join(timeout=1)
    assert results[0]["error"] == "cancelled"
    assert commands == [["docker", "info"]]
    assert processes[0].poll() is not None


def test_native_probe_launch_failure_does_not_expose_external_diagnostics(monkeypatch):
    def unavailable(*args, **options):
        raise OSError("secret-runtime-diagnostic")

    monkeypatch.setattr(subprocess, "Popen", unavailable)
    result = probe_lite_runtime(profile(), Event())
    assert result["error"] == "runtime_probe_failed"
    assert result["artifact_verified"] is None
    assert "secret-runtime-diagnostic" not in str(result)


def test_native_probe_pipe_failure_reaps_the_command_and_closes_input(monkeypatch):
    original = subprocess.Popen

    class Input:
        closed = False

        def write(self, payload):
            raise BrokenPipeError("secret-runtime-diagnostic")

        def close(self):
            self.closed = True

    class Process:
        returncode = None
        stdin = Input()
        stdout = io.BytesIO(b"")

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = -15

        def wait(self, timeout):
            return self.returncode

    owned = Process()

    def launch(command, **options):
        if "inspect" in command:
            return original([sys.executable, "-c", f"print({json.dumps(container())!r})"], **options)
        return owned

    monkeypatch.setattr(subprocess, "Popen", launch)
    result = probe_lite_runtime(profile(), Event())
    assert result["error"] == "runtime_probe_failed"
    assert result["reachable"] is False
    assert owned.poll() is not None
    assert owned.stdin.closed
    assert "secret-runtime-diagnostic" not in str(result)


@pytest.mark.parametrize(
    "change",
    [
        {"privileged": True},
        {"privileged": None},
        {"privileged": 0},
        {"cap_add": ["NET_ADMIN"]},
        {"cap_add": "ALL"},
        {"cap_add": {}},
    ],
)
def test_privileged_or_added_capability_runtime_is_not_admitted(change):
    calls = []
    execute = runner(info={**container(), **change})

    def run(command, **options):
        calls.append(command)
        return execute(command, **options)

    result = probe_lite_runtime(profile(), Event(), runner=run)
    assert result["artifact_verified"] is False
    assert result["error"] == "runtime_not_confined"
    assert all("exec" not in command for command in calls)


@pytest.mark.parametrize("field", ["privileged", "cap_add"])
def test_missing_privilege_inspection_cannot_admit_a_runtime(field):
    info = container()
    info.pop(field)
    result = probe_lite_runtime(profile(), Event(), runner=runner(info=info))
    assert result["artifact_verified"] is False
    assert result["error"] == "runtime_not_confined"


def session_runner(packet):
    def run(command, **options):
        if "inspect" in command:
            output = container()
        else:
            assert "exec" in command
            assert "/waves/session/v1" in command[-1]
            assert json.loads(options["input"]) == {"port": 12340}
            output = {
                "status": 200,
                "encoding": "identity",
                "body": base64.b64encode(json.dumps(packet).encode()).decode(),
            }
        return subprocess.CompletedProcess(command, 0, json.dumps(output).encode(), b"")

    return run


def session_packet(**changes):
    return {
        "protocol": "waves-lite-session-v1",
        "authenticated": True,
        "storefront": "ro",
        "account_id": "",
        "session_revision": "c" * 32 + ":1",
        "error": "",
        **changes,
    }


def test_fresh_versioned_session_is_observed_without_implying_artifact_approval():
    result = probe_lite_runtime(
        replace(profile(), protocol="lite-session-v1"), Event(), runner=session_runner(session_packet())
    )
    assert result["reachable"] is True
    assert result["protocol_compatible"] is True
    assert result["session_protocol_compatible"] is True
    assert result["authenticated"] is True
    assert result["account_id"] == ""
    assert result["storefront"] == "ro"
    assert result["qualification"] == "pending"
    assert result["approval_record"] == ""
    assert result["session_revision"]


@pytest.mark.parametrize(
    "change",
    [
        {"protocol": "unreviewed-session-v2"},
        {"authenticated": 1},
        {"authenticated": False},
        {"storefront": "RO"},
        {"storefront": ["ro"]},
        {"account_id": "private-account-label"},
        {"session_revision": "private-token"},
        {"session_revision": "c" * 32 + ":0"},
        {"session_revision": "c" * 32 + ":9007199254740992"},
        {"error": "private-upstream-diagnostic"},
        {"error": "upstream_rejected"},
        {"qualification": "approved"},
    ],
)
def test_session_claims_require_the_exact_reviewed_contract(change):
    result = probe_lite_runtime(
        replace(profile(), protocol="lite-session-v1"), Event(), runner=session_runner(session_packet(**change))
    )
    assert result["authenticated"] is None
    assert result["session_protocol_compatible"] is False
    assert result["qualification"] == "pending"
    assert result["error"] == "invalid_session_protocol"
    assert "private-" not in str(result)


@pytest.mark.parametrize("error", ["upstream_rejected", "upstream_unavailable", "credential_context_changed"])
def test_unknown_session_responses_do_not_misclassify_a_rejected_request_as_logout(error):
    result = probe_lite_runtime(
        replace(profile(), protocol="lite-session-v1"),
        Event(),
        runner=session_runner(session_packet(authenticated=None, storefront="", error=error)),
    )
    assert result["authenticated"] is None
    assert result["session_protocol_compatible"] is True
    assert result["storefront"] == ""
    assert result["error"] == error


def test_approval_is_bound_to_the_artifact_and_native_host():
    from waves.providers.apple.lite_runtime import LiteSessionApproval

    approval = LiteSessionApproval(
        IMAGE, sys.platform, platform.machine(), "d" * 40, "e" * 64, "https://example.test/qualification"
    )
    result = probe_lite_runtime(
        replace(profile(), protocol="lite-session-v1"),
        Event(),
        approval=approval,
        runner=session_runner(session_packet()),
    )
    assert result["authenticated"] is True
    assert result["qualification"] == "approved"
    assert result["approval_record"] == "https://example.test/qualification"
    for wrong in (
        replace(approval, image_digest="sha256:" + "f" * 64),
        replace(approval, host_platform="other-platform"),
        replace(approval, host_architecture="other-architecture"),
        replace(approval, source_revision=""),
        replace(approval, patch_sha256=""),
        replace(approval, approval_record=""),
        replace(approval, application_kind="packaged"),
    ):
        result = probe_lite_runtime(
            replace(profile(), protocol="lite-session-v1"),
            Event(),
            approval=wrong,
            runner=session_runner(session_packet()),
        )
        assert result["authenticated"] is True
        assert result["qualification"] == "pending"
        assert result["approval_record"] == ""


def test_missing_session_observer_preserves_status_regions_without_authentication():
    legacy = {"code": 0, "msg": "SUCCESS", "data": {"regions": ["ro"], "authenticated": True, "account_id": "private"}}

    def run(command, **options):
        if "inspect" in command:
            response = container()
        elif "/waves/session/v1" in command[-1]:
            response = {"status": 404, "encoding": "identity", "body": ""}
        else:
            response = {
                "status": 200,
                "encoding": "identity",
                "body": base64.b64encode(json.dumps(legacy).encode()).decode(),
            }
        return subprocess.CompletedProcess(command, 0, json.dumps(response).encode(), b"")

    result = probe_lite_runtime(replace(profile(), protocol="lite-session-v1"), Event(), runner=run)
    assert result["regions"] == ["ro"]
    assert result["protocol_compatible"] is True
    assert result["session_protocol_compatible"] is False
    assert result["authenticated"] is None
    assert result["qualification"] == "pending"
    assert result["error"] == "session_observer_unavailable"
    assert "private" not in str(result)
