"""#215: first-run welcome, Skip, the Finish-setup chip and the one-time seed.

WHAT THIS FENCES OFF
--------------------
The welcome surface answers once and never nags; Skip lands in the app with
no passive TIDAL overlay and leaves a dismissible chip; the chip is
permanent once dismissed, re-opens the welcome as a page, and disappears the
moment a provider can download; the legacy picker bit seeds the new answer
exactly once and is cleared; the answer reaches the QML settings store, so a
restart reads it.

Drives the REAL Main.qml offscreen (building the bridge installs
process-global handlers), with the account service faked at the provider
boundary.
"""

from __future__ import annotations

import json
import sys

from support.qml import EXIT_OK, EXIT_REGRESSED, boot_main_qml, run_scenario
from support.qml_probe import scene_js

_FINDERS = """
    function pointOfText(scope, needle) {
        var hit = findFirst(scope, function (o) {
            return o.text !== undefined && String(o.text) === needle;
        });
        if (!hit) return "";
        var p = hit.mapToItem(null, hit.width / 2, hit.height / 2);
        if (p.x < 0 || p.y < 0 || p.x > root.width || p.y > root.height) return "";
        return JSON.stringify([p.x, p.y]);
    }
    function pointOfObject(scope, name) {
        var hit = findFirst(scope, function (o) { return o.objectName === name; });
        if (!hit) return "";
        var p = hit.mapToItem(null, hit.width / 2, hit.height / 2);
        if (p.x < 0 || p.y < 0 || p.x > root.width || p.y > root.height) return "";
        return JSON.stringify([p.x, p.y]);
    }
"""


def _text_point(scope: str, needle: str) -> str:
    return scene_js(_FINDERS + f"\n    return pointOfText({scope}, {json.dumps(needle)});")


def _object_point(scope: str, name: str) -> str:
    return scene_js(_FINDERS + f"\n    return pointOfObject({scope}, {json.dumps(name)});")


def test_the_welcome_answers_once_and_leaves_a_working_app():
    run_scenario(
        __file__,
        "--run-scenario",
        timeout=180,
        sandbox_prefix="waves-onboarding-",
        failure_message="the onboarding state model regressed",
    )


def _run_scenario() -> int:  # noqa: C901 (one straight scenario)
    booted = boot_main_qml()
    if isinstance(booted, int):
        return booted
    root, q, settle, bridge = booted

    def click(point) -> bool:
        if point in ("", None):
            return False
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest

        x, y = json.loads(point)
        pos = QPoint(int(x), int(y))
        root.requestActivate()
        settle(80)
        QTest.mouseMove(root, pos)
        settle(60)
        QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, pos)
        settle(220)
        return True

    failures: list[str] = []

    # boot_main_qml parks the first-run gates by assigning visible=false,
    # which breaks the gate's binding; re-arm it for this scenario. The
    # login panel stays parked here by design: the startup-picker and
    # TIDAL-reachability scenarios own its visibility, and this one asserts
    # the state flag the panel keys on.
    q("providerPicker.visible = Qt.binding(function() { return root.welcomeDue })")
    # The scroll dressing sits over the page and swallows synthetic clicks.
    q("scrollDressing.visible = false")
    settle(150)

    # A fresh profile: logged-out session resolved, nothing answered.
    bridge._session_resolved = True
    bridge.sessionResolvedChanged.emit()
    settle(250)

    if not q("providerPicker.visible"):
        failures.append("the welcome did not appear on a fresh profile")
    if q("setupSettings.firstRunAnswered"):
        failures.append("a fresh profile starts answered")
    if bool(q("root.setupUnfinished")):
        failures.append("the chip showed before the welcome was answered")

    # Skip: the welcome closes, the app is usable, no passive overlay, chip up.
    if not click(q(_text_point("providerPicker", "Not now"))):
        failures.append("the welcome exposes no Skip action")
    else:
        if q("providerPicker.visible"):
            failures.append("Skip left the welcome up")
        if not q("setupSettings.firstRunAnswered"):
            failures.append("Skip did not persist the answer")
        if q("root.setupChoiceTidal"):
            failures.append("Skip chose the TIDAL sign-in path")
        if not bool(q("root.setupUnfinished")):
            failures.append("the chip did not appear after Skip")
        if q(_object_point("headerRow", "setupChip")) in ("", None):
            failures.append("the chip did not render on screen")

    # The answer reaches the QML settings store (written on the settings
    # debounce), so a restart reads it: probe it with a fresh Settings
    # instance rather than trusting the live object.
    persisted = False
    for _ in range(12):
        settle(250)
        if q("""
            (function () {
                var probe = Qt.createQmlObject('import QtCore; Settings { category: "setup"; property bool firstRunAnswered: false }', root)
                var seen = probe.firstRunAnswered === true
                probe.destroy()
                return seen
            })()
        """):
            persisted = True
            break
    if not persisted:
        failures.append("the answer did not reach the settings store after Skip")

    # The ✕ dismisses the chip for good.
    if not click(q(_object_point("headerRow", "setupChipDismiss"))):
        failures.append("the chip exposes no dismiss action")
    else:
        if bool(q("root.setupUnfinished")):
            failures.append("the chip stayed after dismissal")
        if not q("setupSettings.setupChipDismissed"):
            failures.append("the dismissal did not persist")

    # Settings -> Providers, or a chip click, re-opens the surface as a page.
    q("waves.showSetup()")
    settle(300)
    if not q("setupOpen") or not q("setupPane.visible"):
        failures.append("showSetup did not open the welcome page")
    if q("providerPicker.visible"):
        failures.append("re-opening raised the first-run gate instead of the page")
    q("root.openBrowse()")
    settle(250)
    if q("setupOpen"):
        failures.append("navigating away did not close the welcome page")

    # The legacy picker bit seeds the new answer exactly once, then clears.
    q("setupSettings.firstRunAnswered = false; setupSettings.providerPickerDone = true")
    q("setupSettings.migrateOnboarding()")
    if not q("setupSettings.firstRunAnswered"):
        failures.append("the legacy answer did not seed the new one")
    if q("setupSettings.providerPickerDone"):
        failures.append("the legacy key was not cleared")

    # A provider that can download retires the chip.
    q("setupSettings.setupChipDismissed = false")
    bridge._set_logged_in(True)
    settle(300)
    if bool(q("root.setupUnfinished")):
        failures.append("the chip survived a signed-in provider")

    if failures:
        for line in failures:
            print(line, file=sys.stderr)
        return EXIT_REGRESSED
    print("ok")
    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    sys.exit(_run_scenario())
