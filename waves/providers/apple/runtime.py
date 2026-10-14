"""Managed Apple runtime for Waves (spec section 2 and 10).

The full Apple tier needs two provisioned pieces Waves owns end to end,
FFmpeg-manager style: the N_m3u8DL-RE fetch binary (pinned release,
downloaded as tar.gz or zip per platform, checksum-verified, extracted,
chmod'd) and the wrapper-v2 container image (Waves-built, pinned) running
on a free high port. The image carries the guest libraries, so no APK is
provisioned or supplied at runtime; image publishing owns that step.

The cookies-only fallback tier needs none of this: a Netscape cookies
export from a logged-in music.apple.com session unlocks AAC 256 and
Atmos straight away and is verified here too.

Nothing here touches Qt, so it is pure and unit-testable; the Qt
slots/signals that drive the Settings UI live in
:mod:`waves.desktop.backend`.

Config isolation: Waves owns its engine configuration surface entirely.
This module never reads, inherits, or mutates a user-visible
``~/.gamdl/config.ini``. Everything the engine needs travels as explicit
arguments (cookies path, binary paths, wrapper URL); the only directory
this module writes is its own managed area under the app config dir plus
an isolated engine config dir inside it for any file the engine insists
on materialising. Tests pin that no Apple path references the user home.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import platform
import shutil
import socket
import stat
import subprocess
import tarfile
import tempfile
import time
from collections.abc import Generator
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Event, Lock, local

import requests

from waves.file_integrity import sha256_file
from waves.providers.apple import child_guard

logger = logging.getLogger("waves.providers.apple.runtime")

_HTTP_TIMEOUT = 30
_IO_CHUNK = 1 << 16  # 64 KiB streaming chunks
_UA = "Waves-apple-runtime"

# Pins: config-first initial values; engine bumps ride Waves' updater (spec 10.4).

# Waves-built wrapper-v2 image, pinned. Waves builds from source (Unlicense)
# and never vendors the image into its own package (spec 10.1); the setup
# flow pulls this exact tag. The digest is the registry manifest the runbook
# documents; ensure_image checks it when the runtime can report one, so a
# retagged or mutated registry copy is refused.
WRAPPER_V2_IMAGE = "ghcr.io/ranokay/waves-wrapper-v2:0.2.4"
WRAPPER_V2_IMAGE_DIGEST = "sha256:79a36375a3555ca9e4aa6a9d1ccffbf0ac45a1604d19d307761c6d6ba29b428b"
# The (image, digest, guest libs) pins this build approves for rollback. A
# stored receipt verifies only by naming one, since app data cannot approve
# itself; the libs entry decides its compatibility. A pin bump appends the
# new pin and keeps the previous ones.
APPROVED_WRAPPER_V2_IMAGES: tuple[tuple[str, str, str], ...] = (
    (
        "ghcr.io/ranokay/waves-wrapper-v2:0.2.4",
        "sha256:79a36375a3555ca9e4aa6a9d1ccffbf0ac45a1604d19d307761c6d6ba29b428b",
        "17.0.0",
    ),
)
# The wrapper's guest-lib set this image was built against, mirrored from
# wrapper-v2's LIBS_VERSION.json. Surfaced in the wizard's image detail and
# in the custom-build extraction plan, so an image and an APK can never
# silently disagree.
WRAPPER_LIBS_VERSION = "17.0.0"
# The N_m3u8DL-RE release the managed install provisions: the latest
# published upstream tag at pin time. Pinned so every machine fetches the
# same bytes; bumps ship through Waves' normal update channel with
# provenance recorded in the manifest. Re-pin by updating the asset names
# and the SHA-256 table below from the release page in the same commit.
NM3U8DLRE_VERSION = "v0.6.0-beta"
_NM3U8DLRE_BASE = "https://github.com/nilaoda/N_m3u8DL-RE/releases/download/v0.6.0-beta"
NM3U8DLRE_RELEASES = {
    # Exact published asset names per (os_key, arch). macOS/Linux ship
    # .tar.gz holding one root-level binary; Windows ships .zip holding one
    # root-level .exe. Tests inject their own Release so no test ever
    # touches the network.
    ("macos", "arm64"): f"{_NM3U8DLRE_BASE}/N_m3u8DL-RE_v0.6.0-beta_osx-arm64_20260629.tar.gz",
    ("macos", "amd64"): f"{_NM3U8DLRE_BASE}/N_m3u8DL-RE_v0.6.0-beta_osx-x64_20260629.tar.gz",
    ("linux", "amd64"): f"{_NM3U8DLRE_BASE}/N_m3u8DL-RE_v0.6.0-beta_linux-x64_20260629.tar.gz",
    ("linux", "arm64"): f"{_NM3U8DLRE_BASE}/N_m3u8DL-RE_v0.6.0-beta_linux-arm64_20260629.tar.gz",
    ("windows", "amd64"): f"{_NM3U8DLRE_BASE}/N_m3u8DL-RE_v0.6.0-beta_win-x64_20260629.zip",
    ("windows", "arm64"): f"{_NM3U8DLRE_BASE}/N_m3u8DL-RE_v0.6.0-beta_win-arm64_20260629.zip",
}
# SHA-256 of each pinned asset above, taken from the upstream release
# binaries at pin time and reviewed into git here. The release
# publishes no checksum sidecars, so these inline pins ARE the
# verification: the install refuses to proceed without a matching entry
# (fail-closed), and a bump re-pins the table. Trust note (same limit as
# the FFmpeg manager's same-origin sidecar): the pins prove the bytes match
# what upstream served at pin time, reviewed in the bump commit — not an
# independent audit of upstream.
NM3U8DLRE_SHA256 = {
    ("macos", "arm64"): "ca181b7e8976564766c34e3cefe48fff409f58289ca970ade062668c01c53918",
    ("macos", "amd64"): "4dab8d256ae3164557f48a3326c8fa60da99e37536ee1589ce6c841180fa8204",
    ("linux", "amd64"): "2ebcd450594a08c0de0bcd502a80c5d3f89a702a0fa6604199527bb8d6eee4db",
    ("linux", "arm64"): "17f3c2c2372cbb859bf42e77bf59f7a049e5642fc4f6d234195e70bbea178299",
    ("windows", "amd64"): "3825fd42ee502f98a9378f6fdddb2f7822709f521806214f466db6935c950f1a",
    ("windows", "arm64"): "3a13527812a5f18b9981b3cd6f7f36bd17cd7d76b5f3273281a58354e5fcebd6",
}
# The APK version the published wrapper image is built from. 3.6.0-beta
# (build 1109) is the proven combo: its native libs carry DT_HASH, export
# the symbols the wrapper resolves, and need nothing newer than the chroot's
# libc. (4.7.0 fails all three: GNU-hash-only main lib, hidden make_shared,
# API-23+ imports.) Image publishing owns fetching and extraction; the pin
# test checks the workflow inputs and the runbook against this constant.
APK_PINNED_VERSION = "3.6.0-beta"

# Wrapper HTTP API: never port 80 on a desktop (collision-prone). The
# manager picks a free high port and passes it explicitly everywhere.
WRAPPER_PORT_LOW = 49152
WRAPPER_PORT_HIGH = 65535


class AppleRuntimeUnsupportedPlatform(Exception):
    """Raised when the current OS/arch has no pinned N_m3u8DL-RE asset."""


class AppleRuntimeCancelled(Exception):
    """Raised when a provision is aborted via its :class:`~threading.Event`."""


class AppleRuntimeBusy(Exception):
    """An active tool lease or another maintenance action prevents mutation."""


def _check_runtime_abort(abort: Event | None) -> None:
    if abort is not None and abort.is_set():
        raise AppleRuntimeCancelled()


@dataclass(frozen=True)
class Nm3u8dlreRelease:
    """A pinned N_m3u8DL-RE build to provision."""

    version: str
    url: str
    sha256_url: str | None = None
    sha256: str | None = None


def target() -> tuple[str, str]:
    """Return ``(os_key, arch_key)`` for the running machine."""
    system = platform.system()
    machine = platform.machine().lower()
    is_arm = "arm" in machine or "aarch64" in machine
    arch = "arm64" if is_arm else "amd64"
    if system == "Darwin":
        return "macos", arch
    if system == "Linux":
        return "linux", arch
    if system == "Windows":
        return "windows", arch
    raise AppleRuntimeUnsupportedPlatform(f"No Apple runtime asset for {system}/{machine}")


def _safe_target() -> tuple[str, str]:
    try:
        return target()
    except AppleRuntimeUnsupportedPlatform:
        return "", ""


def _exe_name(os_key: str) -> str:
    return "N_m3u8DL-RE.exe" if os_key == "windows" else "N_m3u8DL-RE"


def pinned_release(os_key: str = "", arch: str = "") -> Nm3u8dlreRelease | None:
    """The pinned N_m3u8DL-RE release for this (or the given) platform.

    Carries the exact published asset URL plus its inline pinned SHA-256
    (the release publishes no checksum sidecars). None when the platform
    has no pinned asset.
    """
    if not os_key or not arch:
        os_key, arch = _safe_target()
    url = NM3U8DLRE_RELEASES.get((os_key, arch))
    if not url:
        return None
    return Nm3u8dlreRelease(
        version=NM3U8DLRE_VERSION,
        url=url,
        sha256_url=None,
        sha256=NM3U8DLRE_SHA256.get((os_key, arch)),
    )


def _session() -> requests.Session:
    sess = requests.Session()
    sess.headers["User-Agent"] = _UA
    return sess


# Container runtime: detect, gentle-start, never install.


def detect_container_runtime(runner=None, timeout: int = 10) -> dict:
    """Detect the container runtime the full tier needs.

    Returns ``{"name", "available", "running", "hint"}``. ``available``
    means a runtime binary exists; ``running`` means its daemon answers.
    Docker is probed first, then a Docker-compatible fallback (Podman);
    a stopped first candidate never hides a running second one. Waves
    never silently installs one: when absent the hint guides the user to
    install Docker themselves.

    ``runner`` is an injectable ``subprocess.run`` for tests; ``timeout``
    bounds each probe (the GUI thread uses a short one via the bridge's
    cached wrapper, workers use the full one).
    """
    run = runner or (lambda *a, **k: subprocess.run(*a, **k))
    degraded: dict | None = None
    for name, probe in (("docker", ["docker", "info"]), ("podman", ["podman", "info"])):
        try:
            proc = run(probe, capture_output=True, text=True, timeout=timeout, **child_guard.NO_WINDOW)
        except FileNotFoundError:
            continue
        except Exception:
            logger.debug("Container probe for %s failed", name, exc_info=True)
            continue
        if proc.returncode == 0:
            return {"name": name, "available": True, "running": True, "hint": ""}
        # Binary exists but the daemon is not answering. Keep looking: a
        # stopped Docker must not hide a running Podman.
        if degraded is None:
            started = "Docker Desktop" if name == "docker" else "Podman"
            degraded = {
                "name": name,
                "available": True,
                "running": False,
                "hint": f"Start {started}, then continue setup.",
            }
    if degraded is not None:
        return degraded
    return {
        "name": "",
        "available": False,
        "running": False,
        "hint": (
            "Install Docker Desktop for your platform, start it, then continue setup. Waves never installs it for you."
        ),
    }


def gentle_start_command(name: str = "docker") -> list[str] | None:
    """The gentle start attempt for an idle container runtime, if any.

    macOS only: ``open -a`` wakes the desktop app without installing
    anything (Docker Desktop, or Podman Desktop for a Podman runtime).
    Other platforms return None: the wizard guides instead.
    """
    if platform.system() != "Darwin":
        return None
    app = "Podman Desktop" if name == "podman" else "Docker"
    return ["open", "-a", app]


def attempt_gentle_start(runner=None, name: str = "docker") -> bool:
    """Try the gentle start for the detected runtime; True when it launched.

    Returns False when there is no gentle start for this platform/runtime
    or the launch itself failed, so the caller falls back to the manual
    guidance instead of claiming an attempt.
    """
    cmd = gentle_start_command(name)
    if not cmd:
        return False
    run = runner or (lambda *a, **k: subprocess.run(*a, **k))
    try:
        proc = run(cmd, capture_output=True, timeout=30, **child_guard.NO_WINDOW)
    except Exception:
        logger.debug("Gentle container start failed", exc_info=True)
        return False
    else:
        return proc.returncode == 0


# Free high port (never port 80).


def pick_free_high_port(low: int = WRAPPER_PORT_LOW, high: int = WRAPPER_PORT_HIGH) -> int:
    """Pick a free TCP port on loopback in the high range (never port 80).

    Binds each candidate to prove it is free, then releases it. The small
    TOCTOU window (another process grabbing it before the wrapper starts)
    is closed by the caller retrying on EADDRINUSE; this only picks the
    first offer. Raises OSError when the whole high range is taken.
    """
    for port in range(low, high + 1):
        with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            try:
                # Bind exactly as the consumer will: loopback, no SO_REUSEADDR.
                # BSD lets a reusing specific-address bind succeed while
                # another process listens on the wildcard address (macOS
                # Continuity holds *:49152), which would hand out an occupied
                # port; a plain bind fails there.
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise OSError("no free high port available")


def wrapper_url(port: int) -> str:
    """The wrapper HTTP API URL for an explicitly picked port."""
    return f"http://127.0.0.1:{int(port)}"


# Wrapper guest account: /me state plus the one-time login + 2FA handshake.


def _wrapper_error(exc: Exception) -> str:
    """One readable line off a wrapper request failure."""
    text = str(exc or "").strip()
    return text or type(exc).__name__


def _wrapper_status_error(response, fallback: str) -> str:
    """A failure line off a non-OK wrapper reply, with its status."""
    try:
        detail = str(response.text or "").strip()
    except Exception:
        detail = ""
    status = getattr(response, "status_code", "")
    if detail:
        detail = detail[:200]
        return f"{fallback} ({status}: {detail})" if status else f"{fallback} ({detail})"
    return f"{fallback} ({status})" if status else fallback


def _wrapper_account_label(payload: dict, auth: dict) -> str:
    """A human account label off a /me reply, or "".

    The live guest names an authenticated account under ``apple_id`` /
    ``username`` inside ``auth``; other wrapper builds may use an
    ``account`` block or a top-level email. First non-empty wins.
    """
    for candidate in (
        payload.get("account"),
        auth.get("account"),
        auth.get("apple_id"),
        payload.get("email"),
        auth.get("username"),
        payload.get("username"),
    ):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
        if isinstance(candidate, dict):
            for key in ("email", "name", "displayName"):
                value = candidate.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return ""


def _wrapper_context_fields(payload: dict, auth: dict) -> dict[str, str]:
    """Read explicit machine identity fields, never a display/login label.

    Conflicting identifiers or storefronts stay unknown. No value is inferred
    from cookies, the catalog client's default, or an Apple ID email address.
    """
    accounts = tuple(value for value in (payload.get("account"), auth.get("account")) if isinstance(value, dict))
    identities: set[str] = set()
    storefronts: set[str] = set()
    for block in (payload, auth, *accounts):
        keys = ("account_id", "dsid", "id") if any(block is account for account in accounts) else ("account_id", "dsid")
        for key in keys:
            value = block.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                value = str(value)
            if isinstance(value, str):
                value = value.strip()
                if 0 < len(value) <= 128 and all(
                    character.isascii() and (character.isalnum() or character in "-_.:") for character in value
                ):
                    identities.add(value)
        storefront = block.get("storefront")
        if isinstance(storefront, int) and not isinstance(storefront, bool) and storefront > 0:
            storefront = str(storefront)
        if isinstance(storefront, str):
            storefront = storefront.strip().lower()
            if 0 < len(storefront) <= 64 and all(
                character.isascii() and (character.isalnum() or character in "-_") for character in storefront
            ):
                storefronts.add(storefront)
    result = {}
    if len(identities) == 1:
        result["account_id"] = identities.pop()
    if len(storefronts) == 1:
        result["storefront"] = storefronts.pop()
    return result


def wrapper_auth_state(base_url: str, session=None, timeout: int = 10) -> dict:
    """The wrapper guest's account state from its ``/me`` endpoint.

    Returns ``{"reachable", "state", "logged_in", "account", "error"}``.
    ``state`` keeps the guest's own spelling (the live guest answers
    ``authenticated``); ``logged_in`` folds it to one boolean, true whenever
    the guest answered with a state that is not ``logged_out`` (the same
    rule gamdl uses). Never raises: the caller reads the dict.
    Optional ``account_id`` and ``storefront`` appear only when explicitly
    supplied without conflicts. The account label is never an identifier.
    """
    base = str(base_url or "").strip().rstrip("/")
    if not base:
        return {
            "reachable": False,
            "state": "",
            "logged_in": False,
            "account": "",
            "error": "The wrapper tier is not set up.",
        }
    client = session if session is not None else _session()
    try:
        response = client.get(f"{base}/me", timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return {"reachable": False, "state": "", "logged_in": False, "account": "", "error": _wrapper_error(exc)}
    if not isinstance(payload, dict):
        return {
            "reachable": True,
            "state": "",
            "logged_in": False,
            "account": "",
            "error": "The wrapper sent an unexpected reply.",
        }
    auth = payload.get("auth") if isinstance(payload.get("auth"), dict) else {}
    state = str(auth.get("state") or "").strip().lower()
    return {
        "reachable": True,
        "state": state,
        "logged_in": bool(state and state != "logged_out"),
        "account": _wrapper_account_label(payload, auth),
        "error": "",
        **_wrapper_context_fields(payload, auth),
    }


def wrapper_login(base_url: str, username: str, password: str, session=None, timeout: int = 30) -> dict:
    """Start a wrapper guest sign-in with Apple ID credentials.

    ``{"ok", "needs_2fa", "error"}``: the guest answers 200 when the
    session is authenticated and 202 when it wants a two-factor code.
    """
    base = str(base_url or "").strip().rstrip("/")
    if not base:
        return {"ok": False, "needs_2fa": False, "error": "The wrapper tier is not set up."}
    user = str(username or "").strip()
    secret = str(password or "")
    if not user or not secret:
        return {"ok": False, "needs_2fa": False, "error": "Apple ID and password are both required."}
    client = session if session is not None else _session()
    try:
        response = client.post(f"{base}/login", json={"username": user, "password": secret}, timeout=timeout)
    except Exception as exc:
        return {"ok": False, "needs_2fa": False, "error": _wrapper_error(exc)}
    status = int(getattr(response, "status_code", 0) or 0)
    if status == 200:
        return {"ok": True, "needs_2fa": False, "error": ""}
    if status == 202:
        return {"ok": True, "needs_2fa": True, "error": ""}
    return {
        "ok": False,
        "needs_2fa": False,
        "error": _wrapper_status_error(response, "The wrapper refused the sign-in."),
    }


def wrapper_login_2fa(base_url: str, code: str, session=None, timeout: int = 30) -> dict:
    """Finish a wrapper guest sign-in with the two-factor code."""
    base = str(base_url or "").strip().rstrip("/")
    if not base:
        return {"ok": False, "error": "The wrapper tier is not set up."}
    value = str(code or "").strip()
    if not value:
        return {"ok": False, "error": "Enter the two-factor code."}
    client = session if session is not None else _session()
    try:
        response = client.post(f"{base}/login/2fa", json={"code": value}, timeout=timeout)
        response.raise_for_status()
    except Exception as exc:
        return {"ok": False, "error": _wrapper_error(exc)}
    return {"ok": True, "error": ""}


def describe_image_pull_error(exc: Exception | str, image: str = WRAPPER_V2_IMAGE) -> str:
    """Plain-words guidance for a failed wrapper-image pull.

    A registry "denied"/"unauthorized" refusal almost always means access,
    not a broken setup: the image is private to accounts without access, or
    the runtime is not logged in. Say so with the next action instead of
    surfacing the daemon's raw stderr alone.
    """
    raw = str(exc or "").strip() or "container runtime refused"
    lowered = raw.lower()
    if "denied" in lowered or "unauthorized" in lowered or "authentication required" in lowered:
        return (
            f"Image pull was denied by the registry ({image}). The Waves wrapper image is visible "
            "only to accounts with access: run `docker login ghcr.io` with an account that has it, "
            "or ask for the image to be made public. Original error: " + raw
        )
    return f"Could not pull {image}: {raw}"


# Cookies fallback: Netscape export carrying a signed-in session.


def verify_cookies_file(path: str) -> dict:
    """Check a Netscape cookies export unlocks the cookies tier.

    Returns ``{"ok", "path", "has_token"}``. ``has_token`` is True when a
    ``media-user-token`` cookie for an Apple domain is present and not
    expired: the marker gamdl's ``create_from_netscape_cookies`` needs to
    build a session. Missing file, no token, or a concrete past expiry
    raises with wizard-ready words.
    """
    p = Path(str(path or "").strip()).expanduser()
    if not str(path or "").strip() or not p.is_file():
        raise FileNotFoundError("Set a cookies export in Settings under Providers, Apple Music.")
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ValueError(f"Could not read the cookies export: {exc}") from exc
    has_token = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        fields = [field.strip() for field in stripped.split("\t")]
        if len(fields) < 7 or fields[5] != "media-user-token":
            continue
        # The domain decides, not a substring: a token filed under a
        # lookalike domain is not an Apple session.
        cookie_domain = fields[0].lstrip(".")
        if cookie_domain != "apple.com" and not cookie_domain.endswith(".apple.com"):
            continue
        # Netscape field 5 is the expiry epoch; 0 is a session cookie
        # (no static expiry to check).
        try:
            expires = int(fields[4] or 0)
        except ValueError:
            expires = 0
        if expires > 0 and expires < time.time():
            raise ValueError(
                "That cookies export's Apple session has expired. "
                "Export fresh cookies from a logged-in music.apple.com tab."
            )
        has_token = True
        break
    if not has_token:
        raise ValueError(
            "That cookies export has no signed-in Apple session (no media-user-token cookie). "
            "Export again from a logged-in music.apple.com tab."
        )
    return {"ok": True, "path": str(p), "has_token": True}


# Setup state: one describer for the slot and the schema.

_STATE_WORDS = {
    "off": "Off",
    "not_set_up": "Not set up",
    "runtime_ready": "Runtime ready",
    "signed_in": "Signed in",
    "needs_attention": "Needs attention",
}


def describe_setup(
    *,
    enabled: bool,
    runtime_ready: bool = False,
    signed_in: bool = False,
    needs_attention: bool = False,
    cookies_ready: bool = False,
    wrapper_ready: bool = False,
) -> dict:
    """Describe the Apple setup wizard state for the status light.

    Precedence: off > needs_attention > signed_in > runtime_ready >
    not_set_up. ``signed_in`` covers both tiers: a verified cookies export
    or a live wrapper session. ``cookies_ready`` without ``signed_in``
    still counts as signed in for the light (the cookies tier unlocks
    AAC 256 + Atmos with no runtime at all). ``wrapper_ready`` names the
    full tier once the wrapper guest reports an authenticated session.
    """
    if not enabled:
        state = "off"
    elif needs_attention:
        state = "needs_attention"
    elif signed_in or cookies_ready:
        state = "signed_in"
    elif runtime_ready:
        state = "runtime_ready"
    else:
        state = "not_set_up"
    tier = "none"
    if state == "signed_in":
        # The cookies tier: AAC 256 + Atmos unlocked. The fetch binary is
        # shared download plumbing, not a tier upgrade; the full tier
        # (wrapper ALAC) names itself once a wrapper session exists.
        tier = "full" if wrapper_ready else "cookies"
    elif state == "runtime_ready":
        tier = "runtime"
    next_step = {
        "off": "Turn on Apple Music to start setup.",
        "not_set_up": "Continue setup: provision the runtime or add a cookies export.",
        "runtime_ready": "Sign in: add a cookies export or complete wrapper login.",
        "signed_in": "",
        "needs_attention": "Re-open setup: the saved cookies or runtime needs attention.",
    }[state]
    return {
        "state": state,
        "word": _STATE_WORDS[state],
        "tier": tier,
        # Whether an Apple download can start at all from this state (an
        # account exists): the wizard's "skip for now" retires once true,
        # and callers read this rather than re-deriving the tier words.
        "downloads_ready": tier in ("cookies", "full"),
        "next_step": next_step,
    }


# Manager: N_m3u8DL-RE provisioning + isolated engine config + provenance.


class AppleRuntimeManager:
    """Provision and inspect the managed Apple runtime under ``app_dir``."""

    def __init__(self, app_dir: str | os.PathLike) -> None:
        self.app_dir = Path(app_dir)
        self.os_key, self.arch = _safe_target()
        self._lifecycle_lock = Lock()
        self._users = 0
        self._maintaining = False
        self._binary_observation: tuple[tuple[int, int, int, int, int], str] | None = None
        # How many usage leases this thread holds. While one is held,
        # maintenance cannot replace the tool, so verify() hashes it only
        # when its file metadata changed.
        self._leases = local()

    @contextlib.contextmanager
    def usage(self, *, verify_binary: bool = True) -> Generator[None]:
        """Lease this manager's tools for an active engine operation.

        Callers share this manager instance. A maintenance action rejects new
        leases, and an existing lease prevents install, removal and rollback.
        Set verify_binary=False when the engine uses an explicit unmanaged tool.
        """
        with self._lifecycle_lock:
            if self._maintaining:
                raise AppleRuntimeBusy("Apple runtime maintenance is in progress.")
            self._users += 1
        depth = getattr(self._leases, "depth", 0)
        try:
            if verify_binary:
                verified = self.verify()
                integrity = verified.get("binary_integrity")
                if integrity in ("mismatch", "incomplete") or (
                    integrity == "unknown" and self._read_manifest().get("binary_sha256")
                ):
                    raise RuntimeError("The managed Apple tool cannot be verified. Reinstall or roll back it.")
            self._leases.depth = depth + 1
            yield
        finally:
            self._leases.depth = depth
            with self._lifecycle_lock:
                self._users -= 1

    @contextlib.contextmanager
    def maintenance(self) -> Generator[None]:
        """Acquire exclusive maintenance while no engine holds a usage lease."""
        with self._lifecycle_lock:
            if self._users or self._maintaining:
                raise AppleRuntimeBusy("Apple runtime is in use. Install or roll back when it is idle.")
            self._maintaining = True
        try:
            yield
        finally:
            with self._lifecycle_lock:
                self._maintaining = False

    @property
    def runtime_dir(self) -> Path:
        return self.app_dir / "apple-runtime"

    @property
    def bin_dir(self) -> Path:
        return self.runtime_dir / "bin"

    @property
    def binary_path(self) -> Path:
        return self.bin_dir / _exe_name(self.os_key or "macos")

    @property
    def manifest_path(self) -> Path:
        return self.runtime_dir / "nm3u8dlre.json"

    @property
    def previous_dir(self) -> Path:
        return self.runtime_dir / "nm3u8dlre-previous"

    @property
    def pending_dir(self) -> Path:
        return self.runtime_dir / "nm3u8dlre-pending"

    @property
    def port_path(self) -> Path:
        return self.runtime_dir / "wrapper-port.json"

    def _private_dir(self, directory: Path) -> Path:
        self.runtime_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name != "nt":
            self.runtime_dir.chmod(0o700)
            directory.chmod(0o700)
        return directory

    def engine_config_dir(self) -> Path:
        """Waves-owned isolated config dir for the Apple engine.

        The engine never sees the user's home: anything it insists on
        materialising lands here, never in ``~/.gamdl/``.
        """
        return self._private_dir(self.runtime_dir / "engine-config")

    def session_data_dir(self) -> Path:
        """Private Waves-owned wrapper session storage, separate from tool files."""
        return self._private_dir(self.runtime_dir / "wrapper-data")

    def engine_env(self, port: int = 0) -> dict:
        """Environment for engine subprocesses: isolated HOME + wrapper URL."""
        env = dict(os.environ)
        # HOME redirect keeps tools that resolve ~/config under our dir.
        # XDG_CONFIG_HOME covers the Linux/macOS config lookup; the engine
        # itself is still always passed explicit paths (cookies, binaries,
        # wrapper URL), so these are belt and braces, never the mechanism.
        isolated = str(self.engine_config_dir())
        env["WAVES_APPLE_ENGINE_CONFIG"] = isolated
        env["XDG_CONFIG_HOME"] = isolated
        if port:
            env["WAVES_APPLE_WRAPPER_URL"] = wrapper_url(port)
        return env

    def is_installed(self) -> bool:
        p = self.binary_path
        return p.is_file() and os.access(p, os.X_OK)

    def _read_manifest(self) -> dict:
        try:
            with open(self.manifest_path, encoding="utf-8") as fh:
                data = json.load(fh)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def read_port(self) -> int:
        """The persisted wrapper port, or 0 when none was picked yet."""
        try:
            with open(self.port_path, encoding="utf-8") as fh:
                data = json.load(fh)
                port = int((data or {}).get("port") or 0)
                return port if 1024 <= port <= 65535 else 0
        except Exception:
            return 0

    def ensure_port(self, preferred: int = 0) -> int:
        """Persist and return the wrapper port.

        A nonzero explicit override (the config-first ``apple_wrapper_port``)
        wins when it is unprivileged and free; otherwise Waves picks a free
        high port itself. The picked port is always high; only an explicit
        user choice may sit elsewhere in the unprivileged range.
        """
        if preferred and 1024 <= preferred <= 65535 and _port_free(preferred):
            port = int(preferred)
        else:
            port = pick_free_high_port()
        self._private_dir(self.runtime_dir)
        tmp_fd, tmp_name = tempfile.mkstemp(dir=self.runtime_dir, prefix="wrapper-port.", suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
                json.dump({"port": port, "url": wrapper_url(port)}, fh, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, self.port_path)
        except Exception:
            with contextlib.suppress(OSError):
                os.remove(tmp_name)
            raise
        return port

    def _base_status(self) -> dict:
        """Managed pins and cached integrity carried by every status response."""
        return {
            "wrapper_image": WRAPPER_V2_IMAGE,
            "wrapper_libs": WRAPPER_LIBS_VERSION,
            "binary_integrity": "incomplete" if self.pending_dir.exists() else "unknown",
            "verified": False,
            "rollback_available": self._generation_present(self.pending_dir)
            or self._generation_present(self.previous_dir),
        }

    def _binary_fingerprint(self) -> tuple[int, int, int, int, int] | None:
        try:
            value = self.binary_path.stat()
        except OSError:
            return None
        return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)

    def verify(self) -> dict:
        """Observe managed binary integrity on a worker and cache it for status.

        Status performs only metadata reads. A changed file or a newly restored
        manager remains unknown until this method or a usage lease observes it.
        Inside a lease on this thread, an observation of the unchanged file
        stands; a replaced or rewritten file changes its ctime and is hashed.
        """
        observation = self._binary_observation
        if (
            getattr(self._leases, "depth", 0)
            and observation is not None
            and observation[0] == self._binary_fingerprint()
        ):
            return self.status()
        before = self._binary_fingerprint()
        if before is not None:
            try:
                digest = sha256_file(self.binary_path)
            except OSError:
                self._binary_observation = None
            else:
                after = self._binary_fingerprint()
                self._binary_observation = (before, digest) if before == after else None
        else:
            self._binary_observation = None
        return self.status()

    def _install_is_stale(self) -> bool:
        """Whether the managed binary predates the shipped pin.

        Compares the provenance the install recorded -- version, asset URL and
        verified checksum -- against the pinned release this build ships. A
        manifest from before a field existed counts as stale, because the pass
        that re-installs it is also what records the field. An unsupported
        platform (no pinned asset) can never be stale.
        """
        pinned = pinned_release(self.os_key, self.arch)
        if pinned is None:
            return False
        mani = self._read_manifest()
        return (
            str(mani.get("version") or "") != str(pinned.version or "")
            or str(mani.get("url") or "") != str(pinned.url or "")
            or str(mani.get("sha256") or "") != str(pinned.sha256 or "")
        )

    def status(self, custom_path: str = "") -> dict:
        """Describe the managed N_m3u8DL-RE for the UI.

        An explicit override or a binary on PATH reports as an unmanaged
        ``path`` (the FFmpeg manager's precedence); only the copy this
        manager provisioned reports ``managed``. A managed copy whose
        recorded provenance differs from the shipped pin reports
        ``runtime_stale`` (a pin bump must not let an old binary
        look current forever); the state stays ``managed`` because the binary
        still works, and Install is the one-click way to replace it.
        """
        if self.is_installed():
            mani = self._read_manifest()
            recorded_digest = str(mani.get("binary_sha256") or "")
            integrity = "unknown"
            observed = self._binary_observation
            if recorded_digest and observed is not None and observed[0] == self._binary_fingerprint():
                integrity = "verified" if observed[1] == recorded_digest else "mismatch"
            if self.pending_dir.exists():
                integrity = "incomplete"
            return {
                **self._base_status(),
                "state": "managed",
                "available": integrity not in ("mismatch", "incomplete"),
                "managed": True,
                "path": str(self.binary_path),
                "version": str(mani.get("version") or NM3U8DLRE_VERSION),
                "source_url": str(mani.get("url") or ""),
                "sha256": str(mani.get("sha256") or ""),
                "runtime_stale": self._install_is_stale(),
                "binary_integrity": integrity,
                "verified": integrity == "verified",
            }
        cp = (custom_path or "").strip()
        if cp and Path(cp).is_file():
            return {
                **self._base_status(),
                "state": "path",
                "available": True,
                "managed": False,
                "path": cp,
                "version": "",
                "source_url": "",
                "sha256": "",
                "runtime_stale": False,
            }
        found = shutil.which("N_m3u8DL-RE")
        if found:
            return {
                **self._base_status(),
                "state": "path",
                "available": True,
                "managed": False,
                "path": found,
                "version": "",
                "source_url": "",
                "sha256": "",
                "runtime_stale": False,
            }
        return {
            **self._base_status(),
            "state": "missing",
            "available": False,
            "managed": False,
            "path": "",
            "version": "",
            "source_url": "",
            "sha256": "",
            "runtime_stale": False,
        }

    def update_status(self) -> dict:
        """Offer only the approved pins shipped with Waves, without a network check.

        Missing optional assets are setup requirements rather than updates.
        Bundled clients update with Waves. This policy approves no lite image
        and never discovers or modifies a user-managed service.
        """
        current = self.status()
        pin = pinned_release(self.os_key, self.arch)
        image = self.image_status()
        binary_update = bool(
            pin
            and current.get("managed")
            and (
                current.get("runtime_stale")
                or not self._read_manifest().get("binary_sha256")
                or current.get("binary_integrity") in ("mismatch", "incomplete")
            )
        )
        image_update = bool(image["image"] and (not image["verified"] or not image["current"]))
        with self._lifecycle_lock:
            busy = bool(self._users or self._maintaining)
        return {
            "available": binary_update or image_update,
            "manual_install_default": True,
            "client_updates": "waves",
            "busy": busy,
            "rollback_available": bool(current["rollback_available"]),
            "binary": {
                "available": binary_update,
                "version": pin.version if pin else "",
                "source_url": pin.url if pin else "",
                "sha256": pin.sha256 if pin else "",
                "installed_version": str(current.get("version") or ""),
                "integrity": str(current["binary_integrity"]),
            },
            "image": {
                "available": image_update,
                "image": WRAPPER_V2_IMAGE,
                "digest": WRAPPER_V2_IMAGE_DIGEST,
                "installed_image": image["image"],
                "provenance": image["provenance"],
                "rollback_available": image["rollback_available"],
            },
        }

    def install(
        self,
        release: Nm3u8dlreRelease | None = None,
        progress_cb=None,
        log_cb=None,
        abort: Event | None = None,
        session: requests.Session | None = None,
    ) -> dict:
        """Download, verify, extract and install N_m3u8DL-RE; return ``status()``.

        Stage, checksum-verify and smoke-test before activation. A recovery
        snapshot retains the preceding binary and receipt. An interrupted
        activation remains unavailable until rollback restores that pair.
        The receipt records the source archive and extracted binary digests.
        """
        with self.maintenance():
            return self._install(release, progress_cb, log_cb, abort, session)

    def _install(self, release, progress_cb, log_cb, abort, session) -> dict:

        def _log(msg: str) -> None:
            logger.info("apple-runtime: %s", msg)
            if log_cb:
                log_cb(msg)

        def _check_abort() -> None:
            _check_runtime_abort(abort)

        sess = session or _session()
        if release is None:
            _log("resolving pinned N_m3u8DL-RE release")
            release = pinned_release(self.os_key, self.arch)
        if release is None:
            raise AppleRuntimeUnsupportedPlatform(f"No N_m3u8DL-RE build for {self.os_key}/{self.arch}")

        self._private_dir(self.bin_dir)
        _check_abort()

        _log(f"downloading N_m3u8DL-RE {release.version}")
        arc_suffix = ".zip" if str(release.url).lower().endswith(".zip") else ".tar.gz"
        with tempfile.NamedTemporaryFile(dir=self.bin_dir, suffix=arc_suffix, delete=False) as tmp:
            arc_tmp = Path(tmp.name)
        fd_staged, staged_name = tempfile.mkstemp(
            dir=self.bin_dir, prefix=_exe_name(self.os_key or "macos") + ".", suffix=".new"
        )
        os.close(fd_staged)
        staged = Path(staged_name)
        try:
            self._download(sess, release.url, arc_tmp, progress_cb, abort)
            _check_abort()

            expected = release.sha256 or self._fetch_sha256(sess, release.sha256_url)
            if not expected:
                raise ValueError("refusing to install N_m3u8DL-RE: no checksum available to verify the download")
            _log("verifying checksum")
            actual = sha256_file(arc_tmp)
            if actual.lower() != expected.lower():
                raise ValueError(f"checksum mismatch: expected {expected}, got {actual}")

            _log("installing")
            _extract_binary(arc_tmp, staged, _exe_name(self.os_key or "macos"))
            staged.chmod(
                staged.stat().st_mode | stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH
            )

            ver = _probe_version(str(staged))
            if not ver:
                raise RuntimeError("N_m3u8DL-RE downloaded but would not run, keeping the existing binary")

            manifest = {
                **asdict(release),
                "sha256": expected,
                "binary_sha256": sha256_file(staged),
                "binary_version": ver,
                "installed_at": int(time.time()),
            }
            self._activate(staged, manifest, abort=abort)
        finally:
            arc_tmp.unlink(missing_ok=True)
            staged.unlink(missing_ok=True)
        _log(f"installed N_m3u8DL-RE {ver}")
        return self.verify()

    def _activate(self, staged: Path, manifest: dict, *, abort: Event | None = None) -> None:
        _check_runtime_abort(abort)
        if self.pending_dir.exists():
            raise RuntimeError("An Apple tool installation was interrupted. Roll back before installing again.")
        fd_manifest, name = tempfile.mkstemp(dir=self.runtime_dir, prefix="nm3u8dlre.", suffix=".tmp")
        staged_manifest = Path(name)
        try:
            with os.fdopen(fd_manifest, "w", encoding="utf-8") as output:
                json.dump(manifest, output, indent=2)
                output.flush()
                os.fsync(output.fileno())
            self._save_generation()
            try:
                _check_runtime_abort(abort)
                os.replace(staged, self.binary_path)
                os.replace(staged_manifest, self.manifest_path)
                if (self.pending_dir / self.binary_path.name).is_file():
                    if self.previous_dir.exists():
                        shutil.rmtree(self.previous_dir)
                    os.replace(self.pending_dir, self.previous_dir)
                else:
                    shutil.rmtree(self.pending_dir)
            except Exception:
                self._restore_generation(self.pending_dir)
                shutil.rmtree(self.pending_dir)
                raise
        finally:
            staged_manifest.unlink(missing_ok=True)

    def _save_generation(self) -> None:
        staged = Path(tempfile.mkdtemp(dir=self.runtime_dir, prefix="nm3u8dlre-generation."))
        try:
            receipt = {}
            for path in (self.binary_path, self.manifest_path):
                if path.is_file():
                    copy = staged / path.name
                    shutil.copy2(path, copy)
                    receipt[path.name] = sha256_file(copy)
            (staged / "generation.json").write_text(json.dumps(receipt), encoding="utf-8")
            os.replace(staged, self.pending_dir)
        finally:
            if staged.exists():
                shutil.rmtree(staged)

    def _generation_receipt(self, directory: Path) -> dict[str, str] | None:
        try:
            receipt = json.loads((directory / "generation.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(receipt, dict):
            return None
        if not all(
            name in (self.binary_path.name, self.manifest_path.name)
            and isinstance(digest, str)
            and len(digest) == 64
            and all(character in "0123456789abcdef" for character in digest)
            for name, digest in receipt.items()
        ):
            return None
        if any(
            (directory / name).is_file() != (name in receipt)
            for name in (self.binary_path.name, self.manifest_path.name)
        ):
            return None
        return receipt

    def _generation_present(self, directory: Path) -> bool:
        receipt = self._generation_receipt(directory)
        return receipt is not None and all((directory / name).is_file() for name in receipt)

    def _generation_matches(self, directory: Path) -> bool:
        receipt = self._generation_receipt(directory)
        if receipt is None:
            return False
        try:
            return all(sha256_file(directory / name) == digest for name, digest in receipt.items())
        except OSError:
            return False

    def _restore_generation(self, directory: Path) -> None:
        if not self._generation_matches(directory):
            raise RuntimeError("The previous Apple tool files do not match their recovery receipt.")
        for target in (self.binary_path, self.manifest_path):
            source = directory / target.name
            if not source.is_file():
                target.unlink(missing_ok=True)
                continue
            fd, name = tempfile.mkstemp(dir=target.parent, prefix=target.name + ".", suffix=".restore")
            os.close(fd)
            staged = Path(name)
            try:
                shutil.copy2(source, staged)
                os.replace(staged, target)
            finally:
                staged.unlink(missing_ok=True)

    def rollback(self) -> dict:
        """Restore the retained binary and its original receipt together.

        An interrupted activation's snapshot takes precedence. Recovery never
        downloads files or changes the wrapper's account/session storage.
        """
        with self.maintenance():
            if self.pending_dir.exists():
                self._restore_generation(self.pending_dir)
                shutil.rmtree(self.pending_dir)
                return self.verify()
            if not self._generation_matches(self.previous_dir):
                raise RuntimeError("The previous Apple tool files do not match their recovery receipt.")
            self._save_generation()
            try:
                self._restore_generation(self.previous_dir)
            except Exception:
                self._restore_generation(self.pending_dir)
                shutil.rmtree(self.pending_dir)
                raise
            shutil.rmtree(self.pending_dir)
            return self.verify()

    def remove(self) -> dict:
        with self.maintenance():
            self.binary_path.unlink(missing_ok=True)
            self.manifest_path.unlink(missing_ok=True)
            for generation in (self.previous_dir, self.pending_dir):
                if generation.exists():
                    shutil.rmtree(generation)
            return self.status()

    @property
    def image_manifest_path(self) -> Path:
        return self.runtime_dir / "wrapper-image.json"

    @property
    def image_previous_path(self) -> Path:
        return self.runtime_dir / "wrapper-image-previous.json"

    def _read_image_receipt(self, path: Path) -> dict:
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return receipt if isinstance(receipt, dict) else {}

    def _image_receipt_status(self, receipt: dict) -> dict:
        image = str(receipt.get("image") or "")
        digest = str(receipt.get("digest") or "")
        current = image == WRAPPER_V2_IMAGE and digest == WRAPPER_V2_IMAGE_DIGEST
        # The build, not the receipt, says which guest libs an approved pin
        # carries; a receipt's own libs or protocol can only narrow that.
        approved_libs = (
            WRAPPER_LIBS_VERSION
            if current
            else next(
                (libs for pin, pinned, libs in APPROVED_WRAPPER_V2_IMAGES if (pin, pinned) == (image, digest)), ""
            )
        )
        verified = bool(approved_libs and receipt.get("digest_ok") is True)
        compatible = bool(
            verified
            and approved_libs == WRAPPER_LIBS_VERSION
            and str(receipt.get("libs") or approved_libs) == approved_libs
            and str(receipt.get("protocol") or "wrapper-v2") == "wrapper-v2"
        )
        provenance = "unknown"
        if not image or not receipt.get("pulled_at"):
            provenance = "missing"
            verified = compatible = False
        elif receipt.get("digest_ok") is False:
            provenance = "mismatch"
        elif verified:
            provenance = "verified"
        elif image != WRAPPER_V2_IMAGE:
            provenance = "stale"
        elif digest and digest != WRAPPER_V2_IMAGE_DIGEST:
            provenance = "mismatch"
        return {
            "image": image,
            "digest": digest,
            "provenance": provenance,
            "verified": verified,
            "compatible": compatible,
            "current": current,
        }

    def image_status(self) -> dict:
        """Describe recorded image provenance without probing or starting it.

        A legacy pull receipt without a digest is unknown. The current pin or
        an earlier pin listed in APPROVED_WRAPPER_V2_IMAGES establishes
        verification. Compatibility remains separate and is required for activation.
        """
        state = self._image_receipt_status(self._read_image_receipt(self.image_manifest_path))
        previous = self._image_receipt_status(self._read_image_receipt(self.image_previous_path))
        return {
            **state,
            "pulled": self.image_pulled(),
            "rollback_available": previous["verified"] and previous["compatible"],
        }

    def active_image(self) -> str:
        """The verified compatible immutable image for the next managed start."""
        state = self.image_status()
        if not state["verified"] or not state["compatible"]:
            return ""
        return state["image"].rsplit(":", 1)[0] + "@" + state["digest"]

    def rollback_image(self, runner=None, binary: str = "docker") -> dict:
        """Restore a previously approved compatible local image receipt.

        This does not pull, start or stop any container. The supervisor consumes
        active_image only on its next permitted start, preserving session state
        and the separate intentional-stop choice.
        """
        with self.maintenance():
            receipt = self._read_image_receipt(self.image_previous_path)
            state = self._image_receipt_status(receipt)
            if not state["verified"] or not state["compatible"]:
                raise RuntimeError("The previous Apple image is not verified and compatible; no image was changed.")
            reference = state["image"].rsplit(":", 1)[0] + "@" + state["digest"]
            run = runner or subprocess.run
            try:
                result = run(
                    [binary, "image", "inspect", "--format", "{{.Id}}", reference],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    **child_guard.NO_WINDOW,
                )
            except Exception as exc:
                raise RuntimeError("The previous Apple image could not be inspected; no image was changed.") from exc
            if result.returncode != 0 or not str(result.stdout or "").strip():
                raise RuntimeError("The previous Apple image is not installed locally; no image was changed.")
            self._write_image_receipt(receipt, self.image_manifest_path)
            return self.image_status()

    def image_pulled(self) -> bool:
        """Whether setup has a pull receipt or compatible verified restored image.

        Current legacy receipts may still be unknown. Admission requiring
        verified provenance uses image_status rather than this setup flag.
        """
        data = self._read_image_receipt(self.image_manifest_path)
        state = self._image_receipt_status(data)
        if state["verified"] and state["compatible"]:
            return True
        if data.get("image") != WRAPPER_V2_IMAGE or not data.get("pulled_at"):
            return False
        # A receipt that recorded a mismatch (a hand-edited or future legacy
        # file) never counts as pulled; a missing field is an old receipt from
        # before digest verification, which pull-time checks cover on refresh.
        return data.get("digest_ok") is not False and state["provenance"] not in ("missing", "mismatch", "stale")

    def ensure_image(
        self,
        runner=None,
        binary: str = "docker",
        log_cb=None,
        *,
        abort: Event | None = None,
        require_verified: bool = False,
    ) -> dict:
        """Pull the pinned Waves-built wrapper-v2 image and record it.

        Waves builds the image from source and pins the tag; this only
        fetches that exact tag through the user's own container runtime
        (Docker by default, or the detected compatible binary the caller
        passes). Records provenance (image + pull time) beside the runtime
        manifest. ``runner`` is an injectable ``subprocess.run`` for tests.
        Running the container and its health/idle lifecycle is session
        supervision's job, not this manager's.
        require_verified=True refuses an unreportable digest. Native commands
        are cancellable when abort is supplied; injected synchronous runners
        receive cancellation checks before and after their call.
        """
        with self.maintenance():
            return self._ensure_image(runner, binary, log_cb, abort, require_verified)

    def _ensure_image(self, runner, binary, log_cb, abort, require_verified) -> dict:
        def check_abort() -> None:
            _check_runtime_abort(abort)

        check_abort()
        run = runner or (lambda *a, **k: self._run_image_command(*a, abort=abort, **k))
        if log_cb:
            log_cb(f"pulling {WRAPPER_V2_IMAGE}")
        logger.info("apple-runtime: pulling %s", WRAPPER_V2_IMAGE)
        check_abort()
        proc = run(
            [binary, "pull", WRAPPER_V2_IMAGE], capture_output=True, text=True, timeout=600, **child_guard.NO_WINDOW
        )
        check_abort()
        if proc.returncode != 0:
            raise RuntimeError(describe_image_pull_error((proc.stderr or proc.stdout or "").strip(), WRAPPER_V2_IMAGE))
        digest = self._local_image_digest(run, binary)
        check_abort()
        if digest and digest != WRAPPER_V2_IMAGE_DIGEST:
            raise RuntimeError(
                "The pulled wrapper image does not match its pinned digest "
                f"({digest} instead of {WRAPPER_V2_IMAGE_DIGEST}); refusing to use it."
            )
        if require_verified and digest != WRAPPER_V2_IMAGE_DIGEST:
            raise RuntimeError("Could not verify the pulled wrapper image digest; refusing verified admission.")
        self._private_dir(self.runtime_dir)
        manifest = {
            "image": WRAPPER_V2_IMAGE,
            "libs": WRAPPER_LIBS_VERSION,
            "pulled_at": int(time.time()),
            # Provenance: the registry digest when the runtime can
            # report one, and whether it matched the pin. None means the
            # runtime could not say (podman's inspect format may differ);
            # a mismatch never reaches the receipt.
            "digest": digest,
            "digest_ok": (digest == WRAPPER_V2_IMAGE_DIGEST) if digest else None,
            "protocol": "wrapper-v2",
        }
        previous = self._read_image_receipt(self.image_manifest_path)
        previous_state = self._image_receipt_status(previous)
        if (
            previous_state["verified"]
            and previous_state["compatible"]
            and (previous.get("image"), previous.get("digest")) != (manifest["image"], manifest["digest"])
        ):
            self._write_image_receipt(previous, self.image_previous_path, abort=abort)
        self._write_image_receipt(manifest, self.image_manifest_path, abort=abort)
        if log_cb:
            log_cb(f"pulled {WRAPPER_V2_IMAGE}")
        return manifest

    def _write_image_receipt(self, receipt: dict, path: Path, *, abort: Event | None = None) -> None:
        tmp_fd, tmp_name = tempfile.mkstemp(dir=self.runtime_dir, prefix="wrapper-image.", suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
                json.dump(receipt, fh, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            _check_runtime_abort(abort)
            os.replace(tmp_name, path)
        except Exception:
            with contextlib.suppress(OSError):
                os.remove(tmp_name)
            raise

    def _run_image_command(
        self,
        command: list[str],
        *,
        abort: Event | None,
        timeout: int,
        capture_output: bool,
        text: bool,
        **options,
    ):
        if abort is None:
            return subprocess.run(command, capture_output=capture_output, text=text, timeout=timeout, **options)
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=text, **options)
        deadline = time.monotonic() + timeout

        def remaining_time() -> float:
            _check_runtime_abort(abort)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, timeout)
            return remaining

        try:
            while True:
                remaining = remaining_time()
                try:
                    stdout, stderr = process.communicate(timeout=min(0.2, remaining))
                except subprocess.TimeoutExpired:
                    continue
                return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
        except BaseException:
            if process.poll() is None:
                with contextlib.suppress(ProcessLookupError):
                    process.terminate()
                try:
                    process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    with contextlib.suppress(ProcessLookupError):
                        process.kill()
                    process.communicate(timeout=5)
            raise

    def _local_image_digest(self, run, binary: str) -> str:
        """The pulled image's repo digest, or "" when the runtime cannot say."""
        try:
            proc = run(
                [binary, "image", "inspect", "--format", "{{json .RepoDigests}}", WRAPPER_V2_IMAGE],
                capture_output=True,
                text=True,
                timeout=60,
                **child_guard.NO_WINDOW,
            )
        except Exception:
            return ""
        if proc.returncode != 0:
            return ""
        try:
            entries = json.loads(proc.stdout or "[]")
        except ValueError:
            return ""
        repo = WRAPPER_V2_IMAGE.rsplit(":", 1)[0]
        matches = [str(entry).split("@", 1)[1] for entry in entries if str(entry).startswith(repo + "@")]
        if not matches:
            return ""
        # A containerd runtime can report more than one digest (an index and a
        # platform manifest); the pin itself wins when present.
        return WRAPPER_V2_IMAGE_DIGEST if WRAPPER_V2_IMAGE_DIGEST in matches else matches[0]

    def _download(self, sess, url: str, dest: Path, progress_cb, abort: Event | None) -> None:
        with sess.get(url, stream=True, timeout=_HTTP_TIMEOUT) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            with open(dest, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=_IO_CHUNK):
                    if abort is not None and abort.is_set():
                        raise AppleRuntimeCancelled()
                    if not chunk:
                        continue
                    fh.write(chunk)
                    done += len(chunk)
                    if progress_cb and total:
                        progress_cb(min(100.0, done / total * 100.0))
            if progress_cb and not total:
                progress_cb(100.0)

    def _fetch_sha256(self, sess, sha_url: str | None) -> str | None:
        if not sha_url:
            return None
        try:
            resp = sess.get(sha_url, timeout=_HTTP_TIMEOUT)
            resp.raise_for_status()
            text = resp.text
        except Exception:
            logger.debug("could not fetch sha256 from %s", sha_url, exc_info=True)
            return None
        parts = text.split()
        return parts[0] if parts else None


def _port_free(port: int) -> bool:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        try:
            sock.bind(("127.0.0.1", int(port)))
        except OSError:
            return False
        return True


def _extract_binary(arc_path: Path, dest: Path, exe_name: str) -> None:
    """Extract the N_m3u8DL-RE executable from its archive to ``dest``.

    Upstream ships .tar.gz on macOS/Linux and .zip on Windows, each holding
    one root-level binary. Dispatch on the archive suffix so a platform's
    real format extracts; anything else raises instead of guessing.
    """
    suffix = arc_path.suffix.lower()
    if suffix == ".zip":
        _extract_binary_zip(arc_path, dest, exe_name)
    elif arc_path.name.endswith(".tar.gz") or suffix in (".tgz", ".gz"):
        _extract_binary_tar(arc_path, dest, exe_name)
    else:
        raise ValueError(f"unsupported N_m3u8DL-RE archive format: {arc_path.name}")


def _extract_binary_tar(arc_path: Path, dest: Path, exe_name: str) -> None:
    with tarfile.open(arc_path, "r:gz") as tf:
        members = [m for m in tf.getmembers() if m.isfile()]
        cand = [m for m in members if os.path.basename(m.name) == exe_name]
        if not cand:
            # Single-binary archives sometimes carry no directory: take the
            # shallowest executable-looking member as a last resort.
            cand = sorted(members, key=lambda m: m.name.count("/"))
            if not cand:
                raise FileNotFoundError(f"no '{exe_name}' inside {arc_path.name}")
        # Prefer one under a bin/ dir, else the shallowest path.
        cand.sort(key=lambda m: (0 if "/bin/" in f"/{m.name}" else 1, m.name.count("/")))
        member = cand[0]
        src = tf.extractfile(member)
        if src is None:
            raise FileNotFoundError(f"no '{exe_name}' inside {arc_path.name}")
        with src, open(dest, "wb") as out:
            while True:
                chunk = src.read(_IO_CHUNK)
                if not chunk:
                    break
                out.write(chunk)


def _extract_binary_zip(arc_path: Path, dest: Path, exe_name: str) -> None:
    import zipfile

    with zipfile.ZipFile(arc_path) as zf:
        members = [n for n in zf.namelist() if not n.endswith("/")]
        cand = [n for n in members if os.path.basename(n) == exe_name]
        if not cand:
            cand = sorted(members, key=lambda n: n.count("/"))
            if not cand:
                raise FileNotFoundError(f"no '{exe_name}' inside {arc_path.name}")
        cand.sort(key=lambda n: (0 if "/bin/" in f"/{n}" else 1, n.count("/")))
        with zf.open(cand[0]) as src, open(dest, "wb") as out:
            while True:
                chunk = src.read(_IO_CHUNK)
                if not chunk:
                    break
                out.write(chunk)


def _probe_version(path: str) -> str:
    """Return the binary's ``--version`` first line, or "" when it won't run."""
    try:
        out = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=10, **child_guard.NO_WINDOW)
    except Exception:
        return ""
    if out.returncode != 0:
        return ""
    first = ((out.stdout or "") + (out.stderr or "")).splitlines()
    return first[0].strip() if first else ""
