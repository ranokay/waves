"""The search sort control is remembered across launches.

The order is stored by NAME (relevance, date, name, popularity) rather than
by index, so the option list can change without a saved choice landing on
the wrong entry, and the direction is a real bool. ``setWavesPref`` coerces
against the default's type, so both survive a round trip through it.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from support.paths import QML_DIR
from support.qml import EXIT_OK, EXIT_REGRESSED, boot_main_qml, run_scenario
from support.qml_probe import scene_js

from waves.desktop import backend


def _bridge():
    b = backend.WavesBridge.__new__(backend.WavesBridge)
    b._waves_prefs = backend.WavesBridge._default_waves_prefs(b)
    b._save_waves_prefs = lambda: None
    b._factory_reset = False
    b.settings = SimpleNamespace(data=SimpleNamespace())
    return b


def test_the_sort_prefs_default_to_relevance_descending():
    prefs = backend.WavesBridge._default_waves_prefs(_bridge())
    assert prefs["search_sort"] == "relevance"
    assert prefs["search_sort_asc"] is False


def test_the_sort_prefs_round_trip_with_their_types():
    b = _bridge()
    b.setWavesPref("search_sort", "popularity")
    b.setWavesPref("search_sort_asc", True)
    assert b.wavesPref("search_sort") == "popularity"
    assert b.wavesPref("search_sort_asc") is True
    # The QML side hands the bool over as a real bool, but a string form
    # (the str-coercing path) must not turn "false" into a truthy value.
    b.setWavesPref("search_sort_asc", "false")
    assert b.wavesPref("search_sort_asc") is False


def test_the_direction_button_is_inert_at_relevance_in_source():
    """The Relevance guard lives on the shared tap area, not a MouseArea.

    Without the ``enabled`` gate the dimmed arrow still flips and persists;
    without the shared area there is no tab stop, no accessible name and no
    Space/Return path.
    """
    src = (QML_DIR / "Main.qml").read_text(encoding="utf-8")
    flat = re.sub(r"\s+", " ", src)
    assert 'objectName: "sortDirectionButton"' in flat, "the direction button has no stable name"
    assert "enabled: sortBox.currentIndex !== 0" in flat, "the direction button is live at Relevance"
    assert 'accessibleLabel: root.sortAsc ? "Sort ascending" : "Sort descending"' in flat, (
        "the direction button names no direction"
    )
    assert "Relevance has no direction" in src, "the direction button says nothing about why it is inert"


@pytest.mark.qml
def test_the_direction_button_is_inert_at_relevance():
    run_scenario(
        Path(__file__),
        "--run-scenario",
        timeout=180,
        sandbox_prefix="waves-sort-direction-test-",
        failure_message="the sort direction button is live at Relevance.",
    )


_FIND_SORT_DIR = """
var btn = findObject(root, "sortDirectionButton");
"""


def _run_scenario() -> int:
    try:
        return _scenario_body()
    except Exception:
        import traceback

        print(traceback.format_exc(), file=sys.stderr)
        return EXIT_REGRESSED


def _scenario_body() -> int:  # noqa: C901 (one straight scenario, two legs)
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    booted = boot_main_qml()
    if isinstance(booted, int):
        return booted
    root, q, settle, bridge = booted
    problems: list[str] = []

    q("openSearch()")
    settle(300)
    # The search row gates on a live provider; Apple on makes the row (and
    # the sort control inside it) live without touching the real network.
    bridge.settings.data.apple_enabled = True
    bridge.appleStatusChanged.emit()
    settle(400)

    # A known start: Relevance, descending, persisted descending.
    q("sortBox.currentIndex = 0; root.sortAsc = false")
    q("waves.setWavesPref('search_sort_asc', false)")
    settle(250)

    if not bool(q(scene_js(_FIND_SORT_DIR + "return btn ? true : false;"))):
        problems.append("the sort direction button is not in the tree")
        return _finish(problems)

    # --- At Relevance the control is inert and visually disabled.
    if bool(q(scene_js(_FIND_SORT_DIR + "return btn.enabled === true;"))):
        problems.append("the direction button is enabled at the Relevance index")
    name = q(scene_js(_FIND_SORT_DIR + "return '' + btn.Accessible.name;"))
    if name != "Sort descending":
        problems.append(f"the accessible name is {name!r}, not 'Sort descending'")
    tip = q(scene_js(_FIND_SORT_DIR + "return btn && btn.parent ? '' + btn.parent.ToolTip.text : '';"))
    if "Relevance" not in str(tip):
        problems.append("the direction button carries no tooltip saying why it is inert")

    # A real click on its own pixels while inert: nothing flips, nothing persists.
    before_pref = bridge.wavesPref("search_sort_asc")
    cx = float(q(scene_js(_FIND_SORT_DIR + "return btn.mapToItem(null, btn.width / 2, btn.height / 2).x;")))
    cy = float(q(scene_js(_FIND_SORT_DIR + "return btn.mapToItem(null, btn.width / 2, btn.height / 2).y;")))
    root.requestActivate()
    settle(100)
    QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, QPoint(int(cx), int(cy)))
    settle(400)
    if bool(q("root.sortAsc === true")):
        problems.append("clicking the inert direction button flipped the direction")
    if bridge.wavesPref("search_sort_asc") != before_pref:
        problems.append("clicking the inert direction button wrote search_sort_asc")

    # --- Away from Relevance the control answers Tab, Space, Return and Enter.
    q("sortBox.currentIndex = 2")
    settle(250)
    if not bool(q(scene_js(_FIND_SORT_DIR + "return btn.enabled === true;"))):
        problems.append("the direction button stayed inert away from Relevance")
    elif not bool(q(scene_js(_FIND_SORT_DIR + "return btn.activeFocusOnTab === true;"))):
        problems.append("the direction button is not Tab-reachable when enabled")
    else:
        q(scene_js(_FIND_SORT_DIR + "btn.forceActiveFocus(); return true;"))
        settle(150)
        if not bool(q(scene_js(_FIND_SORT_DIR + "return btn.activeFocus === true;"))):
            problems.append("the direction button never took keyboard focus")
        else:
            # Every key the spec names flips it on its own: reset to
            # descending before each so each press proves its own flip.
            for key, words in ((Qt.Key_Space, "Space"), (Qt.Key_Return, "Return"), (Qt.Key_Enter, "Enter")):
                q("root.sortAsc = false")
                q("waves.setWavesPref('search_sort_asc', false)")
                settle(150)
                q(scene_js(_FIND_SORT_DIR + "btn.forceActiveFocus(); return true;"))
                settle(150)
                if not bool(q(scene_js(_FIND_SORT_DIR + "return btn.activeFocus === true;"))):
                    problems.append("the direction button never took keyboard focus")
                    break
                root.requestActivate()
                settle(100)
                QTest.keyClick(root, key)
                settle(400)
                if not bool(q("root.sortAsc === true")):
                    problems.append(f"{words} on the direction button never flipped it")
                    break
                if bridge.wavesPref("search_sort_asc") is not True:
                    problems.append(f"the {words} flip never persisted search_sort_asc")
                    break
            else:
                flipped_name = q(scene_js(_FIND_SORT_DIR + "return '' + btn.Accessible.name;"))
                if flipped_name != "Sort ascending":
                    problems.append(f"after the flip the accessible name is {flipped_name!r}")

    return _finish(problems)


def _finish(problems: list[str]) -> int:
    if problems:
        for line in problems:
            print(f"REGRESSED: {line}", file=sys.stderr)
        return EXIT_REGRESSED
    print("ok")
    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    sys.exit(_run_scenario())
