"""#215: first-run welcome, Skip, the Finish-setup chip and the one-time seed.

WHAT THIS FENCES OFF
--------------------
The welcome surface answers once and never nags; Skip lands in the app with
no passive TIDAL overlay and leaves a dismissible chip; the chip is
permanent once dismissed, and re-opens the welcome as a page through
Settings -> Providers -> "Set up providers"; the legacy picker bit seeds the
new answer exactly once and is cleared; and a second boot from the same
store shows no welcome.

The rendered scenario drives the REAL Main.qml offscreen (building the
bridge installs process-global handlers), with the account service faked at
the provider boundary. Its two restart modes run as separate children of
the restart test, sharing one settings store.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from support.qml import (
    EXIT_NO_QT,
    EXIT_OK,
    EXIT_REGRESSED,
    boot_main_qml,
    missing_qt,
    run_scenario,
    scenario_env,
)
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


def _has_label(scope: str, needle: str) -> str:
    """Whether a label is rendered anywhere under the scope (visibility and
    scroll position aside: a deep settings row may be below the fold)."""
    return scene_js(
        _FINDERS
        + "\n    return findFirst("
        + scope
        + ", function (o) { return o.text !== undefined && String(o.text) === "
        + json.dumps(needle)
        + "; }) !== null;"
    )


def test_the_answer_survives_a_restart():
    """The acceptance's restart: one child answers Skip, a second boots from
    the same store and shows no welcome."""
    if missing_qt():
        pytest.skip("PySide6 / offscreen Qt unavailable")
    sandbox = tempfile.mkdtemp(prefix="waves-onboarding-restart-")
    try:
        for flag in ("--answer-skip", "--expect-answered"):
            proc = subprocess.run(  # noqa: S603 (fixed argv: this interpreter, this file)
                [sys.executable, str(Path(__file__).resolve()), flag],
                env=scenario_env(sandbox),
                capture_output=True,
                text=True,
                timeout=180,
            )
            if proc.returncode == EXIT_NO_QT:
                pytest.skip("PySide6 / offscreen Qt unavailable")
            if proc.returncode != EXIT_OK:
                pytest.fail(f"{flag} failed\n" + (proc.stdout + proc.stderr).strip()[-1200:])
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


@pytest.mark.qml
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

    def click(point_expr: str, done_expr: str) -> bool:
        """Click where the expression says until the done predicate holds.

        The first activation resolves font aliases and can shift the layout,
        and a synthetic click can land on the control the hover moved out
        from under it; one retry with a fresh point keeps the scenario about
        the state model, not about offscreen input delivery.
        """
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest

        root.requestActivate()
        settle(150)
        for _ in range(2):
            raw = q(point_expr)
            if raw in ("", None):
                return False
            x, y = json.loads(raw)
            QTest.mouseMove(root, QPoint(int(x), int(y)))
            settle(120)
            raw = q(point_expr)  # fresh after the hover
            if raw in ("", None):
                return False
            x, y = json.loads(raw)
            QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, QPoint(int(x), int(y)))
            settle(300)
            if q(done_expr):
                return True
        return False

    failures: list[str] = []

    # boot_main_qml parks the first-run gates by assigning visible=false,
    # which breaks the gate's binding; re-arm it for this scenario. The
    # login panel stays parked here by design: the startup-picker and
    # TIDAL-reachability scenarios own its visibility, and this one asserts
    # the state flag the panel keys on. The onboarding flags are reset too:
    # on macOS the QML store can survive the harness's clear, and this test
    # needs a fresh profile every run.
    q("providerPicker.visible = Qt.binding(function() { return root.welcomeDue })")
    q(
        "setupSettings.firstRunAnswered = false; setupSettings.setupChipDismissed = false;"
        " setupSettings.providerPickerDone = false"
    )
    # A reused config directory can carry an enabled Apple from another run;
    # the fresh-profile semantics this scenario tests mean Apple off.
    q('waves.applySettings({"apple_enabled": false})')
    # The scroll dressing sits over the page and swallows synthetic clicks.
    q("scrollDressing.visible = false")
    settle(150)

    # A fresh profile: logged-out session resolved, nothing answered.
    bridge._session_resolved = True
    bridge.sessionResolvedChanged.emit()
    settle(250)

    if not q("providerPicker.visible"):
        failures.append(
            "the welcome did not appear on a fresh profile: "
            f"due={q('root.welcomeDue')} resolved={q('waves.sessionResolved')} "
            f"answered={q('setupSettings.firstRunAnswered')} apple={q('waves.appleEnabled')}"
        )
    if q("setupSettings.firstRunAnswered"):
        failures.append("a fresh profile starts answered")
    if bool(q("root.downloadsNeedSetup")):
        failures.append("the chip showed before the welcome was answered")
    # One card per provider, from the descriptors: both marks and both
    # actions are rendered by the same generic delegate.
    if q(_text_point("providerPicker", "CONTINUE WITH TIDAL")) in ("", None):
        failures.append("the TIDAL card did not render from its descriptor")
    if q(_text_point("providerPicker", "CONTINUE WITH APPLE MUSIC")) in ("", None):
        failures.append("the Apple Music card did not render from its descriptor")

    # Skip: the welcome closes, the app is usable, no passive overlay, chip up.
    if not click(_text_point("providerPicker", "Not now"), "setupSettings.firstRunAnswered === true"):
        failures.append("the welcome exposes no Skip action")
    else:
        if q("providerPicker.visible"):
            failures.append("Skip left the welcome up")
        if not q("setupSettings.firstRunAnswered"):
            failures.append("Skip did not persist the answer")
        if q("root.setupChoiceTidal"):
            failures.append("Skip chose the TIDAL sign-in path")
        if not bool(q("root.downloadsNeedSetup")):
            failures.append(
                "the chip did not appear after Skip: "
                f"answered={q('setupSettings.firstRunAnswered')} signedIn={q('root.signedIn')} "
                f"dismissed={q('setupSettings.setupChipDismissed')} "
                f"apple={q('String(root.appleLight.state || \'\')')}"
            )
        if q(_object_point("headerRow", "setupChip")) in ("", None):
            failures.append("the chip did not render on screen")

    # The ✕ dismisses the chip for good. Its handler is invoked through the
    # named MouseArea: the pixel path over this 26px target is covered for
    # larger controls elsewhere and only adds offscreen-input flake here.
    dismissed = bool(q("typeof root.dismissSetupChip === 'function'"))
    q("root.dismissSetupChip()")
    settle(200)
    if not dismissed:
        failures.append("the chip exposes no dismiss action")
    else:
        if bool(q("root.downloadsNeedSetup")):
            failures.append("the chip stayed after dismissal")
        if not q("setupSettings.setupChipDismissed"):
            failures.append("the dismissal did not persist")

    # Settings -> Providers -> "Set up providers" re-opens the surface as a
    # page: the pill travels schema -> renderer -> bridge -> page. The
    # Providers section must be open for its rows to render.
    q(
        "root.navPush(); root.markNav('settings'); root.settingsOpen = true;"
        " root.artistOpen = false; root.libraryOpen = false"
    )
    settle(300)
    q("settingsPage.setSectionOpen('providers', true)")
    settle(300)
    # The pill renders (its label is in the section's rows) and its handler
    # opens the page. The pixel click over this deep-field row is not part of
    # this scenario: the page's scroll position and the synthetic-input flake
    # would make the state model test about the harness instead.
    if not q(_has_label("settingsPage", "SET UP PROVIDERS")):
        failures.append("Settings -> Providers exposes no Set up providers pill")
    q("waves.showSetup()")  # the pill's handler, one step short of the pixel
    settle(300)
    if not q("setupOpen") or not q("setupPane.visible"):
        failures.append("the Settings pill did not open the welcome page")
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
    if bool(q("root.downloadsNeedSetup")):
        failures.append("the chip survived a signed-in provider")

    if failures:
        for line in failures:
            print(line, file=sys.stderr)
        return EXIT_REGRESSED
    print("ok")
    return EXIT_OK


def _run_answer_skip() -> int:
    """First child of the restart test: answer Skip and let it persist."""
    booted = boot_main_qml()
    if isinstance(booted, int):
        return booted
    _root, q, settle, _bridge = booted
    q("setupSettings.firstRunAnswered = false; setupSettings.setupChipDismissed = false")
    q("root.answerWelcome('skip')")
    settle(500)
    if not q("setupSettings.firstRunAnswered"):
        print("the first child did not answer the welcome", file=sys.stderr)
        return EXIT_REGRESSED
    settle(1200)  # the settings write is debounced
    print("ok")
    return EXIT_OK


def _run_expect_answered() -> int:
    """Second child: the persisted answer means no welcome on this boot."""
    booted = boot_main_qml(keep_settings=True)
    if isinstance(booted, int):
        return booted
    _root, q, settle, _bridge = booted
    q("providerPicker.visible = Qt.binding(function() { return root.welcomeDue })")
    settle(300)
    if not q("setupSettings.firstRunAnswered"):
        print("the second child did not read the persisted answer", file=sys.stderr)
        return EXIT_REGRESSED
    if q("providerPicker.visible"):
        print("the welcome came back on the second child", file=sys.stderr)
        return EXIT_REGRESSED
    print("ok")
    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    sys.exit(_run_scenario())
if __name__ == "__main__" and "--answer-skip" in sys.argv:
    sys.exit(_run_answer_skip())
if __name__ == "__main__" and "--expect-answered" in sys.argv:
    sys.exit(_run_expect_answered())
