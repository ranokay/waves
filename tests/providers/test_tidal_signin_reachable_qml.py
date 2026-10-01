"""TIDAL sign-in stays reachable without any latched overlay, with Apple on.

WHAT THIS FENCES OFF
--------------------
1. A sign-in surface covering the app for the rest of the session. With the
   first-run picker answered and Apple off, NOTHING is up: the old latched
   full-window login panel is gone, so a real click on the Settings nav must
   open the page directly. A reintroduced full-window panel fails here.

2. Sign-in being unreachable from the provider card. The TIDAL session row
   carries a SIGN IN action while signed out (see the schema test in
   test_providers_settings_area.py); a real click on that pill must open the
   welcome surface on its inline sign-in steps, NOT start a browser login.

3. The explicit click opening the flow. OPEN BROWSER LOGIN is the only caller
   of beginLogin; a real click on it must open the browser and bring the
   paste field back with it.

4. Sign-out only living in the top bar. The TIDAL session row carries a
   SIGN OUT action while signed in; a real click must end the session and
   fall back to the SIGN IN action through the schema refresh the logout
   signal drives.

Drives the REAL Main.qml with REAL mouse events, so the wiring is what is
under test, not the function behind it.

Runs in a SUBPROCESS like the other Main.qml scenarios: building the bridge
installs process-global handlers that must not leak into the suite.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from support.paths import QML_MAIN
from support.qml import run_scenario
from support.qml_probe import scene_js

_EXIT_OK = 0
_EXIT_REGRESSED = 1
_EXIT_NO_QT = 77
_EXIT_PRECONDITION = 78


def _center(scope: str, predicate: str) -> str:
    """Scene coordinates of the first item matching ``predicate``."""
    return scene_js(
        f"  var hit = findFirst({scope}, function (o) {{ return {predicate}; }});\n"
        "  if (!hit || hit.width <= 0 || hit.height <= 0) return null;\n"
        "  var p = hit.mapToItem(null, hit.width / 2, hit.height / 2);\n"
        "  return (p.x < 0 || p.y < 0) ? null : p;\n"
    )


def _visible(scope: str, predicate: str) -> str:
    """Whether a matching item exists and is itself visible."""
    return scene_js(
        f"  var hit = findFirst({scope}, function (o) {{ return {predicate}; }});\n"
        "  return hit !== null && hit.visible === true;\n"
    )


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


# A provider card's action pill, found by its action key through the
# settings tree, mapped to window coordinates for a real click.
def _pill_point(key: str) -> str:
    return (
        "(function () {"
        "  function find(it) {"
        f"    if (it.actKey !== undefined && String(it.actKey) === '{key}') return it;"
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


@pytest.mark.qml
def test_tidal_signin_stays_reachable_without_a_latched_overlay_and_with_apple_on():
    run_scenario(Path(__file__), "--run-scenario", timeout=120, sandbox_prefix="waves-tidal-signin-test-")


@pytest.mark.qml
def test_tidal_signout_pill_ends_the_session_and_flips_the_card():
    run_scenario(Path(__file__), "--run-signout-scenario", timeout=120, sandbox_prefix="waves-tidal-signout-test-")


def _run_scenario() -> int:
    # THIS checkout's waves, not the venv's editable install.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    try:
        from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer, QUrl
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtQml import QQmlApplicationEngine, QQmlEngine, QQmlExpression
        from PySide6.QtTest import QTest
    except ImportError as exc:
        print(f"PySide6 unavailable: {exc}", file=sys.stderr)
        return _EXIT_NO_QT

    from support.offline import patch_offline
    from support.qml import sandbox_qml_settings

    patch_offline()
    app = QGuiApplication.instance() or QGuiApplication([])
    sandbox_qml_settings()
    try:
        from waves.desktop.app import _load_mono
        from waves.desktop.backend import WavesBridge
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
    # already answered and Apple off: no sign-in surface is up (a started
    # sign-in never latches over the app), so the nav is directly clickable.
    bridge._session_resolved = True
    bridge.sessionResolvedChanged.emit()
    q("setupSettings.firstRunAnswered = true; root.setupMode = 'cards'; root.setupUrlOpened = false")
    settle(200)

    bad: list[str] = []

    if bool(q("providerPicker.visible")) or bool(q("root.setupOpen")) or bool(q("root.setupUrlOpened")):
        print("the scenario needs no sign-in surface up with Settings closed", file=sys.stderr)
        return _EXIT_PRECONDITION

    # 1. A real click on the Settings nav lands with nothing in the way: a
    #    full-window sign-in panel reintroduced here would swallow it.
    point = q(_SETTINGS_TAB_POINT)
    if point is None:
        print("could not locate the Settings nav tab", file=sys.stderr)
        return _EXIT_PRECONDITION
    # The offscreen window needs a mouse move plus a warm-up click before
    # a GateAction reacts; the delayed press/release then lands.
    QTest.mouseMove(root, QPoint(int(point.x()), int(point.y())))
    settle(60)
    QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, QPoint(int(point.x()), int(point.y())))
    settle(80)
    QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, QPoint(int(point.x()), int(point.y())), 40)
    settle(250)
    if not bool(q("root.settingsOpen")):
        bad.append("a sign-in surface swallowed the Settings nav click")

    # 2. With Apple enabled no sign-in surface is up either; the card's
    #    sign-in action opens the welcome page on its inline steps and must
    #    NOT open a browser.
    q('waves.applySettings({"apple_enabled": true})')
    settle(300)
    if bool(q("root.setupUrlOpened")) or bool(q("root.setupMode") != "cards"):
        print("a sign-in surface was up after Apple was enabled", file=sys.stderr)
        return _EXIT_PRECONDITION

    q('settingsPage.jumpToCard("providers_tidal")')
    settle(350)
    point = q(_pill_point("tidal_signin"))
    if point is None:
        print("the TIDAL card exposes no sign-in action", file=sys.stderr)
        return _EXIT_PRECONDITION
    # The offscreen window needs a mouse move plus a warm-up click before
    # a GateAction reacts; the delayed press/release then lands.
    QTest.mouseMove(root, QPoint(int(point.x()), int(point.y())))
    settle(60)
    QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, QPoint(int(point.x()), int(point.y())))
    settle(80)
    QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, QPoint(int(point.x()), int(point.y())), 40)
    settle(400)

    if not bool(q("root.setupOpen")) or bool(q("root.setupMode") != "tidal"):
        bad.append("the card's sign-in action did not open the welcome page on its sign-in steps")
    if bool(q("root.setupUrlOpened")):
        bad.append("the card's sign-in action opened a browser on its own")
    if not q(_visible("setupPane", "o.objectName === 'welcomeSignInOpen'")):
        bad.append("the inline sign-in steps expose no OPEN BROWSER LOGIN action")

    # 3. The explicit click starts the flow, and the paste field comes with
    #    it, with pixels to click.
    open_point = q(_center("setupPane", "o.objectName === 'welcomeSignInOpen'"))
    if open_point is None:
        print("the inline steps expose no OPEN BROWSER LOGIN action", file=sys.stderr)
        return _EXIT_PRECONDITION
    QTest.mouseMove(root, QPoint(int(open_point.x()), int(open_point.y())))
    settle(60)
    QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, QPoint(int(open_point.x()), int(open_point.y())))
    settle(80)
    QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, QPoint(int(open_point.x()), int(open_point.y())), 40)
    settle(1200)

    if not bool(q("root.setupUrlOpened")):
        bad.append("clicking OPEN BROWSER LOGIN did not start the login flow")
    if bool(q("root.setupMode") != "tidal") or not bool(q("root.setupOpen")):
        bad.append("the sign-in surface left while a login was in progress")
    if not q(_visible("setupPane", "o.objectName === 'signInPaste'")):
        bad.append("the sign-in surface came back without the paste field")
    if (
        not float(
            q(
                scene_js(
                    "  var f = findFirst(setupPane, function (o) { return o.objectName === 'signInField'; });\n"
                    "  return f ? f.width * f.height : 0;\n"
                )
            )
        )
        > 0
    ):
        bad.append("the paste field has no pixels to click")

    for line in bad:
        print(f"REGRESSED: {line}", file=sys.stderr)
    return _EXIT_REGRESSED if bad else _EXIT_OK


def _run_signout_scenario() -> int:
    # THIS checkout's waves, not the venv's editable install.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    try:
        from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer, QUrl
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtQml import QQmlApplicationEngine, QQmlEngine, QQmlExpression
        from PySide6.QtTest import QTest
    except ImportError as exc:
        print(f"PySide6 unavailable: {exc}", file=sys.stderr)
        return _EXIT_NO_QT

    from support.offline import patch_offline
    from support.qml import sandbox_qml_settings

    patch_offline()
    app = QGuiApplication.instance() or QGuiApplication([])
    sandbox_qml_settings()
    try:
        from waves.desktop.app import _load_mono
        from waves.desktop.backend import WavesBridge
    except Exception as exc:
        print(f"Qt platform/backend unavailable: {exc}", file=sys.stderr)
        return _EXIT_NO_QT

    engine = QQmlApplicationEngine()
    bridge = WavesBridge(tidal=None)
    # The sign-in flip makes Main re-fetch Browse; keep the scenario offline.
    bridge._browse_root = lambda: {"sections": [], "genres": [], "moods": [], "decades": [], "error": True}
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
    # Let the cached-token check resolve before faking a signed-in state, so
    # the scenario is not racing the bridge's own session worker.
    for _ in range(40):
        if bridge._session_resolved:
            break
        settle(50)
    # A resolved install that is signed in, with the first-run picker
    # answered: no login overlay, and the session card offers sign-out.
    q("setupSettings.firstRunAnswered = true")
    bridge._logged_in = True
    bridge.loggedInChanged.emit()
    settle(150)
    # A signed-in returning user meets the terms gate and the first-run
    # FFmpeg gate (both full-window overlays); this session has already
    # walked past them.
    q("legalSettings.termsAcceptedVersion = root.termsVersion")
    q("legalSettings.termsAccepted = true")
    q("setupSettings.ffmpegSetupDone = true")
    q("ffmpegGate.sessionSnoozed = true")

    # Open Settings directly: this scenario is about the session pill, and
    # the nav click is covered by the reachability scenario above.
    q("root.settingsOpen = true")
    settle(250)
    if not bool(q("root.settingsOpen")) or bool(q("providerPicker.visible")) or bool(q("root.setupOpen")):
        print(
            "the scenario needs Settings open with no sign-in surface"
            f" (settingsOpen={bool(q('root.settingsOpen'))} setupOpen={bool(q('root.setupOpen'))}"
            f" mode={q('root.setupMode')} signedIn={bool(q('root.signedIn'))}"
            f" picker={bool(q('providerPicker.visible'))})",
            file=sys.stderr,
        )
        return _EXIT_PRECONDITION
    q('settingsPage.jumpToCard("providers_tidal")')
    settle(350)

    point = q(_pill_point("tidal_signout"))
    if point is None:
        print("REGRESSED: the signed-in TIDAL card exposes no sign-out action", file=sys.stderr)
        return _EXIT_REGRESSED
    q("root.requestActivate()")
    settle(100)
    # The offscreen window needs a mouse move plus a warm-up click before
    # a GateAction reacts; the delayed press/release then lands.
    QTest.mouseMove(root, QPoint(int(point.x()), int(point.y())))
    settle(60)
    QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, QPoint(int(point.x()), int(point.y())))
    settle(80)
    QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, QPoint(int(point.x()), int(point.y())), 40)
    settle(600)
    if bridge._logged_in:
        # The first synthetic click after the session flip can land on the
        # replaced delegate; re-query and try once more.
        point = q(_pill_point("tidal_signout"))
        if point is not None:
            QTest.mouseMove(root, QPoint(int(point.x()), int(point.y())))
            settle(60)
            QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, QPoint(int(point.x()), int(point.y())), 40)
            settle(500)

    bad: list[str] = []
    if bridge._logged_in:
        bad.append("clicking the card's sign-out action did not sign out")
    if q(_pill_point("tidal_signin")) is None:
        bad.append("the card did not fall back to the sign-in action after sign-out")

    # The Apple row's pill follows the live light: a wrapper sign-in landing
    # while Settings is open adds SIGN OUT without a schema rebuild.
    bridge._apple_live_flags = lambda: {"enabled": True, "signed_in": True, "cookies_ready": True}
    bridge.appleStatusChanged.emit()
    settle(250)
    if q(_pill_point("apple_signout")) is None:
        bad.append("the live Apple light did not add the sign-out action")

    for line in bad:
        print(f"REGRESSED: {line}", file=sys.stderr)
    return _EXIT_REGRESSED if bad else _EXIT_OK


if __name__ == "__main__":
    if "--run-scenario" in sys.argv:
        raise SystemExit(_run_scenario())
    if "--run-signout-scenario" in sys.argv:
        raise SystemExit(_run_signout_scenario())
    raise SystemExit(_EXIT_PRECONDITION)
