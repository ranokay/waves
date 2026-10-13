"""Settings exposes explicit account admission and runtime disconnect actions."""

import sys

import pytest
from support.qml import EXIT_OK, boot_main_qml, run_scenario, wait_until
from support.qml_probe import scene_js

from waves.providers.apple.runtime import AppleRuntimeCancelled
from waves.providers.apple.supervision import RuntimeIdentity


@pytest.mark.qml
def test_settings_runtime_confirmation_disconnect_and_reconnect():
    run_scenario(
        __file__,
        "--run-scenario",
        timeout=120,
        sandbox_prefix="waves-runtime-controls-",
        failure_message="Apple runtime controls failed",
    )


def button_script(name, *, trigger=False, visible_only=True):
    # Absence checks include hidden controls to fence off unused subtrees;
    # actions still select the visible instance.
    visibility = " && o.visible === true" if visible_only else ""
    action = "button.clicked(); return true;" if trigger else "return !!button;"
    return scene_js(
        f"""
        var button = findFirst(settingsPage, function(o) {{
            return o.objectName === '{name}'{visibility};
        }});
        if (!button) return false;
    """
        + action
    )


def run() -> int:
    booted = boot_main_qml()
    if isinstance(booted, int):
        return booted
    _, q, _, bridge = booted
    restored = []
    bridge.appleRuntimeStatusChanged.connect(lambda: restored.append(True))
    q("waves.bootRevealed()")
    wait_until(
        lambda: bool(restored) and not bridge.appleExecutionState()["stopped"],
        5000,
        message="runtime stop choice restored",
    )
    bridge.apple_wrapper_auth_state = lambda **kwargs: {
        "reachable": True,
        "state": "authenticated",
        "logged_in": True,
        "account": "",
        "error": "",
    }
    bridge._apple_supervisor.observe_identity = lambda *args: RuntimeIdentity(True, "isolated-runtime")
    q(
        "waves.applySettings({apple_enabled: true, apple_runtime_mode: 'user_managed', apple_wrapper_url: 'http://127.0.0.1:50100'})"
    )
    bridge._apple_wrapper_auth_cache = {
        "result": bridge.apple_wrapper_auth_state(),
        "runtime_revision": "isolated-runtime",
    }
    bridge._apple_engine_facts()
    q("settingsOpen = true; settingsPage.jumpToCard('providers_apple')")
    bridge.appleRuntimeStatusChanged.emit()
    wait_until(
        lambda: bool(q(button_script("appleConfirmRuntimeAccount"))), 5000, message="account confirmation visible"
    )
    for name in (
        "appleResumeExecution",
        "appleCancelRuntimeSetup",
        "appleRollbackRuntime",
        "appleRollbackImage",
        "appleCheckLiteRuntime",
        "appleCancelLiteRuntimeProbe",
        "appleConfirmLiteRuntimeAccount",
        "appleStopLiteRuntime",
        "appleResumeLiteRuntime",
        "appleRuntimeLoginForm",
    ):
        assert not q(button_script(name, visible_only=False)), name
    q("settingsPage.appleLoginOpen = true")
    wait_until(lambda: bool(q(button_script("appleRuntimeLoginForm"))), 5000, message="sign-in form opened")
    q("settingsPage.appleLoginOpen = false")
    wait_until(
        lambda: not q(button_script("appleRuntimeLoginForm", visible_only=False)),
        5000,
        message="closed sign-in form unloaded",
    )
    q("settingsPage.appleLoginPass = 'isolated-test-secret'; settingsPage.appleLogin2fa = '123456'")
    q("settingsPage.appleWrapperLive = ({logged_in: true})")
    assert q("settingsPage.appleLoginPass === '' && settingsPage.appleLogin2fa === ''")
    assert q(button_script("appleConfirmRuntimeAccount", trigger=True))
    wait_until(lambda: bridge.appleExecutionState()["state"] == "ready", 5000, message="account admitted")
    assert q(button_script("appleStopExecution", trigger=True))
    wait_until(lambda: bool(q(button_script("appleResumeExecution"))), 5000, message="runtime disconnected")
    assert not q(button_script("appleStopExecution", visible_only=False))
    assert q(button_script("appleResumeExecution", trigger=True))
    wait_until(lambda: not bridge.appleExecutionState()["stopped"], 5000, message="explicit reconnect")
    bridge._apple_runtime_abort.clear()
    states = []
    bridge.appleRuntimeStateChanged.connect(lambda state, message: states.append(state))

    def cancellable_install(*, abort, **kwargs):
        if not abort.wait(5):
            raise AssertionError("Setup cancellation did not reach the transfer")
        raise AppleRuntimeCancelled()

    bridge._apple_runtime.install = cancellable_install
    q("waves.installAppleRuntime()")
    wait_until(lambda: bool(q(button_script("appleCancelRuntimeSetup"))), 5000, message="setup cancellation visible")
    assert q(button_script("appleCancelRuntimeSetup", trigger=True))
    wait_until(lambda: not bridge.appleExecutionState()["setup_busy"], 5000, message="setup cancellation finished")
    assert "cancelled" in states
    wait_until(
        lambda: not q(button_script("appleCancelRuntimeSetup", visible_only=False)),
        5000,
        message="finished setup cancellation unloaded",
    )
    q("waves.applySettings({apple_lite_container: 'isolated-lite', apple_lite_endpoint: 'http://127.0.0.1:12340'})")
    wait_until(lambda: bool(q(button_script("appleStopLiteRuntime"))), 5000, message="separate lite disconnect visible")
    assert not q(button_script("appleResumeLiteRuntime", visible_only=False))
    assert q(button_script("appleStopLiteRuntime", trigger=True))
    wait_until(lambda: bool(q(button_script("appleResumeLiteRuntime"))), 5000, message="lite disconnected")
    assert not q(button_script("appleStopLiteRuntime", visible_only=False))
    assert not q(button_script("appleCheckLiteRuntime", visible_only=False))
    assert not bridge.appleExecutionState()["stopped"]
    assert q(button_script("appleResumeLiteRuntime", trigger=True))
    wait_until(lambda: not bridge.appleLiteRuntimeState()["stopped"], 5000, message="lite explicitly reconnected")
    assert bridge.appleLiteRuntimeState()["state"] == "unknown"
    wait_until(lambda: bool(q(button_script("appleStopLiteRuntime"))), 5000, message="lite disconnect restored")
    assert not q(button_script("appleResumeLiteRuntime", visible_only=False))
    q("settingsPage.setSectionOpen('providers', false)")
    wait_until(
        lambda: (
            not q(button_script("appleStopExecution", visible_only=False))
            and not q(button_script("appleStopLiteRuntime", visible_only=False))
        ),
        5000,
        message="collapsed runtime controls unloaded",
    )
    q("settingsPage.jumpToCard('providers_apple')")
    wait_until(
        lambda: bool(q(button_script("appleStopExecution"))) and bool(q(button_script("appleStopLiteRuntime"))),
        5000,
        message="reopened runtime controls restored",
    )
    q("settingsPage.jumpToCard('downloads')")
    wait_until(
        lambda: bool(q(button_script("settingsStepper_downloads_concurrent_max"))),
        5000,
        message="integer settings control visible",
    )
    assert q(
        scene_js(
            """
            var stepper = findFirst(settingsPage, function(o) {
                return o.objectName === 'settingsStepper_downloads_concurrent_max' && o.visible === true;
            });
            if (!stepper) return false;
            stepper.changed(3);
            return true;
            """
        )
    )
    assert q("settingsPage.val({key: 'downloads_concurrent_max'})") == 3
    q("settingsPage.setSectionOpen('downloads', false)")
    wait_until(
        lambda: not q(button_script("settingsStepper_downloads_concurrent_max", visible_only=False)),
        5000,
        message="collapsed integer control unloaded",
    )
    q("settingsPage.jumpToCard('downloads')")
    wait_until(
        lambda: bool(q(button_script("settingsStepper_downloads_concurrent_max"))),
        5000,
        message="integer control restored",
    )
    assert q("settingsPage.val({key: 'downloads_concurrent_max'})") == 3
    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    sys.exit(run())
