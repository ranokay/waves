"""Bounded local transport for the profile owner's provider controls.

Dispatchers receive the validated request and its monotonic deadline. They must
check that deadline before performing a deferred action on another thread.
"""

from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import math
import os
import re
import socket
import stat
import struct
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

from waves.desktop.providers.profile_owner import ProfileOwner

MAX_MESSAGE = 4096
TIMEOUT = 1.0
MAX_CLIENTS = 4
_STATES = frozenset(
    {
        "signed_out",
        "checking",
        "authenticating",
        "awaiting_verification",
        "authenticated",
        "expired_rejected",
        "unavailable_unknown",
    }
)
_ACTIONS = frozenset(
    {"none", "open_waves", "connect_provider", "complete_verification", "enable_provider", "start_runtime"}
)
_FACTS = frozenset({"catalog", "runtime", "identity", "storefront", "delivery"})
_FACT_VALUES = frozenset({"ready", "not_ready", "unknown"})
_ACTIVE_LOCK = threading.Lock()
_ACTIVE_ENDPOINTS: set[str] = set()
_ERRORS = frozenset(
    {
        "invalid_request",
        "unsupported_version",
        "unsupported_operation",
        "unsupported_provider",
        "too_large",
        "timeout",
        "busy",
        "unavailable",
    }
)


class IPCUnavailable(Exception):
    """The local control transport cannot be used safely."""


def _error(code: str) -> dict:
    return {"version": 1, "error": code}


def _namespace(profile: Path, *, create: bool) -> Path:  # noqa: C901 - validates each ownership boundary
    if sys.platform == "darwin":
        root = Path("/private/tmp")
    elif sys.platform.startswith("linux"):
        root = Path("/tmp")  # noqa: S108 - validated root and private namespace
    else:
        raise IPCUnavailable()
    root_info = root.lstat()
    if not stat.S_ISDIR(root_info.st_mode) or root_info.st_uid != 0 or not root_info.st_mode & stat.S_ISVTX:
        raise IPCUnavailable()
    control = profile / "provider-control"
    control_fd = os.open(control, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        control_info = os.fstat(control_fd)
        if (
            control_info.st_uid != os.getuid()
            or stat.S_IMODE(control_info.st_mode) != 0o700
            or (control_info.st_dev, control_info.st_ino) != (control.lstat().st_dev, control.lstat().st_ino)
        ):
            raise IPCUnavailable()
        try:
            record_fd = os.open("namespace", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=control_fd)
        except FileNotFoundError:
            namespace = None
        else:
            try:
                info = os.fstat(record_fd)
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) != 0o600
                    or info.st_nlink != 1
                ):
                    raise IPCUnavailable()
                name = os.read(record_fd, 64).decode("ascii")
                if not re.fullmatch(r"w-[a-z0-9_]{8}", name):
                    raise IPCUnavailable()
                namespace = root / name
            finally:
                os.close(record_fd)
        if namespace is not None and create:
            try:
                info = namespace.lstat()
            except FileNotFoundError:
                namespace = None
            else:
                if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                    namespace = None
        if namespace is None:
            if not create:
                raise IPCUnavailable()
            namespace = Path(tempfile.mkdtemp(prefix="w-", dir=root))
            record_fd, record_path = tempfile.mkstemp(prefix=".namespace-", dir=control)
            try:
                os.fchmod(record_fd, 0o600)
                os.write(record_fd, namespace.name.encode("ascii"))
                os.replace(record_path, "namespace", dst_dir_fd=control_fd)
            finally:
                os.close(record_fd)
                if os.path.exists(record_path):
                    os.unlink(record_path)
    finally:
        os.close(control_fd)
    fd = os.open(namespace, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        path_info = namespace.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700
            or (info.st_dev, info.st_ino) != (path_info.st_dev, path_info.st_ino)
        ):
            raise IPCUnavailable()
    finally:
        os.close(fd)
    return namespace


def _endpoint(profile: Path, *, create: bool) -> Path:
    identity = hashlib.sha256(os.fsencode(Path(profile).resolve(strict=True))).hexdigest()
    path = _namespace(Path(profile).resolve(strict=True), create=create) / (identity + ".sock")
    if len(os.fsencode(path)) >= 104:
        raise IPCUnavailable()
    return path


def _peer_uid(conn: socket.socket) -> int:
    if sys.platform == "darwin":
        libc = ctypes.CDLL(None, use_errno=True)
        uid = ctypes.c_uint()
        gid = ctypes.c_uint()
        func = libc.getpeereid
        func.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint)]
        func.restype = ctypes.c_int
        if func(conn.fileno(), ctypes.byref(uid), ctypes.byref(gid)) != 0:
            raise IPCUnavailable()
        return uid.value
    if sys.platform.startswith("linux"):
        return struct.unpack("3i", conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))[1]
    raise IPCUnavailable()


def _unique(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


def _receive(conn: socket.socket, deadline: float) -> object:
    data = bytearray()
    while b"\n" not in data:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError()
        conn.settimeout(remaining)
        chunk = conn.recv(min(1024, MAX_MESSAGE + 1 - len(data)))
        if not chunk:
            raise ValueError()
        data.extend(chunk)
        if len(data) > MAX_MESSAGE:
            raise OverflowError()
    if not data.endswith(b"\n") or data.count(b"\n") != 1:
        raise ValueError()
    return json.loads(data[:-1], object_pairs_hook=_unique)


def _send(conn: socket.socket, value: dict, deadline: float) -> None:
    data = json.dumps(value, separators=(",", ":"), ensure_ascii=True).encode() + b"\n"
    if len(data) > MAX_MESSAGE:
        raise ValueError()
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError()
    conn.settimeout(remaining)
    conn.sendall(data)


def _validate(request: object) -> str | None:
    if not isinstance(request, dict) or type(request.get("version")) is not int:
        return "invalid_request"
    if request["version"] != 1:
        return "unsupported_version"
    if "deadline" in request:
        value = request["deadline"]
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            return "invalid_request"
    fields = set(request) - {"deadline"}
    op = request.get("op")
    if not isinstance(op, str) or op not in {"status", "ensure", "activate"}:
        return "unsupported_operation"
    if op == "activate":
        return None if fields == {"version", "op"} else "invalid_request"
    if fields != {"version", "op", "provider"}:
        return "invalid_request"
    if not isinstance(request["provider"], str) or request["provider"] not in {"tidal", "apple"}:
        return "unsupported_provider"
    return None


def _safe_response(value: object, request: dict) -> dict:
    if not isinstance(value, dict):
        return _error("unavailable")
    if request["op"] == "activate":
        return {"version": 1, "result": "activated"} if value.get("result") == "activated" else _error("unavailable")
    state, action, facts = value.get("state"), value.get("action"), value.get("facts")
    if not isinstance(state, str) or state not in _STATES or not isinstance(action, str) or action not in _ACTIONS:
        return _error("unavailable")
    if not isinstance(facts, dict) or set(facts) != _FACTS:
        return _error("unavailable")
    if any(not isinstance(v, str) or v not in _FACT_VALUES for v in facts.values()):
        return _error("unavailable")
    result = "action_required" if action != "none" else "checking" if state in {"checking", "authenticating"} else "ok"
    return {
        "version": 1,
        "result": result,
        "state": state,
        "action": action,
        "facts": {k: facts[k] for k in sorted(_FACTS)},
    }


def _remove_owned_socket(path: Path, expected: os.stat_result | None = None) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if (
        not stat.S_ISSOCK(info.st_mode)
        or info.st_uid != os.getuid()
        or (expected is not None and (info.st_dev, info.st_ino) != (expected.st_dev, expected.st_ino))
    ):
        raise IPCUnavailable()
    path.unlink()


def _remove_stale_socket(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
        raise IPCUnavailable()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.2)
        try:
            probe.connect(str(path))
        except OSError as exc:
            if exc.errno != errno.ECONNREFUSED:
                raise IPCUnavailable() from exc
        else:
            raise IPCUnavailable()
    _remove_owned_socket(path, info)


class SessionServer:
    """A bounded threaded server; the dispatcher is never called on the caller's thread."""

    def __init__(
        self,
        owner: ProfileOwner,
        dispatch: Callable[[dict, float], object],
        *,
        timeout: float = TIMEOUT,
        on_close: Callable[[], None] | None = None,
    ):
        self._dispatch = dispatch
        self._on_close = None
        self._timeout = timeout
        self._clients = threading.BoundedSemaphore(MAX_CLIENTS)
        self._dispatches = threading.BoundedSemaphore(MAX_CLIENTS)
        self._stop = threading.Event()
        self._lock_fd = None
        self._socket = None
        self._socket_info = None
        self._registered = False
        try:
            self._lock_fd = owner.duplicate_lock()
            held = os.fstat(self._lock_fd)
            lock = (owner.control_dir / "owner.lock").lstat()
            if (held.st_dev, held.st_ino) != (lock.st_dev, lock.st_ino):
                raise IPCUnavailable()  # noqa: TRY301
            profile = owner.control_dir.parent
            self.path = _endpoint(profile, create=True)
            if self.path.stem != owner.endpoint_id:
                raise IPCUnavailable()  # noqa: TRY301
            with _ACTIVE_LOCK:
                if str(self.path) in _ACTIVE_ENDPOINTS:
                    raise IPCUnavailable()  # noqa: TRY301
                _ACTIVE_ENDPOINTS.add(str(self.path))
                self._registered = True
            _remove_stale_socket(self.path)
            self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._socket.bind(str(self.path))
            self._socket_info = self.path.lstat()
            os.chmod(self.path, 0o600)
            self._socket.listen(MAX_CLIENTS)
            self._socket.settimeout(0.1)
            self._thread = threading.Thread(target=self._serve, args=(self._socket,), daemon=True)
            self._thread.start()
            self._on_close = on_close
        except Exception as exc:
            self.close()
            raise IPCUnavailable() from exc

    def _serve(self, listener: socket.socket) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            if not self._clients.acquire(blocking=False):
                conn.close()
                continue
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn: socket.socket) -> None:
        deadline = time.monotonic() + self._timeout
        try:
            with conn:
                if _peer_uid(conn) != os.getuid():
                    return
                try:
                    request = _receive(conn, deadline)
                    problem = _validate(request)
                    if problem:
                        result = _error(problem)
                    elif isinstance(request, dict):
                        deadline = min(deadline, request.pop("deadline", deadline))
                        result = self._call(request, deadline)
                    else:
                        result = _error("invalid_request")
                except OverflowError:
                    result = _error("too_large")
                except TimeoutError:
                    result = _error("timeout")
                except (ValueError, UnicodeError, json.JSONDecodeError):
                    result = _error("invalid_request")
                _send(conn, result, max(deadline, time.monotonic() + 0.05))
        except (OSError, IPCUnavailable, ValueError, TimeoutError):
            pass
        finally:
            self._clients.release()

    def _call(self, request: dict, deadline: float) -> dict:
        if not self._dispatches.acquire(blocking=False):
            return _error("busy")
        done = threading.Event()
        result = []

        def run() -> None:
            try:
                result.append(_safe_response(self._dispatch(request, deadline), request))
            except Exception:
                result.append(_error("unavailable"))
            finally:
                self._dispatches.release()
                done.set()

        threading.Thread(target=run, daemon=True).start()
        if not done.wait(max(0.0, deadline - time.monotonic())):
            return _error("timeout")
        return result[0]

    def close(self) -> None:
        if self._on_close is not None:
            callback, self._on_close = self._on_close, None
            callback()
        self._stop.set()
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        thread = getattr(self, "_thread", None)
        if thread is not None:
            thread.join(timeout=1.0)
        try:
            if self._socket_info is not None:
                _remove_owned_socket(self.path, self._socket_info)
                self._socket_info = None
                with suppress(OSError):
                    self.path.parent.rmdir()
        finally:
            if self._registered:
                with _ACTIVE_LOCK:
                    _ACTIVE_ENDPOINTS.discard(str(self.path))
                self._registered = False
            if self._lock_fd is not None:
                os.close(self._lock_fd)
                self._lock_fd = None

    def __enter__(self) -> SessionServer:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def request(profile: Path, message: dict, *, timeout: float = TIMEOUT) -> dict:
    """Send a control request; failures and malformed replies have fixed error codes."""
    deadline = time.monotonic() + timeout
    try:
        path = _endpoint(profile, create=False)
        info = path.lstat()
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise IPCUnavailable()  # noqa: TRY301
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(max(0.001, deadline - time.monotonic()))
            conn.connect(str(path))
            if _peer_uid(conn) != os.getuid():
                raise IPCUnavailable()  # noqa: TRY301
            _send(conn, {**message, "deadline": deadline}, deadline)
            response = _receive(conn, deadline)
        if not isinstance(response, dict) or type(response.get("version")) is not int or response["version"] != 1:
            return _error("unavailable")
        if (
            isinstance(response, dict)
            and set(response) == {"version", "error"}
            and response["version"] == 1
            and response["error"] in _ERRORS
        ):
            return response
        if _validate(message) is not None:
            return _error("unavailable")
        return _safe_response(response, message)
    except (OSError, IPCUnavailable, ValueError, TypeError, OverflowError, TimeoutError):
        return _error("unavailable")
