"""Startup provider picker.

First run offers the provider choice instead of dropping straight into the
TIDAL browser login: a picker overlay with the official marks, TIDAL
continuing into the login panel, Apple Music enabling the provider (its
setup wizard opens itself), "Not now" falling back to the passive panel.
Answered once and persisted; nothing ever opens a browser on its own
(beginLogin stays click-only).

Runs offscreen through the real bridge on a temp config: fresh installs
resolve logged-out with Apple off, which is exactly the picker state.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from support.paths import QML_MAIN
from support.qml import run_scenario
from support.qml_probe import scene_js


def _scenario() -> int:  # noqa: C901 (one straight scenario)
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from PySide6.QtCore import QEventLoop, QTimer, QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine, QQmlEngine, QQmlExpression

    app = QGuiApplication.instance() or QGuiApplication([])
    from support.offline import patch_offline
    from support.qml import sandbox_qml_settings

    patch_offline()
    sandbox_qml_settings()
    from waves.waves_ui.app import _load_mono
    from waves.waves_ui.backend import WavesBridge

    engine = QQmlApplicationEngine()
    bridge = WavesBridge(tidal=None)
    engine.rootContext().setContextProperty("waves", bridge)
    engine.rootContext().setContextProperty("monoFont", _load_mono())
    engine.rootContext().setContextProperty("uiFontFamily", app.font().family())
    engine.load(QUrl.fromLocalFile(str(QML_MAIN)))
    if not engine.rootObjects():
        raise RuntimeError("Main.qml loaded no root object")
    root = engine.rootObjects()[0]
    root.setProperty("width", 1100)
    root.setProperty("height", 900)

    def q(expression: str):
        context = QQmlEngine.contextForObject(root)
        value = QQmlExpression(context, root, expression)
        result = value.evaluate()
        if value.hasError():
            raise RuntimeError(value.error().toString())
        return result[0] if isinstance(result, tuple) else result

    def settle(timeout_ms: int = 300) -> None:
        loop = QEventLoop()
        QTimer.singleShot(timeout_ms, loop.quit)
        loop.exec()

    settle()
    # Deterministic session state, no network timing: a fresh install that
    # resolved logged-out with Apple off.
    bridge._session_resolved = True
    bridge.sessionResolvedChanged.emit()
    settle(100)

    # First run: the picker owns the screen, the TIDAL panel stays hidden,
    # and no browser opened on its own. The card logos render at tile size,
    # not source pixels (issue #84: RowLayout ignores width/height); the
    # marks now live inside the welcome component, so find them by name.
    def _logo_width(name: str) -> str:
        return scene_js(
            'var hit = findFirst(root, function (o) { return o.objectName === "'
            + name
            + '"; }); return hit ? hit.width : -1;'
        )

    problems: list[str] = []
    if not q("providerPicker.visible"):
        problems.append("the first-run welcome did not show")
    if q("loginPanel.visible") or q("loginPanel.urlOpened"):
        problems.append("the TIDAL panel was up before any choice")
    if q("waves.appleEnabled"):
        problems.append("Apple was enabled before any choice")
    if q(_logo_width("tidalPickLogo")) != 30:
        problems.append(f"the TIDAL mark rendered {q(_logo_width('tidalPickLogo'))} wide, not 30")
    if q(_logo_width("applePickLogo")) != 22:
        problems.append(f"the Apple mark rendered {q(_logo_width('applePickLogo'))} wide, not 22")

    # Choosing TIDAL lands on the login panel (still click-to-open).
    q("setupSettings.firstRunAnswered = true; root.setupChoiceTidal = true")
    settle(100)
    if q("providerPicker.visible"):
        problems.append("the welcome stayed up after choosing TIDAL")
    if not q("loginPanel.visible") or q("loginPanel.urlOpened"):
        problems.append("choosing TIDAL did not raise the click-to-open login panel")

    # Choosing Apple enables the provider (persisted) and never shows the
    # TIDAL panel; the setup wizard opens itself off the flip signal.
    q("setupSettings.firstRunAnswered = false; root.setupChoiceTidal = false")
    settle(50)
    q('waves.applySettings({"apple_enabled": true})')
    settle(200)
    if q("providerPicker.visible"):
        problems.append("the welcome stayed up after enabling Apple")
    if q("loginPanel.visible"):
        problems.append("the TIDAL panel showed with Apple enabled")
    if not q("waves.appleEnabled") or bridge.settings.data.apple_enabled is not True:
        problems.append("choosing Apple did not persist the enable")

    if problems:
        for line in problems:
            print(line, file=sys.stderr)
        return 1
    return 0


@pytest.mark.qml
def test_first_run_offers_the_provider_choice_and_never_auto_opens_login():
    run_scenario(Path(__file__), "--run-scenario", timeout=120, sandbox_prefix="waves-picker-test-")


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_scenario())
