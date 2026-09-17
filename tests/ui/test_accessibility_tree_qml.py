"""The accessibility tree of the primary controls (issue #240 / audit UI-08).

The app's controls are custom MouseAreas over rectangles, so before this the
tab order was whatever Qt derived from the text fields: the download button,
the header nav, the queue button and every dialog action were invisible to a
screen reader and unreachable without a pointer. The scenario walks the live
tree and asserts the metadata and focus reachability that make them usable
keyboard-only:

- each NavTab and the QUEUE button carry a role, a non-empty name and
  ``activeFocusOnTab``;
- a search result's DownloadButton does the same, with the activation path
  the tap area takes (the gates included);
- the queue drawer's actions (PAUSE/RESUME, STOP, close) are ``SpecBtns``,
  which carry the metadata for every dialog action;
- the search field is named.

The companion source test pins the key handlers, because a name alone cannot
be activated by a screen reader without its press action and QML cannot be
driven with synthetic key events from the scenario harness.
"""

from __future__ import annotations

import json
import sys

import pytest
from support.paths import QML_MAIN
from support.qml import EXIT_OK, EXIT_REGRESSED, boot_main_qml, run_scenario
from support.qml_probe import scene_js

# QAccessible::Button.
_ROLE_BUTTON = 43

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

# Every object under the scene whose own shape says "a named button the
# accessibility tree should expose" (marker properties per component), as
# [word, name, role, focusable].
_BUTTONS_BODY = """
    var marker = ARG_MARKER;
    var out = [];
    function walk(o) {
        if (!o) return;
        // Only what is on screen counts: overlays and dismissed panes keep
        // their items in the tree, and a hidden control is not a missing one.
        if (o.visible !== false && o.width > 0 && marker(o)) {
            out.push({ word: "" + (o.label || o.accessibleLabel || ""),
                       name: "" + (o.Accessible.name || ""),
                       role: Number(o.Accessible.role),
                       focusable: o.activeFocusOnTab === true });
        }
        var kids = o.children || [];
        for (var i = 0; i < kids.length; i++) walk(kids[i]);
        if (o.contentItem) walk(o.contentItem);
        if (o.item) walk(o.item);
    }
    var roots = ARG_SCOPE;
    for (var r = 0; r < roots.length; r++) walk(roots[r]);
    return JSON.stringify(out);
"""


@pytest.mark.qml
def test_primary_controls_carry_accessible_names_and_focus():
    run_scenario(
        __file__,
        "--run-scenario",
        timeout=180,
        sandbox_prefix="waves-accessibility-test-",
        failure_message="a primary control is missing its accessible name or keyboard path",
    )


def test_the_handlers_behind_the_keyboard_paths_exist():
    """The scenario proves the metadata; this pins that Enter/Space handlers
    were not dropped from the components the scenario walks (a name alone
    cannot be activated by a screen reader without its press action)."""
    qml = QML_MAIN.read_text(encoding="utf-8")
    for needle in (
        "Accessible.onPressAction: sb.clicked()",
        "Keys.onReturnPressed: sb.clicked()",
        "Keys.onSpacePressed: sb.clicked()",
        "Accessible.onPressAction: nt.clicked()",
        "Keys.onReturnPressed: nt.clicked()",
        "Accessible.onPressAction: db.activate()",
        "Keys.onSpacePressed: db.activate()",
        "Accessible.onPressAction: queueDrawer.open()",
    ):
        assert needle in qml, f"the keyboard path is missing: {needle}"


def _buttons(q, marker: str, scope: str = "[root.contentItem]") -> list[dict]:
    # A Drawer declared at root level is not under contentItem, so callers
    # that need its content pass it explicitly in the scope list.
    body = _BUTTONS_BODY.replace("ARG_MARKER", marker).replace("ARG_SCOPE", scope)
    return list(json.loads(q(scene_js(body))))


def _check_buttons(problems: list[str], buttons: list[dict], what: str, *, minimum: int = 1) -> None:
    """Named, button-roled and tab-reachable: what a screen reader needs."""
    if len(buttons) < minimum:
        problems.append(f"{what}: {len(buttons)} found, expected at least {minimum}")
        return
    for button in buttons:
        where = f"{what} ({button['word'] or 'unnamed'})"
        if not button["name"]:
            problems.append(f"{where} carries no accessible name")
        if button["role"] != _ROLE_BUTTON:
            problems.append(f"{where} is not exposed as a button (role {button['role']})")
        if not button["focusable"]:
            problems.append(f"{where} is not in the tab order")


def _show_search_results(q, settle, bridge) -> None:
    q("openSearch()")
    settle(200)
    q("root._searchSeq = root._navSeq")
    bridge.searchResults.emit(
        {
            "artists": [],
            "albums": [],
            "tracks": [TRACK],
            "videos": [],
            "playlists": [],
            "mixes": [],
            "top": None,
        }
    )
    settle(400)


def _run_scenario() -> int:
    import traceback

    try:
        return _scenario_body()
    except Exception:
        print(traceback.format_exc(), file=sys.stderr)
        return EXIT_REGRESSED


def _scenario_body() -> int:
    booted = boot_main_qml()
    if isinstance(booted, int):
        return booted
    _, q, settle, bridge = booted

    # A visible main surface: the first-run surfaces answered and dismissed
    # (the same three keys every scenario sets).
    q("legalSettings.termsAcceptedVersion = root.termsVersion")
    q("legalSettings.termsAccepted = true")
    q("setupSettings.firstRunAnswered = true")
    settle(200)

    problems: list[str] = []
    # NavTab is the only component carrying its own `active` flag.
    tabs = _buttons(
        q, "function (o) { return o.active !== undefined && o.label !== undefined && o.clicked !== undefined; }"
    )
    _check_buttons(problems, tabs, "a top-bar nav tab", minimum=3)
    _check_buttons(problems, _buttons(q, "function (o) { return o.objectName === 'queueBtn'; }"), "the QUEUE button")
    _show_search_results(q, settle, bridge)
    search = _buttons(q, "function (o) { return o.objectName === 'searchField'; }")
    if not search or not search[0]["name"]:
        problems.append("the search field carries no accessible name")
    _check_buttons(
        problems,
        _buttons(q, "function (o) { return o.chooserKind !== undefined && ('' + o.mediaId) === 't1'; }"),
        "the search result's download button",
    )

    # The queue drawer's actions are SpecBtns (their own primary/danger/icon
    # trio is this component's shape and no other's).
    q("queueDrawer.open()")
    settle(300)
    _check_buttons(
        problems,
        _buttons(
            q,
            "function (o) { return o.primary !== undefined && o.danger !== undefined && o.icon !== undefined; }",
            "[root.contentItem, queueDrawer]",
        ),
        "a queue action",
        minimum=2,
    )

    if problems:
        for line in problems:
            print(f"REGRESSED: {line}", file=sys.stderr)
        return EXIT_REGRESSED
    print("ok")
    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    sys.exit(_run_scenario())
