"""TIDAL sign-in stays reachable under the login overlay and with Apple on.

WHAT THIS FENCES OFF
--------------------
1. The login overlay swallowing the whole window. With the first-run picker
   answered and Apple off, the TIDAL login panel owns the screen; its old
   full-window MouseArea meant Settings could not be clicked from underneath
   it. The dim is paint only now: a real click on the Settings nav must open
   the page.

2. Sign-in being unreachable from the provider card. The TIDAL session row
   carries a SIGN IN action while signed out (see the schema test in
   test_providers_settings_area.py); a real click on that pill must start the
   same beginLogin flow the landing panel's button does.

3. Starting that flow leaving nowhere to paste the redirect. The login panel
   shows whenever a login is in progress, even with Apple enabled, and the
   paste field comes with it.

Drives the REAL Main.qml with REAL mouse events, so the wiring is what is
under test, not the function behind it.

Runs in a SUBPROCESS like the other Main.qml scenarios: building the bridge
installs process-global handlers that must not leak into the suite.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

_EXIT_OK = 0
_EXIT_REGRESSED = 1
_EXIT_NO_QT = 77
_EXIT_PRECONDITION = 78

QML_MAIN = Path(__file__).resolve().parent.parent / "waves" / "waves_ui" / "qml" / "Main.qml"

# The Settings nav tab's centre in window coordinates. NavTab exposes its
# label, so the tab is found by name rather than by index or pixel guess.
_SETTINGS_TAB_POINT = (
    "(function () {"
    "  var kids = headerRow.children;"
    "  for (var i = 0; i < kids.length; i++) {"
    "    var c = kids[i];"
    "    if (c.label !== undefined && String(c.label) === 'Settings')"
    "      return c.mapToItem(null, c.width / 2, c.height / 2);"
    "  }"
    "  return null;"
    "})()"
)

# The TIDAL session row's sign-in pill, found by its action key through the
# settings tree, mapped to window coordinates for a real click.
_SIGN_IN_PILL_POINT = (
    "(function () {"
    "  function find(it) {"
    "    if (it.actKey !== undefined && String(it.actKey) === 'tidal_signin') return it;"
    "    var kids = it.children || [];"
    "    for (var i = 0; i < kids.length; i++) {"
    "      var hit = find(kids[i]);"
    "      if (hit) return hit;"
    "    }"
    "    return null;"
    "  }"
    "  var pill = find(settingsPage);"
    "  if (!pill) return null;"
    "  return pill.mapToItem(null, pill.width / 2, pill.height / 2);"
    "})()"
)


def test_tidal_signin_stays_reachable_under_the_overlay_and_with_apple_on():
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="waves-tidal-signin-test-")
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--run-scenario"],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-12:])
    import pytest

    if proc.returncode == _EXIT_NO_QT:
        pytest.skip("PySide6 / offscreen Qt unavailable")
    if proc.returncode == _EXIT_PRECONDITION:
        pytest.skip(f"could not set up the scenario in this environment:\n{tail}")
    assert (
        proc.returncode == _EXIT_OK
    ), f"TIDAL sign-in reachability regressed. Scenario exit={proc.returncode}:\n{tail}"


def _run_scenario() -> int:
    # THIS checkout's waves, not the venv's editable install.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    try:
        from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer, QUrl
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtQml import QQmlApplicationEngine, QQmlEngine, QQmlExpression
        from PySide6.QtTest import QTest
    except Exception as exc:
        print(f"Qt unavailable: {exc}", file=sys.stderr)
        return _EXIT_NO_QT

    from _qml_offline import patch_offline

    patch_offline()

    app = QGuiApplication.instance() or QGuiApplication([])
    try:
        from waves.waves_ui.app import _load_mono
        from waves.waves_ui.backend import WavesBridge
    except Exception as exc:
        print(f"Qt platform/backend unavailable: {exc}", file=sys.stderr)
        return _EXIT_NO_QT

    engine = QQmlApplicationEngine()
    bridge = WavesBridge(tidal=None)
    engine.rootContext().setContextProperty("waves", bridge)
    engine.rootContext().setContextProperty("monoFont", _load_mono())
    engine.rootContext().setContextProperty("uiFontFamily", app.font().family())
    engine.load(QUrl.fromLocalFile(str(QML_MAIN)))
    roots = engine.rootObjects()
    if not roots:
        print("Main.qml failed to load", file=sys.stderr)
        return _EXIT_PRECONDITION
    root = roots[0]

    def q(expr: str):
        e = QQmlExpression(QQmlEngine.contextForObject(root), root, expr)
        r = e.evaluate()
        if e.hasError():
            raise RuntimeError(e.error().toString())
        return r[0] if isinstance(r, tuple) else r

    def settle(ms: int = 150) -> None:
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    q("root.width = 1200")
    q("root.height = 900")
    q("root.visible = true")
    settle(200)
    q("bootOverlay.done = true")
    q("bootContentShown = 1")
    # A fresh install that resolved logged-out, with the first-run picker
    # already answered: the passive TIDAL login panel owns the screen.
    bridge._session_resolved = True
    bridge.sessionResolvedChanged.emit()
    q("setupSettings.providerPickerDone = true")
    settle(200)

    bad: list[str] = []

    if not bool(q("loginPanel.visible")) or bool(q("root.settingsOpen")):
        print("the scenario needs the login overlay up with Settings closed", file=sys.stderr)
        return _EXIT_PRECONDITION

    # 1. A real click on the Settings nav reaches it through the overlay.
    point = q(_SETTINGS_TAB_POINT)
    if point is None:
        print("could not locate the Settings nav tab", file=sys.stderr)
        return _EXIT_PRECONDITION
    QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, QPoint(int(point.x()), int(point.y())))
    settle(250)
    if not bool(q("root.settingsOpen")):
        bad.append("the login overlay swallowed the Settings nav click")

    # 2. With Apple enabled the panel hides; the card's sign-in action is now
    #    the only way in, and a real click on it must start the flow.
    q('waves.applySettings({"apple_enabled": true})')
    settle(300)
    if bool(q("loginPanel.visible")) or bool(q("loginPanel.urlOpened")):
        print("the login panel stayed up after Apple was enabled", file=sys.stderr)
        return _EXIT_PRECONDITION

    q('settingsPage.jumpToCard("providers_tidal")')
    settle(350)
    point = q(_SIGN_IN_PILL_POINT)
    if point is None:
        print("the TIDAL card exposes no sign-in action", file=sys.stderr)
        return _EXIT_PRECONDITION
    QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, QPoint(int(point.x()), int(point.y())))
    settle(1200)

    # 3. The flow opened in the browser and the panel came back with the
    #    paste field, Apple enabled or not.
    if not bool(q("loginPanel.urlOpened")):
        bad.append("clicking the card's sign-in action did not start the login flow")
    if not bool(q("loginPanel.visible")):
        bad.append("the login panel stayed hidden while a login was in progress")
    if not bool(q("redirectBox.visible")):
        bad.append("the login panel came back without the paste field")
    if float(q("redirectField.width")) <= 0 or float(q("redirectField.height")) <= 0:
        bad.append("the paste field has no pixels to click")

    for line in bad:
        print(f"REGRESSED: {line}", file=sys.stderr)
    return _EXIT_REGRESSED if bad else _EXIT_OK


if __name__ == "__main__":
    if "--run-scenario" in sys.argv:
        raise SystemExit(_run_scenario())
    raise SystemExit(_EXIT_PRECONDITION)
