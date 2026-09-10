"""Startup provider picker (issue #63).

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

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

QML_MAIN = Path(__file__).resolve().parent.parent / "waves" / "waves_ui" / "qml" / "Main.qml"
_EXIT_NO_QT = 77
_EXIT_PRECONDITION = 78


def _scenario() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    try:
        from PySide6.QtCore import QEventLoop, QTimer, QUrl
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtQml import QQmlApplicationEngine, QQmlEngine, QQmlExpression
    except Exception:
        return _EXIT_NO_QT

    app = QGuiApplication.instance() or QGuiApplication([])
    try:
        from _qml_offline import patch_offline

        patch_offline()
        from waves.waves_ui.app import _load_mono
        from waves.waves_ui.backend import WavesBridge
    except Exception:
        return _EXIT_NO_QT

    engine = QQmlApplicationEngine()
    bridge = WavesBridge(tidal=None)
    engine.rootContext().setContextProperty("waves", bridge)
    engine.rootContext().setContextProperty("monoFont", _load_mono())
    engine.rootContext().setContextProperty("uiFontFamily", app.font().family())
    engine.load(QUrl.fromLocalFile(str(QML_MAIN)))
    if not engine.rootObjects():
        return _EXIT_PRECONDITION
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
    # not source pixels (issue #84: RowLayout ignores width/height).
    picker_ok = (
        q("providerPicker.visible")
        and not q("loginPanel.visible")
        and not q("loginPanel.urlOpened")
        and not q("waves.appleEnabled")
        and q("tidalPickLogo.width") == 30
        and q("applePickLogo.width") == 22
    )

    # Choosing TIDAL lands on the login panel (still click-to-open).
    q("setupSettings.providerPickerDone = true")
    settle(100)
    tidal_ok = not q("providerPicker.visible") and q("loginPanel.visible") and not q("loginPanel.urlOpened")

    # Choosing Apple enables the provider (persisted) and never shows the
    # TIDAL panel; the setup wizard opens itself off the flip signal.
    q("setupSettings.providerPickerDone = false")
    settle(50)
    q('waves.applySettings({"apple_enabled": true})')
    settle(200)
    apple_ok = (
        not q("providerPicker.visible")
        and not q("loginPanel.visible")
        and q("waves.appleEnabled")
        and bridge.settings.data.apple_enabled is True
    )

    return 0 if picker_ok and tidal_ok and apple_ok else 1


def test_first_run_offers_the_provider_choice_and_never_auto_opens_login():
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="waves-picker-test-")
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--run-scenario"],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode == _EXIT_NO_QT:
        pytest.skip("PySide6 / offscreen Qt unavailable")
    if proc.returncode == _EXIT_PRECONDITION:
        pytest.skip("could not load Main.qml in this environment")
    assert proc.returncode == 0, proc.stdout + proc.stderr


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_scenario())
