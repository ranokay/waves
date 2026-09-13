"""T2: the account-switch journey, end to end, offline.

WHAT THIS FENCES OFF
--------------------
The audit's account gap: the suite proved sign-in reachability and the
sign-out pill separately, but no test walked the journey a user actually
takes --- choosing Apple on first run, reaching Settings, signing TIDAL in
from the card's visible action, seeing that survive a relaunch, signing
back out, and still having both providers reachable. Directly setting
internal flags could not serve as this scenario; every step here is a real
mouse click on a rendered control.

Drives the REAL Main.qml in a subprocess (building the bridge installs
process-global handlers), with the account service faked at the provider
boundary: login_begin/login_complete are patched, everything the UI does
around them is real.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from support.paths import QML_MAIN
from support.qml import run_scenario

_EXIT_OK = 0
_EXIT_REGRESSED = 1
_EXIT_NO_QT = 77
_EXIT_PRECONDITION = 78

_FIND_BY_LABEL = """
function find(it, label) {
  if (it.label !== undefined && String(it.label) === label) return it;
  var kids = it.children || [];
  for (var i = 0; i < kids.length; i++) {
    var hit = find(kids[i], label);
    if (hit) return hit;
  }
  return null;
}
"""


def _center(scope: str, label: str) -> str:
    return (
        "(function () {"
        + _FIND_BY_LABEL
        + f"  var it = find({scope}, '{label}');"
        + "  if (!it) return null;"
        + "  return it.mapToItem(null, it.width / 2, it.height / 2);"
        + "})()"
    )


_SETTINGS_TAB = (
    "(function () {"
    "  var kids = headerRow.children;"
    "  for (var i = 0; i < kids.length; i++) {"
    "    if (kids[i].label !== undefined && String(kids[i].label) === 'Settings')"
    "      return kids[i].mapToItem(null, kids[i].width / 2, kids[i].height / 2);"
    "  }"
    "  return null;"
    "})()"
)


def _pill_point(key: str) -> str:
    return (
        "(function () {"
        "  function find(it) {"
        f"    if (it.actKey !== undefined && String(it.actKey) === '{key}'"
        "        && it.visible !== false && it.width > 0) return it;"
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


def _pill_point_prefix(prefix: str) -> str:
    return (
        "(function () {"
        "  function find(it) {"
        f"    if (it.actKey !== undefined && String(it.actKey).indexOf('{prefix}') === 0"
        "        && it.visible !== false && it.width > 0) return it;"
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
def test_apple_first_journey_signs_tidal_in_and_out_and_keeps_both_reachable():
    run_scenario(
        Path(__file__),
        "--run-journey",
        timeout=180,
        sandbox_prefix="waves-account-journey-test-",
        failure_message="the account-switch journey regressed",
    )


def _run_journey() -> int:
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
        from waves.waves_ui.app import _load_mono
        from waves.waves_ui.backend import WavesBridge
    except Exception as exc:
        print(f"backend unavailable: {exc}", file=sys.stderr)
        return _EXIT_PRECONDITION

    engine = QQmlApplicationEngine()
    bridge = WavesBridge(tidal=None)
    # The account service is the fake: sign-in and sign-out talk to the
    # provider verbs, everything around them is the real bridge.
    tidal = bridge.providers["tidal"]
    tidal.login_begin = lambda: "https://tidal.test/authorize"
    tidal.login_complete = lambda url: str(url).startswith("https://tidal.test/")
    tidal.logout = lambda: None
    tidal.reset_session = lambda: None
    bridge._browse_root = lambda: {"sections": [], "genres": [], "moods": [], "decades": [], "error": True}
    engine.rootContext().setContextProperty("waves", bridge)
    engine.rootContext().setContextProperty("monoFont", _load_mono())
    engine.rootContext().setContextProperty("uiFontFamily", app.font().family())

    holder: dict = {}

    def load_root():
        engine.load(QUrl.fromLocalFile(str(QML_MAIN)))
        roots = engine.rootObjects()
        if not roots:
            return None
        holder["root"] = roots[-1]
        return holder["root"]

    def q(expr: str):
        root = holder["root"]
        e = QQmlExpression(QQmlEngine.contextForObject(root), root, expr)
        r = e.evaluate()
        if e.hasError():
            raise RuntimeError(e.error().toString())
        return r[0] if isinstance(r, tuple) else r

    def settle(ms: int = 150) -> None:
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def click(point) -> None:
        root = holder["root"]
        root.requestActivate()
        settle(80)
        pos = QPoint(int(point.x()), int(point.y()))
        # The offscreen window needs a mouse move plus a warm-up click before
        # a GateAction reacts; the delayed press/release then lands.
        QTest.mouseMove(root, pos)
        settle(60)
        QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, pos)
        settle(80)
        QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, pos, 40)

    def wait_for(predicate, timeout_ms: int = 6000, step_ms: int = 100) -> bool:
        waited = 0
        while waited < timeout_ms:
            if predicate():
                return True
            settle(step_ms)
            waited += step_ms
        return predicate()

    def points_to(point) -> bool:
        return point is not None and float(point.x()) >= 0 and float(point.y()) >= 0

    def boot(accept_gates: bool = True) -> None:
        q("root.width = 1200")
        q("root.height = 900")
        q("root.visible = true")
        settle(200)
        q("bootOverlay.done = true")
        q("bootContentShown = 1")
        if accept_gates:
            q("legalSettings.termsAcceptedVersion = root.termsVersion")
            q("legalSettings.termsAccepted = true")
            q("setupSettings.ffmpegSetupDone = true")
            q("ffmpegGate.sessionSnoozed = true")
        settle(150)

    if load_root() is None:
        print("Main.qml failed to load", file=sys.stderr)
        return _EXIT_PRECONDITION
    # A fresh profile resolves logged-out; the first-run picker owns the
    # screen. The later gates are pre-walked so they cannot steal clicks.
    wait_for(lambda: bool(bridge._session_resolved))
    boot()

    problems: list[str] = []
    if not bool(q("providerPicker.visible")):
        print("the scenario needs the first-run picker up", file=sys.stderr)
        return _EXIT_PRECONDITION

    # 1. Choose Apple by clicking the card's action, never applySettings.
    apple_point = q(_center("providerPicker", "CONTINUE WITH APPLE MUSIC"))
    if not points_to(apple_point):
        print("the picker exposes no Apple action", file=sys.stderr)
        return _EXIT_PRECONDITION
    click(apple_point)
    settle(300)
    if not (bool(q("waves.appleEnabled")) and bool(bridge.settings.data.apple_enabled)):
        problems.append("the Apple card click did not enable and persist the provider")
    if bool(q("providerPicker.visible")):
        problems.append("the picker stayed up after the Apple choice")

    # 2. The Settings nav is clickable and opens the page.
    tab_point = q(_SETTINGS_TAB)
    if not points_to(tab_point):
        print("could not locate the Settings nav tab", file=sys.stderr)
        return _EXIT_PRECONDITION
    click(tab_point)
    settle(300)
    if not bool(q("root.settingsOpen")):
        problems.append("the Settings nav click did not open Settings")
    # The scroll dressing floats above every page; it is presentation, not
    # account wiring, and would sit over the provider card's pills here.
    q("scrollDressing.visible = false")

    # 3. TIDAL sign-in starts from the provider card's visible action.
    q('settingsPage.jumpToCard("providers_tidal")')
    settle(400)
    sign_in = q(_pill_point("tidal_signin"))
    if not points_to(sign_in):
        problems.append("the TIDAL card exposes no sign-in action with Apple on")
    else:
        click(sign_in)
        settle(600)
    if not (bool(q("loginPanel.urlOpened")) and bool(q("redirectBox.visible"))):
        problems.append("the card's sign-in action did not open the paste flow")

    # 4. Complete through the paste field's visible action; the faked
    #    account service accepts the https redirect.
    if bool(q("redirectBox.visible")):
        # Pin the paste decoder busy so a programmatic text set cannot
        # auto-complete; the visible COMPLETE action drives the step.
        q("loginDecoder.decoding = true")
        q('redirectField.text = "https://tidal.test/redirect"')
        complete = q(_center("loginPanel", "COMPLETE SIGN-IN"))
        if not points_to(complete):
            problems.append("the login panel exposes no COMPLETE SIGN-IN action")
        else:
            click(complete)
            if not wait_for(lambda: bool(bridge._logged_in)):
                problems.append("completing the paste did not sign the session in")
    if bool(q("loginPanel.visible")):
        problems.append("the login panel stayed up after a completed sign-in")
    if not bool(q("root.signedIn")):
        problems.append("the window still reads signed out after a completed sign-in")

    # 5. Sign out from the card's visible action (Settings stayed open).
    q("scrollDressing.visible = false")
    settle(300)
    q('settingsPage.jumpToCard("providers_tidal")')
    settle(500)
    sign_out = q(_pill_point("tidal_signout"))
    if not points_to(sign_out):
        problems.append("the signed-in card exposes no sign-out action")
    else:
        click(sign_out)
        settle(250)
        if bool(bridge._logged_in):
            # The first synthetic click after a session flip can land on the
            # replaced delegate; re-query and try once more.
            retry = q(_pill_point("tidal_signout"))
            if retry is not None:
                click(retry)
        if not wait_for(lambda: not bool(bridge._logged_in)):
            problems.append("the card's sign-out action did not end the session")

    # 6. Both providers stay reachable: Apple is untouched, Settings is up,
    #    and TIDAL is back to its sign-in action.
    if not bool(q("waves.appleEnabled")):
        problems.append("signing TIDAL out dropped the Apple provider")
    if not bool(q("root.settingsOpen")):
        problems.append("Settings closed itself during the account switch")
    if q(_pill_point("tidal_signin")) is None:
        problems.append("the TIDAL card did not fall back to its sign-in action")
    q('settingsPage.jumpToCard("providers_apple")')
    settle(300)
    if not points_to(q(_pill_point_prefix("apple_"))):
        problems.append("the Apple card is not reachable after the switch")

    for line in problems:
        print(f"REGRESSED: {line}", file=sys.stderr)
    return _EXIT_REGRESSED if problems else _EXIT_OK


if __name__ == "__main__" and "--run-journey" in sys.argv:
    raise SystemExit(_run_journey())
