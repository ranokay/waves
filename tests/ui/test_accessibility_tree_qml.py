"""The accessibility tree of the primary controls (issue #240 / audit UI-08).

The app's controls are custom MouseAreas over rectangles, so before this the
tab order was whatever Qt derived from the text fields: the download button,
the header nav, the queue button and every dialog action were invisible to a
screen reader and unreachable without a pointer. The scenario walks the live
tree and asserts the metadata and focus reachability that make them usable
keyboard-only:

- each NavTab and the QUEUE button carry a role, a non-empty name and
  ``activeFocusOnTab``;
- a search result's DownloadButton does the same (its activation path is the
  tap area's: both call the one activate(), pinned by the source test);
- the queue drawer's actions (PAUSE/RESUME, STOP, close) are ``SpecBtns``,
  which carry the metadata for every dialog action, and the repeated CLEAR /
  RETRY ALL controls name their own section;
- the search field is named;
- the Chooser's rows are named, uniquely, as pickers/checkboxes/buttons, its
  picks and toggle reach the parked ask through the shared paths, and a closed
  popover leaves no tab stop inside it (issue #284);
- a real Tab walk (QtTest key delivery) never lands on a control that is not
  on screen: thousands of controls inside closed surfaces (mostly Qt's own
  TextField/ComboBox defaults in the hidden Settings page) keep
  ``activeFocusOnTab`` flags, but Qt's chain filters on effective visibility,
  and the walk proves it (issue #295).

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
from support.qml import EXIT_OK, EXIT_PRECONDITION, EXIT_REGRESSED, boot_main_qml, run_scenario
from support.qml_probe import scene_js

# QAccessible::Button / CheckBox / RadioButton.
_ROLE_BUTTON = 43
_ROLE_CHECKBOX = 44
_ROLE_RADIO = 45

# The Chooser popover's own rows: every named, tab-reachable item inside it,
# with the state a reader announces (issue #284).
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

# One stop of a real Tab walk (issue #295): the stop's tree path (for cycle
# detection), what it is, and the effective flags Qt's chain filters on. A
# stop inside a closed surface (the Settings page, the Chooser popover, the
# queue drawer) is a failure, whatever its flags say.
_TAB_STOP_BODY = """
    function pathOf(o, target, path, depth) {
        if (!o || depth > 200) return null;
        if (o === target) return path;
        var kids = o.children || [];
        for (var i = 0; i < kids.length; i++) {
            var hit = pathOf(kids[i], target, path + "/c" + i, depth + 1);
            if (hit) return hit;
        }
        if (o.contentItem && o.contentItem !== o) {
            var content = pathOf(o.contentItem, target, path + "/content", depth + 1);
            if (content) return content;
        }
        if (o.item && o.item !== o) {
            var loaded = pathOf(o.item, target, path + "/item", depth + 1);
            if (loaded) return loaded;
        }
        return null;
    }
    var it = root.activeFocusItem;
    // No focused control: keep the stop's full shape so callers can read its
    // flags without a KeyError (the path is the broken-chain signal).
    if (!it) return JSON.stringify({ path: null,
                                     object: "", label: "", type: "",
                                     visible: false, enabled: false,
                                     inSettings: false, inChooser: false, inDrawer: false });
    function inTree(o, needle) {
        while (o) { if (o === needle) return true; o = o.parent; }
        return false;
    }
    var chooser = findObject(root, "chooserPopover");
    return JSON.stringify({ path: pathOf(root, it, "root", 0),
                            object: "" + (it.objectName || ""),
                            label: "" + (it.label || ""),
                            type: "" + it,
                            visible: it.visible !== false,
                            enabled: it.enabled !== false,
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
    # The download control, the queue drawer and the shared action button
    # live in their own files since #315; the pins span the whole
    # primary-control surface, so read all four.
    qml = QML_MAIN.read_text(encoding="utf-8") + (QML_DIR / "DownloadButton.qml").read_text(encoding="utf-8")
    qml += (QML_DIR / "QueueDrawer.qml").read_text(encoding="utf-8")
    qml += (QML_DIR / "SpecBtn.qml").read_text(encoding="utf-8")
    press_actions = qml.count("Accessible.onPressAction")
    assert press_actions >= 5, "the primary controls lost their press actions"
    for key in ("Return", "Enter", "Space"):
        handlers = qml.count(f"Keys.on{key}Pressed")
        assert handlers >= press_actions, f"only {handlers} {key} handlers for {press_actions} press actions"
    flat = re.sub(r"\s+", " ", qml)
    for needle in (
        "if (!event.isAutoRepeat)",
        "event.accepted = true",
        "Keys.onDownPressed: function (event) { if (db.chooserReachable())",
        "Keys.onDeletePressed: function (event) {",
        "Keys.onEscapePressed: function (event) {",
        "Accessible.checkable: true",
        "function cancel() {",
        # The Chooser's own rows (issue #284): each drawn option's key handlers
        # call the one pick/toggle path the pointer and the reader use, and the
        # confirm carries its press action like every other action.
        "db.chooserPickTier(modelData.word)",
        "db.chooserPickAudio(modelData)",
        'db.chooserToggle("lyrics_ttml_file")',
        "Accessible.onPressAction: function () { db.confirmChooser() }",
        # The gate card's spoken name carries its chip (issue #284).
        'Accessible.name: gcard.title + (gcard.chip !== ""',
        # The queue's repeated actions name their own section (issue #284).
        '"Retry all " + host.queueSectionWord(secItem.section)',
        '"Clear " + host.queueSectionWord(secItem.section)',
    ):
        assert re.sub(r"\s+", " ", needle) in flat, f"the keyboard path is missing: {needle}"


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
    """Real Tab presses from the current focus (issue #295).

    Returns every stop and whether the chain came back to its first stop.
    A stop whose ``path`` is None is one the walk could not locate in the tree
    (the focused control or the harness is off), which the caller reads as a
    broken chain; it ends the walk.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    stops: list[dict] = []
    for _ in range(limit):
        QTest.keyClick(root, Qt.Key_Tab)
        settle(20)
        stop = json.loads(q(scene_js(_TAB_STOP_BODY)))
        if stop["path"] is None:
            stops.append(stop)
            return stops, False
        if stops and stop["path"] == stops[0]["path"]:
            return stops, True
        stops.append(stop)
    return stops, False


# The closed surfaces a stop must never belong to: all three are closed at
# every walk in the scenario, so any stop inside one is a failure even when
# its own `visible` read is true (the #284 popup case).
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

    # --- The real Tab chain (issue #295). Flag reads (this scenario's and
    # #284's) find thousands of hidden tab stops: every TextField/ComboBox
    # default inside the closed Settings page keeps `activeFocusOnTab`, and
    # the Chooser's rows did before #284. Qt's chain filters on effective
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
            opened_settings = bool(
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
            if not opened_settings or not bool(q("root.settingsOpen")):
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

    # --- The Chooser (issue #284): its rows are named, tab-reachable controls,
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
    q(
        "queueModel.append({'qid': 'a11y-row', 'title': 'Song', 'sub': 'Artist',"
        " 'state': 'queued', 'uiGroup': 'queued'})"
    )
    settle(150)
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

    # Repeated CLEAR / RETRY ALL controls must name their own section
    # (issue #284's second item). Two sections are on screen, so the names have
    # to differ; the view pools headers, so identical (name) pairs from the
    # same section dedupe before the uniqueness read.
    q(
        "queueModel.append({'qid': 'a11y-failed', 'title': 'Broken', 'sub': 'Artist', 'state': 'failed', 'uiGroup': 'failed'})"
    )
    settle(200)
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

    # No tab stop may sit behind a closed popup (issue #284's third item, for
    # the Chooser): after confirming, nothing in the popover keeps
    # activeFocusOnTab.
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
    # say (issue #295's closed-surface invariant for the popup surfaces that
    # only exist after a first open). The guard keeps a surface that went
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

    if problems:
        for line in problems:
            print(f"REGRESSED: {line}", file=sys.stderr)
        return EXIT_REGRESSED
    print("ok")
    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    sys.exit(_run_scenario())
