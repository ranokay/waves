"""The accessibility tree of the primary controls.

The app's controls are custom MouseAreas over rectangles, so the tab order Qt
derives from the text fields alone leaves the download button, the header nav,
the queue button and every dialog action invisible to a screen reader and
unreachable without a pointer. The scenario walks the live tree and asserts
the metadata and focus reachability that make them usable keyboard-only:

- each NavTab and the QUEUE button carry a role, a non-empty name and
  ``activeFocusOnTab``;
- a search result's DownloadButton does the same (its activation path is the
  tap area's: both call the one activate(), pinned by the source test);
- the queue drawer's actions (PAUSE/RESUME, STOP, close) are ``SpecBtns``,
  which carry the metadata for every dialog action, and the repeated CLEAR /
  RETRY ALL controls name their own section;
- a seeded queue's rows carry a keyboard path: Tab reaches each row's card,
  its retry mark and its give-up control, each named for its row; Return
  retries a settled row (or opens a ledger) and Delete gives the row up;
- the search field is named;
- the type chips, SHOW ALL, the logs drawer's level/FOLLOW chips and the gate
  checkboxes are named tab stops that answer Space/Return;
- the Chooser's rows are named, uniquely, as pickers/checkboxes/buttons, its
  picks and toggle reach the parked ask through the shared paths, and a closed
  popover leaves no tab stop inside it;
- the Settings commit actions (CANCEL, SAVE CHANGES) and the update toast's
  actions are named tab stops that answer the keyboard with the commit or the
  branch the pointer takes, and the gate actions (a ``GateAction`` and a
  gate's raw tap target) do the same;
- a real Tab walk (QtTest key delivery) never lands on a control that is not
  on screen: thousands of controls inside closed surfaces (mostly Qt's own
  TextField/ComboBox defaults in the hidden Settings page) keep
  ``activeFocusOnTab`` flags, but Qt's chain filters on effective visibility,
  and the walk proves it.

The companion source test pins the activation handlers (Return/Enter/Space,
Escape, Delete), which the scenario does not drive; the Tab walk below uses
real QtTest key delivery on the chain itself, so a hidden control that somehow
entered it fails the scenario rather than passing on flag reads.
"""

from __future__ import annotations

import json
import re
import sys

import pytest
from support.paths import QML_DIR, QML_MAIN
from support.qml import EXIT_OK, EXIT_PRECONDITION, EXIT_REGRESSED, boot_main_qml, run_scenario, scoped_q
from support.qml_probe import scene_js

# QAccessible::Button / CheckBox / RadioButton.
_ROLE_BUTTON = 43
_ROLE_CHECKBOX = 44
_ROLE_RADIO = 45

# The Chooser popover's own rows: every named, tab-reachable item inside it,
# with the state a reader announces.
_CHOOSER_ROWS_BODY = """
    var pop = findObject(root, "chooserPopover");
    if (!pop || !pop.visible) return JSON.stringify({open: false, rows: []});
    // Walk the contentItem only: reading Accessible off the Popup object
    // itself is what Qt warns about, and the rows live in the content.
    var out = [];
    function walk(o) {
        if (!o) return;
        var name = "" + (o.Accessible && o.Accessible.name ? o.Accessible.name : "");
        // Every tab-reachable row is collected, named or not: a row that loses
        // its name must fail the Python assertion, not vanish from the walk.
        if (o.activeFocusOnTab === true && o.visible !== false && o.width > 0) {
            out.push({ name: name,
                       object: "" + (o.objectName || ""),
                       role: Number(o.Accessible.role),
                       checkable: o.Accessible.checkable === true,
                       checked: o.Accessible.checked === true });
        }
        var kids = o.children || [];
        for (var i = 0; i < kids.length; i++) walk(kids[i]);
        if (o.item) walk(o.item);
    }
    walk(pop.contentItem);
    return JSON.stringify({ open: true, rows: out });
"""

# One stop of a real Tab walk: the stop's identity (for cycle detection),
# what it is, its spoken name, and the effective flags Qt's chain
# filters on. A stop inside a closed surface (the Settings page, the Chooser
# popover, the queue drawer) is a failure, whatever its flags say.
# The identity is the object itself, not a downward tree path: a Popup's
# content hangs off the window's overlay, which an ApplicationWindow's
# contentItem does not contain, so a downward walk from root can never
# locate a drawer's rows.
_TAB_STOP_BODY = """
    var it = root.activeFocusItem;
    // No focused control: keep the stop's full shape so callers can read its
    // flags without a KeyError (the null identity is the broken-chain signal).
    if (!it) return JSON.stringify({ path: null,
                                     object: "", name: "", label: "", type: "",
                                     visible: false, enabled: false, focusable: false,
                                     inSettings: false, inChooser: false, inDrawer: false });
    function inTree(o, needle) {
        while (o) { if (o === needle) return true; o = o.parent; }
        return false;
    }
    var chooser = findObject(root, "chooserPopover");
    return JSON.stringify({ path: "" + it,
                            object: "" + (it.objectName || ""),
                            name: "" + (it.Accessible && it.Accessible.name ? it.Accessible.name : ""),
                            label: "" + (it.label || ""),
                            type: "" + it,
                            visible: it.visible !== false,
                            enabled: it.enabled !== false,
                            focusable: it.activeFocusOnTab === true,
                            inSettings: inTree(it, settingsPage),
                            inChooser: chooser ? inTree(it, chooser.contentItem) : false,
                            inDrawer: queueDrawer.contentItem ? inTree(it, queueDrawer.contentItem) : false });
"""


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

# The Apple enable switch: the one control on the Settings page whose own
# toggle stages an edit, so the commit-action leg has something to commit and
# discard. The schema renders a copy of every field's controls in every
# delegate, so the objectName alone can land on a hidden copy: the switch
# binds its tab stop to its own visibility, which is what selects the one
# on screen.
_APPLE_SWITCH = """
    var sw = findFirst(root, function (o) {
        return o.objectName === "appleEnableSwitch" && o.visible === true && o.activeFocusOnTab === true;
    });
"""

# A seeded queue for the row-level keyboard legs: one settled failure with a
# retry mark and a give-up control, one running collection row whose Return
# opens its ledger, and one queued row whose Delete gives up the wait. The
# row shape is the bridge's own (the one reconcileQueue carries).
_QUEUE_ROWS = (
    "{qid: 9001, name: 'Broken Song', type: 'track', status: 'failed', progress: 0, "
    "media_id: 'm9001', template: '', collection: false, artist: 'Artist', tracks: 0, art: ''},"
    "{qid: 9002, name: 'Rolling Album', type: 'album', status: 'running', progress: 40, "
    "media_id: 'm9002', template: '', collection: true, artist: 'Artist', tracks: 10, art: ''},"
    "{qid: 9003, name: 'Waiting Song', type: 'track', status: 'queued', progress: 0, "
    "media_id: 'm9003', template: '', collection: false, artist: 'Artist', tracks: 0, art: ''}"
)

# Every spoken name the seeded queue's row controls must carry: each row's
# card, its retry mark (when retryable) and its give-up control.
_QUEUE_ROW_NAMES = [
    "Broken Song by Artist",
    "Cancel Rolling Album by Artist",
    "Cancel Waiting Song by Artist",
    "Remove Broken Song by Artist",
    "Retry Broken Song by Artist",
    "Rolling Album by Artist",
    "Waiting Song by Artist",
]


def _adopted(q, object_name: str):
    """The adopted tap area the named host owns, or None.

    The host is the control itself for a direct adoption, or the component
    instance (a ``GateAction``/``GateCard``/``Check``) whose inner tap area
    carries the contract. Reached by objectName, so a hidden copy of the same
    control on another surface can never answer for it. The host counts only
    when it carries an accessible role itself: a component like ``Check``
    declares ``accessibleLabel`` without adopting the primitive, so returning
    the host there would read the wrong object.
    """
    return q(
        scene_js(
            f'var host = findObject(root, "{object_name}");'
            " if (!host) return null;"
            " if (host.accessibleLabel !== undefined && Number(host.Accessible.role) !== 0) return host;"
            " return findFirst(host, function (o) { return o.accessibleLabel !== undefined && Number(o.Accessible.role) !== 0; });"
        )
    )


def _control_facts(q, finder_js: str) -> dict | None:
    """The reader facts of the control a JS expression names."""
    return json.loads(
        q(
            scene_js(f"""
        var c = {finder_js};
        return JSON.stringify(c ? {{ name: "" + c.Accessible.name,
                                    role: Number(c.Accessible.role),
                                    checkable: c.Accessible.checkable === true,
                                    checked: c.Accessible.checked === true,
                                    focusable: c.activeFocusOnTab === true }} : null);
    """)
        )
    )


def _focus(q, finder_js: str) -> None:
    """Give the control a JS expression names the active focus."""
    q(scene_js(f"var c = {finder_js}; if (c) c.forceActiveFocus();"))


def _check_finder(host_js: str) -> str:
    """A JS expression naming the checkbox tap area inside a host."""
    return f"findFirst({host_js}, function (o) {{ return Number(o.Accessible.role) === {_ROLE_CHECKBOX}; }})"


def _press_checkbox(problems: list[str], q, settle, root, finder_js: str, key, checked_js: str, what: str) -> None:
    """A gate checkbox is a named checkbox tab stop, and ``key`` ticks it."""
    from PySide6.QtTest import QTest

    facts = _control_facts(q, finder_js)
    if facts is None or not facts["focusable"] or not facts["name"]:
        problems.append(f"{what} is not a named tab stop: {facts}")
        return
    if facts["role"] != _ROLE_CHECKBOX:
        problems.append(f"{what} is not exposed as a checkbox: {facts}")
        return
    _focus(q, finder_js)
    settle(80)
    QTest.keyClick(root, key)
    settle(150)
    if not bool(q(checked_js)):
        problems.append(f"the key press on {what} never ticked it")


def _spoken_name(q, object_name: str) -> str:
    """The spoken name of the named control, or "" when it is not in the tree."""
    return q(
        scene_js(f'var c = findObject(root, "{object_name}"); return c && c.Accessible ? "" + c.Accessible.name : "";')
    )


def _open_settings(q, settle) -> bool:
    """Open the Settings page through its nav tab; whether it is open after."""
    opened = bool(
        q(
            scene_js("""
        var tab = findFirst(root, function (o) { return o.label === "Settings" && o.clicked !== undefined; });
        if (!tab) return false;
        tab.clicked();
        return true;
    """)
        )
    )
    settle(300)
    return opened and bool(q("root.settingsOpen"))


def _tab_step(q, settle, root) -> dict:
    """One real Tab press and the stop it landed on."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    QTest.keyClick(root, Qt.Key_Tab)
    settle(20)
    return json.loads(q(scene_js(_TAB_STOP_BODY)))


def _tab_until(q, settle, root, want, *, limit: int = 300) -> tuple[dict | None, list[str]]:
    """Real Tab presses until a stop matches ``want``.

    Returns the matching stop (or None) and the spoken names of the stops the
    walk did reach, so a control that fell out of the tab order fails with
    what was there instead. The walk ends when the chain comes back to its
    first stop or loses the focused control.
    """
    names: list[str] = []
    first: str | None = None
    for _ in range(limit):
        stop = _tab_step(q, settle, root)
        if stop["path"] is None:
            names.append("<focus lost>")
            return None, names
        names.append(stop["name"] or stop["object"] or stop["type"])
        if want(stop):
            return stop, names
        if first is None:
            first = stop["path"]
        elif stop["path"] == first:
            return None, names
    return None, names


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
    """The scenario proves the metadata and drives Tab; this pins the
    activation handlers it does not drive. Every press action has its own
    Return/Enter/Space handler, each accepts the event and ignores
    auto-repeat, and the two extra keys (Down opens the chooser, Escape
    clears the search box, Delete cancels a queued row) are present."""
    # The download control, the queue drawer, the shared action button, the
    # gate action, the paste-decode controller and the nav chrome live in
    # their own files, and the controls that adopted the shared tap area now
    # answer through TapAction.qml; the pins span the whole primary-control
    # surface, so read all thirteen.
    qml = QML_MAIN.read_text(encoding="utf-8") + (QML_DIR / "DownloadButton.qml").read_text(encoding="utf-8")
    qml += (QML_DIR / "QueueDrawer.qml").read_text(encoding="utf-8")
    qml += (QML_DIR / "SpecBtn.qml").read_text(encoding="utf-8")
    qml += (QML_DIR / "GateAction.qml").read_text(encoding="utf-8")
    qml += (QML_DIR / "DecodeController.qml").read_text(encoding="utf-8")
    qml += (QML_DIR / "NavTab.qml").read_text(encoding="utf-8")
    qml += (QML_DIR / "NavCrumbTrail.qml").read_text(encoding="utf-8")
    qml += (QML_DIR / "GateCard.qml").read_text(encoding="utf-8")
    qml += (QML_DIR / "TapAction.qml").read_text(encoding="utf-8")
    qml += (QML_DIR / "Check.qml").read_text(encoding="utf-8")
    qml += (QML_DIR / "ShowAllLabel.qml").read_text(encoding="utf-8")
    qml += (QML_DIR / "LogsDrawer.qml").read_text(encoding="utf-8")
    # The settings commit actions are adoptions too; the page's switch answers
    # Keys.onPressed (one handler, three keys), so it stays outside the
    # per-file Return/Enter/Space shape below but inside the adoption count.
    qml += (QML_DIR / "SettingsPage.qml").read_text(encoding="utf-8")
    press_actions = qml.count("Accessible.onPressAction")
    assert press_actions >= 5, "the primary controls lost their press actions"
    # The shared TapAction answers every control that adopts it with one
    # handler trio, so the global counts no longer pair one-to-one; the shape
    # that still holds is per file: a file that answers presses carries at
    # least as many Return/Enter/Space handlers.
    for name in (
        "Main.qml",
        "DownloadButton.qml",
        "QueueDrawer.qml",
        "SpecBtn.qml",
        "GateAction.qml",
        "DecodeController.qml",
        "NavTab.qml",
        "NavCrumbTrail.qml",
        "GateCard.qml",
        "TapAction.qml",
        "Check.qml",
        "ShowAllLabel.qml",
        "LogsDrawer.qml",
    ):
        body = (QML_MAIN if name == "Main.qml" else QML_DIR / name).read_text(encoding="utf-8")
        file_presses = body.count("Accessible.onPressAction")
        for key in ("Return", "Enter", "Space"):
            handlers = body.count(f"Keys.on{key}Pressed")
            assert handlers >= file_presses, f"{name}: only {handlers} {key} handlers for {file_presses} press actions"
    # Every adoption names itself: the primitive defaults its spoken name to
    # empty, so an unnamed adopter would ship a silent button. The label
    # bindings are pinned one by one, since counting ``accessibleLabel:``
    # across the files would be satisfied by the unrelated declarations in
    # QueueDrawer/SpecBtn/TapAction.
    assert qml.count("TapAction {") >= 8, "the adopted controls lost their tap area"
    flat = re.sub(r"\s+", " ", qml)
    for needle in (
        "if (!event.isAutoRepeat)",
        "event.accepted = true",
        "Keys.onDownPressed: function (event) { if (db.chooserReachable())",
        "Keys.onDeletePressed: function (event) {",
        "Keys.onEscapePressed: function (event) {",
        "Accessible.checkable: true",
        "function cancel() {",
        # The Chooser's own rows: each drawn option's key handlers
        # call the one pick/toggle path the pointer and the reader use, and the
        # confirm carries its press action like every other action.
        "db.chooserPickTier(modelData.word)",
        "db.chooserPickAudio(modelData)",
        'db.chooserToggle("lyrics_ttml_file")',
        "Accessible.onPressAction: function () { db.confirmChooser() }",
        # Every adopted tap area carries its spoken name, the toast's
        # following the face it draws.
        'accessibleLabel: "CANCEL"',
        'accessibleLabel: "SAVE CHANGES"',
        "accessibleLabel: utAct.realLabel",
        'accessibleLabel: updateToast.face === "ready" ? "LATER" : "Dismiss"',
        'accessibleLabel: "Not now"',
        'accessibleLabel: "I don\'t need FFmpeg. Stop showing this at launch."',
        "accessibleLabel: ga.label",
        # The gate card's spoken name carries its chip.
        'accessibleLabel: gcard.title + (gcard.chip !== ""',
        # The queue's repeated actions name their own section.
        '"Retry all " + host.queueSectionWord(secItem.section)',
        '"Clear " + host.queueSectionWord(secItem.section)',
        # The queue's row controls name their own row, and the row's
        # Return/Delete ride the row's own activate/give-up paths.
        "qrow.rowActivate()",
        "qrow.giveUp()",
        'accessibleLabel: "Retry " + qrow.spokenName()',
        '(qrow.live ? "Cancel " : "Remove ") + qrow.spokenName()',
        # The chips, SHOW ALL and the gate checkboxes speak the words they
        # draw, and a checkable one says so.
        "accessibleLabel: saText.text",
        "accessibleLabel: tchip.modelData[1]",
        '"Log level " + modelData[1]',
        'accessibleLabel: "Follow new log lines"',
        'accessibleLabel: "Don\'t ask again"',
        'accessibleLabel: "Don\'t warn me again"',
        'accessibleLabel: "I have read and agree to these terms."',
        "onTriggered: chk.toggled()",
    ):
        assert re.sub(r"\s+", " ", needle) in flat, f"the keyboard path is missing: {needle}"
    # The queue row's Delete key is the row's own give-up path, not a
    # second copy of the cancel/remove rule.
    queue_qml = (QML_DIR / "QueueDrawer.qml").read_text(encoding="utf-8")
    assert "Keys.onDeletePressed" in queue_qml, "the queue row lost its Delete key"
    assert queue_qml.count("waves.cancelQueueItem(model.qid)") == 1, "the queue row grew a second cancel path"
    assert queue_qml.count("waves.removeQueueItem(model.qid)") == 1, "the queue row grew a second remove path"


def _buttons(q, marker: str, scope: str = "[root.contentItem]") -> list[dict]:
    # A Drawer declared at root level is not under contentItem, so callers
    # that need its content pass it explicitly in the scope list.
    body = _BUTTONS_BODY.replace("ARG_MARKER", marker).replace("ARG_SCOPE", scope)
    return list(json.loads(q(scene_js(body))))


def _check_buttons(
    problems: list[str], buttons: list[dict], what: str, *, minimum: int = 1, role: int = _ROLE_BUTTON
) -> None:
    """Named, correctly-roled and tab-reachable: what a screen reader needs."""
    if len(buttons) < minimum:
        problems.append(f"{what}: {len(buttons)} found, expected at least {minimum}")
        return
    for button in buttons:
        where = f"{what} ({button['word'] or 'unnamed'})"
        if not button["name"]:
            problems.append(f"{where} carries no accessible name")
        if button["role"] != role:
            problems.append(f"{where} is not exposed with role {role} (role {button['role']})")
        if not button["focusable"]:
            problems.append(f"{where} is not in the tab order")


def _show_search_results(q, settle, bridge) -> None:
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


def _tab_cycle(q, settle, root, *, limit: int = 500) -> tuple[list[dict], bool]:
    """Real Tab presses from the current focus.

    Returns every stop and whether the chain came back to its first stop.
    A stop whose ``path`` is None is one the walk could not locate in the tree
    (the focused control or the harness is off), which the caller reads as a
    broken chain; it ends the walk.
    """
    stops: list[dict] = []
    for _ in range(limit):
        stop = _tab_step(q, settle, root)
        if stop["path"] is None:
            stops.append(stop)
            return stops, False
        if stops and stop["path"] == stops[0]["path"]:
            return stops, True
        stops.append(stop)
    return stops, False


# The closed surfaces a stop must never belong to: all three are closed at
# every walk in the scenario, so any stop inside one is a failure even when
# its own `visible` read is true (the closed-popup case).
_CLOSED_SURFACES = ("inSettings", "inChooser", "inDrawer")


def _offscreen(stop: dict) -> bool:
    """Whether a keyboard user must never reach this stop."""
    return not stop["visible"] or not stop["enabled"] or any(stop[key] for key in _CLOSED_SURFACES)


def _run_scenario() -> int:
    import traceback

    try:
        return _scenario_body()
    except Exception:
        print(traceback.format_exc(), file=sys.stderr)
        return EXIT_REGRESSED


def _scenario_body() -> int:  # noqa: C901 (one straight scenario)
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QAccessible
    from PySide6.QtTest import QTest

    booted = boot_main_qml()
    if isinstance(booted, int):
        return booted
    root, q, settle, bridge = booted

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
    if not search or not any(field["name"] for field in search):
        problems.append("the search field carries no accessible name")
    _check_buttons(
        problems,
        _buttons(q, "function (o) { return o.chooserKind !== undefined && ('' + o.mediaId) === 't1'; }"),
        "the search result's download button",
    )

    # --- The real Tab chain. Flag reads find thousands of hidden tab stops:
    # every TextField/ComboBox default inside the closed Settings page keeps
    # `activeFocusOnTab`, and the Chooser's rows keep theirs behind the closed
    # popover. Qt's chain filters on effective
    # visibility and enabled, so a keyboard user never reaches them. One full
    # cycle of real Tab presses proves it: every stop must be a control that
    # is on screen, and none of the closed surfaces may own a stop.
    root.requestActivate()
    settle(100)
    stops, cycled = _tab_cycle(q, settle, root)
    if any(s["path"] is None for s in stops):
        problems.append("the Tab walk lost the focused control")
    elif not cycled:
        problems.append(f"the Tab walk made {len(stops)} stops without returning to its first")
    else:
        offscreen = [s for s in stops if _offscreen(s)]
        if offscreen:
            problems.append(f"Tab reaches a control that is not on screen: {offscreen[:3]}")
        if len(stops) < 5:
            labels = [s["object"] or s["type"] for s in stops]
            problems.append(f"the Tab walk stalled after {len(stops)} stops: {labels}")
        if "queueBtn" not in {s["object"] for s in stops} or not any(s["label"] == "Settings" for s in stops):
            problems.append(f"the Tab walk missed the top bar's controls: {[s['object'] or s['type'] for s in stops]}")

        # Two-sided proof for the Settings page's fields: none of them is
        # reachable while the page is closed (above), and they are once the
        # page is open. The page's programmatic close restores the surface,
        # and the walk after it must lose the fields again.
        if bool(q("root.settingsOpen")):
            problems.append("the Tab walk ran with the Settings page open")
        else:
            if not _open_settings(q, settle):
                problems.append("the Settings tab did not open the Settings page")
            else:
                page_stops, _ = _tab_cycle(q, settle, root, limit=80)
                if any(s["path"] is None for s in page_stops):
                    problems.append("the Tab walk lost the focused control on the open Settings page")
                else:
                    if not any(s["inSettings"] for s in page_stops):
                        problems.append("the Settings page's fields are not in the tab order while the page is open")
                    if any(not s["visible"] or not s["enabled"] for s in page_stops):
                        problems.append(f"Tab reached a hidden control on the open Settings page: {page_stops[:3]}")
                q("settingsPage.closed()")
                settle(250)
                closed_stops, _ = _tab_cycle(q, settle, root, limit=80)
                if any(s["path"] is None for s in closed_stops):
                    problems.append("the Tab walk lost the focused control after closing Settings")
                else:
                    if any(s["inSettings"] for s in closed_stops):
                        problems.append("the closed Settings page kept a tab stop")
                    if any(_offscreen(s) for s in closed_stops):
                        problems.append(
                            f"Tab reaches a control that is not on screen after closing Settings: {closed_stops[:3]}"
                        )

    # --- The Chooser: its rows are named, tab-reachable controls,
    # and a keyboard user's picks reach the queue through the shared paths.
    opened = q(
        scene_js("""
        var b = findFirst(root, function (o) { return o.chooserKind !== undefined && ('' + o.mediaId) === 't1'; });
        if (!b) return false;
        b.openChooser();
        return true;
    """)
    )
    if not opened:
        problems.append("the search result's download button could not open its Chooser")
    settle(250)
    popover = json.loads(q(scene_js(_CHOOSER_ROWS_BODY)))
    if not popover["open"]:
        problems.append("the Chooser popover did not open")
    rows = popover["rows"]
    tiers = [r for r in rows if r["object"] == "chooserTierRow"]
    audio = [r for r in rows if r["object"] == "chooserAudioTile"]
    toggles = [r for r in rows if r["object"].startswith("chooserLyrics") or r["object"].startswith("chooserCover")]
    actions = [r for r in rows if r["object"] in ("chooserSetDefaults", "chooserConfirm")]
    if len(tiers) < 3:
        problems.append(f"the Chooser's tier rows are not exposed as pickers ({len(tiers)} found)")
    elif any(t["role"] != _ROLE_RADIO for t in tiers):
        problems.append(f"a Chooser tier row is not a radio button: {[t['role'] for t in tiers]}")
    if not any(t["checked"] for t in tiers):
        problems.append("no Chooser tier row reports itself as picked")
    if len(audio) < 1:
        problems.append("the Chooser's audio rows are not exposed as pickers")
    elif any(a["role"] != _ROLE_RADIO for a in audio):
        problems.append(f"a Chooser audio tile is not a radio button: {[a['role'] for a in audio]}")
    if len(toggles) < 1:
        problems.append("the Chooser's lyrics/art toggles are not exposed as checkboxes")
    elif any(t["role"] != _ROLE_CHECKBOX for t in toggles):
        problems.append(f"a Chooser toggle is not a checkbox: {[t['role'] for t in toggles]}")
    if len(actions) < 2:
        problems.append(f"the Chooser's actions are not both reachable ({len(actions)} found)")
    unnamed = [r["object"] or "?" for r in rows if not r["name"]]
    if unnamed:
        problems.append(f"a Chooser row carries no accessible name: {unnamed}")
    names = [r["name"] for r in rows]
    if len(names) != len(set(names)):
        problems.append(f"the Chooser's rows repeat a spoken name: {names}")

    # The pick/confirm paths the handlers call (the key handlers themselves are
    # pinned by the companion source test): choose a tier and an audio word and
    # flip a toggle, confirm, and read the parked click's ask.
    q(
        scene_js("""
        var b = findFirst(root, function (o) { return o.chooserKind !== undefined && ('' + o.mediaId) === 't1'; });
        if (!b) return false;
        b.chooserPickTier("LOSSLESS");
        b.chooserPickAudio("atmos");
        b.chooserToggle("cover_file");
        b.confirmChooser();
        return true;
    """)
    )
    settle(250)
    parked = getattr(bridge, "_chooser_refetch_pins", {}).get(("track", "t1"))
    if parked is None:
        problems.append("confirming the Chooser never parked its click's ask")
    else:
        kind, tier, audio_word, toggles_picked = parked
        if (kind, tier, audio_word) != ("track", "LOSSLESS", "atmos"):
            problems.append(f"the Chooser confirmed the wrong ask: {parked}")
        # The sandbox default has the cover sidecar on, so the toggle flips it
        # off; the ask must carry the flipped value, not the default.
        if toggles_picked.get("cover_album_file") is not False:
            problems.append(f"the Chooser's toggle never reached the ask: {parked}")
    if bool(q(scene_js('var p = findObject(root, "chooserPopover"); return p ? p.visible : false;'))):
        problems.append("the Chooser popover stayed open after confirming")

    # The queue drawer's actions are SpecBtns (their own primary/danger/icon
    # trio is this component's shape and no other's). A queued row puts PAUSE
    # beside the always-present close button, so the assertion sees drawer
    # actions rather than anything else in the tree.
    q("queueDrawer.open()")
    settle(300)
    if not bool(q("queueDrawer.opened")):
        print("the queue drawer did not open", file=sys.stderr)
        return EXIT_PRECONDITION
    q(f"reconcileQueue([{_QUEUE_ROWS}])")
    settle(250)
    _check_buttons(
        problems,
        _buttons(
            q,
            "function (o) { return o.primary !== undefined && o.danger !== undefined && o.icon !== undefined; }",
            "[queueDrawer.contentItem]",
        ),
        "a queue action",
        minimum=2,
    )

    # Repeated CLEAR / RETRY ALL controls must name their own section.
    # Two sections are on screen, so the names have
    # to differ; the view pools headers, so identical (name) pairs from the
    # same section dedupe before the uniqueness read.
    drawer_names = sorted(
        {
            row["name"]
            for row in _buttons(
                q,
                "function (o) { return o.primary !== undefined && o.danger !== undefined && o.icon !== undefined; }",
                "[queueDrawer.contentItem]",
            )
            if row["name"]
        }
    )
    clears = sorted(name for name in drawer_names if name.startswith("Clear "))
    if len(clears) < 2:
        problems.append(f"the queue's CLEAR controls do not name their own sections: {drawer_names}")
    retries = sorted(name for name in drawer_names if name.startswith("Retry all "))
    if retries != ["Retry all Failed downloads"]:
        problems.append(f"the queue's RETRY ALL control does not name its section: {drawer_names}")

    # --- The row-level keyboard paths. Every row control is a named tab
    # stop that names its row; Tab reaches the card, the retry mark and the
    # give-up control, and the keys take the row's own bridge paths (recorded
    # here, since the seeded rows are QML-side only). The card's Return opens
    # a ledger where there is one and retries where there is not; Delete
    # gives the row up, cancelling a live one and removing a settled one.
    calls: list[tuple[str, int]] = []
    bridge.retryQueueItem = lambda qid: calls.append(("retry", int(qid)))
    bridge.cancelQueueItem = lambda qid: calls.append(("cancel", int(qid)))
    bridge.removeQueueItem = lambda qid: calls.append(("remove", int(qid)))

    rows = _buttons(
        q,
        "function (o) { return o.objectName === 'queueRowCard' || o.objectName === 'queueRowRetry' || o.objectName === 'queueRowGiveUp'; }",
        "[queueDrawer.contentItem]",
    )
    row_names = sorted({row["name"] for row in rows})
    if row_names != _QUEUE_ROW_NAMES:
        problems.append(f"the queue rows do not name their own controls: {row_names}")
    problems.extend(
        f"a queue row control is not a named tab stop: {row}" for row in rows if not row["name"] or not row["focusable"]
    )

    # The pointer path is unchanged: a real click on the album row's card
    # opens its ledger exactly once per click (the keyboard's retry must not
    # ride the click, and no handler pair may toggle it twice), and a click
    # on a settled row's card reaches no row action.
    def _card_point(name: str) -> dict | None:
        raw = q(
            scene_js(f"""
        var c = findFirst(queueDrawer.contentItem, function (o) {{
            return o.objectName === "queueRowCard" && ("" + o.Accessible.name) === "{name}";
        }});
        if (!c) return null;
        var p = c.mapToItem(null, c.width / 2, c.height / 2);
        return JSON.stringify({{ x: Math.round(p.x), y: Math.round(p.y) }});
    """)
        )
        return json.loads(raw) if raw is not None else None

    album_point = _card_point("Rolling Album by Artist")
    if album_point is None:
        problems.append("the album row's card is not in the tree to click")
    else:
        before = len(calls)
        QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, QPoint(album_point["x"], album_point["y"]))
        settle(300)
        if not bool(q("queueExpanded[9002] === true")):
            problems.append("a click on the album row's card never opened its ledger")
        if len(calls) != before:
            problems.append(f"a click on the album row's card reached a row action: {calls[before:]}")
        # Re-measure: the card grew its ledger under the first click.
        album_point = _card_point("Rolling Album by Artist")
        if album_point is None:
            problems.append("the album row's card left the tree after opening")
        else:
            QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, QPoint(album_point["x"], album_point["y"]))
            settle(300)
            if bool(q("queueExpanded[9002] === true")):
                problems.append("a second click on the album row's card never closed its ledger")
    failed_point = _card_point("Broken Song by Artist")
    if failed_point is not None:
        before = len(calls)
        QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, QPoint(failed_point["x"], failed_point["y"]))
        settle(250)
        if len(calls) != before:
            problems.append(f"a click on a settled row's card reached a row action: {calls[before:]}")

    qd = scoped_q(q, "queueDrawer.background")
    qd("queueCloseBtn.forceActiveFocus()")
    settle(80)

    def _row_stop(name: str, limit: int = 140) -> tuple[dict | None, list[str]]:
        return _tab_until(q, settle, root, lambda s: s["name"] == name, limit=limit)

    # The failed row's card: Return retries it, Delete removes it.
    stop, seen = _row_stop("Broken Song by Artist")
    if stop is None:
        problems.append(f"Tab never reached the failed row's card: {seen[-8:]}")
    else:
        QTest.keyClick(root, Qt.Key_Return)
        settle(200)
        if ("retry", 9001) not in calls:
            problems.append(f"Return on the failed row's card never retried it: {calls}")
        QTest.keyClick(root, Qt.Key_Delete)
        settle(200)
        if ("remove", 9001) not in calls:
            problems.append(f"Delete on the failed row's card never removed it: {calls}")

    # Its retry mark and give-up control answer Return on their own, and
    # Delete works from any of the row's stops: the key bubbles from the
    # focused control to the delegate's one give-up handler.
    stop, seen = _row_stop("Retry Broken Song by Artist")
    if stop is None:
        problems.append(f"Tab never reached the row's retry mark: {seen[-8:]}")
    else:
        QTest.keyClick(root, Qt.Key_Return)
        settle(200)
        if calls.count(("retry", 9001)) < 2:
            problems.append(f"Return on the retry mark never retried the row: {calls}")
        QTest.keyClick(root, Qt.Key_Delete)
        settle(200)
        if calls.count(("remove", 9001)) < 2:
            problems.append(f"Delete on the retry mark never gave the row up: {calls}")
    stop, seen = _row_stop("Remove Broken Song by Artist")
    if stop is None:
        problems.append(f"Tab never reached the row's give-up control: {seen[-8:]}")
    else:
        QTest.keyClick(root, Qt.Key_Return)
        settle(200)
        if calls.count(("remove", 9001)) < 3:
            problems.append(f"Return on the give-up control never removed the row: {calls}")

    # A collection row's card opens its ledger on Return; a live row's card
    # gives the wait up on Delete.
    stop, seen = _row_stop("Rolling Album by Artist")
    if stop is None:
        problems.append(f"Tab never reached the album row's card: {seen[-8:]}")
    else:
        QTest.keyClick(root, Qt.Key_Return)
        settle(250)
        if not bool(q("queueExpanded[9002] === true")):
            problems.append("Return on an album row's card never opened its ledger")
    stop, seen = _row_stop("Waiting Song by Artist")
    if stop is None:
        problems.append(f"Tab never reached the queued row's card: {seen[-8:]}")
    else:
        QTest.keyClick(root, Qt.Key_Delete)
        settle(200)
        if ("cancel", 9003) not in calls:
            problems.append(f"Delete on the queued row's card never gave up the wait: {calls}")

    # No tab stop may sit behind a closed popup: after confirming, nothing in
    # the popover keeps activeFocusOnTab.
    q("queueDrawer.close()")
    settle(250)
    hidden = list(
        json.loads(
            q(
                scene_js("""
        var pop = findObject(root, "chooserPopover");
        var out = [];
        function walk(o) {
            if (!o) return;
            // Any tab stop left in the closed popover is the regression: the
            // rows' own `visible` stays true behind a closed Popup, so only
            // their `activeFocusOnTab` gate keeps them out of the tab order.
            if (o.activeFocusOnTab === true) {
                out.push("" + (o.objectName || "?"));
            }
            var kids = o.children || [];
            for (var i = 0; i < kids.length; i++) walk(kids[i]);
            if (o.item) walk(o.item);
        }
        if (pop) walk(pop.contentItem);
        return JSON.stringify(out);
    """)
            )
        )
    )
    if hidden:
        problems.append(f"controls inside the closed Chooser keep a tab stop: {hidden}")

    # The drawer and the popover have now been built and closed; a real Tab
    # walk from here must not land inside either, whatever their rows' flags
    # say. The invariant covers the popup surfaces that only exist after a
    # first open; the guard keeps a surface that went
    # missing from passing the walk vacuously.
    settle(100)
    built = json.loads(
        q(
            scene_js("""
        var pop = findObject(root, "chooserPopover");
        return JSON.stringify({ pop: pop !== null,
                                drawer: queueDrawer.contentItem !== null,
                                popOpen: pop ? pop.visible : false,
                                drawerOpen: queueDrawer.visible });
    """)
        )
    )
    if not built["pop"] or not built["drawer"] or built["popOpen"] or built["drawerOpen"]:
        problems.append(f"the closed surfaces are not ready for the Tab walk: {built}")
    else:
        final_stops, _ = _tab_cycle(q, settle, root, limit=80)
        if any(s["path"] is None for s in final_stops):
            problems.append("the closing Tab walk lost the focused control")
        else:
            stray = [s for s in final_stops if _offscreen(s)]
            if stray:
                problems.append(f"Tab reaches a control behind a closed surface: {stray[:3]}")

    # --- The Settings commit actions: an edit stages, Tab reaches CANCEL and
    # SAVE CHANGES in the page's own chain, Return commits, and Space
    # discards without ever committing the pointer's side.
    if not _open_settings(q, settle):
        problems.append("the Settings tab did not open the Settings page for the commit actions")
    else:
        before = bool(q("waves.appleEnabled"))
        saved = before
        staged = bool(q(scene_js(_APPLE_SWITCH + "if (!sw) return false; sw.toggle(); return true;")))
        settle(250)
        if not staged or not bool(q("settingsPage.dirty")):
            problems.append("the Apple switch could not stage an edit to commit")
        else:
            q("settingsPage.forceActiveFocus()")
            settle(80)
            cancel_stop, seen = _tab_until(
                q, settle, root, lambda s: s["object"] == "cancelEditsBtn" and s["inSettings"], limit=120
            )
            if cancel_stop is None:
                problems.append(f"Tab never reached CANCEL inside Settings: {seen[-8:]}")
            elif cancel_stop["name"] != "CANCEL" or not cancel_stop["focusable"]:
                problems.append(
                    f"CANCEL is not a named tab stop: name={cancel_stop['name']!r} focusable={cancel_stop['focusable']}"
                )
            save_stop, seen = _tab_until(
                q, settle, root, lambda s: s["object"] == "saveChangesBtn" and s["inSettings"], limit=120
            )
            if save_stop is None:
                problems.append(f"Tab never reached SAVE CHANGES inside Settings: {seen[-8:]}")
            elif save_stop["name"] != "SAVE CHANGES" or not save_stop["focusable"]:
                problems.append(
                    f"SAVE CHANGES is not a named tab stop: name={save_stop['name']!r} focusable={save_stop['focusable']}"
                )
            elif not save_stop["enabled"]:
                problems.append("SAVE CHANGES is not enabled while an edit is staged")
            else:
                QTest.keyClick(root, Qt.Key_Return)
                settle(500)
                saved = bool(q("waves.appleEnabled"))
                if bool(q("settingsPage.dirty")) or not bool(q("settingsPage.savedFlash")):
                    problems.append("Return on SAVE CHANGES never committed the staged edit")
                elif saved == before:
                    problems.append("the committed edit never changed the provider setting")

            # A second edit, discarded with Space on CANCEL: the committed
            # value must survive it.
            if not bool(q(scene_js(_APPLE_SWITCH + "if (!sw) return false; sw.toggle(); return true;"))):
                problems.append("the Apple switch vanished before the CANCEL leg")
            else:
                settle(250)
                if not bool(q("settingsPage.dirty")):
                    problems.append("the second edit did not stage")
                else:
                    q("settingsPage.forceActiveFocus()")
                    settle(80)
                    cancel_stop, seen = _tab_until(
                        q, settle, root, lambda s: s["object"] == "cancelEditsBtn" and s["inSettings"], limit=120
                    )
                    if cancel_stop is None:
                        problems.append(f"Tab never reached CANCEL for the discard: {seen[-8:]}")
                    else:
                        QTest.keyClick(root, Qt.Key_Space)
                        settle(400)
                        if bool(q("settingsPage.dirty")):
                            problems.append("Space on CANCEL never discarded the staged edit")
                        elif bool(q("waves.appleEnabled")) != saved:
                            problems.append("CANCEL discarded the committed value, not just the staged edit")
    q("settingsPage.closed()")
    settle(250)

    # --- The update toast: both actions are named as drawn, tab-reachable,
    # and the key press takes the same branch the pointer does. The install
    # worker is pinned inflight, so the branch's own bookkeeping runs without
    # spawning a real download.
    bridge._app_update_inflight = True
    q('updateToast.offer("9.9.9")')
    q("updateToast.selfInstall = true")
    settle(250)
    if q("updateToast.phase") != "offer":
        problems.append("the update toast did not offer for the toast leg")
    else:
        primary = _adopted(q, "updateToastPrimary")
        if primary is None:
            problems.append("the toast's primary action is not in the tree")
        elif not bool(primary.property("activeFocusOnTab")):
            problems.append("the toast's primary action is not a tab stop")
        else:
            primary.forceActiveFocus()
            settle(80)
            QTest.keyClick(root, Qt.Key_Return)
            settle(300)
            if q("updateToast.phase") != "installing":
                problems.append("Return on the toast's INSTALL never took the install branch")
            elif q("setupSettings.updateToastDismissed") != "9.9.9":
                problems.append("the toast's key press never marked the offer acted on")

        # Every face's word rides the spoken name: CANCEL on the installing
        # face the press just reached, then RESTART NOW, RETRY, INSTALL and
        # VIEW on the other faces.
        for phase, word in (
            ("installing", "CANCEL"),
            ("ready", "RESTART NOW"),
            ("failed", "RETRY"),
            ("offer", "INSTALL"),
        ):
            q(f"updateToast.phase = '{phase}'")
            settle(150)
            spoken = _spoken_name(q, "updateToastPrimary")
            if spoken != word:
                problems.append(f"the toast's {word} face speaks as {spoken!r}")
        q("updateToast.selfInstall = false")
        settle(150)
        if _spoken_name(q, "updateToastPrimary") != "VIEW":
            problems.append("the toast's package-manager face does not speak VIEW")

        # The secondary answers Space and dismisses; its name is LATER while
        # the face says LATER, and Dismiss while it draws only the glyph.
        q("updateToast.phase = 'ready'")
        settle(250)
        if _spoken_name(q, "updateToastSecondary") != "LATER":
            problems.append("the toast's LATER action is not named LATER")
        later = _adopted(q, "updateToastSecondary")
        if later is None:
            problems.append("the toast's LATER action is not in the tree")
        elif not bool(later.property("activeFocusOnTab")):
            problems.append("the toast's LATER action is not a tab stop")
        else:
            later.forceActiveFocus()
            settle(80)
            QTest.keyClick(root, Qt.Key_Space)
            settle(300)
            if q("updateToast.phase") != "":
                problems.append("Space on the toast's LATER never dismissed it")
        q("updateToast.phase = 'offer'")
        settle(250)
        if _spoken_name(q, "updateToastSecondary") != "Dismiss":
            problems.append("the toast's glyph action is not named Dismiss")
    q("updateToast.phase = ''")
    bridge._app_update_inflight = False
    settle(200)

    # --- The gate actions: a GateAction, a GateCard and a gate's raw tap
    # target are named tab stops, and their key presses take the gate's own
    # path. The GateCard's own action starts a real install, so only its
    # metadata is read. The FFmpeg state is forced missing (and the gate up)
    # so the option cards are really on screen, not hidden behind state.
    q('appFfmpeg.status = {state: "missing"}')
    q("ffmpegGate.visible = true")
    settle(300)
    card = json.loads(
        q(
            scene_js("""
        var c = findFirst(root, function (o) {
            return o.accessibleLabel !== undefined && o.accessibleLabel.indexOf("Install a managed copy") === 0;
        });
        return JSON.stringify(c ? { name: "" + c.Accessible.name,
                                    role: Number(c.Accessible.role),
                                    focusable: c.activeFocusOnTab === true } : null);
    """)
        )
    )
    if card is None:
        problems.append("the FFmpeg gate's managed-install card is not in the tree")
    else:
        if not card["name"].startswith("Install a managed copy, RECOMMENDED"):
            problems.append(f"the managed-install card speaks as {card['name']!r}, without its chip")
        if card["role"] != _ROLE_BUTTON:
            problems.append(f"the managed-install card is not exposed as a button (role {card['role']})")
        if not card["focusable"]:
            problems.append("the managed-install card is not in the tab order")

    # The card's action, driven for real: "Set it up myself later" only
    # records the choice, unlike the install card next to it.
    later_card = _adopted(q, "ffmpegGateLaterCard")
    if later_card is None:
        problems.append("the FFmpeg gate's later card is not in the tree")
    else:
        later_card.forceActiveFocus()
        settle(80)
        QTest.keyClick(root, Qt.Key_Return)
        settle(300)
        if not bool(q("ffmpegGate.sessionSnoozed")):
            problems.append("Return on a gate card never took the card's path")
    q("ffmpegGate.visible = false")
    settle(150)

    q("root.ffmpegBlocked = true")
    settle(300)
    _check_buttons(
        problems,
        _buttons(q, "function (o) { return o.accessibleLabel === 'Continue anyway'; }"),
        "the FFmpeg block gate's CONTINUE action",
    )
    continue_anyway = _adopted(q, "ffmpegGateContinue")
    if continue_anyway is None:
        problems.append("the FFmpeg block gate's CONTINUE action is not in the tree")
    else:
        continue_anyway.forceActiveFocus()
        settle(80)
        QTest.keyClick(root, Qt.Key_Return)
        settle(300)
        if bool(q("root.ffmpegBlocked")):
            problems.append("Return on a gate action never took the gate's path")

    q("root.folderGateBlocking = true")
    settle(300)
    _check_buttons(
        problems,
        _buttons(q, "function (o) { return o.accessibleLabel === 'Not now'; }"),
        "the folder gate's Not now action",
    )
    not_now = _adopted(q, "folderGateNotNow")
    if not_now is None:
        problems.append("the folder gate's Not now action is not in the tree")
    else:
        not_now.forceActiveFocus()
        settle(80)
        QTest.keyClick(root, Qt.Key_Space)
        settle(300)
        if bool(q("root.folderGateBlocking")):
            problems.append("Space on the folder gate's Not now never closed the gate")

    # A disabled host disables its tap area: the terms gate's ACKNOWLEDGE is
    # inert until its checkbox is ticked, so while disabled it is no tab stop,
    # and ticking the box makes it one again. Without the host binding the
    # tap area keeps the MouseArea's own enabled=true and stays reachable.
    q("termsGate.visible = true")
    settle(300)
    ack = _adopted(q, "termsAckAction")
    if ack is None:
        problems.append("the terms gate's ACKNOWLEDGE action is not in the tree")
    else:
        if bool(ack.property("enabled")):
            problems.append("a disabled gate action's tap area still reads enabled")
        if bool(ack.property("activeFocusOnTab")):
            problems.append("a disabled gate action is still a tab stop")
        # The gate's checkbox answers the keyboard too: its tap area is a
        # named checkbox tab stop, and Space ticks it, which is what arms
        # ACKNOWLEDGE.
        _press_checkbox(
            problems,
            q,
            settle,
            root,
            _check_finder("ackChk"),
            Qt.Key_Space,
            "ackChk.checked",
            "the terms gate's checkbox",
        )
        if not bool(ack.property("enabled")) or not bool(ack.property("activeFocusOnTab")):
            problems.append("ticking the terms checkbox never enabled its ACKNOWLEDGE action")
    q("termsGate.visible = false")
    settle(150)

    # --- The repeated filter/toggle controls: the search type chips, SHOW
    # ALL, the logs drawer's level and FOLLOW chips, and the remaining two
    # gate checkboxes. Each is a named tab stop that answers Space/Return
    # through the same handler the pointer takes.
    bridge._logged_in = True
    bridge.loggedInChanged.emit()
    q("root.refreshProviderSurfaces()")
    settle(200)
    q("openSearch()")
    settle(200)
    q("root._searchSeq = root._navSeq")
    many_tracks = [
        {
            "id": f"t{i}",
            "kind": "track",
            "title": f"Track {i}",
            "artist": "Artist",
            "artist_id": "a1",
            "album": "Album",
            "album_id": "al1",
            "num": i,
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
        for i in range(1, 7)
    ]
    bridge.searchResults.emit(
        {
            "groups": [
                {
                    "provider": "tidal",
                    "artists_layout": "strip",
                    "head_when_alone": False,
                    "artists": [],
                    "albums": [],
                    "tracks": many_tracks,
                    "videos": [],
                    "playlists": [],
                    "mixes": [],
                    "top": None,
                    "error": "",
                }
            ]
        }
    )
    settle(500)
    if not bool(q("root.signedIn")) or not bool(q("root.hasResults")):
        problems.append("the scenario never reached a signed-in search page for the chips")

    chips = _buttons(q, "function (o) { return o.objectName === 'searchTypeChip'; }")
    _check_buttons(problems, chips, "a search type chip", minimum=7, role=_ROLE_RADIO)
    chip_names = sorted(chip["name"] for chip in chips)
    if chip_names != ["Albums", "All", "Artists", "Mixes", "Playlists", "Tracks", "Videos"]:
        problems.append(f"the type chips do not speak their own words: {chip_names}")

    # Tab from the search field to the Albums chip and activate it; the
    # results filter the way the pointer's click filters.
    q("searchField.forceActiveFocus()")
    settle(80)
    stop, seen = _tab_until(
        q, settle, root, lambda s: s["object"] == "searchTypeChip" and s["name"] == "Albums", limit=140
    )
    if stop is None:
        problems.append(f"Tab never reached the Albums chip: {seen[-8:]}")
    else:
        QTest.keyClick(root, Qt.Key_Return)
        settle(250)
        if str(q("root.filterType")) != "albums":
            problems.append(f"Return on the Albums chip never filtered the results: {q('root.filterType')!r}")
        q("root.filterType = 'all'")
        settle(200)

    # The platform's Toggle (what macOS sends for an AX press on a checkable
    # role) reaches a chip through the primitive's one toggle handler.
    chip_item = q(
        scene_js("""
        return findFirst(root, function (o) {
            return o.objectName === "searchTypeChip" && ("" + o.Accessible.name) === "Tracks";
        });
    """)
    )
    chip_actions = None
    if chip_item is not None:
        chip_iface = QAccessible.queryAccessibleInterface(chip_item)
        chip_actions = chip_iface.actionInterface() if chip_iface is not None and chip_iface.isValid() else None
    if chip_actions is None or "Toggle" not in list(chip_actions.actionNames()):
        problems.append("the Tracks chip advertises no platform toggle action")
    else:
        chip_actions.doAction("Toggle")
        settle(250)
        if str(q("root.filterType")) != "tracks":
            problems.append("the platform Toggle never reached the Tracks chip")
        q("root.filterType = 'all'")
        settle(200)

    # SHOW ALL: the capped tracks section's only way open. A disclosure, not
    # a checkbox: its drawn words already state the state (SHOW ALL/SHOW
    # LESS), so it stays a plain button whose name follows the label.
    show_all = _buttons(
        q,
        "function (o) { return o.objectName === 'showAllToggle' && ('' + o.Accessible.name).indexOf('SHOW ALL') === 0; }",
    )
    if not show_all:
        problems.append("the capped tracks section offers no SHOW ALL control")
    else:
        _check_buttons(problems, show_all, "the tracks section's SHOW ALL")
        stop, seen = _tab_until(q, settle, root, lambda s: s["name"] == "SHOW ALL 6", limit=140)
        if stop is None:
            problems.append(f"Tab never reached the tracks SHOW ALL: {seen[-8:]}")
        else:
            QTest.keyClick(root, Qt.Key_Return)
            settle(300)
            if not bool(q("root.searchGroupFor('tidal').isExpanded('tracks')")):
                problems.append("Return on SHOW ALL never expanded the section")

    # The logs drawer's level and FOLLOW chips.
    q("logsDrawer.open()")
    settle(400)
    log_chips = _buttons(
        q,
        "function (o) { return o.objectName === 'logLevelChip'; }",
        "[logsDrawer.contentItem]",
    )
    _check_buttons(problems, log_chips, "a log level chip", minimum=4, role=_ROLE_RADIO)
    follow = _buttons(
        q,
        "function (o) { return o.objectName === 'logFollowChip'; }",
        "[logsDrawer.contentItem]",
    )
    _check_buttons(problems, follow, "the logs FOLLOW chip", role=_ROLE_CHECKBOX)
    qd_logs = scoped_q(q, "logsDrawer.background")
    qd_logs("logsCloseBtn.forceActiveFocus()")
    settle(80)
    stop, seen = _tab_until(q, settle, root, lambda s: s["name"] == "Log level ERROR", limit=40)
    if stop is None:
        problems.append(f"Tab never reached the logs ERROR chip: {seen[-6:]}")
    else:
        QTest.keyClick(root, Qt.Key_Return)
        settle(200)
        if int(q("logsDrawer.logsMinLevel")) != 3:
            problems.append("Return on the logs ERROR chip never raised the level filter")
    stop, seen = _tab_until(q, settle, root, lambda s: s["name"] == "Follow new log lines", limit=40)
    if stop is None:
        problems.append(f"Tab never reached the logs FOLLOW chip: {seen[-6:]}")
    else:
        QTest.keyClick(root, Qt.Key_Space)
        settle(200)
        if bool(q("logsDrawer.logsFollow")):
            problems.append("Space on the logs FOLLOW chip never took the follow off")
    q("logsDrawer.close()")
    settle(250)

    # The exit gate's checkbox and the bulk-download gate's. The gates live
    # in different layers (the exit gate in the window's overlay), so each is
    # reached through its own control id rather than a root-down walk.
    q("exitGate.open = true")
    settle(300)
    _press_checkbox(
        problems,
        q,
        settle,
        root,
        _check_finder("exitSkip"),
        Qt.Key_Space,
        "exitSkip.checked",
        "the exit gate's checkbox",
    )
    q("exitGate.open = false")
    settle(250)

    q("root.catDlPrompt = {path: 'playlists/1', title: 'Category', count: 2}")
    settle(300)
    _press_checkbox(
        problems,
        q,
        settle,
        root,
        _check_finder("cdSkip"),
        Qt.Key_Return,
        "cdSkip.checked",
        "the bulk-download checkbox",
    )
    q("root.catDlDismiss()")
    settle(150)

    if problems:
        for line in problems:
            print(f"REGRESSED: {line}", file=sys.stderr)
        return EXIT_REGRESSED
    print("ok")
    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    sys.exit(_run_scenario())
