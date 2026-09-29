"""The main window rides ``visibility``, never ``visible`` (issue #547).

Qt treats ``visible`` and ``visibility`` set on one Window as ambiguous and
warns "Conflicting properties 'visible' and 'visibility'" at component level.
The warning fired on a real launch whenever a maximized frame was restored:
the window was initialised ``visible: false`` and the restore then assigned
``visibility = Window.Maximized``, so both were explicitly set and they
conflicted. This scenario boots the real Main.qml twice -- once restoring a
saved maximized frame, once on a fresh install -- and asserts the launch
warning is gone while the window still opens, maximized or windowed.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from support.qml import run_scenario, sandbox_qml_settings


def _scenario(maximized: bool) -> int:
    from PySide6.QtCore import QEventLoop, QTimer, QUrl, qInstallMessageHandler
    from PySide6.QtGui import QGuiApplication, QWindow
    from PySide6.QtQml import QQmlApplicationEngine

    app = QGuiApplication.instance() or QGuiApplication([])
    sandbox_qml_settings()
    from support.offline import patch_offline

    patch_offline()
    from support.paths import QML_MAIN

    from waves.desktop.app import _load_mono
    from waves.desktop.backend import WavesBridge
    from waves.paths import path_config_base

    # Only a saved frame takes the restore path that assigned BOTH properties
    # at startup; a fresh install showed the window through one of them.
    if maximized:
        cfg = path_config_base()
        os.makedirs(cfg, exist_ok=True)
        with open(os.path.join(cfg, "waves.json"), "w", encoding="utf-8") as fh:
            json.dump({"win_x": 130, "win_y": 140, "win_w": 900, "win_h": 700, "win_max": True}, fh)

    engine = QQmlApplicationEngine()
    bridge = WavesBridge(tidal=None)
    engine.rootContext().setContextProperty("waves", bridge)
    engine.rootContext().setContextProperty("monoFont", _load_mono())
    engine.rootContext().setContextProperty("uiFontFamily", app.font().family())

    # Our own handler, installed after the bridge (whose construction routes Qt
    # messages into the app log): an absent handler would collect nothing and
    # pass this guard for the wrong reason.
    messages: list[str] = []
    qInstallMessageHandler(lambda _mode, _ctx, message: messages.append(str(message)))
    try:
        engine.load(QUrl.fromLocalFile(str(QML_MAIN)))
        if not engine.rootObjects():
            print("Main.qml loaded no root object", file=sys.stderr)
            return 1
        root = engine.rootObjects()[0]
        loop = QEventLoop()
        QTimer.singleShot(300, loop.quit)
        loop.exec()

        conflicts = [m for m in messages if "Conflicting properties" in m]
        expected = QWindow.Maximized if maximized else QWindow.Windowed
        problems: list[str] = []
        if conflicts:
            problems.append("the visible/visibility conflict warning is back: " + conflicts[0])
        if not root.property("visible"):
            problems.append("the window did not open")
        if root.property("visibility") != expected:
            problems.append(f"visibility {root.property('visibility')} != {expected}")

        for problem in problems:
            print(f"regressed: {problem}", file=sys.stderr)
        print(f"visible={root.property('visible')} visibility={root.property('visibility')}", flush=True)
        return 0 if not problems else 1
    finally:
        qInstallMessageHandler(None)


@pytest.mark.qml
def test_a_restored_maximized_frame_opens_maximized_without_the_conflict_warning():
    run_scenario(
        Path(__file__),
        "--run-scenario",
        "--maximized",
        timeout=120,
        sandbox_prefix="waves-window-visibility-test-",
        failure_message="the main window conflicted on visible/visibility",
    )


@pytest.mark.qml
def test_a_fresh_launch_opens_windowed_without_the_conflict_warning():
    run_scenario(
        Path(__file__),
        "--run-scenario",
        timeout=120,
        sandbox_prefix="waves-window-visibility-test-",
        failure_message="the main window conflicted on visible/visibility",
    )


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_scenario("--maximized" in sys.argv))
