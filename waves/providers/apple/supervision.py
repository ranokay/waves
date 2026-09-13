"""Apple session supervision: sidecar lifecycle, pacing and throttle recovery.

Spec section 3 governs this module. The wrapper-v2 sidecar is on demand:
search, browsing and link resolution never start it (they ride the
auto-scraped dev token alone). Waves starts it lazily on the first Apple
download that needs it, health-probes its HTTP API, and stops it after an
idle period, so an idle container runtime does not burn memory and battery.

Failure classes and what the user sees (presentations, never new queue
states): a runtime that is missing or dies mid-run holds Apple rows with one
clear message and resumes automatically when it returns; a license-exchange
429 shows THROTTLED with a visible resume countdown inside the normal
downloading state and resumes the same job in place; dev-token scraper
breakage keeps the honest "a Waves update is needed" words; session/cookies
expiry flips the status light to needs attention with a one-click re-login.

Nothing here touches Qt, so it is pure and unit-testable; the Qt
slots/signals that drive the queue rows live in
:mod:`waves.waves_ui.backend`.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

logger = logging.getLogger("waves.providers.apple.supervision")

# The held-not-failed verdicts are canonical in the engine (the sidecar's own
# errors subclass them there); this module re-exports them so callers read
# one hierarchy, never two same-named ones.
from waves.providers.apple.engine import AppleHeld, AppleWrapperDown  # noqa: E402

__all__ = [
    "AppleHeld",
    "AppleWrapperDown",
]

# Pins: config-first initial values (spec section 3).

# Proactive pacing: pause after N songs for N seconds, same shape as TIDAL's
# api_rate_limit_*. Initial values tuned to the undocumented 429 threshold.
PACING_BATCH_DEFAULT = 25
PACING_DELAY_DEFAULT = 30.0

# Idle sidecar stop: an idle runtime stops itself after this long without an
# Apple download needing it. Advanced-tunable via settings.
IDLE_TIMEOUT_DEFAULT = 300.0

# Reactive throttle backoff: honor Retry-After when present, else exponential
# backoff capped at a few minutes, then resume the same job in place. The job
# keeps retrying while throttled (automatic recovery is never a failure).
THROTTLE_BASE_SEC = 5.0
THROTTLE_CAP_SEC = 180.0

# How often a held job re-probes the runtime while it waits for it to return.
HELD_POLL_SEC = 5.0

# How many consecutive failed start attempts a held job tolerates before it
# stops waiting and hands the click to setup. One failure is a blip the next
# poll may heal; a runtime that will not come up on its own needs the wizard,
# and a row that holds forever cannot say so.
HELD_START_FAILURES = 2

# The supervised container's fixed name: one sidecar per install, so ensure
# and stop are idempotent across restarts and retries.
WRAPPER_CONTAINER_NAME = "waves-wrapper-v2"

# Inside the container the Rust supervisor owns HTTP :80 and raw decrypt
# TCP :10020 (compose.yaml). The host sides are the free high ports Waves
# picks at setup time and passes explicitly everywhere, never port 80.
WRAPPER_CONTAINER_HTTP_PORT = 80
WRAPPER_CONTAINER_DECRYPT_PORT = 10020

# The sidecar carries the Apple session, so its published ports must bind
# loopback only. Docker's empty HostIp means every interface.
_LOOPBACK_BIND = "127.0.0.1"
_LOOPBACK_HOSTS = {_LOOPBACK_BIND, "::1"}

# Where the guest's Apple session persists inside the container (compose.yaml
# volume shape). The host side lives under the managed runtime dir so the
# session survives container restarts and needs no re-login.
_WRAPPER_DATA_CONTAINER_PATH = "/app/rootfs/data/data/com.apple.android.music/files"


# User-facing words: one clear message, no wall of failures.


# The user-facing path every setup message names, so a held row or a failed
# runtime says where the repair lives instead of leaving the user to guess.
SETUP_PATH = "Settings, Providers, Apple Music"


def held_message(detail: str = "") -> str:
    """One clear held row reason. Stays under Queued with this reason.

    The words name the setup path, because a held row is the user's only clue
    when the runtime does not come back on its own.
    """
    base = f"Held: the Apple runtime is not running. Waiting for it to return; finish setup in {SETUP_PATH} if it does not."
    detail = str(detail or "").strip()
    return f"{base} {detail}".strip() if detail else base


def throttled_message(wait_sec: float) -> str:
    """A throttled row reason with its visible resume countdown."""
    try:
        secs = max(0, round(float(wait_sec)))
    except (TypeError, ValueError):
        secs = 0
    if secs <= 1:
        return "Throttled: Apple is rate-limiting. Retrying now."
    return f"Throttled: Apple is rate-limiting. Retrying in {secs}s."


def pacing_message(pause_sec: float, batch: int) -> str:
    """The proactive pause status line (a deliberate stall, not a fault)."""
    try:
        secs = float(pause_sec)
    except (TypeError, ValueError):
        secs = 0.0
    return f"Pausing Apple downloads for {secs:g}s after {int(batch)} songs."


# Proactive pacing, same shape as TIDAL's api_rate_limit_*.


def pacing_policy(batch, delay) -> tuple[int, float]:
    """Sanitized (batch, delay): either at zero means never pause.

    Best-effort like the other per-download settings reads: a value that
    cannot be read means no pause, never a download that will not start.
    """
    try:
        every = int(batch or 0)
    except (TypeError, ValueError):
        return 0, 0.0
    try:
        seconds = float(delay or 0.0)
    except (TypeError, ValueError):
        return 0, 0.0
    return max(0, every), max(0.0, seconds)


def pacing_due(track_index_1based: int, batch: int) -> bool:
    """Whether the 1-based track at this position opens a new pacing batch."""
    try:
        pos = int(track_index_1based)
        every = int(batch)
    except (TypeError, ValueError):
        return False
    return every > 0 and pos > 1 and (pos - 1) % every == 0


# Reactive throttle backoff: Retry-After wins, else exponential, capped.


def _retry_after_value(value) -> float | None:
    """A raw Retry-After value as seconds: numeric delay or RFC HTTP-date."""
    try:
        text = str(value).strip()
    except (TypeError, AttributeError):
        return None
    if not text:
        return None
    # A numeric delay (a list takes the first member); an HTTP-date carries
    # a comma too ("Wed, 09 Sep ..."), so the comma split applies to the
    # numeric probe only, never to the date parse below.
    try:
        secs = float(text.split(",")[0].strip())
    except (TypeError, ValueError):
        pass
    else:
        return secs if secs >= 0 else None
    # RFC 9110 allows an HTTP-date instead of a delay: wait until then.
    try:
        from email.utils import parsedate_to_datetime
    except ImportError:
        return None
    try:
        when = parsedate_to_datetime(text)
    except (TypeError, ValueError, OverflowError):
        return None
    try:
        import datetime

        now = datetime.datetime.now(datetime.UTC)
        moment = when if when.tzinfo is not None else when.replace(tzinfo=datetime.UTC)
        return max(0.0, (moment - now).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None


def _scan_header_items(headers):
    """A Retry-After value found by case-insensitive items scan, or None."""
    try:
        items = headers.items() if hasattr(headers, "items") else None
    except (TypeError, AttributeError):
        return None
    if items is None:
        return None
    try:
        for key, val in items:
            if str(key).lower() == "retry-after":
                return val
    except (TypeError, ValueError, AttributeError):
        return None
    return None


def _get_header_keys(headers):
    """A Retry-After value found by exact .get lookup, or None."""
    if not hasattr(headers, "get"):
        return None
    try:
        for key in ("Retry-After", "retry-after", "RETRY_AFTER"):
            value = headers.get(key)
            if value is not None:
                return value
    except (TypeError, AttributeError):
        return None
    return None


def _headers_retry_after(headers) -> float | None:
    """A Retry-After value off one headers mapping, or None.

    Scans case-insensitively: mappings with any key spelling (including
    mixed case) match, whether or not they offer .get.
    """
    found = _scan_header_items(headers)
    if found is None:
        found = _get_header_keys(headers)
    if found is None:
        return None
    return _retry_after_value(found)


def _attrs_retry_after(exc: BaseException) -> float | None:
    """A Retry-After value off exception attributes, or None."""
    for attr in ("retry_after", "retryAfter", "retry_after_sec"):
        try:
            value = getattr(exc, attr, None)
            if value is None:
                continue
            secs = float(str(value).strip())
            if secs >= 0:
                return secs
        except (TypeError, ValueError):
            continue
    return None


def _text_retry_after(exc: BaseException) -> float | None:
    """A Retry-After value off the exception message text, or None."""
    text = str(exc or "")
    for pattern in (
        r"retry-after\s*[:=]\s*(\d+(?:\.\d+)?)",
        r"retry\s+in\s+(\d+(?:\.\d+)?)\s*s",
        r"retry\s+after\s+(\d+(?:\.\d+)?)\s*s",
    ):
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                secs = float(match.group(1))
            except (TypeError, ValueError):
                continue
            if secs >= 0:
                return secs
    return None


def parse_retry_after(exc: BaseException) -> float | None:
    """A 429's Retry-After wait in seconds, or None when there is none.

    Gamdl surfaces license-exchange throttles as plain errors, so this reads
    every shape one can carry: a response/headers mapping, a retry_after
    attribute, and the message text itself ("Retry-After: 120",
    "retry in 30s"). Unreadable means the backoff decides.
    """
    headers_list: list = []
    resp = getattr(exc, "response", None)
    if getattr(resp, "headers", None) is not None:
        headers_list.append(resp.headers)
    for attr in ("headers", "header"):
        headers = getattr(exc, attr, None)
        if headers is not None:
            headers_list.append(headers)
    for headers in headers_list:
        found = _headers_retry_after(headers)
        if found is not None:
            return found
    found = _attrs_retry_after(exc)
    if found is not None:
        return found
    return _text_retry_after(exc)


def throttle_delay(attempt: int, retry_after: float | None = None) -> float:
    """How long to wait before retrying a throttled track, in seconds.

    A server-sent Retry-After is honored as given: the service knows its
    own window, and shortening it would retry too early. Without one,
    exponential backoff from 5s, doubling per attempt, capped at 180s.
    """
    try:
        wait = float(retry_after) if retry_after is not None else None
    except (TypeError, ValueError):
        wait = None
    if wait is not None and wait >= 0:
        return wait
    try:
        n = max(0, int(attempt))
    except (TypeError, ValueError):
        n = 0
    return min(THROTTLE_BASE_SEC * (2.0**n), THROTTLE_CAP_SEC)


def is_wrapper_down_error(exc: BaseException) -> bool:
    """Whether an Apple failure means the sidecar is down (held, not failed).

    The wrapper tier raises AppleWrapperDown directly; older callers and
    gamdl's own errors arrive as plain download errors whose words name the
    wrapper or its URL. Credentials (login needed) and integrity verdicts
    are not down: they have their own recovery paths.
    """
    from waves.providers.apple.engine import AppleCredentialsError, AppleIntegrityError

    if isinstance(exc, (AppleCredentialsError, AppleIntegrityError)):
        return False
    if isinstance(exc, AppleHeld):
        return True
    text = f"{type(exc).__name__}: {exc}".lower()
    return (
        "wrapper" in text
        and (
            "unreachable" in text
            or "refused" in text
            or "closed" in text
            or "down" in text
            or "not running" in text
            or "no such container" in text
            or "connection" in text
        )
    ) or ("all connection attempts failed" in text and "127.0.0.1" in text)


# Sidecar lifecycle: ensure lazily, probe, stop after idle.


def wrapper_data_host_dir(app_dir: str | Path) -> Path:
    """The host dir mounted into the guest for its persistent Apple session."""
    return Path(app_dir) / "apple-runtime" / "wrapper-data"


def health_url(port: int) -> str:
    """The wrapper HTTP API liveness probe for an explicitly picked port."""
    return f"http://127.0.0.1:{int(port)}/health"


def is_health_ok(payload) -> bool:
    """Whether a /health reply means the sidecar can serve downloads."""
    if not isinstance(payload, dict):
        return False
    status = str(payload.get("status") or "").strip().lower()
    if status and status not in ("ok", "healthy", "ready", "up"):
        return False
    runtime = payload.get("runtime")
    if isinstance(runtime, dict):
        ready = runtime.get("playback_ready")
        if ready is not None:
            return bool(ready)
    return status in ("ok", "healthy", "ready", "up") or "version" in payload or "runtime" in payload


def probe_health(port: int, http_get=None, timeout: int = 5) -> dict | None:
    """GET the wrapper /health endpoint, or None when it does not answer."""
    get = http_get
    if get is None:
        import requests

        def get(url: str, timeout: int = 5):
            return requests.get(url, timeout=timeout)

    try:
        resp = get(health_url(port), timeout=timeout)
    except Exception:
        return None
    try:
        if getattr(resp, "status_code", 200) != 200:
            return None
        payload = resp.json() if hasattr(resp, "json") else None
    except Exception:
        logger.debug("Wrapper health probe returned no JSON", exc_info=True)
        return None
    return payload if isinstance(payload, dict) else None


def container_run_args(
    *,
    image: str,
    http_port: int,
    decrypt_port: int = WRAPPER_CONTAINER_DECRYPT_PORT,
    data_dir: str | Path = "",
    name: str = WRAPPER_CONTAINER_NAME,
    binary: str = "docker",
) -> list[str]:
    """The `docker run` that starts the supervised sidecar.

    Maps the picked high HTTP port onto the container's :80 and the decrypt
    TCP port onto :10020, both bound to loopback (the sidecar carries the
    Apple session and is never reached from another machine), mounts the
    persistent session dir, and carries the chroot capabilities the compose
    file documents. Never port 80 on the host: the caller passes the
    explicitly picked high ports.
    """
    args = [
        str(binary),
        "run",
        "-d",
        "--name",
        str(name),
        "--restart",
        "unless-stopped",
        "--cap-add",
        "SYS_ADMIN",
        "--cap-add",
        "SYS_CHROOT",
        "--cap-add",
        "SYS_PTRACE",
        "--security-opt",
        "apparmor:unconfined",
        "-p",
        f"{_LOOPBACK_BIND}:{int(http_port)}:{WRAPPER_CONTAINER_HTTP_PORT}",
        "-p",
        f"{_LOOPBACK_BIND}:{int(decrypt_port)}:{WRAPPER_CONTAINER_DECRYPT_PORT}",
        "-v",
        f"{data_dir}:{_WRAPPER_DATA_CONTAINER_PATH}",
        "-e",
        f"WRAPPER_PORT={WRAPPER_CONTAINER_HTTP_PORT}",
        "-e",
        f"WRAPPER_DECRYPT_PORT={WRAPPER_CONTAINER_DECRYPT_PORT}",
        str(image),
    ]
    return args


def _port_number(value, default: int = 0) -> int:
    """A TCP port from an untyped value, or the default when unreadable."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def port_bindings_are_private(payload: str, http_port: int, decrypt_port: int) -> bool:
    """Whether a container's `HostConfig.PortBindings` is loopback-only.

    The payload is `docker inspect --format '{{json .HostConfig.PortBindings}}'`
    stdout. Both mappings must exist, point at the given host ports, and bind
    only loopback addresses; an unreadable, missing, extra or wildcard
    binding is not private.
    """
    try:
        bindings = json.loads(payload or "")
    except (TypeError, ValueError):
        return False
    if not isinstance(bindings, dict):
        return False
    wanted = {
        f"{WRAPPER_CONTAINER_HTTP_PORT}/tcp": int(http_port),
        f"{WRAPPER_CONTAINER_DECRYPT_PORT}/tcp": int(decrypt_port),
    }
    seen: set[str] = set()
    for key, entries in bindings.items():
        if key not in wanted:
            if isinstance(entries, list) and entries:
                return False
            continue
        if not isinstance(entries, list) or not entries:
            return False
        for entry in entries:
            if not isinstance(entry, dict):
                return False
            host = str(entry.get("HostIp") or "").strip()
            port = str(entry.get("HostPort") or "").strip()
            if host not in _LOOPBACK_HOSTS or port != str(wanted[key]):
                return False
        seen.add(key)
    return seen == set(wanted)


def container_start_args(name: str = WRAPPER_CONTAINER_NAME, binary: str = "docker") -> list[str]:
    """Restart an existing (stopped) sidecar container by name."""
    return [str(binary), "start", str(name)]


def container_stop_args(name: str = WRAPPER_CONTAINER_NAME, binary: str = "docker") -> list[str]:
    """Stop the supervised sidecar container by name (kept for restart)."""
    return [str(binary), "stop", str(name)]


def container_remove_args(name: str = WRAPPER_CONTAINER_NAME, binary: str = "docker") -> list[str]:
    """Remove the supervised sidecar container so a fresh one can take its ports."""
    return [str(binary), "rm", "-f", str(name)]


def container_states(ps_output: str) -> dict[str, str]:
    """A `docker ps -a --format {{.Names}} {{.State}}` listing as {name: state}."""
    states: dict[str, str] = {}
    for line in str(ps_output or "").splitlines():
        parts = line.strip().rsplit(None, 1)
        if len(parts) == 2 and parts[0]:
            states[parts[0]] = parts[1].strip().lower()
    return states


def container_exists(running_names: str, name: str = WRAPPER_CONTAINER_NAME) -> bool:
    """Whether a container listing names our sidecar (any state, either listing shape)."""
    wanted = str(name).strip()
    if not wanted:
        return False
    return any((line.strip().split(None, 1) or [""])[0] == wanted for line in str(running_names or "").splitlines())


class SidecarSupervisor:
    """Lazily start, health-probe and idle-stop the wrapper sidecar.

    Thin state around the pure helpers above so the bridge stays small:
    `note_activity()` on every Apple download that needs the wrapper,
    `should_stop()` when the idle timeout has passed with no activity and no
    Apple work queued or running. All subprocess and HTTP reaches are
    injectable for tests; production passes the container binary the setup
    wizard detected.
    """

    def __init__(
        self,
        *,
        manager=None,
        runner=None,
        http_get=None,
        monotonic=None,
        container: str = WRAPPER_CONTAINER_NAME,
        binary: str = "docker",
    ) -> None:
        self._manager = manager
        self._runner = runner
        self._http_get = http_get
        self._monotonic = monotonic or time.monotonic
        self._container = str(container or WRAPPER_CONTAINER_NAME)
        self._binary = str(binary or "docker")
        # None until the first noted wrapper activity: a monotonic clock can
        # legitimately read 0.0, so 0.0 must not mean "never noted".
        self._last_activity: float | None = None

    def note_activity(self) -> float:
        """Record Apple wrapper work; returns the stamp."""
        self._last_activity = float(self._monotonic())
        return self._last_activity

    def idle_seconds(self) -> float:
        """Seconds since the last noted wrapper activity (0 when never)."""
        if self._last_activity is None:
            return 0.0
        return max(0.0, float(self._monotonic()) - self._last_activity)

    def should_stop(self, idle_timeout: float, *, apple_busy: bool = False) -> bool:
        """Whether the idle sidecar should stop itself."""
        try:
            limit = float(idle_timeout)
        except (TypeError, ValueError):
            return False
        if limit <= 0 or apple_busy or self._last_activity is None:
            return False
        return self.idle_seconds() >= limit

    def health(self, port: int) -> dict | None:
        """The sidecar's /health reply, or None when it does not answer."""
        try:
            return probe_health(int(port), http_get=self._http_get)
        except (TypeError, ValueError):
            return None

    def is_ready(self, port: int) -> bool:
        """Whether the sidecar answers healthy on this HTTP port."""
        try:
            payload = self.health(int(port))
        except Exception:
            return False
        return payload is not None and is_health_ok(payload)

    def _run(self, args: list[str], timeout: int = 60):
        import subprocess

        run = self._runner or (lambda *a, **k: subprocess.run(*a, **k))
        return run(args, capture_output=True, text=True, timeout=timeout)

    def _resolve_image(self, image: str) -> str:
        """The sidecar image to run: explicit, else the pinned managed one."""
        img = str(image or "").strip()
        if img or self._manager is None:
            return img
        try:
            from waves.providers.apple.runtime import WRAPPER_V2_IMAGE
        except Exception:
            return ""
        else:
            return WRAPPER_V2_IMAGE

    def _resolve_data_dir(self, data_dir: str | Path) -> str:
        """The host session dir to mount, or "" when it cannot be made."""
        host_data = str(data_dir or "").strip()
        if not host_data and self._manager is not None:
            try:
                app_dir = getattr(self._manager, "app_dir", "")
                host_data = str(wrapper_data_host_dir(app_dir)) if app_dir else ""
            except Exception:
                host_data = ""
        if not host_data:
            return ""
        try:
            Path(host_data).mkdir(parents=True, exist_ok=True)
        except Exception:
            logger.debug("Could not create the wrapper session dir", exc_info=True)
            return ""
        return host_data

    def _container_state(self) -> str:
        """Our sidecar's state ("running", "exited", ...) or "" when absent."""
        try:
            proc = self._run(
                [self._binary, "ps", "-a", "--format", "{{.Names}} {{.State}}"],
                timeout=15,
            )
        except Exception:
            logger.debug("Wrapper container list failed", exc_info=True)
            return ""
        if getattr(proc, "returncode", 1) != 0:
            return ""
        return container_states(getattr(proc, "stdout", "") or "").get(self._container, "")

    def _have_container(self) -> bool:
        """Whether a sidecar container exists to restart by name (any state)."""
        return bool(self._container_state())

    def _container_bindings_private(self, http_port: int, decrypt_port: int) -> bool:
        """Whether the existing sidecar publishes both ports on loopback only."""
        try:
            proc = self._run(
                [
                    self._binary,
                    "inspect",
                    "--format",
                    "{{json .HostConfig.PortBindings}}",
                    self._container,
                ],
                timeout=15,
            )
        except Exception:
            logger.debug("Wrapper port bindings could not be read", exc_info=True)
            return False
        if getattr(proc, "returncode", 1) != 0:
            return False
        return port_bindings_are_private(getattr(proc, "stdout", "") or "", http_port, decrypt_port)

    def _run_fresh(self, *, image: str, port: int, decrypt_port: int, host_data: str, start_timeout: int) -> None:
        """Run a fresh sidecar from the image with the current port mapping."""
        try:
            proc = self._run(
                container_run_args(
                    image=image,
                    http_port=port,
                    decrypt_port=int(decrypt_port or WRAPPER_CONTAINER_DECRYPT_PORT),
                    data_dir=host_data,
                    name=self._container,
                    binary=self._binary,
                ),
                timeout=start_timeout,
            )
        except Exception:
            logger.debug("Wrapper sidecar start failed", exc_info=True)
            return
        if getattr(proc, "returncode", 1) != 0:
            logger.warning(
                "Wrapper sidecar would not start: %s",
                ((getattr(proc, "stderr", "") or getattr(proc, "stdout", "")) or "").strip()
                or "container runtime refused",
            )

    def _remove_container(self) -> bool:
        """Remove the named sidecar so a fresh one can take its ports."""
        try:
            proc = self._run(container_remove_args(self._container, self._binary), timeout=60)
        except Exception:
            logger.debug("Wrapper sidecar remove failed", exc_info=True)
            return False
        return bool(getattr(proc, "returncode", 1) == 0)

    def _start_container(
        self, *, state: str, image: str, port: int, decrypt_port: int, host_data: str, start_timeout: int
    ) -> None:
        """Restart a stopped container, else run a fresh one from the image.

        A running-but-unhealthy container is never "started" (a no-op that
        would leave the rows held): it is removed and recreated with the
        current port mapping, which also heals a stale `-p` mapping after
        the wrapper port setting changed.
        """
        if state and state != "running":
            try:
                proc = self._run(container_start_args(self._container, self._binary), timeout=60)
            except Exception:
                logger.debug("Wrapper sidecar start failed", exc_info=True)
                return
            if getattr(proc, "returncode", 1) != 0:
                logger.warning(
                    "Wrapper sidecar would not start: %s",
                    ((getattr(proc, "stderr", "") or getattr(proc, "stdout", "")) or "").strip()
                    or "container runtime refused",
                )
            return
        if state == "running":
            self._remove_container()
        self._run_fresh(
            image=image, port=port, decrypt_port=decrypt_port, host_data=host_data, start_timeout=start_timeout
        )

    def ensure_started(
        self,
        *,
        http_port: int,
        image: str = "",
        data_dir: str | Path = "",
        decrypt_port: int = WRAPPER_CONTAINER_DECRYPT_PORT,
        start_timeout: int = 120,
    ) -> bool:
        """Start the sidecar when its health probe does not answer.

        Restarts a stopped container by name; a running-but-unhealthy one
        (or a stale port mapping) is recreated from the pinned image with
        the session volume mounted, then probed again. Returns True when
        the probe answers afterwards. Never pulls or provisions: the runtime
        is the setup wizard's artifact.
        """
        port = _port_number(http_port)
        if port <= 0:
            return False
        host_decrypt = _port_number(decrypt_port or WRAPPER_CONTAINER_DECRYPT_PORT, WRAPPER_CONTAINER_DECRYPT_PORT)
        # A sidecar whose published bindings are not loopback-private (an
        # older container or a stale mapping) is removed so the run below
        # rebinds both mappings to loopback. The session lives in the host
        # data dir, so recreation preserves it. A removal that fails holds the
        # row instead of trusting the exposed container's health.
        state = self._container_state()
        migrated = False
        if state and not self._container_bindings_private(port, host_decrypt):
            if not self._remove_container():
                return False
            state = ""
            migrated = True
        if not migrated and self.is_ready(port):
            self.note_activity()
            return True
        img = self._resolve_image(image)
        if not img:
            return False
        host_data = self._resolve_data_dir(data_dir)
        if not host_data:
            return False
        # Either way the probe afterwards decides, never the exit code alone.
        self._start_container(
            state=state,
            image=img,
            port=port,
            decrypt_port=host_decrypt,
            host_data=host_data,
            start_timeout=start_timeout,
        )
        if self.is_ready(port):
            self.note_activity()
            return True
        if state == "running":
            # Already recreated once above with the current mapping; probing
            # again decides, never a third churn in one pass.
            return False
        # A start that left no healthy probe heals one way: recreate from
        # the image with the current mapping and probe once more.
        self._remove_container()
        self._run_fresh(
            image=img, port=port, decrypt_port=host_decrypt, host_data=host_data, start_timeout=start_timeout
        )
        ready = self.is_ready(port)
        if ready:
            self.note_activity()
        return ready

    def stop(self, timeout: int = 60) -> bool:
        """Stop the idle sidecar (kept by name for the next lazy start)."""
        try:
            proc = self._run(container_stop_args(self._container, self._binary), timeout=timeout)
        except Exception:
            logger.debug("Wrapper sidecar stop failed", exc_info=True)
            return False
        return bool(getattr(proc, "returncode", 1) == 0)
