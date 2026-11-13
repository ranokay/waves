"""Queue local session controls onto the bridge's Qt thread."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Qt, Signal, Slot

from waves.providers.apple.engine import AppleCredential


@dataclass(eq=False)
class _Request:
    message: dict
    deadline: float
    generation: int
    done: threading.Event = field(default_factory=threading.Event)
    result: dict = field(default_factory=dict)


def _response(state: str, action: str = "none", *, catalog: str = "unknown", runtime: str = "unknown") -> dict:
    return {
        "state": state,
        "action": action,
        "facts": {
            "catalog": catalog,
            "runtime": runtime,
            "identity": "unknown",
            "storefront": "unknown",
            "delivery": "unknown",
        },
    }


def _tidal_snapshot(bridge) -> dict:
    active = getattr(bridge, "_provider_login_attempts", {}).get("tidal")
    if active is not None:
        if active.resume:
            return _response("checking")
        return _response("authenticating", "none" if active.submitted else "open_waves")
    if getattr(bridge, "_logged_in", False):
        return _response("authenticated")
    if not getattr(bridge, "_session_resolved", False):
        return _response("checking")
    if "tidal" in getattr(bridge, "_provider_cleanup_events", {}):
        return _response("signed_out", "connect_provider")
    # A failed startup resume includes offline failures, so it is not proof of
    # deliberate sign-out or credential rejection.
    return _response("unavailable_unknown", "open_waves")


def _apple_cookies_state(bridge) -> bool | None:
    """Read worker-verified cookies evidence without touching its file."""
    data = getattr(getattr(bridge, "settings", None), "data", None)
    path = str(getattr(data, "apple_cookies_path", "") or "")
    if not path:
        return False
    if (
        getattr(bridge, "_apple_session_expired", False)
        and getattr(bridge, "_apple_session_credential", "") != AppleCredential.WRAPPER
    ):
        return False
    provider = (getattr(bridge, "providers", None) or {}).get("apple")
    if str(getattr(provider, "cookies_path", "") or "") != path:
        return None
    cache = getattr(bridge, "_apple_engine_facts_cache", None)
    contexts = getattr(bridge, "_provider_contexts", None)
    if not isinstance(cache, tuple) or len(cache) < 7 or contexts is None:
        return None
    token, when, facts, _, generation, revision, evidence = cache[:7]
    age = time.time() - when
    if not contexts.current(token) or generation != getattr(bridge, "_apple_engine_facts_gen", 0) or not 0 <= age < 30:
        return None
    sessions = getattr(bridge, "_apple_runtime_sessions", None)
    if sessions is not None and sessions.revision("apple:wrapper-v2")[0] != revision[0]:
        return None
    if not isinstance(evidence, tuple) or len(evidence) != 3 or evidence[0] != path:
        return None
    _, fingerprint, expires = evidence
    if not fingerprint or getattr(facts, "cookies_ready", None) is not True:
        return False
    return not expires or time.time() < expires


def _apple_snapshot(bridge) -> dict:
    data = getattr(getattr(bridge, "settings", None), "data", None)
    if not bool(getattr(data, "apple_enabled", False)):
        return _response("unavailable_unknown", "enable_provider", catalog="not_ready")
    if getattr(bridge, "_apple_signout_inflight", False):
        return _response("checking")
    sessions = getattr(bridge, "_apple_runtime_sessions", None)
    cookies = _apple_cookies_state(bridge)
    stopped = sessions is not None and sessions.choices_restored and sessions.is_stopped("apple:wrapper-v2")
    if cookies is True:
        return _response("authenticated", runtime="not_ready" if stopped else "unknown")
    wrapper = _apple_wrapper_snapshot(bridge, sessions, stopped)
    if cookies is None and wrapper["state"] != "authenticated":
        return _response("checking", runtime=wrapper["facts"]["runtime"])
    return wrapper


def _apple_wrapper_snapshot(bridge, sessions, stopped: bool) -> dict:
    if sessions is not None:
        if not sessions.choices_restored:
            return _response("checking")
        if stopped:
            return _response("unavailable_unknown", "start_runtime", runtime="not_ready")
    if (
        getattr(bridge, "_apple_session_expired", False)
        and getattr(bridge, "_apple_session_credential", "") != AppleCredential.COOKIES
    ):
        return _response("expired_rejected", "connect_provider")
    if getattr(bridge, "_apple_wrapper_login_inflight", False):
        return _response("authenticating")
    if (getattr(bridge, "_apple_wrapper_login_result", None) or {}).get("needs_2fa"):
        return _response("awaiting_verification", "complete_verification")
    return _apple_cached_auth(getattr(bridge, "_apple_wrapper_auth_cache", None) or {})


def _apple_cached_auth(auth_cache: dict) -> dict:
    auth = auth_cache.get("result")
    if not isinstance(auth, dict):
        return _response("checking")
    if time.time() - float(auth_cache.get("at") or 0) > 30:
        return _response("unavailable_unknown", "open_waves")
    if auth.get("reachable") is not True:
        return _response("unavailable_unknown", "open_waves")
    state = auth.get("state")
    if state == "authenticated" and auth.get("logged_in") is True:
        return _response("authenticated")
    if state == "awaiting_2fa":
        return _response("awaiting_verification", "complete_verification")
    if state == "logged_out":
        return _response("signed_out", "connect_provider")
    return _response("unavailable_unknown", "open_waves")


class SessionDispatcher(QObject):
    """Dispatch off-thread requests through the owner thread's event loop.

    Pass ``dispatch`` to SessionServer and ``close`` as its ``on_close``.
    Close the adapter before releasing the session owner.
    """

    _queued = Signal(object)

    def __init__(self, bridge, activate: Callable[[], None]) -> None:
        super().__init__()
        self._bridge = bridge
        self._activate = activate
        self._lock = threading.RLock()
        self._closed = False
        self._generation = 0
        self._pending: set[_Request] = set()
        self._apple_refresh_key = None
        self._apple_refresh_started = 0.0
        self._queued.connect(self._apply, Qt.ConnectionType.QueuedConnection)

    def dispatch(self, message: dict, deadline: float) -> dict:
        with self._lock:
            if self._closed or time.monotonic() >= deadline:
                return {}
            job = _Request(message, deadline, self._generation)
            self._pending.add(job)
            self._queued.emit(job)
        job.done.wait(max(0.0, deadline - time.monotonic()))
        with self._lock:
            self._pending.discard(job)
            if not job.done.is_set() or self._closed or job.generation != self._generation:
                return {}
            return job.result

    def _current(self, job: _Request) -> bool:
        return (
            not self._closed
            and job in self._pending
            and job.generation == self._generation
            and time.monotonic() < job.deadline
        )

    @Slot(object)
    def _apply(self, job: _Request) -> None:
        with self._lock:
            try:
                if not self._current(job):
                    return
                op = job.message["op"]
                if op == "activate":
                    if self._current(job):
                        self._activate()
                        job.result = {"result": "activated"}
                    return
                provider = job.message["provider"]
                result = _tidal_snapshot(self._bridge) if provider == "tidal" else _apple_snapshot(self._bridge)
                if op == "ensure" and self._current(job):
                    result = self._ensure(job, provider, result)
                if result["action"] != "none" and op == "ensure" and self._current(job):
                    self._activate()
                    if self._current(job):
                        if provider == "tidal":
                            self._bridge.signInRequested.emit(provider)
                        else:
                            self._bridge.appleSetupRequested.emit("setup")
                if self._current(job):
                    job.result = result
            except Exception:
                job.result = {}
            finally:
                job.done.set()

    def _ensure(self, job: _Request, provider: str, result: dict) -> dict:  # noqa: C901 - explicit lifecycle guards
        bridge = self._bridge
        if provider == "tidal":
            if result["state"] != "unavailable_unknown":
                return result
            if "tidal" in getattr(bridge, "_provider_cleanup_events", {}):
                return result
            provider_obj = getattr(bridge, "providers", {}).get("tidal")
            eligible = getattr(provider_obj, "has_resumable_session", None)
            resume = getattr(bridge, "_try_token_login", None)
            if callable(eligible) and eligible() and callable(resume) and self._current(job):
                resume()
                return _response("checking")
            return result

        data = getattr(getattr(bridge, "settings", None), "data", None)
        if (
            bool(getattr(data, "apple_enabled", False))
            and str(getattr(data, "apple_cookies_path", "") or "")
            and _apple_cookies_state(bridge) is None
            and result["state"] != "authenticated"
            and not getattr(bridge, "_apple_signout_inflight", False)
        ):
            refresh = getattr(bridge, "_apple_engine_details", None)
            pool = getattr(getattr(bridge, "threadpool", None), "start", None)
            if callable(refresh) and callable(pool) and self._current(job):
                refresh()
                return _response("checking", runtime=result["facts"]["runtime"])

        if result["state"] not in {"checking", "unavailable_unknown"} or result["action"] in {
            "enable_provider",
            "start_runtime",
        }:
            return result
        sessions = getattr(bridge, "_apple_runtime_sessions", None)
        if sessions is not None and (not sessions.choices_restored or sessions.is_stopped("apple:wrapper-v2")):
            return result
        if getattr(bridge, "_apple_signout_inflight", False) or getattr(bridge, "_apple_wrapper_login_inflight", False):
            return result
        cache = getattr(bridge, "_apple_wrapper_auth_cache", None)
        if (
            isinstance(cache, dict)
            and isinstance(cache.get("result"), dict)
            and time.time() - float(cache.get("at") or 0) <= 30
        ):
            return result
        schedule = getattr(bridge, "_schedule_apple_wrapper_auth_refresh", None)
        if not callable(schedule):
            return result
        key = (id(cache), (cache or {}).get("at"))
        if key == self._apple_refresh_key and time.monotonic() - self._apple_refresh_started < 10:
            return _response("checking")
        if self._current(job) and schedule():
            self._apple_refresh_key = key
            self._apple_refresh_started = time.monotonic()
            return _response("checking")
        return result

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._generation += 1
            for job in self._pending:
                job.done.set()
