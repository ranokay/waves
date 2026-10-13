"""Bounded status and session observation of a confined user-managed lite runtime.

Image identity and advertised regions establish no authentication. The versioned
session observer establishes authentication separately from artifact approval
and delivered-media qualification.
"""

from __future__ import annotations

import base64
import binascii
import contextlib
import hashlib
import json
import platform
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from threading import Event, Thread
from typing import Literal, Protocol, TypedDict, Unpack
from urllib.parse import urlsplit

from waves.providers.apple.child_guard import NO_WINDOW
from waves.providers.apple.runtime_sessions import RuntimeKind, RuntimeProfile, local_wrapper_endpoint

_STATUS_LIMIT = 16 * 1024
_COMMAND_LIMIT = 64 * 1024
_INSPECTION = (
    '{"id":{{json .Id}},"image":{{json .Image}},"started_at":{{json .State.StartedAt}},'
    '"running":{{json .State.Running}},"ports":{{json .NetworkSettings.Ports}},'
    '"bindings":{{json .HostConfig.PortBindings}},"readonly":{{json .HostConfig.ReadonlyRootfs}},'
    '"cap_drop":{{json .HostConfig.CapDrop}},"cap_add":{{json .HostConfig.CapAdd}},'
    '"privileged":{{json .HostConfig.Privileged}},"user":{{json .Config.User}},'
    '"args":{{json .Args}},"network":{{json .HostConfig.NetworkMode}}}'
)
# Only the port enters stdin. The guest can observe one fixed status route.
_STATUS_RPC = """
import base64, http.client, json, sys
try:
    request = json.loads(sys.stdin.buffer.read(1025))
    connection = http.client.HTTPConnection('127.0.0.1', request['port'], timeout=5)
    connection.request('GET', '/status', headers={'Accept-Encoding': 'identity'})
    response = connection.getresponse()
    body = response.read(16385)
    if len(body) > 16384:
        raise ValueError()
    result = {'status': response.status,
              'encoding': response.getheader('Content-Encoding', 'identity'),
              'body': base64.b64encode(body).decode('ascii')}
    connection.close()
    sys.stdout.write(json.dumps(result, separators=(',', ':')))
except Exception:
    sys.exit(1)
"""
_SESSION_RPC = _STATUS_RPC.replace("'GET', '/status'", "'GET', '/waves/session/v1'").replace("timeout=5", "timeout=18")
_SESSION_ERRORS = {
    "",
    "credentials_unavailable",
    "credential_context_changed",
    "observer_busy",
    "upstream_unavailable",
    "upstream_rejected",
    "invalid_upstream_response",
    "observer_unavailable",
}


@dataclass(frozen=True)
class LiteSessionApproval:
    """Reviewed native evidence for one exact user-managed artifact and host."""

    image_digest: str
    host_platform: str
    host_architecture: str
    source_revision: str
    patch_sha256: str
    approval_record: str
    application_kind: str = "source"


# Entries require recorded artifact, transport and native-host qualification.
# A configured digest or a runtime's own assertion cannot create approval.
APPROVED_LITE_SESSION_ARTIFACTS: tuple[LiteSessionApproval, ...] = ()


class LiteRuntimeStatus(TypedDict):
    reachable: bool | None
    protocol_compatible: bool | None
    artifact_verified: bool | None
    authenticated: bool | None
    account_id: str
    storefront: str
    session_revision: str
    session_protocol_compatible: bool | None
    approval_record: str
    regions: list[str]
    qualification: str
    error: str


class _RunnerOptions(TypedDict):
    input: bytes | None
    timeout: int
    capture_output: bool


class _Runner(Protocol):
    def __call__(self, command: list[str], **options: Unpack[_RunnerOptions]) -> subprocess.CompletedProcess[bytes]: ...


class _ProbeFailed(RuntimeError):
    """Fixed local categories never retain guest responses or diagnostics."""


def _check_abort(abort: Event) -> None:
    if abort.is_set():
        raise _ProbeFailed("cancelled")


def _unique_fields(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for name, value in pairs:
        if name in result:
            raise _ProbeFailed("duplicate_json_field")
        result[name] = value
    return result


def _json_object(data: bytes) -> dict:
    try:
        result = json.loads(data, object_pairs_hook=_unique_fields)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise _ProbeFailed("invalid_json") from exc
    if not isinstance(result, dict):
        raise _ProbeFailed("invalid_json_object")
    return result


def _profile_port(profile: RuntimeProfile) -> int:
    if profile.kind != RuntimeKind.USER_MANAGED or profile.protocol not in ("lite-status-v1", "lite-session-v1"):
        raise _ProbeFailed("invalid_runtime_profile")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", profile.container):
        raise _ProbeFailed("invalid_runtime_container")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", profile.artifact_digest):
        raise _ProbeFailed("missing_runtime_identity")
    try:
        endpoint = local_wrapper_endpoint(profile.endpoint)
    except ValueError as exc:
        raise _ProbeFailed("invalid_runtime_endpoint") from exc
    return int(urlsplit(endpoint).port or 0)


def _no_published_ports(value) -> bool:
    return value is None or (isinstance(value, dict) and all(item is None or item == [] for item in value.values()))


def _argument_matches(arguments: list[str], name: str, value: str) -> bool:
    if arguments.count(name) != 1:
        return False
    index = arguments.index(name) + 1
    return index < len(arguments) and arguments[index] == value


def _confined(info: dict, port: int) -> bool:
    arguments = info.get("args")
    capabilities = info.get("cap_drop")
    return bool(
        info.get("running") is True
        and info.get("readonly") is True
        and isinstance(info.get("user"), str)
        and re.fullmatch(r"[1-9][0-9]*(?::[0-9]+)?", info["user"])
        and isinstance(capabilities, list)
        and "ALL" in capabilities
        and info.get("privileged") is False
        and "cap_add" in info
        and (info["cap_add"] is None or info["cap_add"] == [])
        and isinstance(info.get("network"), str)
        and info["network"] not in ("", "host")
        and "ports" in info
        and "bindings" in info
        and _no_published_ports(info.get("ports"))
        and _no_published_ports(info.get("bindings"))
        and isinstance(arguments, list)
        and all(isinstance(item, str) for item in arguments)
        and _argument_matches(arguments, "--host", "127.0.0.1")
        and _argument_matches(arguments, "--port", str(port))
    )


def _session_revision(info: dict) -> str:
    identifier, started = info.get("id"), info.get("started_at")
    if not isinstance(identifier, str) or not re.fullmatch(r"[0-9a-f]{64}", identifier):
        raise _ProbeFailed("invalid_runtime_identity")
    if not isinstance(started, str) or not 0 < len(started) <= 128 or any(ord(item) < 32 for item in started):
        raise _ProbeFailed("invalid_runtime_identity")
    return hashlib.sha256(json.dumps([identifier, started, info["image"]]).encode()).hexdigest()


def _stop_command(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    with contextlib.suppress(ProcessLookupError):
        process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        process.wait(timeout=2)


def _wait_command(process: subprocess.Popen[bytes], abort: Event, overflow: Event, timeout: int) -> None:
    deadline = time.monotonic() + timeout
    while process.poll() is None:
        _check_abort(abort)
        if overflow.is_set() or time.monotonic() >= deadline:
            raise _ProbeFailed("runtime_probe_bound")
        abort.wait(0.05)
    _check_abort(abort)


def _close_command(process: subprocess.Popen[bytes], reader: Thread, reader_started: bool) -> None:
    _stop_command(process)
    if process.stdin is not None:
        with contextlib.suppress(OSError):
            process.stdin.close()
    if reader_started:
        reader.join(timeout=1)
    if process.stdout is not None and (not reader_started or not reader.is_alive()):
        process.stdout.close()


def _native_command(
    command: list[str], payload: bytes | None, timeout: int, abort: Event
) -> subprocess.CompletedProcess[bytes]:
    process = subprocess.Popen(  # noqa: S603 - fixed Docker operations, validated container, no shell
        command,
        stdin=subprocess.PIPE if payload is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=0,
        **NO_WINDOW,
    )
    output = bytearray()
    overflow = Event()
    failed = Event()
    stream = process.stdout
    if stream is None:
        _stop_command(process)
        raise _ProbeFailed("runtime_probe_failed")

    def read_output() -> None:
        try:
            while chunk := stream.read(8192):
                if len(output) + len(chunk) > _COMMAND_LIMIT:
                    overflow.set()
                    return
                output.extend(chunk)
        except OSError:
            failed.set()

    reader = Thread(target=read_output, daemon=True)
    reader_started = False
    try:
        reader.start()
        reader_started = True
        if payload is not None and process.stdin is not None:
            process.stdin.write(payload)
            process.stdin.close()
        _wait_command(process, abort, overflow, timeout)
        reader.join(timeout=1)
        if reader.is_alive() or failed.is_set() or overflow.is_set():
            raise _ProbeFailed("runtime_probe_bound")
        if process.returncode is None:
            raise _ProbeFailed("runtime_probe_failed")
        return subprocess.CompletedProcess(command, process.returncode, bytes(output), b"")
    finally:
        _close_command(process, reader, reader_started)


def _command_result(
    command: list[str], payload: bytes | None, timeout: int, abort: Event, runner: _Runner | None
) -> subprocess.CompletedProcess[bytes]:
    _check_abort(abort)
    if runner is None:
        result = _native_command(command, payload, timeout, abort)
    else:
        result = runner(command, input=payload, timeout=timeout, capture_output=True)
    _check_abort(abort)
    if not isinstance(result.stdout, bytes) or len(result.stdout) > _COMMAND_LIMIT:
        raise _ProbeFailed("runtime_probe_bound")
    return result


def _command(command: list[str], payload: bytes | None, timeout: int, abort: Event, runner: _Runner | None) -> bytes:
    result = _command_result(command, payload, timeout, abort, runner)
    if result.returncode != 0:
        raise _ProbeFailed("runtime_probe_failed")
    return result.stdout


def _detect_binary(abort: Event, runner: _Runner | None) -> str:
    from waves.providers.apple.runtime import detect_container_runtime

    def run(command: list[str], *, timeout: int, **_options) -> subprocess.CompletedProcess[bytes]:
        # Detection reads only return codes; capture stays bounded bytes.
        return _command_result(command, None, timeout, abort, runner)

    container = detect_container_runtime(runner=run, timeout=5)
    _check_abort(abort)
    return str(container.get("name") or "docker")


def _rpc_body(output: bytes, protocol: Literal["status", "session"]) -> bytes:
    reply = _json_object(output)
    if type(reply.get("status")) is not int or reply["status"] != 200 or reply.get("encoding") != "identity":
        raise _ProbeFailed(f"invalid_{protocol}_http_response")
    try:
        body = base64.b64decode(reply["body"], validate=True)
    except (KeyError, TypeError, ValueError, binascii.Error) as exc:
        raise _ProbeFailed(f"invalid_{protocol}_rpc_response") from exc
    if not 0 < len(body) <= _STATUS_LIMIT:
        raise _ProbeFailed(f"{protocol}_response_bound")
    return body


def _regions(output: bytes) -> list[str]:
    status = _json_object(_rpc_body(output, "status"))
    data = status.get("data")
    if type(status.get("code")) is not int or status["code"] != 0 or not isinstance(status.get("msg"), str):
        raise _ProbeFailed("invalid_status_protocol")
    regions = data.get("regions") if isinstance(data, dict) else None
    if (
        not isinstance(regions, list)
        or len(regions) > 16
        or not all(isinstance(item, str) and re.fullmatch(r"[a-z]{2}", item) for item in regions)
    ):
        raise _ProbeFailed("invalid_status_regions")
    return regions


def _admit_inspection(info: dict, profile: RuntimeProfile, port: int, result: LiteRuntimeStatus) -> None:
    if info.get("image") != profile.artifact_digest:
        result["artifact_verified"] = False
        raise _ProbeFailed("runtime_identity_mismatch")
    if not _confined(info, port):
        result["artifact_verified"] = False
        raise _ProbeFailed("runtime_not_confined")
    result["session_revision"] = _session_revision(info)
    result["artifact_verified"] = True


def _session_observation(output: bytes, result: LiteRuntimeStatus) -> None:
    packet = _json_object(_rpc_body(output, "session"))
    if set(packet) != {"protocol", "authenticated", "storefront", "account_id", "session_revision", "error"}:
        raise _ProbeFailed("invalid_session_protocol")
    authenticated, storefront = packet["authenticated"], packet["storefront"]
    revision, error = packet["session_revision"], packet["error"]
    valid_revision = (
        isinstance(revision, str)
        and re.fullmatch(r"[0-9a-f]{32}:[1-9][0-9]{0,15}", revision) is not None
        and int(revision.split(":")[1]) <= (1 << 53) - 1
    )
    if (
        packet["protocol"] != "waves-lite-session-v1"
        or packet["account_id"] != ""
        or not isinstance(error, str)
        or error not in _SESSION_ERRORS
        or not (valid_revision or (revision == "" and authenticated is None and error == "observer_unavailable"))
    ):
        raise _ProbeFailed("invalid_session_protocol")
    if authenticated is True:
        if error or not isinstance(storefront, str) or re.fullmatch(r"[a-z]{2}", storefront) is None:
            raise _ProbeFailed("invalid_session_protocol")
    elif authenticated is not None or storefront != "":
        raise _ProbeFailed("invalid_session_protocol")
    result["authenticated"] = authenticated
    result["storefront"] = storefront
    result["regions"] = [storefront] if storefront else []
    result["session_revision"] = (
        hashlib.sha256(json.dumps([result["session_revision"], revision]).encode()).hexdigest() if revision else ""
    )
    result["error"] = error
    result["protocol_compatible"] = True
    result["session_protocol_compatible"] = True


def _unchanged_inspection(
    binary: str, profile: RuntimeProfile, initial: dict, abort: Event, runner: _Runner | None
) -> bool:
    try:
        current = _json_object(
            _command([binary, "inspect", "--format", _INSPECTION, "--", profile.container], None, 5, abort, runner)
        )
    except (_ProbeFailed, OSError, subprocess.SubprocessError):
        _check_abort(abort)
        return False
    # Every identity and confinement field must still match the admitted snapshot.
    return current == initial


def _unknown_status(error: str = "") -> LiteRuntimeStatus:
    return {
        "reachable": None,
        "protocol_compatible": None,
        "artifact_verified": None,
        "authenticated": None,
        "account_id": "",
        "storefront": "",
        "session_revision": "",
        "session_protocol_compatible": None,
        "approval_record": "",
        "regions": [],
        "qualification": "pending",
        "error": error,
    }


def _apply_session_approval(
    profile: RuntimeProfile, result: LiteRuntimeStatus, approval: LiteSessionApproval | None, application_kind: str
) -> None:
    candidates = (approval,) if approval is not None else APPROVED_LITE_SESSION_ARTIFACTS
    for record in candidates:
        if (
            record.image_digest == profile.artifact_digest
            and record.host_platform == sys.platform
            and record.host_architecture.casefold() == platform.machine().casefold()
            and record.application_kind == application_kind
            and re.fullmatch(r"[0-9a-f]{40}", record.source_revision)
            and re.fullmatch(r"[0-9a-f]{64}", record.patch_sha256)
            and 0 < len(record.approval_record) <= 1024
            and record.approval_record.startswith("https://")
        ):
            result["qualification"] = "approved"
            result["approval_record"] = record.approval_record
            return


def probe_lite_runtime(
    profile: RuntimeProfile,
    abort: Event,
    *,
    binary: str | None = "docker",
    runner: _Runner | None = None,
    approval: LiteSessionApproval | None = None,
    application_kind: str = "source",
) -> LiteRuntimeStatus:
    """Observe identity, confinement and one fixed private runtime route.

    Run on a worker. The injected runner has subprocess.run's bytes interface;
    Native commands bound output and poll cancellation. Legacy status regions
    leave authentication unknown. The versioned session route supplies fresh
    authentication and credential continuity, never an account identifier.
    With binary=None, detect Docker/Podman using the same owned cancellable
    commands. Detection stays local and publishes no shared bridge cache.
    """
    result = _unknown_status()
    contacted = False
    try:
        _check_abort(abort)
        port = _profile_port(profile)
        if binary is None:
            binary = _detect_binary(abort, runner)
        info = _json_object(
            _command([binary, "inspect", "--format", _INSPECTION, "--", profile.container], None, 5, abort, runner)
        )
        _admit_inspection(info, profile, port, result)
        contacted = True
        response = _command(
            [
                binary,
                "exec",
                "--interactive",
                info["id"],
                "/usr/bin/python3",
                "-c",
                _SESSION_RPC if profile.protocol == "lite-session-v1" else _STATUS_RPC,
            ],
            json.dumps({"port": port}).encode(),
            20 if profile.protocol == "lite-session-v1" else 10,
            abort,
            runner,
        )
        session_missing = profile.protocol == "lite-session-v1" and _json_object(response).get("status") == 404
        if session_missing:
            response = _command(
                [binary, "exec", "--interactive", info["id"], "/usr/bin/python3", "-c", _STATUS_RPC],
                json.dumps({"port": port}).encode(),
                10,
                abort,
                runner,
            )
        if _unchanged_inspection(binary, profile, info, abort, runner):
            result["reachable"] = True
            result["protocol_compatible"] = False
            if profile.protocol == "lite-session-v1" and not session_missing:
                result["session_protocol_compatible"] = False
                _session_observation(response, result)
                _apply_session_approval(profile, result, approval, application_kind)
            else:
                regions = _regions(response)
                result["regions"] = regions
                result["storefront"] = regions[0] if regions and len(set(regions)) == 1 else ""
                result["protocol_compatible"] = True
                if session_missing:
                    result["session_protocol_compatible"] = False
                    result["error"] = "session_observer_unavailable"
        else:
            result = _unknown_status("runtime_context_changed")
            contacted = False
    except _ProbeFailed as exc:
        result["error"] = str(exc)
    except (OSError, subprocess.SubprocessError):
        result["error"] = "runtime_probe_failed"
    if contacted and result["reachable"] is None and result["error"] != "cancelled":
        result["reachable"] = False
    return result
