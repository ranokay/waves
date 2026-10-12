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


def button_script(name, *, trigger=False):
    action = "button.clicked(); return true;" if trigger else "return !!button;"
    return scene_js(
        f"""
        var button = findFirst(settingsPage, function(o) {{
            return o.objectName === '{name}' && o.visible === true;
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
    assert q(button_script("appleConfirmRuntimeAccount", trigger=True))
    wait_until(lambda: bridge.appleExecutionState()["state"] == "ready", 5000, message="account admitted")
    assert q(button_script("appleStopExecution", trigger=True))
    wait_until(lambda: bool(q(button_script("appleResumeExecution"))), 5000, message="runtime disconnected")
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
    q("waves.applySettings({apple_lite_container: 'isolated-lite', apple_lite_endpoint: 'http://127.0.0.1:12340'})")
    wait_until(lambda: bool(q(button_script("appleStopLiteRuntime"))), 5000, message="separate lite disconnect visible")
    assert q(button_script("appleStopLiteRuntime", trigger=True))
    wait_until(lambda: bool(q(button_script("appleResumeLiteRuntime"))), 5000, message="lite disconnected")
    assert not bridge.appleExecutionState()["stopped"]
    assert q(button_script("appleResumeLiteRuntime", trigger=True))
    wait_until(lambda: not bridge.appleLiteRuntimeState()["stopped"], 5000, message="lite explicitly reconnected")
    assert bridge.appleLiteRuntimeState()["state"] == "unknown"
    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    sys.exit(run())
