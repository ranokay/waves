"""AX press and toggle reach the switches and the welcome skip.

The platform contract this pins (Qt 6.11, verified against its source):
macOS delivers an AX press as the Toggle action on CheckBox/RadioButton/Switch
roles and as Press on Buttons. A checkable item with only
``Accessible.onPressAction`` silently drops the press: the Toggle half finds no
handler, and the role-default fallback needs a ``checked`` property none of
these items has. So every checkable role carries both handlers, and the
scenario below drives the exact action strings the platform sends rather than
calling the QML functions behind them.
"""

from __future__ import annotations

import re
import sys

import pytest
from support.paths import QML_DIR
from support.qml import EXIT_OK, EXIT_REGRESSED, boot_main_qml, run_scenario
from support.qml_probe import scene_js


@pytest.mark.qml
def test_ax_actions_toggle_the_switches_and_press_the_welcome_skip():
    run_scenario(
        __file__,
        "--run-scenario",
        timeout=240,
        sandbox_prefix="waves-ax-toggle-test-",
        failure_message="an AX toggle or press never reached its control",
    )


def test_every_checkable_role_answers_the_toggle_action():
    """Each checkable role pairs its press handler with a toggle handler.

    Without the pair the platform's Toggle delivery (what macOS sends for an
    AX press on a checkbox) falls through to a role-default that needs a
    ``checked`` property these items do not have: a silent no-op.
    """
    qml = (QML_DIR / "SettingsPage.qml").read_text(encoding="utf-8")
    qml += (QML_DIR / "DownloadButton.qml").read_text(encoding="utf-8")
    roles = len(re.findall(r"Accessible\.role: Accessible\.(?:CheckBox|RadioButton|Switch)", qml))
    toggles = qml.count("Accessible.onToggleAction")
    assert roles > 0, "the checkable roles are gone from the scanned files"
    assert roles == toggles, f"{roles} checkable roles but {toggles} toggle handlers"
    # The adopters that take their checkable role from the shared tap area
    # are answered by its one toggle handler, so their files carry no pair of
    # their own: the primitive must keep the checkable flag and the handler
    # gated on it.
    tap = re.sub(r"\s+", " ", (QML_DIR / "TapAction.qml").read_text(encoding="utf-8"))
    assert "Accessible.checkable: ta.checkable" in tap, "the shared tap area lost its checkable flag"
    assert "Accessible.onToggleAction" in tap, "the shared tap area lost its toggle action"
    assert "if (ta.checkable && ta.enabled)" in tap, "the shared toggle no longer gates on checkable"


def test_the_welcome_skip_is_a_named_press_target():
    """The welcome's skip carries the name and press a reader needs."""
    flat = re.sub(r"\s+", " ", (QML_DIR / "WelcomePicker.qml").read_text(encoding="utf-8"))
    assert 'objectName: "welcomeSkip"' in flat, "the welcome skip has no stable name"
    assert 'Accessible.name: "Not now"' in flat, "the welcome skip has no accessible name"
    assert "Accessible.onPressAction: pickCard.skipped()" in flat, "the welcome skip answers no press"
    assert "activeFocusOnTab: visible" in flat, "the welcome skip is not Tab-reachable"
    for key in ("Keys.onReturnPressed", "Keys.onEnterPressed", "Keys.onSpacePressed"):
        assert key in flat, f"the welcome skip answers no {key}"


TRACK = {
    "id": "t1",
    "kind": "track",
    "title": "Track",
    "artist": "Artist",
    "artist_id": "a1",
    "album": "Album",
    "album_id": "al1",
    "num": 1,
    "vol": 1,
    "art": "",
    "year": "2026",
    "date": "2026-09-01",
    "duration": "3:00",
    "duration_sec": 180,
    "quality": "LOSSLESS",
    "popularity": 1,
    "explicit": False,
    "added": "",
}

_FIND_SWITCH = """
var sw = findFirst(root, function (o) {
    return o.objectName === "appleEnableSwitch" && o.visible === true && o.activeFocusOnTab === true;
});
"""

_FIND_SKIP = """
var skip = findFirst(providerPicker, function (o) {
    return o.objectName === "welcomeSkip" && o.visible !== false && o.width > 0;
});
"""


def _run_scenario() -> int:
    import traceback

    try:
        return _scenario_body()
    except Exception:
        print(traceback.format_exc(), file=sys.stderr)
        return EXIT_REGRESSED


def _scenario_body() -> int:  # noqa: C901 (one straight scenario, four legs)
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QAccessible
    from PySide6.QtTest import QTest

    booted = boot_main_qml()
    if isinstance(booted, int):
        return booted
    root, q, settle, bridge = booted
    problems: list[str] = []

    def action_of(item):
        iface = QAccessible.queryAccessibleInterface(item)
        if iface is None or not iface.isValid():
            return None
        return iface.actionInterface()

    # --- The welcome skip: named, button-roled, and its press skips.
    q("legalSettings.termsAcceptedVersion = root.termsVersion")
    q("legalSettings.termsAccepted = true")
    # boot_main_qml parks the first-run gate by assigning visible=false,
    # which breaks the gate's binding; re-arm it (the onboarding scenario's
    # shape) so the welcome is up for this leg.
    q("providerPicker.visible = Qt.binding(function() { return root.welcomeDue })")
    q(
        "setupSettings.firstRunAnswered = false; setupSettings.setupChipDismissed = false;"
        " setupSettings.providerPickerDone = false"
    )
    q("root.setupMode = 'cards'; root.setupUrlOpened = false")
    q('waves.applySettings({"apple_enabled": false})')
    bridge._session_resolved = True
    bridge.sessionResolvedChanged.emit()
    settle(300)
    if not bool(q(scene_js(_FIND_SKIP + "return skip ? true : false;"))):
        problems.append("the welcome skip is not in the tree at boot")
    else:
        skip_name = q(scene_js(_FIND_SKIP + "return '' + skip.Accessible.name;"))
        skip_role = q(scene_js(_FIND_SKIP + "return Number(skip.Accessible.role);"))
        if skip_name != "Not now":
            problems.append(f"the welcome skip is named {skip_name!r}, not 'Not now'")
        if skip_role != 43:
            problems.append(f"the welcome skip is not exposed as a button (role {skip_role})")
        skip_action = action_of(q(scene_js(_FIND_SKIP + "return skip;")))
        if skip_action is None or "Press" not in list(skip_action.actionNames()):
            problems.append("the welcome skip advertises no press action")
        else:
            skip_action.doAction("Press")
            settle(300)
            if not bool(q("setupSettings.firstRunAnswered === true")):
                problems.append("pressing the welcome skip never skipped")
    # --- The welcome skip: Tab-reachable and keyboard-operable. Re-answer
    # the welcome first: the press leg above skipped it, and a hidden skip
    # is no skip in the tree.
    q(
        "setupSettings.firstRunAnswered = false; setupSettings.setupChipDismissed = false;"
        " root.setupMode = 'cards'; root.setupUrlOpened = false"
    )
    settle(250)
    if not bool(q(scene_js(_FIND_SKIP + "return skip ? skip.activeFocusOnTab === true : false;"))):
        problems.append("the welcome skip is not Tab-reachable (activeFocusOnTab)")
    else:
        for key, words in ((Qt.Key_Return, "Return"), (Qt.Key_Enter, "Enter"), (Qt.Key_Space, "Space")):
            q(
                "setupSettings.firstRunAnswered = false; setupSettings.setupChipDismissed = false;"
                " root.setupMode = 'cards'; root.setupUrlOpened = false"
            )
            settle(250)
            q(scene_js(_FIND_SKIP + "skip.forceActiveFocus(); return true;"))
            settle(150)
            if not bool(q(scene_js(_FIND_SKIP + "return skip.activeFocus === true;"))):
                problems.append("the welcome skip never took keyboard focus")
                break
            root.requestActivate()
            settle(100)
            QTest.keyClick(root, key)
            settle(300)
            if not bool(q("setupSettings.firstRunAnswered === true")):
                problems.append(f"the welcome skip's {words} key never skipped")
                break
    q("setupSettings.firstRunAnswered = true")
    settle(200)

    # --- The Settings switch: the platform's Toggle flips it, Press flips back.
    opened = bool(
        q(
            scene_js(
                """
        var tab = findFirst(root, function (o) { return o.label === "Settings" && o.clicked !== undefined; });
        if (!tab) return false;
        tab.clicked();
        return true;
        """
            )
        )
    )
    settle(400)
    if not opened or not bool(q("root.settingsOpen")):
        problems.append("the Settings tab did not open the Settings page")
    elif not bool(q(scene_js(_FIND_SWITCH + "return sw ? true : false;"))):
        problems.append("the Apple switch is not in the open Settings page")
    else:

        def checked() -> bool:
            return bool(q(scene_js(_FIND_SWITCH + "return sw.Accessible.checked === true;")))

        switch_action = action_of(q(scene_js(_FIND_SWITCH + "return sw;")))
        if switch_action is None or "Toggle" not in list(switch_action.actionNames()):
            problems.append("the Apple switch advertises no toggle action")
        else:
            start = checked()
            switch_action.doAction("Toggle")
            settle(250)
            if checked() == start:
                problems.append("the platform Toggle never flipped the Apple switch")
            else:
                switch_action.doAction("Press")
                settle(250)
                if checked() != start:
                    problems.append("the platform Press never flipped the Apple switch back")
    q("settingsPage.closed()")
    settle(250)

    # --- A Chooser checkbox: the same Toggle reaches the shared toggle path.
    q("openSearch()")
    settle(200)
    q("root._searchSeq = root._navSeq")
    bridge.searchResults.emit(
        {
            "groups": [
                {
                    "provider": "tidal",
                    "artists_layout": "strip",
                    "head_when_alone": False,
                    "artists": [],
                    "albums": [],
                    "tracks": [TRACK],
                    "videos": [],
                    "playlists": [],
                    "mixes": [],
                    "top": None,
                    "error": "",
                }
            ]
        }
    )
    settle(400)
    chooser_open = bool(
        q(
            scene_js(
                """
        var b = findFirst(root, function (o) { return o.chooserKind !== undefined && ('' + o.mediaId) === 't1'; });
        if (!b) return false;
        b.openChooser();
        return true;
        """
            )
        )
    )
    settle(300)
    tile_on = q(
        scene_js(
            """
        var tile = findObject(root, "chooserLyricsEmbed");
        return tile ? tile.Accessible.checked === true : null;
        """
        )
    )
    if not chooser_open:
        problems.append("no download button opened its Chooser")
    elif tile_on is None:
        problems.append("the Chooser lyrics checkbox is not in the open popover")
    else:
        tile_action = action_of(q(scene_js('return findObject(root, "chooserLyricsEmbed");')))
        if tile_action is None or "Toggle" not in list(tile_action.actionNames()):
            problems.append("the Chooser checkbox advertises no toggle action")
        else:
            tile_action.doAction("Toggle")
            settle(250)
            flipped = q(
                scene_js(
                    """
                var tile = findObject(root, "chooserLyricsEmbed");
                return tile.Accessible.checked === true;
                """
                )
            )
            if bool(flipped) == bool(tile_on):
                problems.append("the platform Toggle never flipped the Chooser checkbox")

    if problems:
        for line in problems:
            print(f"REGRESSED: {line}", file=sys.stderr)
        return EXIT_REGRESSED
    print("ok")
    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    sys.exit(_run_scenario())
