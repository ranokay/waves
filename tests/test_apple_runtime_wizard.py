"""Issue #31: managed runtime + setup wizard (spec section 2, 9.2, 10).

WHAT THIS FENCES OFF
--------------------
Turning Apple on starts the in-place setup wizard: the managed runtime
provisioned FFmpeg-manager style (Waves-built pinned wrapper-v2 image;
N_m3u8DL-RE downloaded, checksum-verified, tar.gz extracted, chmod'd),
Apple ID login + 2FA and the user-supplied APK (pinned version,
SHA-verified, extraction scripted, never fetched/bundled/proxied), with
the cookies-only fallback tier in the same wizard. The status light goes
live (not set up / runtime ready / signed in / needs attention). The
container runtime is detected with a gentle start attempt, never a silent
install. Waves owns its engine configuration surface entirely (no user
engine config file read or mutated); the wrapper runs on a free high port.

The wrapper login + 2FA itself stays human (spec ground rule 6): this
slice ships the runtime provisioning, the APK/cookies verification, the
container detect/guide, the isolated config + free-port plumbing, the
live light, and the wizard state the QML renders. The live wrapper
session (health probe, idle stop) lands with session supervision (#33).
"""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from waves.apple_runtime import (
    APK_PINNED_VERSION,
    NM3U8DLRE_VERSION,
    WRAPPER_V2_IMAGE,
    AppleRuntimeManager,
    apk_extract_plan,
    describe_setup,
    detect_container_runtime,
    gentle_start_command,
    pick_free_high_port,
    pinned_release,
    verify_apk,
    verify_cookies_file,
    wrapper_url,
)
from waves.waves_ui.backend import WavesBridge, _apple_status


def _cookies_file(tmp_path: Path, *, with_token: bool = True) -> str:
    lines = ["# Netscape HTTP Cookie File", ""]
    if with_token:
        lines.append(".apple.com\tTRUE\t/\tTRUE\t0\tmedia-user-token\tabc123")
    else:
        lines.append(".apple.com\tTRUE\t/\tTRUE\t0\tsome-other-cookie\txyz")
    p = tmp_path / "cookies.txt"
    p.write_text("\n".join(lines), encoding="utf-8")
    return str(p)


# ---- pins ------------------------------------------------------------------ #


def test_pins_are_versioned_not_floating():
    assert WRAPPER_V2_IMAGE.count(":") == 1 and WRAPPER_V2_IMAGE.split(":")[1]
    assert NM3U8DLRE_VERSION.startswith("v")
    assert APK_PINNED_VERSION
    rel = pinned_release("macos", "arm64")
    assert rel is not None and rel.version == NM3U8DLRE_VERSION
    assert rel.url.endswith("osx-arm64_20260629.tar.gz")
    assert rel.sha256  # inline pin: the release publishes no checksum sidecars


def test_pin_table_covers_every_desktop_platform_with_a_hash():
    from waves.apple_runtime import NM3U8DLRE_RELEASES, NM3U8DLRE_SHA256

    for platform_key in [
        ("macos", "arm64"),
        ("macos", "amd64"),
        ("linux", "amd64"),
        ("linux", "arm64"),
        ("windows", "amd64"),
        ("windows", "arm64"),
    ]:
        url = NM3U8DLRE_RELEASES[platform_key]
        assert url.startswith("https://github.com/nilaoda/N_m3u8DL-RE/releases/download/")
        assert NM3U8DLRE_VERSION in url
        if platform_key[0] == "windows":
            assert url.endswith(".zip")
        else:
            assert url.endswith(".tar.gz")
        sha = NM3U8DLRE_SHA256[platform_key]
        assert len(sha) == 64 and all(c in "0123456789abcdef" for c in sha)
        rel = pinned_release(*platform_key)
        assert rel is not None and rel.url == url and rel.sha256 == sha


def test_pinned_release_unknown_platform_is_none():
    assert pinned_release("plan9", "sparc") is None


# ---- setup state ------------------------------------------------------------ #


def test_describe_setup_precedence():
    assert describe_setup(enabled=False)["state"] == "off"
    assert describe_setup(enabled=True)["state"] == "not_set_up"
    assert describe_setup(enabled=True, runtime_ready=True)["state"] == "runtime_ready"
    assert describe_setup(enabled=True, cookies_ready=True)["state"] == "signed_in"
    assert describe_setup(enabled=True, signed_in=True)["state"] == "signed_in"
    # Cookies alone unlock the tier with no runtime (spec section 2).
    assert describe_setup(enabled=True, cookies_ready=True)["tier"] == "cookies"
    assert describe_setup(enabled=True, runtime_ready=True, cookies_ready=True)["tier"] == "full"
    # Repair beats everything but off.
    assert describe_setup(enabled=True, signed_in=True, needs_attention=True)["state"] == "needs_attention"
    assert describe_setup(enabled=True, runtime_ready=True, signed_in=True)["state"] == "signed_in"


def test_apple_status_helper_covers_all_five():
    assert _apple_status(False) == {"state": "off", "word": "Off"}
    assert _apple_status(True) == {"state": "not_set_up", "word": "Not set up"}
    assert _apple_status(True, runtime_ready=True) == {"state": "runtime_ready", "word": "Runtime ready"}
    assert _apple_status(True, cookies_ready=True) == {"state": "signed_in", "word": "Signed in"}
    assert _apple_status(True, signed_in=True) == {"state": "signed_in", "word": "Signed in"}
    assert _apple_status(True, signed_in=True, needs_attention=True)["state"] == "needs_attention"


# ---- container runtime ------------------------------------------------------- #


def test_detect_container_prefers_docker_when_running():
    def runner(cmd, **_k):
        assert cmd[:2] == ["docker", "info"]
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    found = detect_container_runtime(runner=runner)
    assert found == {"name": "docker", "available": True, "running": True, "hint": ""}


def test_detect_container_daemon_down_guides_not_installs():
    def runner(cmd, **_k):
        return SimpleNamespace(returncode=1, stdout="", stderr="Cannot connect")

    found = detect_container_runtime(runner=runner)
    assert found["available"] is True and found["running"] is False
    assert "Start" in found["hint"] and "install" not in found["hint"].lower()


def test_detect_container_keeps_probing_past_a_stopped_docker():
    calls = []

    def runner(cmd, **_k):
        calls.append(cmd[0])
        if cmd[0] == "docker":
            return SimpleNamespace(returncode=1, stdout="", stderr="Cannot connect")
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    found = detect_container_runtime(runner=runner)
    assert calls == ["docker", "podman"]
    assert found == {"name": "podman", "available": True, "running": True, "hint": ""}


def test_detect_container_hint_names_the_idle_runtime():
    def runner(cmd, **_k):
        if cmd[0] == "docker":
            raise FileNotFoundError(cmd[0])
        return SimpleNamespace(returncode=1, stdout="", stderr="stopped")

    found = detect_container_runtime(runner=runner)
    assert found["name"] == "podman" and found["running"] is False
    assert "Podman" in found["hint"] and "Docker Desktop" not in found["hint"]


def test_detect_container_absent_guides_to_manual_install():
    def runner(cmd, **_k):
        raise FileNotFoundError(cmd[0])

    found = detect_container_runtime(runner=runner)
    assert found == {
        "name": "",
        "available": False,
        "running": False,
        "hint": (
            "Install Docker Desktop for your platform, start it, then continue setup. Waves never installs it for you."
        ),
    }
    assert "never installs" in found["hint"].lower() or "never installs" in found["hint"]


def test_gentle_start_is_macos_only(monkeypatch):
    import platform as _platform

    monkeypatch.setattr(_platform, "system", lambda: "Darwin")
    assert gentle_start_command() == ["open", "-a", "Docker"]
    monkeypatch.setattr(_platform, "system", lambda: "Linux")
    assert gentle_start_command() is None


# ---- free high port ----------------------------------------------------------- #


def test_picked_port_is_high_and_free():
    port = pick_free_high_port()
    assert 49152 <= port <= 65535
    assert wrapper_url(port) == f"http://127.0.0.1:{port}"


def test_pick_exhausted_high_range_raises():
    with pytest.raises(OSError, match="no free high port"):
        pick_free_high_port(low=65535, high=65534)


def test_manager_ensure_port_prefers_override_when_free(tmp_path):
    mgr = AppleRuntimeManager(tmp_path)
    port = mgr.ensure_port(0)
    assert 1024 <= port <= 65535
    assert mgr.read_port() == port
    # A second ensure with the now-taken persisted port still answers a port.
    again = mgr.ensure_port(port)
    assert 1024 <= again <= 65535


# ---- APK ---------------------------------------------------------------------- #


def test_verify_apk_needs_a_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        verify_apk(str(tmp_path / "nope.apkm"))


def test_verify_apk_rejects_wrong_extension(tmp_path):
    p = tmp_path / "music.txt"
    p.write_bytes(b"hello")
    with pytest.raises(ValueError, match="apk"):
        verify_apk(str(p))


def test_verify_apk_checks_hash_when_pinned(tmp_path):
    p = tmp_path / "music.apkm"
    p.write_bytes(b"fake-apk-bytes")
    digest = hashlib.sha256(b"fake-apk-bytes").hexdigest()
    ok = verify_apk(str(p), expected_sha256=digest)
    assert ok["ok"] is True and ok["sha256"] == digest and ok["hash_pending"] is False
    with pytest.raises(ValueError, match="mismatch"):
        verify_apk(str(p), expected_sha256="0" * 64)


def test_verify_apk_without_pinned_hash_checks_presence(tmp_path):
    p = tmp_path / "music.apk"
    p.write_bytes(b"bytes")
    ok = verify_apk(str(p), expected_sha256="")
    assert ok["ok"] is True and ok["hash_pending"] is True
    assert "pending" in ok["note"]


def test_apk_plan_scripts_extraction_and_names_pin(tmp_path):
    from waves.apple_runtime import APK_SHA256

    plan = apk_extract_plan(str(tmp_path / "music.apkm"))
    assert any(APK_PINNED_VERSION in step for step in plan)
    if APK_SHA256:
        assert any("fail-closed" in step for step in plan)
    else:
        # No pinned hash published: the plan must say so, never claim a
        # check that did not run.
        assert any("pending" in step for step in plan)
    assert any("Waves never fetches" in verify_apk(str(_apk(tmp_path)), expected_sha256="")["note"] for _ in [0])


def test_apk_plan_with_pinned_hash_claims_the_check():
    plan = apk_extract_plan("/m.apkm", hash_pinned=True)
    assert any("fail-closed" in step for step in plan)
    pending = apk_extract_plan("/m.apkm", hash_pinned=False)
    assert any("pending" in step for step in pending)


def _apk(tmp_path: Path) -> str:
    p = tmp_path / "pinned.apkm"
    p.write_bytes(b"x")
    return str(p)


# ---- cookies ------------------------------------------------------------------- #


def test_verify_cookies_accepts_signed_in_export(tmp_path):
    path = _cookies_file(tmp_path, with_token=True)
    assert verify_cookies_file(path) == {"ok": True, "path": path, "has_token": True}


def test_verify_cookies_rejects_export_without_token(tmp_path):
    with pytest.raises(ValueError, match="media-user-token"):
        verify_cookies_file(_cookies_file(tmp_path, with_token=False))


def test_verify_cookies_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        verify_cookies_file(str(tmp_path / "missing.txt"))


# ---- manager: provisioning ------------------------------------------------------- #


def _make_tarball(exe_name: str, payload: bytes = b"#!/bin/sh\necho v0\n") -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = tarfile.TarInfo(name=f"dist/{exe_name}")
        info.size = len(payload)
        info.mode = 0o755
        tf.addfile(info, io.BytesIO(payload))
    return buf.getvalue()


def _make_zip(exe_name: str, payload: bytes = b"MZ-fake-binary") -> bytes:
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr(exe_name, payload)
    return buf.getvalue()


def test_extract_reads_tar_gz_and_zip(tmp_path):
    from waves.apple_runtime import _exe_name, _extract_binary

    mgr = AppleRuntimeManager(tmp_path)
    exe = _exe_name(mgr.os_key or "macos")
    tar_dest, zip_dest = tmp_path / "from-tar", tmp_path / "from-zip"
    tarball, zipped = tmp_path / "a.tar.gz", tmp_path / "b.zip"
    tarball.write_bytes(_make_tarball(exe, b"tar-payload"))
    zipped.write_bytes(_make_zip("N_m3u8DL-RE.exe", b"zip-payload"))
    _extract_binary(tarball, tar_dest, exe)
    assert tar_dest.read_bytes() == b"tar-payload"
    _extract_binary(zipped, zip_dest, "N_m3u8DL-RE.exe")
    assert zip_dest.read_bytes() == b"zip-payload"


def test_extract_rejects_unknown_format(tmp_path):
    from waves.apple_runtime import _extract_binary

    blob = tmp_path / "a.7z"
    blob.write_bytes(b"nope")
    with pytest.raises(ValueError, match="unsupported"):
        _extract_binary(blob, tmp_path / "out", "N_m3u8DL-RE")


class _Resp:
    def __init__(self, payload: bytes):
        self._payload = payload
        self.headers = {"Content-Length": str(len(payload))}

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=1 << 16):
        yield self._payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Sess:
    def __init__(self, payload: bytes, sha_hex: str):
        self._payload = payload
        self._sha = sha_hex

    def get(self, url, **_k):
        if url.endswith(".sha256"):
            return SimpleNamespace(text=f"{self._sha}  archive.tar.gz\n", raise_for_status=lambda: None)
        return _Resp(self._payload)


def test_install_verifies_extracts_chmods_and_records_provenance(tmp_path, monkeypatch):
    from waves.apple_runtime import _exe_name

    mgr = AppleRuntimeManager(tmp_path)
    exe = _exe_name(mgr.os_key or "macos")
    blob = _make_tarball(exe)
    sha = hashlib.sha256(blob).hexdigest()
    monkeypatch.setattr("waves.apple_runtime._probe_version", lambda path: "0.7.3")
    status = mgr.install(
        release=__import__("waves.apple_runtime", fromlist=["Nm3u8dlreRelease"]).Nm3u8dlreRelease(
            version=NM3U8DLRE_VERSION,
            url="https://example.invalid/N.tar.gz",
            sha256_url="https://example.invalid/N.tar.gz.sha256",
        ),
        session=_Sess(blob, sha),
    )
    assert status["state"] == "managed" and status["available"] is True
    assert mgr.is_installed()
    import os as _os

    assert _os.access(mgr.binary_path, _os.X_OK)
    mani = json.loads(mgr.manifest_path.read_text(encoding="utf-8"))
    assert mani["url"].endswith(".tar.gz") and mani["sha256"] == sha


def test_install_fails_closed_without_checksum(tmp_path):
    from waves.apple_runtime import Nm3u8dlreRelease

    mgr = AppleRuntimeManager(tmp_path)
    blob = _make_tarball("N_m3u8DL-RE")

    class _NoSha(_Sess):
        def get(self, url, **_k):
            if url.endswith(".sha256"):
                raise ConnectionError("sidecar gone")
            return _Resp(self._payload)

    with pytest.raises(ValueError, match="no checksum"):
        mgr.install(
            release=Nm3u8dlreRelease(
                version="v0", url="https://example.invalid/N.tar.gz", sha256_url="https://x/s.tar.gz.sha256"
            ),
            session=_NoSha(blob, ""),
        )
    assert not mgr.is_installed()


def test_install_rejects_checksum_mismatch(tmp_path):
    from waves.apple_runtime import Nm3u8dlreRelease

    mgr = AppleRuntimeManager(tmp_path)
    blob = _make_tarball("N_m3u8DL-RE")
    with pytest.raises(ValueError, match="mismatch"):
        mgr.install(
            release=Nm3u8dlreRelease(version="v0", url="https://example.invalid/N.tar.gz", sha256="1" * 64),
            session=_Sess(blob, "2" * 64),
        )
    assert not mgr.is_installed()


def test_remove_clears_binary_and_manifest(tmp_path, monkeypatch):
    from waves.apple_runtime import Nm3u8dlreRelease, _exe_name

    mgr = AppleRuntimeManager(tmp_path)
    blob = _make_tarball(_exe_name(mgr.os_key or "macos"))
    monkeypatch.setattr("waves.apple_runtime._probe_version", lambda path: "0.7.3")
    mgr.install(
        release=Nm3u8dlreRelease(
            version="v", url="https://example.invalid/N.tar.gz", sha256=hashlib.sha256(blob).hexdigest()
        ),
        session=_Sess(blob, hashlib.sha256(blob).hexdigest()),
    )
    assert mgr.is_installed()
    assert mgr.remove()["state"] in ("missing", "path")


# ---- config isolation -------------------------------------------------------------- #


def test_engine_config_lives_under_app_dir_not_home(tmp_path, monkeypatch):
    mgr = AppleRuntimeManager(tmp_path)
    monkeypatch.setenv("HOME", "/nonexistent-home-for-test")
    d = mgr.engine_config_dir()
    assert str(d).startswith(str(tmp_path))
    assert ".gamdl" not in str(d)
    env = mgr.engine_env(port=51234)
    assert env["WAVES_APPLE_WRAPPER_URL"] == "http://127.0.0.1:51234"
    assert env["XDG_CONFIG_HOME"] == str(d)


def test_no_apple_module_touches_user_gamdl_config():
    # Waves owns its engine config surface: no Apple path may resolve a file
    # under the user's home gamdl config. Mentions in comments/docstrings
    # (documenting the ban) are fine; filesystem access is not.
    root = Path(__file__).resolve().parent.parent / "waves"
    hits = []
    for path in [*(root).rglob("apple*.py"), root / "providers" / "apple.py"]:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for marker in ("Path.home()", '"~/.gamdl', "'~/.gamdl", ".gamdl/config", "config.ini"):
            if marker in text:
                # The runtime module names the banned path only to say it
                # never touches it; that is the one allowed mention.
                if path.name == "apple_runtime.py" and marker in ("config.ini", ".gamdl/config"):
                    continue
                hits.append(f"{path.name}: {marker}")
    assert hits == []


# ---- bridge: live light --------------------------------------------------------------- #


def _bridge_stub(tmp_path: Path, *, enabled=True, cookies=""):
    from waves.model.cfg import Settings as ModelSettings

    stub = SimpleNamespace()
    data = ModelSettings()
    data.apple_enabled = enabled
    data.apple_cookies_path = cookies
    data.path_binary_nm3u8dlre = ""
    stub.settings = SimpleNamespace(data=data)
    stub.providers = {}
    stub._apple_runtime = AppleRuntimeManager(tmp_path)
    stub._apple_runtime_ready = WavesBridge._apple_runtime_ready.__get__(stub, SimpleNamespace)
    stub._apple_needs_attention = WavesBridge._apple_needs_attention.__get__(stub, SimpleNamespace)
    stub._apple_cookies_ready = WavesBridge._apple_cookies_ready.__get__(stub, SimpleNamespace)
    stub._apple_live_flags = WavesBridge._apple_live_flags.__get__(stub, SimpleNamespace)
    # GUI-thread callers read the cached probe, never a live subprocess:
    # tests pin the cache instead of touching the machine's runtimes.
    stub._apple_container_cache = {"at": 0.0, "result": None}
    stub._refresh_apple_container_cache = WavesBridge._refresh_apple_container_cache.__get__(stub, SimpleNamespace)
    stub._apple_container_state = WavesBridge._apple_container_state.__get__(stub, SimpleNamespace)
    stub.appleStatus = WavesBridge.appleStatus.__get__(stub, SimpleNamespace)
    stub.appleSetupState = WavesBridge.appleSetupState.__get__(stub, SimpleNamespace)
    stub._apple_wizard_steps = WavesBridge._apple_wizard_steps
    return stub


def test_fresh_machine_light_is_not_set_up(tmp_path):
    stub = _bridge_stub(tmp_path, enabled=True, cookies="")
    assert stub.appleStatus() == {"state": "not_set_up", "word": "Not set up"}


def test_cookies_path_alone_unlocks_signed_in_without_runtime(tmp_path):
    stub = _bridge_stub(tmp_path, enabled=True, cookies=_cookies_file(tmp_path, with_token=True))
    stub.providers["apple"] = SimpleNamespace(cookies_path=stub.settings.data.apple_cookies_path)
    assert stub.appleStatus() == {"state": "signed_in", "word": "Signed in"}
    state = stub.appleSetupState()
    assert state["light"]["tier"] == "cookies"
    assert state["cookies"]["verified"] is True
    assert state["runtime"]["state"] in ("missing", "path")


def test_stale_cookies_export_needs_attention(tmp_path):
    stub = _bridge_stub(tmp_path, enabled=True, cookies=_cookies_file(tmp_path, with_token=False))
    stub.providers["apple"] = SimpleNamespace(cookies_path=stub.settings.data.apple_cookies_path)
    assert stub.appleStatus() == {"state": "needs_attention", "word": "Needs attention"}


def test_missing_saved_cookies_file_needs_attention(tmp_path):
    stub = _bridge_stub(tmp_path, enabled=True, cookies=str(tmp_path / "gone.txt"))
    stub.providers["apple"] = SimpleNamespace(cookies_path=stub.settings.data.apple_cookies_path)
    assert stub.appleStatus() == {"state": "needs_attention", "word": "Needs attention"}


def test_managed_runtime_alone_is_runtime_ready(tmp_path, monkeypatch):
    from waves.apple_runtime import Nm3u8dlreRelease, _exe_name

    mgr = AppleRuntimeManager(tmp_path)
    blob = _make_tarball(_exe_name(mgr.os_key or "macos"))
    monkeypatch.setattr("waves.apple_runtime._probe_version", lambda path: "0.7.3")
    mgr.install(
        release=Nm3u8dlreRelease(
            version="v", url="https://example.invalid/N.tar.gz", sha256=hashlib.sha256(blob).hexdigest()
        ),
        session=_Sess(blob, hashlib.sha256(blob).hexdigest()),
    )
    stub = _bridge_stub(tmp_path, enabled=True, cookies="")
    assert stub.appleStatus() == {"state": "runtime_ready", "word": "Runtime ready"}


def test_setup_state_carries_wizard_pins_and_high_port(tmp_path):
    stub = _bridge_stub(tmp_path, enabled=True, cookies="")
    state = stub.appleSetupState()
    assert state["wrapper"]["image"] == WRAPPER_V2_IMAGE
    assert state["apk"]["pinned_version"] == APK_PINNED_VERSION
    assert state["light"]["next_step"]
    port = state["wrapper"]["port"]
    assert port == 0 or 1024 <= port <= 65535


def test_resolve_prefers_override_then_managed(tmp_path, monkeypatch):
    from waves.apple_runtime import Nm3u8dlreRelease, _exe_name

    stub = _bridge_stub(tmp_path)
    stub._resolve_apple_nm3u8dlre = WavesBridge._resolve_apple_nm3u8dlre.__get__(stub, SimpleNamespace)
    assert stub._resolve_apple_nm3u8dlre() == ""
    stub.settings.data.path_binary_nm3u8dlre = "/custom/N_m3u8DL-RE"
    assert stub._resolve_apple_nm3u8dlre() == "/custom/N_m3u8DL-RE"
    stub.settings.data.path_binary_nm3u8dlre = ""
    mgr = stub._apple_runtime
    blob = _make_tarball(_exe_name(mgr.os_key or "macos"))
    monkeypatch.setattr("waves.apple_runtime._probe_version", lambda path: "0.7.3")
    mgr.install(
        release=Nm3u8dlreRelease(
            version="v", url="https://example.invalid/N.tar.gz", sha256=hashlib.sha256(blob).hexdigest()
        ),
        session=_Sess(blob, hashlib.sha256(blob).hexdigest()),
    )
    assert stub._resolve_apple_nm3u8dlre() == str(mgr.binary_path)


# ---- wrapper image -------------------------------------------------------------- #


def _ok_runner(seen):
    def run(cmd, **_k):
        seen.append(cmd)
        return SimpleNamespace(returncode=0, stdout="Pulled", stderr="")

    return run


def test_ensure_image_pulls_the_pinned_tag_and_records_it(tmp_path):
    mgr = AppleRuntimeManager(tmp_path)
    assert mgr.image_pulled() is False
    seen = []
    mani = mgr.ensure_image(runner=_ok_runner(seen))
    assert seen == [["docker", "pull", WRAPPER_V2_IMAGE]]
    assert mani["image"] == WRAPPER_V2_IMAGE
    assert mgr.image_pulled() is True


def test_ensure_image_failure_raises_and_records_nothing(tmp_path):
    mgr = AppleRuntimeManager(tmp_path)

    def failing(cmd, **_k):
        return SimpleNamespace(returncode=1, stdout="", stderr="no such image")

    with pytest.raises(RuntimeError, match="Could not pull"):
        mgr.ensure_image(runner=failing)
    assert mgr.image_pulled() is False


def test_ensure_image_uses_the_detected_compatible_binary(tmp_path):
    mgr = AppleRuntimeManager(tmp_path)
    seen = []
    mgr.ensure_image(runner=_ok_runner(seen), binary="podman")
    assert seen == [["podman", "pull", WRAPPER_V2_IMAGE]]


# ---- wizard steps ----------------------------------------------------------------- #


def _steps(**over):
    base = {
        "enabled": True,
        "cookies_path": "",
        "cookies_verified": False,
        "cookies_error": "",
        "runtime_state": "missing",
        "container": {"name": "", "available": False, "running": False, "hint": "Install Docker Desktop"},
        "apk_path": "",
        "apk_verified": False,
        "apk_hash_pending": False,
        "apk_error": "",
        "image_pulled": False,
        "port": 0,
    }
    base.update(over)
    return {s["key"]: s for s in WavesBridge._apple_wizard_steps(**base)}


def test_fresh_machine_steps_walk_in_order():
    steps = _steps(enabled=True)
    assert list(steps) == ["enable", "cookies", "runtime", "container", "image", "apk", "port"]
    assert steps["enable"]["state"] == "done"
    assert steps["cookies"]["state"] == "todo" and steps["cookies"]["action"] == ""
    assert steps["runtime"]["action"] == "apple_update_runtime"
    assert steps["container"]["action"] == ""  # absent runtime: guide only, never install
    assert steps["image"]["action"] == "apple_pull_image"
    assert steps["port"]["action"] == "apple_ensure_port"


def test_container_step_offers_the_gentle_start_when_idle():
    steps = _steps(container={"name": "docker", "available": True, "running": False, "hint": "Start Docker Desktop"})
    assert steps["container"]["state"] == "todo"
    assert steps["container"]["action"] == "apple_start_container"


def test_container_running_and_runtime_managed_are_done():
    steps = _steps(
        cookies_verified=True,
        runtime_state="managed",
        container={"name": "docker", "available": True, "running": True, "hint": ""},
        image_pulled=True,
        port=51234,
    )
    assert steps["cookies"]["state"] == "done"
    assert steps["runtime"]["state"] == "done"
    assert steps["container"]["state"] == "done" and steps["container"]["action"] == ""
    assert steps["image"]["state"] == "done"
    assert steps["port"]["state"] == "done" and steps["port"]["action"] == ""


def test_stale_cookies_and_bad_apk_are_attention():
    steps = _steps(cookies_path="/c.txt", cookies_error="no token", apk_path="/m.apkm", apk_error="bad hash")
    assert steps["cookies"]["state"] == "attention"
    assert steps["apk"]["state"] == "attention"


def test_setup_state_carries_steps_plan_image_and_login_hint(tmp_path):
    stub = _bridge_stub(tmp_path, enabled=True, cookies="")
    state = stub.appleSetupState()
    assert [s["key"] for s in state["steps"]] == ["enable", "cookies", "runtime", "container", "image", "apk", "port"]
    assert any(APK_PINNED_VERSION in step for step in state["apk"]["extract_plan"])
    assert state["wrapper"]["image_pulled"] is False
    assert "2FA" in state["wrapper"]["login_hint"]


def test_apk_without_pinned_hash_stays_open_not_done(tmp_path):
    apk = tmp_path / "music.apkm"
    apk.write_bytes(b"bytes")
    stub = _bridge_stub(tmp_path, enabled=True, cookies="")
    stub.settings.data.apple_apk_path = str(apk)
    state = stub.appleSetupState()
    assert state["apk"]["verified"] is False
    assert state["apk"]["hash_pending"] is True
    apk_step = next(s for s in state["steps"] if s["key"] == "apk")
    assert apk_step["state"] == "todo"


def test_container_state_caches_for_gui_callers(tmp_path, monkeypatch):
    calls = []

    def fake_detect(timeout=10):
        calls.append(timeout)
        return {"name": "", "available": False, "running": False, "hint": ""}

    monkeypatch.setattr("waves.apple_runtime.detect_container_runtime", fake_detect)
    stub = _bridge_stub(tmp_path, enabled=True, cookies="")
    stub.appleSetupState()
    stub.appleSetupState()
    assert calls == [3]  # cold probe once, short GUI timeout; the second read rides the cache


def test_container_refresh_uses_the_full_timeout(tmp_path, monkeypatch):
    calls = []

    def fake_detect(timeout=10):
        calls.append(timeout)
        return {"name": "docker", "available": True, "running": True, "hint": ""}

    monkeypatch.setattr("waves.apple_runtime.detect_container_runtime", fake_detect)
    stub = _bridge_stub(tmp_path, enabled=True, cookies="")
    stub._refresh_apple_container_cache(timeout=10)
    assert calls == [10]
    # A fresh cache is returned as-is with no new probe.
    stub._apple_container_state()
    assert calls == [10]


def test_pre_setup_download_click_routes_into_the_wizard(tmp_path):
    seen = []
    provider = SimpleNamespace(cookies_path="")
    stub = SimpleNamespace(
        providers={"apple": provider},
        settings=SimpleNamespace(data=SimpleNamespace(apple_cookies_path="")),
        appleSetupRequested=SimpleNamespace(emit=lambda reason: seen.append(reason)),
        downloadState=SimpleNamespace(emit=lambda *a: None),
    )
    stub._set_status = lambda text: seen.append(text)
    stub._apple_cookies_ready = WavesBridge._apple_cookies_ready.__get__(stub, SimpleNamespace)
    WavesBridge._download_apple(stub, "track", {}, None, "{artist_name}/{track_title}", False, "apple:song-1")
    assert "cookies" in seen
