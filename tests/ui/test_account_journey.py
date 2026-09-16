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

import json
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


# The inline TIDAL sign-in's paste field, found by objectName inside whichever
# welcome surface is on screen (the first-run gate or the page). The decoder
# is a non-visual QtObject reached through the box, so pinning `decoding`
# keeps a programmatic text set from auto-completing while the visible
# COMPLETE SIGN-IN action drives the step.
def _pin_paste(scope: str, text: str) -> str:
    return scene_js(
        f"  var b = findFirst({scope}, function (o) {{ return o.objectName === 'signInPaste'; }});\n"
        "  if (!b) return false;\n"
        "  b.pasteDecoder.decoding = true;\n"
        "  var f = findFirst(b, function (o) { return o.objectName === 'signInField'; });\n"
        "  if (!f) return false;\n"
        f"  f.text = {json.dumps(text)};\n"
        "  return true;\n"
    )


# The Apple provider band's enable switch, found by its status column (the
# one whose switch row reads "Enable Apple Music"), scrolled into view.
_SWITCH_FIND = """
  function hasText(it, text) {
    if (!it) return false;
    if (it.text === text) return true;
    var kids = it.children || [];
    for (var i = 0; i < kids.length; i++) if (hasText(kids[i], text)) return true;
    return false;
  }
  function collect(it, out) {
    if (!it) return out;
    if (it.hasSwitch === true && hasText(it, "Enable Apple Music")) out.push(it);
    var kids = it.children || [];
    for (var i = 0; i < kids.length; i++) collect(kids[i], out);
    return out;
  }
  var cols = collect(settingsPage, []);
  var col = cols.length ? cols[0] : null;
  var sw = col ? findFirst(col, function (o) { return typeof o.toggle === "function"; }) : null;
"""

_SCROLL_TO_APPLE_SWITCH = scene_js(_SWITCH_FIND + """
  if (!sw) return "none";
  var flick = findFirst(settingsPage, function (o) {
    return o.contentY !== undefined && o.contentHeight !== undefined && o.height > 0;
  });
  if (flick) {
    var y = sw.mapToItem(flick.contentItem, 0, 0).y;
    var maxY = Math.max(0, flick.contentHeight - flick.height);
    flick.contentY = Math.max(0, Math.min(y - flick.height / 2, maxY));
  }
  return "scrolled";
""")

_APPLE_SWITCH = scene_js(_SWITCH_FIND + """
  if (!sw) return null;
  return sw.mapToItem(null, sw.width / 2, sw.height / 2);
""")


def _text_point(text: str) -> str:
    """The scene centre of the first Text with this exact string."""
    return scene_js(
        f"  var t = findFirst(settingsPage, function (o) {{ return o.text === {json.dumps(text)}; }});\n"
        "  return t ? t.mapToItem(null, t.width / 2, t.height / 2) : null;\n"
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


def _visible(scope: str, object_name: str) -> str:
    """Whether a named object exists under the scope and is itself visible."""
    return scene_js(
        f"  var hit = findFirst({scope}, function (o) {{ return o.objectName === {json.dumps(object_name)}; }});\n"
        "  return hit !== null && hit.visible === true;\n"
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


@pytest.mark.qml
def test_tidal_first_journey_switches_providers_and_survives_relaunch():
    run_scenario(
        Path(__file__),
        "--run-reverse-journey",
        timeout=240,
        sandbox_prefix="waves-account-reverse-journey-test-",
        failure_message="the reverse account journey regressed",
    )


def _run_journey(reverse: bool = False) -> int:
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

    def tap(point) -> None:
        """One real click: enough for a plain MouseArea, such as a switch."""
        root = holder["root"]
        root.requestActivate()
        settle(80)
        pos = QPoint(int(point.x()), int(point.y()))
        QTest.mouseMove(root, pos)
        settle(60)
        QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, pos)
        settle(120)

    def click(point) -> None:
        root = holder["root"]
        root.requestActivate()
        settle(80)
        pos = QPoint(int(point.x()), int(point.y()))
        # The offscreen window needs a mouse move plus a warm-up click before
        # a GateAction reacts; the delayed press/release then lands. Plain
        # toggles must use tap(): a second press flips them back.
        QTest.mouseMove(root, pos)
        settle(60)
        QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, pos)
        settle(80)
        QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, pos, 40)

    def press_release(point) -> None:
        """A click with the press and release split by a settle.

        The focus-dismiss catcher releases the search field's focus on the
        press; QTest.mouseClick delivers press and release in one go, so the
        catcher still holds the grab when the release lands and the nav tab
        never sees a completed click while a text field has active focus.
        The app is measured with real input; the harness needs the beat.
        """
        root = holder["root"]
        root.requestActivate()
        settle(80)
        pos = QPoint(int(point.x()), int(point.y()))
        QTest.mouseMove(root, pos)
        settle(60)
        QTest.mousePress(root, Qt.LeftButton, Qt.NoModifier, pos)
        settle(120)
        QTest.mouseRelease(root, Qt.LeftButton, Qt.NoModifier, pos)
        settle(200)

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
            # The one-time update opt-in prompt is another full-window gate;
            # this journey is about the account wiring, so it is pre-walked
            # too (see the other gate walks above).
            q("setupSettings.updatePromptAnswered = true")
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

    # 1. Choose the first provider by clicking the card's action, never
    # applySettings. TIDAL's choice swaps the welcome surface to its inline
    # sign-in steps and stays up: the first run is answered by a completed
    # sign-in, not by starting one.
    first_label = "CONTINUE WITH TIDAL" if reverse else "SET UP APPLE MUSIC"
    first_point = q(_center("providerPicker", first_label))
    if not points_to(first_point):
        print(f"the picker exposes no {first_label} action", file=sys.stderr)
        return _EXIT_PRECONDITION
    tap(first_point)
    settle(300)
    if reverse:
        if bool(bridge.settings.data.apple_enabled):
            problems.append("choosing TIDAL enabled Apple too")
        if not bool(q("providerPicker.visible")) or q("root.setupMode") != "tidal":
            problems.append("choosing TIDAL did not keep the welcome up on its sign-in steps")
        if bool(q("setupSettings.firstRunAnswered")):
            problems.append("choosing TIDAL answered the first run before signing in")
        if bool(q("root.setupUrlOpened")):
            problems.append("choosing TIDAL opened the browser on its own")
        # The steps' explicit click is the only caller of beginLogin.
        open_login = q(_center("providerPicker", "OPEN BROWSER LOGIN"))
        if not points_to(open_login):
            problems.append("the inline sign-in steps expose no OPEN BROWSER LOGIN action")
        else:
            tap(open_login)
            if not wait_for(lambda: bool(q("root.setupUrlOpened"))):
                problems.append("OPEN BROWSER LOGIN did not start the sign-in flow")
            elif not q(_visible("providerPicker", "signInPaste")):
                problems.append("the sign-in steps came back without the paste field")
    elif bool(q("providerPicker.visible")):
        problems.append("the picker stayed up after the provider choice")
    elif not (bool(q("waves.appleEnabled")) and bool(bridge.settings.data.apple_enabled)):
        problems.append("the Apple card click did not enable and persist the provider")

    # 2. The Settings nav is clickable and opens the page. In the reverse
    # order the inline sign-in comes first (the first-run gate owns the
    # screen until it is answered).
    def open_settings() -> bool:
        tab_point = q(_SETTINGS_TAB)
        if not points_to(tab_point):
            return False
        # Not the plain click helper: after a sign-in the search field holds
        # focus, and the full-window focus-dismiss catcher needs the press
        # and release split to release it before the tab's click completes.
        press_release(tab_point)
        settle(300)
        # The scroll dressing floats above every page; it is presentation,
        # not account wiring, and would sit over the provider card's pills.
        q("scrollDressing.visible = false")
        return bool(q("root.settingsOpen"))

    if reverse:
        # Complete the inline sign-in from the first-run welcome surface;
        # the faked account service accepts the https redirect.
        if not q(_pin_paste("providerPicker", "https://tidal.test/redirect")):
            problems.append("the sign-in steps expose no paste field to drive")
        complete = q(_center("providerPicker", "COMPLETE SIGN-IN"))
        if not points_to(complete):
            problems.append("the sign-in steps expose no COMPLETE SIGN-IN action")
        else:
            tap(complete)
            if not wait_for(lambda: bool(bridge._logged_in)):
                problems.append("completing the paste did not sign the session in")
        if bool(q("providerPicker.visible")) or q("root.setupMode") != "cards":
            problems.append("the welcome surface stayed up after a completed sign-in")
        if bool(bridge.settings.data.apple_enabled):
            problems.append("the completed sign-in enabled Apple too")
        # The success lands on Search with the field focused (issue #218),
        # before any later navigation in this scenario.
        if q("root.navOrigin") != "search" or not bool(q("searchField.activeFocus")):
            problems.append("a completed sign-in did not land on Search with the field focused")
        if not open_settings():
            print("could not locate the Settings nav tab", file=sys.stderr)
            return _EXIT_PRECONDITION
    elif not open_settings():
        print("could not locate the Settings nav tab", file=sys.stderr)
        return _EXIT_PRECONDITION
    if not bool(q("root.settingsOpen")):
        problems.append("the Settings nav click did not open Settings")

    # 3. TIDAL sign-in from the provider card's visible action: the
    #    Apple-first path. The card opens the welcome page on its sign-in
    #    steps; only the steps' own button opens the browser. The reverse
    #    path completed its sign-in above.
    if not reverse:
        q('settingsPage.jumpToCard("providers_tidal")')
        settle(400)
        sign_in = q(_pill_point("tidal_signin"))
        if not points_to(sign_in):
            problems.append("the TIDAL card exposes no sign-in action with Apple on")
        else:
            tap(sign_in)
            settle(400)
        if not bool(q("root.setupOpen")) or q("root.setupMode") != "tidal":
            problems.append("the card's sign-in action did not open the welcome page on its sign-in steps")
        if bool(q("root.setupUrlOpened")):
            problems.append("the card's sign-in action opened the browser on its own")
        open_login = q(_center("setupPane", "OPEN BROWSER LOGIN"))
        if not points_to(open_login):
            problems.append("the welcome page exposes no OPEN BROWSER LOGIN action")
        else:
            tap(open_login)
            if not wait_for(lambda: bool(q("root.setupUrlOpened"))):
                problems.append("OPEN BROWSER LOGIN did not start the sign-in flow")
            elif not q(_visible("setupPane", "signInPaste")):
                problems.append("the welcome page came back without the paste field")

    # 4. Complete through the paste field's visible action; the faked
    #    account service accepts the https redirect.
    scope = "providerPicker" if reverse else "setupPane"
    if q(_visible(scope, "signInPaste")):
        # Pin the paste decoder busy so a programmatic text set cannot
        # auto-complete; the visible COMPLETE action drives the step.
        if not q(_pin_paste(scope, "https://tidal.test/redirect")):
            problems.append("the sign-in surface exposes no paste field to drive")
        complete = q(_center(scope, "COMPLETE SIGN-IN"))
        if not points_to(complete):
            problems.append("the sign-in surface exposes no COMPLETE SIGN-IN action")
        else:
            tap(complete)
            if not wait_for(lambda: bool(bridge._logged_in)):
                problems.append("completing the paste did not sign the session in")
    if bool(q("providerPicker.visible")) or bool(q("root.setupOpen")):
        problems.append("a sign-in surface stayed up after a completed sign-in")
    if q("root.setupMode") != "cards":
        problems.append("the welcome surface latched on its sign-in steps")
    if not bool(q("root.signedIn")):
        problems.append("the window still reads signed out after a completed sign-in")
    # The success lands on Search with the field focused (issue #218). The
    # reverse path asserted this right where its sign-in completed, before
    # it navigated back to Settings.
    if not reverse and (q("root.navOrigin") != "search" or not bool(q("searchField.activeFocus"))):
        problems.append("a completed sign-in did not land on Search with the field focused")
    # The sign-in landing closed Settings; the card pills below need it back.
    if not open_settings():
        print("could not return to Settings after the sign-in", file=sys.stderr)
        return _EXIT_PRECONDITION

    # 4b. Reverse order: Apple joins through the Settings band's own enable
    #     switch now that TIDAL is signed in.
    if reverse:
        q("scrollDressing.visible = false")
        q('settingsPage.jumpToCard("providers_apple")')
        settle(500)
        if q(_SCROLL_TO_APPLE_SWITCH) != "scrolled":
            problems.append("the Apple card exposes no enable switch")
        else:
            settle(300)
            apple_switch = q(_APPLE_SWITCH)
            if not points_to(apple_switch):
                problems.append("the Apple enable switch has no scene position")
            else:
                tap(apple_switch)
                settle(400)
                if q("settingsPage.dirty") is not True:
                    # The first tap after the landing-page login can land on a
                    # stale frame; re-query and try once more, like the
                    # sign-out pill below.
                    retry = q(_APPLE_SWITCH)
                    if points_to(retry):
                        tap(retry)
                        settle(400)
                if q("settingsPage.dirty") is not True:
                    problems.append("the Apple switch click did not stage an edit")
                save = q(_text_point("SAVE CHANGES"))
                if not points_to(save):
                    problems.append("Settings exposes no SAVE CHANGES action")
                else:
                    click(save)
                    settle(600)
                if not (bool(q("waves.appleEnabled")) and bool(bridge.settings.data.apple_enabled)):
                    problems.append("the Apple switch did not enable and persist the provider")

    # 5. Sign out from the card's visible action (Settings stayed open).
    q("scrollDressing.visible = false")
    settle(300)
    q('settingsPage.jumpToCard("providers_tidal")')
    settle(500)
    sign_out = q(_pill_point("tidal_signout"))
    if not points_to(sign_out):
        problems.append("the signed-in card exposes no sign-out action")
    else:
        # One click: the pill is replaced by SIGN IN the moment the session
        # flips, so the two-click helper's second press would land on it and
        # re-open the sign-in surface.
        tap(sign_out)
        settle(250)
        if bool(bridge._logged_in):
            # The first synthetic click after a session flip can land on the
            # replaced delegate; re-query and try once more.
            retry = q(_pill_point("tidal_signout"))
            if retry is not None:
                tap(retry)
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

    # 7. Relaunch: a fresh Main.qml over the same persisted settings still
    #    reads Apple enabled and TIDAL signed out, and both stay reachable.
    #    The enabled switch is checked on DISK too, so the relaunch cannot
    #    pass on the in-memory bridge alone.
    settings_path = Path(bridge.settings.file_path)

    def enabled_on_disk() -> bool:
        try:
            return json.loads(settings_path.read_text(encoding="utf-8")).get("apple_enabled") is True
        except (OSError, ValueError):
            return False

    if not wait_for(enabled_on_disk, 4000):
        problems.append("the provider switch never reached settings.json")
    if load_root() is None:
        problems.append("Main.qml did not load on relaunch")
    else:
        wait_for(lambda: bool(bridge._session_resolved))
        boot()
        if not (bool(q("root.appleEnabled")) and bool(bridge.settings.data.apple_enabled)):
            problems.append("the relaunch lost the Apple provider")
        if bool(bridge._logged_in):
            problems.append("the relaunch kept a signed-out TIDAL session alive")
        q("scrollDressing.visible = false")
        tab_point = q(_SETTINGS_TAB)
        if points_to(tab_point):
            click(tab_point)
            settle(300)
        q('settingsPage.jumpToCard("providers_tidal")')
        settle(400)
        if q(_pill_point("tidal_signin")) is None:
            problems.append("the relaunch left no reachable TIDAL sign-in")
        q('settingsPage.jumpToCard("providers_apple")')
        settle(300)
        if q(_pill_point_prefix("apple_")) is None:
            problems.append("the relaunch left no reachable Apple card")

    for line in problems:
        print(f"REGRESSED: {line}", file=sys.stderr)
    return _EXIT_REGRESSED if problems else _EXIT_OK


if __name__ == "__main__" and "--run-journey" in sys.argv:
    raise SystemExit(_run_journey())

if __name__ == "__main__" and "--run-reverse-journey" in sys.argv:
    raise SystemExit(_run_journey(reverse=True))
