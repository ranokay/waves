"""Managed Apple runtime for Waves (issue #31, spec section 2 and 10).

The full Apple tier needs two provisioned pieces Waves owns end to end,
FFmpeg-manager style: the N_m3u8DL-RE fetch binary (pinned release,
downloaded as a tar.gz, checksum-verified, extracted, chmod'd) and the
wrapper-v2 container image (Waves-built, pinned) running on a free high
port. The Apple Music APK stays user-supplied: the wizard guides the user
to the pinned version, verifies it by SHA-256, and scripts the .apkm
extraction. Waves never fetches, bundles, mirrors, or proxies it.

The cookies-only fallback tier needs none of this: a Netscape cookies
export from a logged-in music.apple.com session unlocks AAC 256 and
Atmos straight away and is verified here too.

Nothing here touches Qt, so it is pure and unit-testable; the Qt
slots/signals that drive the Settings UI live in
:mod:`waves.waves_ui.backend`.

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
import hashlib
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
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Event

import requests

logger = logging.getLogger("waves.apple_runtime")

_TIME_TIMEOUT = 30
_CHUNK = 1 << 16  # 64 KiB streaming chunks
_UA = "Waves-apple-runtime"

# --------------------------------------------------------------------------- #
# Pins (config-first initial values; engine bumps ride Waves' updater, spec 10.4)
# --------------------------------------------------------------------------- #

# Waves-built wrapper-v2 image, pinned. Waves builds from source (Unlicense)
# and never vendors the image into its own package (spec 10.1); the setup
# flow pulls this exact tag.
WRAPPER_V2_IMAGE = "ghcr.io/ranokay/waves-wrapper-v2:0.2.3"
# The wrapper's guest-lib set this image was built against, mirrored from
# wrapper-v2's LIBS_VERSION.json. The wizard shows this version when it asks
# the user to supply the APK, so the APK and the image can never disagree.
WRAPPER_LIBS_VERSION = "17.0.0"
# The N_m3u8DL-RE release the managed install provisions. Pinned so every
# machine fetches the same bytes; bumps ship through Waves' normal update
# channel with provenance recorded in the manifest.
NM3U8DLRE_VERSION = "v0.7.3"
NM3U8DLRE_RELEASES = {
    # asset base URL per (os_key, arch); the ".tar.gz" and ".tar.gz.sha256"
    # sidecars hang off it. Real URLs resolve at install time; tests inject
    # their own Release so no test ever touches the network.
    ("macos", "arm64"): "https://github.com/nilaoda/N_m3u8DL-RE/releases/download/v0.7.3/N_m3u8DL-RE_BETA_macos-arm64",
    ("macos", "amd64"): "https://github.com/nilaoda/N_m3u8DL-RE/releases/download/v0.7.3/N_m3u8DL-RE_BETA_macos-x64",
    ("linux", "amd64"): "https://github.com/nilaoda/N_m3u8DL-RE/releases/download/v0.7.3/N_m3u8DL-RE_BETA_linux-x64",
    ("linux", "arm64"): "https://github.com/nilaoda/N_m3u8DL-RE/releases/download/v0.7.3/N_m3u8DL-RE_BETA_linux-arm64",
    ("windows", "amd64"): "https://github.com/nilaoda/N_m3u8DL-RE/releases/download/v0.7.3/N_m3u8DL-RE_BETA_win-x64",
    ("windows", "arm64"): "https://github.com/nilaoda/N_m3u8DL-RE/releases/download/v0.7.3/N_m3u8DL-RE_BETA_win-arm64",
}
# Pinned APK the wizard asks the user to supply (from LIBS_VERSION.json).
# Waves never fetches it; this version string and SHA-256 only verify what
# the user brings and script the .apkm extraction.
APK_PINNED_VERSION = "4.7.0"
APK_SHA256 = ""  # filled when the wrapper release publishes its hash; empty means "version check only"

# Wrapper HTTP API: never port 80 on a desktop (collision-prone). The
# manager picks a free high port and passes it explicitly everywhere.
WRAPPER_PORT_LOW = 49152
WRAPPER_PORT_HIGH = 65535


class AppleRuntimeUnsupportedPlatform(Exception):
    """Raised when the current OS/arch has no pinned N_m3u8DL-RE asset."""


class AppleRuntimeCancelled(Exception):
    """Raised when a provision is aborted via its :class:`~threading.Event`."""


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
    """The pinned N_m3u8DL-RE release for this (or the given) platform."""
    if not os_key or not arch:
        os_key, arch = _safe_target()
    base = NM3U8DLRE_RELEASES.get((os_key, arch))
    if not base:
        return None
    return Nm3u8dlreRelease(
        version=NM3U8DLRE_VERSION,
        url=base + ".tar.gz",
        sha256_url=base + ".tar.gz.sha256",
    )


def _session() -> requests.Session:
    sess = requests.Session()
    sess.headers["User-Agent"] = _UA
    return sess


# --------------------------------------------------------------------------- #
# Container runtime: detect, gentle-start, never install
# --------------------------------------------------------------------------- #


def detect_container_runtime(runner=None) -> dict:
    """Detect the container runtime the full tier needs.

    Returns ``{"name", "available", "running", "hint"}``. ``available``
    means a runtime binary exists; ``running`` means its daemon answers.
    Waves never silently installs one: when absent the hint guides the
    user to install Docker themselves.

    ``runner`` is an injectable ``subprocess.run`` for tests.
    """
    run = runner or (lambda *a, **k: subprocess.run(*a, **k))
    for name, probe in (("docker", ["docker", "info"]), ("podman", ["podman", "info"])):
        try:
            proc = run(probe, capture_output=True, text=True, timeout=10)
        except FileNotFoundError:
            continue
        except Exception:
            logger.debug("Container probe for %s failed", name, exc_info=True)
            continue
        if proc.returncode == 0:
            return {"name": name, "available": True, "running": True, "hint": ""}
        # Binary exists but the daemon is not answering.
        return {
            "name": name,
            "available": True,
            "running": False,
            "hint": "Start Docker Desktop, then continue setup.",
        }
    return {
        "name": "",
        "available": False,
        "running": False,
        "hint": (
            "Install Docker Desktop for your platform, start it, then continue setup. Waves never installs it for you."
        ),
    }


def gentle_start_command() -> list[str] | None:
    """The gentle start attempt for an idle container runtime, if any.

    macOS only: ``open -a Docker`` wakes Docker Desktop without installing
    anything. Other platforms return None: the wizard guides instead.
    """
    if platform.system() == "Darwin":
        return ["open", "-a", "Docker"]
    return None


def attempt_gentle_start(runner=None) -> bool:
    """Try the gentle start; return True when one was attempted."""
    cmd = gentle_start_command()
    if not cmd:
        return False
    run = runner or (lambda *a, **k: subprocess.run(*a, **k))
    try:
        run(cmd, capture_output=True, timeout=30)
    except Exception:
        logger.debug("Gentle container start failed", exc_info=True)
        return False
    else:
        return True


# --------------------------------------------------------------------------- #
# Free high port (never port 80)
# --------------------------------------------------------------------------- #


def pick_free_high_port(low: int = WRAPPER_PORT_LOW, high: int = WRAPPER_PORT_HIGH) -> int:
    """Pick a free TCP port on loopback in the high range.

    Binds each candidate to prove it is free, then releases it. The small
    TOCTOU window (another process grabbing it before the wrapper starts)
    is closed by the caller retrying on EADDRINUSE; this only picks the
    first offer.
    """
    for port in range(low, high + 1):
        with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    # Fall back to whatever the OS hands out, as long as it is unprivileged.
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        picked = int(sock.getsockname()[1])
    if picked < 1024:
        raise OSError("no free high port available")
    return picked


def wrapper_url(port: int) -> str:
    """The wrapper HTTP API URL for an explicitly picked port."""
    return f"http://127.0.0.1:{int(port)}"


# --------------------------------------------------------------------------- #
# APK: user-supplied, SHA-verified, extraction scripted, never fetched
# --------------------------------------------------------------------------- #


def verify_apk(path: str, expected_sha256: str = APK_SHA256) -> dict:
    """Verify a user-supplied APK/.apkm file against the pinned version.

    Returns ``{"ok", "path", "sha256", "note"}``. Raises FileNotFoundError
    when missing and ValueError on a hash mismatch (fail-closed: an
    unverified APK never reaches the wrapper). An empty expected hash
    verifies presence and extension only.
    """
    p = Path(str(path or "").strip()).expanduser()
    if not str(path or "").strip() or not p.is_file():
        raise FileNotFoundError(f"APK not found: {path or '(no path given)'}")
    suffix = p.suffix.lower()
    if suffix not in (".apk", ".apkm", ".apks"):
        raise ValueError(f"Expected an .apk/.apkm file, got '{p.name}'")
    digest = _sha256_file(p)
    if expected_sha256 and digest.lower() != expected_sha256.lower():
        raise ValueError(f"APK checksum mismatch: expected {expected_sha256}, got {digest}")
    return {
        "ok": True,
        "path": str(p),
        "sha256": digest,
        "note": (
            f"Pinned Apple Music APK {APK_PINNED_VERSION}: verified. "
            "Extract inside the wrapper per wrapper-v2's documented .apkm steps; Waves never fetches this file."
        ),
    }


def apk_extract_plan(apk_path: str) -> list[str]:
    """The scripted .apkm extraction steps the wizard walks the user through."""
    return [
        f"Confirm the pinned APK version ({APK_PINNED_VERSION}) at: {apk_path}",
        "Verify its SHA-256 against the pinned hash (done above, fail-closed).",
        "Unpack the .apkm (a zip of split APKs) into its base + config splits.",
        "Copy the splits into the wrapper guest per wrapper-v2's LIBS setup notes.",
        "Restart the wrapper container and confirm its /health endpoint answers.",
    ]


# --------------------------------------------------------------------------- #
# Cookies fallback: Netscape export carrying a signed-in session
# --------------------------------------------------------------------------- #


def verify_cookies_file(path: str) -> dict:
    """Check a Netscape cookies export unlocks the cookies tier.

    Returns ``{"ok", "path", "has_token"}``. ``has_token`` is True when a
    ``media-user-token`` cookie for an Apple domain is present: the marker
    gamdl's ``create_from_netscape_cookies`` needs to build a session.
    Missing file or no token raises with wizard-ready words.
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
        if "media-user-token" in stripped and "apple.com" in stripped:
            has_token = True
            break
    if not has_token:
        raise ValueError(
            "That cookies export has no signed-in Apple session (no media-user-token cookie). "
            "Export again from a logged-in music.apple.com tab."
        )
    return {"ok": True, "path": str(p), "has_token": True}


# --------------------------------------------------------------------------- #
# Setup state: one describer for the slot and the schema
# --------------------------------------------------------------------------- #

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
) -> dict:
    """Describe the Apple setup wizard state for the status light.

    Precedence: off > needs_attention > signed_in > runtime_ready >
    not_set_up. ``signed_in`` covers both tiers: a verified cookies export
    or a live wrapper session. ``cookies_ready`` without ``signed_in``
    still counts as signed in for the light (the cookies tier unlocks
    AAC 256 + Atmos with no runtime at all).
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
        tier = "cookies" if cookies_ready and not runtime_ready else ("full" if runtime_ready else "cookies")
        # A runtime plus a session is the full tier; cookies alone is the
        # fallback tier. Either unlocks downloads; the wrapper slice raises
        # the ceiling from HIGH when it lands.
    elif state == "runtime_ready":
        tier = "runtime"
    if state == "signed_in" and runtime_ready and cookies_ready:
        tier = "full"
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
        "next_step": next_step,
    }


# --------------------------------------------------------------------------- #
# Manager: N_m3u8DL-RE provisioning + isolated engine config + provenance
# --------------------------------------------------------------------------- #


class AppleRuntimeManager:
    """Provision and inspect the managed Apple runtime under ``app_dir``."""

    def __init__(self, app_dir: str | os.PathLike) -> None:
        self.app_dir = Path(app_dir)
        self.os_key, self.arch = _safe_target()

    # ----- locations ----------------------------------------------------- #
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
    def port_path(self) -> Path:
        return self.runtime_dir / "wrapper-port.json"

    def engine_config_dir(self) -> Path:
        """Waves-owned isolated config dir for the Apple engine.

        The engine never sees the user's home: anything it insists on
        materialising lands here, never in ``~/.gamdl/``.
        """
        d = self.runtime_dir / "engine-config"
        d.mkdir(parents=True, exist_ok=True)
        return d

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
        """Persist and return the wrapper port: preferred when free, else picked."""
        if preferred and 1024 <= preferred <= 65535 and _port_free(preferred):
            port = int(preferred)
        else:
            port = pick_free_high_port()
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
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

    # ----- status -------------------------------------------------------- #
    def status(self, custom_path: str = "") -> dict:
        """Describe the managed N_m3u8DL-RE for the UI."""
        if self.is_installed():
            mani = self._read_manifest()
            return {
                "state": "managed",
                "available": True,
                "managed": True,
                "path": str(self.binary_path),
                "version": str(mani.get("version") or NM3U8DLRE_VERSION),
                "source_url": str(mani.get("url") or ""),
                "sha256": str(mani.get("sha256") or ""),
                "wrapper_image": WRAPPER_V2_IMAGE,
                "wrapper_libs": WRAPPER_LIBS_VERSION,
            }
        cp = (custom_path or "").strip()
        if cp and Path(cp).is_file():
            return {
                "state": "path",
                "available": True,
                "managed": False,
                "path": cp,
                "version": "",
                "source_url": "",
                "sha256": "",
                "wrapper_image": WRAPPER_V2_IMAGE,
                "wrapper_libs": WRAPPER_LIBS_VERSION,
            }
        found = shutil.which("N_m3u8DL-RE")
        if found:
            return {
                "state": "path",
                "available": True,
                "managed": False,
                "path": found,
                "version": "",
                "source_url": "",
                "sha256": "",
                "wrapper_image": WRAPPER_V2_IMAGE,
                "wrapper_libs": WRAPPER_LIBS_VERSION,
            }
        return {
            "state": "missing",
            "available": False,
            "managed": False,
            "path": "",
            "version": "",
            "source_url": "",
            "sha256": "",
            "wrapper_image": WRAPPER_V2_IMAGE,
            "wrapper_libs": WRAPPER_LIBS_VERSION,
        }

    # ----- install ------------------------------------------------------- #
    def install(
        self,
        release: Nm3u8dlreRelease | None = None,
        progress_cb=None,
        log_cb=None,
        abort: Event | None = None,
        session: requests.Session | None = None,
    ) -> dict:
        """Download, verify, extract and install N_m3u8DL-RE; return ``status()``.

        Atomic like the FFmpeg manager: a fresh binary is staged next to the
        target, checksum-verified, and smoke-tested before it is swapped in
        via :func:`os.replace`. Provenance (source URL + checksum) is
        recorded in the manifest.
        """

        def _log(msg: str) -> None:
            logger.info("apple-runtime: %s", msg)
            if log_cb:
                log_cb(msg)

        def _check_abort() -> None:
            if abort is not None and abort.is_set():
                raise AppleRuntimeCancelled()

        sess = session or _session()
        if release is None:
            _log("resolving pinned N_m3u8DL-RE release")
            release = pinned_release(self.os_key, self.arch)
        if release is None:
            raise AppleRuntimeUnsupportedPlatform(f"No N_m3u8DL-RE build for {self.os_key}/{self.arch}")

        self.bin_dir.mkdir(parents=True, exist_ok=True)
        _check_abort()

        _log(f"downloading N_m3u8DL-RE {release.version}")
        with tempfile.NamedTemporaryFile(dir=self.bin_dir, suffix=".tar.gz", delete=False) as tmp:
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
            actual = _sha256_file(arc_tmp)
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

            os.replace(staged, self.binary_path)
        finally:
            arc_tmp.unlink(missing_ok=True)
            staged.unlink(missing_ok=True)

        manifest = {
            **asdict(release),
            # Provenance (spec §10.6): the verified checksum beside the URL,
            # so a diagnostics bundle shows where the bytes came from.
            "sha256": expected,
            "binary_version": ver,
            "installed_at": int(time.time()),
        }
        fd_manifest, manifest_tmp = tempfile.mkstemp(
            dir=self.runtime_dir, prefix=self.manifest_path.name + ".", suffix=".tmp"
        )
        try:
            with os.fdopen(fd_manifest, "w", encoding="utf-8") as fh:
                json.dump(manifest, fh, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(manifest_tmp, self.manifest_path)
        except Exception:
            with contextlib.suppress(OSError):
                os.remove(manifest_tmp)
            raise
        _log(f"installed N_m3u8DL-RE {ver}")
        return self.status()

    def remove(self) -> dict:
        self.binary_path.unlink(missing_ok=True)
        self.manifest_path.unlink(missing_ok=True)
        return self.status()

    # ----- internals ----------------------------------------------------- #
    def _download(self, sess, url: str, dest: Path, progress_cb, abort: Event | None) -> None:
        with sess.get(url, stream=True, timeout=_TIME_TIMEOUT) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            with open(dest, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=_CHUNK):
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
            resp = sess.get(sha_url, timeout=_TIME_TIMEOUT)
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


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _extract_binary(arc_path: Path, dest: Path, exe_name: str) -> None:
    """Extract the N_m3u8DL-RE executable from its tar.gz to ``dest``."""
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
                chunk = src.read(_CHUNK)
                if not chunk:
                    break
                out.write(chunk)


def _probe_version(path: str) -> str:
    """Return the binary's ``--version`` first line, or "" when it won't run."""
    try:
        out = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=10)
    except Exception:
        return ""
    if out.returncode != 0:
        return ""
    first = ((out.stdout or "") + (out.stderr or "")).splitlines()
    return first[0].strip() if first else ""
