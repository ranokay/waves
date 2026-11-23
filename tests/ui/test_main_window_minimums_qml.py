"""Main-window minimums follow the window screen (QML-06 / issue #501).

The fixed 880x560 minimums overflow small high-DPI displays (a 1366x768
panel at 150% scaling offers ~910x512 logical pixels). The minimums must be
the content floors capped by the window screen's available geometry x 0.9,
so the frame -- status bar included -- fits on screen. This scenario boots
the real Main.qml offscreen and asserts the wiring: each minimum equals
min(floor, screen cap) for the screen the test environment reports.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest
from support.paths import QML_MAIN
from support.qml import run_scenario, sandbox_qml_settings


def _scenario() -> int:
    from PySide6.QtCore import QEventLoop, QTimer, QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine, QQmlEngine, QQmlExpression

    app = QGuiApplication.instance() or QGuiApplication([])
    sandbox_qml_settings()
    from support.offline import patch_offline

    patch_offline()
    from waves.desktop.app import _load_mono
    from waves.desktop.backend import WavesBridge

    engine = QQmlApplicationEngine()
    bridge = WavesBridge(tidal=None)
    engine.rootContext().setContextProperty("waves", bridge)
    engine.rootContext().setContextProperty("monoFont", _load_mono())
    engine.rootContext().setContextProperty("uiFontFamily", app.font().family())
    engine.load(QUrl.fromLocalFile(str(QML_MAIN)))
    if not engine.rootObjects():
        raise RuntimeError("Main.qml loaded no root object")
    root = engine.rootObjects()[0]

    def q(expression: str):
        context = QQmlEngine.contextForObject(root)
        value = QQmlExpression(context, root, expression)
        result = value.evaluate()
        if value.hasError():
            raise RuntimeError(value.error().toString())
        return result[0] if isinstance(result, tuple) else result

    loop = QEventLoop()
    QTimer.singleShot(300, loop.quit)
    loop.exec()

    width_floor = int(root.property("widthFloor"))
    height_floor = int(root.property("heightFloor"))
    minimum_w = int(root.property("minimumWidth"))
    minimum_h = int(root.property("minimumHeight"))

    # The window's own screen, the same quantity the caps bind to: the host
    # primary/available geometry is a different screen on multi-monitor and a
    # different quantity wherever a taskbar is reserved.
    screen_w = int(q("Screen.width"))
    screen_h = int(q("Screen.height"))

    problems: list[str] = []
    if width_floor < 880:
        problems.append(f"widthFloor {width_floor} undercuts the 880 header floor")
    if height_floor != 560:
        problems.append(f"heightFloor {height_floor} != 560 cap")

    cap_w = math.floor(screen_w * 0.9) if screen_w > 0 else width_floor
    cap_h = math.floor(screen_h * 0.9) if screen_h > 0 else height_floor
    if minimum_w != min(width_floor, cap_w):
        problems.append(
            f"minimumWidth {minimum_w} != min(widthFloor {width_floor}, screen cap {cap_w}) at {screen_w}px reported"
        )
    if minimum_h != min(height_floor, cap_h):
        problems.append(
            f"minimumHeight {minimum_h} != min(heightFloor {height_floor}, screen cap {cap_h}) at {screen_h}px reported"
        )
    if minimum_w > width_floor or minimum_h > height_floor:
        problems.append("a screen cap raised a minimum above its floor")

    for problem in problems:
        print(f"regressed: {problem}", file=sys.stderr)
    print(
        f"minimums {minimum_w}x{minimum_h} from floors {width_floor}x{height_floor} at {screen_w}x{screen_h} reported",
        flush=True,
    )
    return 0 if not problems else 1


@pytest.mark.qml
def test_main_window_minimums_follow_the_screen():
    run_scenario(Path(__file__), "--run-scenario", timeout=120, sandbox_prefix="waves-window-minimums-test-")


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_scenario())
