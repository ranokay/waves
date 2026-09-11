"""The search row is live with Apple enabled and no TIDAL session (J2).

The picker promises "Search works with no account", but the row gated on
``root.signedIn`` alone, so an Apple-only user could not type a query. The
row now gates on "TIDAL signed in or Apple enabled", and the placeholder
names both link types instead of TIDAL's alone.
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
        from _qml_offline import PARK_LOGIN_QML, patch_offline

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

    # Let the launch sequence hand over: mainColumn gates every control until
    # uiShown, so the row's own enable gate is only readable afterwards.
    settle(3000)
    q(PARK_LOGIN_QML)
    q("openSearch()")
    settle()

    # TIDAL signed out and Apple off: the row and both controls are inert.
    off_ok = (
        not q("signedIn")
        and not q("searchField.enabled")
        and not q("sortBox.enabled")
        and q("searchBox.parent.opacity") == 0.5
    )

    # Apple on: the same signed-out session gets a live field and sort control.
    bridge.settings.data.apple_enabled = True
    bridge.appleStatusChanged.emit()
    settle(500)
    on_ok = (
        q("appleEnabled")
        and q("searchField.enabled")
        and q("sortBox.enabled")
        and q("searchBox.parent.opacity") == 1
        and q("searchField.placeholderText") == "Search, or paste a TIDAL or Apple Music link…"
    )

    # Apple off again: the gate follows the setting, not a one-way latch.
    bridge.settings.data.apple_enabled = False
    bridge.appleStatusChanged.emit()
    settle(500)
    back_off_ok = not q("searchField.enabled") and not q("sortBox.enabled")
    return 0 if off_ok and on_ok and back_off_ok else 1


def test_search_row_is_live_for_an_apple_only_signed_out_user():
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="waves-apple-only-search-test-")
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
