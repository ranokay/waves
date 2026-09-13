"""The search row is live with Apple enabled and no TIDAL session (J2).

The picker promises "Search works with no account", but the row gated on
``root.signedIn`` alone, so an Apple-only user could not type a query. The
row now gates on "TIDAL signed in or Apple enabled", and the placeholder
names both link types instead of TIDAL's alone.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from support.paths import QML_MAIN
from support.qml import (
    EXIT_NO_QT,
    EXIT_OK,
    EXIT_PRECONDITION,
    EXIT_REGRESSED,
    run_scenario,
    sandbox_qml_settings,
)


@pytest.mark.qml
def test_search_row_is_live_for_an_apple_only_signed_out_user():
    run_scenario(
        Path(__file__),
        "--run-scenario",
        timeout=120,
        sandbox_prefix="waves-apple-only-search-test-",
        failure_message="the Apple-only search row scenario regressed",
        drop=("waves.qt",),
    )


def _run_scenario() -> int:
    try:
        from PySide6.QtCore import QEventLoop, QTimer, QUrl
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtQml import QQmlApplicationEngine, QQmlEngine, QQmlExpression
    except Exception as exc:
        print(f"Qt unavailable: {exc}", file=sys.stderr)
        return EXIT_NO_QT

    app = QGuiApplication.instance() or QGuiApplication([])
    sandbox_qml_settings()
    try:
        from support.offline import PARK_LOGIN_QML, patch_offline

        patch_offline()
        from waves.waves_ui.app import _load_mono
        from waves.waves_ui.backend import WavesBridge
    except Exception as exc:
        print(f"Qt platform/backend unavailable: {exc}", file=sys.stderr)
        return EXIT_NO_QT

    engine = QQmlApplicationEngine()
    bridge = WavesBridge(tidal=None)
    engine.rootContext().setContextProperty("waves", bridge)
    engine.rootContext().setContextProperty("monoFont", _load_mono())
    engine.rootContext().setContextProperty("uiFontFamily", app.font().family())
    engine.load(QUrl.fromLocalFile(str(QML_MAIN)))
    if not engine.rootObjects():
        print("Main.qml failed to load", file=sys.stderr)
        return EXIT_PRECONDITION
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

    if not off_ok:
        print("with TIDAL signed out and Apple off the search row is not inert", file=sys.stderr)
    if not on_ok:
        print("an Apple-only signed-out session did not get a live search row", file=sys.stderr)
    if not back_off_ok:
        print("switching Apple off left the search row live", file=sys.stderr)
    return EXIT_OK if off_ok and on_ok and back_off_ok else EXIT_REGRESSED


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_run_scenario())
