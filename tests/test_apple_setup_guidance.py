"""Apple setup guidance (issue #62).

The Setup wizard pill re-probes the live setup state instead of serving
cached reads that look dead; a denied wrapper-image pull says plainly that
registry access is the problem and what to do; the image step states that
the published image carries the guest libraries, so no APK is asked for.
"""

from __future__ import annotations

from types import SimpleNamespace

from waves.apple_runtime import (
    APK_PINNED_VERSION,
    WRAPPER_LIBS_VERSION,
    WRAPPER_V2_IMAGE,
    apk_extract_plan,
    describe_image_pull_error,
)


def test_denied_pull_names_registry_access_and_the_fix():
    denied = RuntimeError(
        "Could not pull ghcr.io/ranokay/waves-wrapper-v2:0.2.3: Error response from daemon: "
        'Head "https://ghcr.io/v2/ranokay/waves-wrapper-v2/manifests/0.2.3": denied'
    )
    msg = describe_image_pull_error(denied)
    assert "denied" in msg
    assert "docker login ghcr.io" in msg
    assert WRAPPER_V2_IMAGE in msg
    assert "manifests/0.2.3" in msg  # the original error is kept, not swallowed


def test_unauthorized_pull_gets_the_same_guidance():
    msg = describe_image_pull_error(RuntimeError("unauthorized: authentication required"))
    assert "docker login ghcr.io" in msg


def test_generic_pull_failure_keeps_the_old_shape():
    msg = describe_image_pull_error(RuntimeError("no such image"))
    assert msg.startswith(f"Could not pull {WRAPPER_V2_IMAGE}:")
    assert "no such image" in msg


def test_apk_plan_names_version_source_splits_and_libs():
    plan = apk_extract_plan("/m.apkm", hash_pinned=True)
    assert any(APK_PINNED_VERSION in step for step in plan)
    assert any("APKMirror" in step for step in plan)
    assert any("Waves never downloads" in step for step in plan)
    assert any("split" in step for step in plan)
    assert any(WRAPPER_LIBS_VERSION in step for step in plan)


def _wizard_steps(**over):
    from waves.waves_ui.backend import WavesBridge

    base = {
        "enabled": True,
        "cookies_path": "",
        "cookies_verified": False,
        "cookies_error": "",
        "runtime_state": "missing",
        "container": {"name": "", "available": False, "running": False, "hint": "Install Docker Desktop"},
        "wrapper_auth": {},
        "image_pulled": False,
        "port": 0,
    }
    base.update(over)
    base.setdefault("port_dirty", False)
    return {s["key"]: s for s in WavesBridge._apple_wizard_steps(**base)}


def test_image_step_warns_about_registry_access_up_front():
    detail = _wizard_steps()["image"]["detail"]
    assert "docker login ghcr.io" in detail


def test_image_step_names_the_baked_libraries_not_an_apk():
    detail = _wizard_steps()["image"]["detail"]
    assert "no APK" in detail
    steps = _wizard_steps()
    assert "apk" not in steps


def test_refresh_setup_reprobes_and_rebuilds_the_wizard():
    from waves.waves_ui.backend import WavesBridge

    seen = []
    stub = SimpleNamespace()
    stub._refresh_apple_container_cache = lambda timeout=10: seen.append(("probe", timeout)) or {"running": False}
    stub.appleRuntimeStateChanged = SimpleNamespace(emit=lambda *a: seen.append(("state", *a)))
    stub.appleRuntimeStatusChanged = SimpleNamespace(emit=lambda *a: seen.append(("status",)))
    stub.appleStatusChanged = SimpleNamespace(emit=lambda *a: seen.append(("light",)))
    WavesBridge.refreshAppleSetup.__get__(stub, type(stub))()
    kinds = [s[0] for s in seen]
    assert ("probe", 10) in seen
    assert kinds[0] == "state" and seen[0][1] == "downloading"  # visible checking first
    assert "status" in kinds and "light" in kinds  # both mirrors rebuild
    assert kinds[-1] == "state" and seen[-1][1] == "done"  # refreshed, not lingering


def test_setup_pill_and_step_action_refresh_instead_of_rereading():
    from pathlib import Path

    qml = (Path(__file__).resolve().parent.parent / "waves" / "waves_ui" / "qml" / "SettingsPage.qml").read_text()
    assert qml.count("waves.refreshAppleSetup()") >= 2  # status pill + wizard step action
