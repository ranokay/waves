"""Apple setup guidance.

The Setup wizard pill re-probes the live setup state instead of serving
cached reads that look dead; a denied wrapper-image pull says plainly that
registry access is the problem and what to do; the image step states that
the published image carries the guest libraries, so no APK is asked for.

The re-probe is proved on the real Settings page: the visible "Setup wizard"
pill is clicked and the runtime state channel must show the checking state
and then the refreshed answer while the step column stands.
"""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest
from support.qml import (
    EXIT_OK,
    EXIT_PRECONDITION,
    EXIT_REGRESSED,
    boot_main_qml,
    click_point,
    run_scenario,
)
from support.qml_probe import scene_js

from waves.providers.apple.runtime import (
    WRAPPER_V2_IMAGE,
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


# The first visible object whose action key is the setup refresh, as a scene
# point: the status pill's own action, the way the user reaches it.
_PILL_POINT_BODY = """
    var pill = findFirst(settingsPage, function (o) {
        return o.actKey !== undefined && ("" + o.actKey) === "apple_setup"
            && o.visible !== false && o.width > 0;
    });
    return pill ? pill.mapToItem(null, pill.width / 2, pill.height / 2) : null;
"""

# Bring the pill's row inside the Settings viewport before clicking: the
# providers card is taller than the window and the Apple band sits below it.
_SCROLL_TO_PILL_BODY = """
    var pill = findFirst(settingsPage, function (o) {
        return o.actKey !== undefined && ("" + o.actKey) === "apple_setup"
            && o.visible !== false && o.width > 0;
    });
    if (!pill) return "none";
    var flick = findFirst(settingsPage, function (o) {
        return o.contentY !== undefined && o.contentHeight !== undefined && o.height > 0;
    });
    if (!flick) return "no-flick";
    var y = pill.mapToItem(flick.contentItem, 0, 0).y;
    flick.contentY = Math.max(0, Math.min(y - 200, flick.contentHeight - flick.height));
    return "scrolled";
"""

# Every label the Settings page renders, so the check names the step labels
# the live state says should be there.
_STEPS_BODY = """
    var labels = [];
    function collect(o) {
        if (!o) return;
        if (o.text !== undefined && ("" + o.text).length > 0) labels.push("" + o.text);
        if (o.item) collect(o.item);
        var kids = o.children || [];
        for (var i = 0; i < kids.length; i++) collect(kids[i]);
    }
    collect(settingsPage);
    return JSON.stringify(labels.slice(0, 400));
"""


@pytest.mark.qml
def test_setup_pill_reprobes_the_live_state_and_rebuilds_the_steps():
    run_scenario(
        __file__,
        "--run-scenario",
        timeout=180,
        sandbox_prefix="waves-apple-setup-guidance-",
        failure_message="the Setup wizard pill no longer re-probes the live state",
    )


def _run_scenario() -> int:
    booted = boot_main_qml()
    if isinstance(booted, int):
        return booted
    _root, q, settle, bridge = booted

    q("waves.applySettings({'apple_enabled': true})")
    q("root.refreshAppleEnabled()")
    settle(300)

    states: list[str] = []
    bridge.appleRuntimeStateChanged.connect(lambda *a: states.append(str(a[0]) if a else ""))

    q("settingsOpen = true")
    settle(300)
    q("settingsPage.jumpToCard('providers_apple')")
    settle(500)

    if q(scene_js(_SCROLL_TO_PILL_BODY)) != "scrolled":
        print("the Apple status card exposes no live Setup wizard action", file=sys.stderr)
        return EXIT_PRECONDITION
    settle(300)
    point = q(scene_js(_PILL_POINT_BODY))
    if point is None:
        print("the Setup wizard action has no scene position", file=sys.stderr)
        return EXIT_PRECONDITION
    click_point(_root, point, settle)

    waited = 0
    while "done" not in states and waited < 15_000:
        settle(100)
        waited += 100
    settle(300)  # let the refresh worker finish before the engine tears down

    failures = []
    if "downloading" not in states:
        failures.append(f"the pill's refresh never showed the checking state: {states}")
    if "done" not in states:
        failures.append(f"the pill's refresh never finished: {states}")

    steps = bridge.appleSetupState().get("steps") or []
    if not steps:
        failures.append("the setup wizard built no steps to rebuild")
    else:
        expected = [str(s.get("label", "")) for s in steps]
        rendered = str(q(scene_js(_STEPS_BODY)))
        shown = json.loads(rendered) if rendered else []
        missing = [label for label in expected if label not in shown]
        if missing:
            failures.append(f"the wizard column renders no step(s) {missing} (saw {shown[:12]})")

    if failures:
        for line in failures:
            print(line, file=sys.stderr)
        return EXIT_REGRESSED
    print("ok")
    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    sys.exit(_run_scenario())
