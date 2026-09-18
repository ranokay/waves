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
  popover leaves no tab stop inside it (issue #284).

The companion source test pins the key handlers, because a name alone cannot
be activated by a screen reader without its press action and QML cannot be
driven with synthetic key events from the scenario harness.
"""

from __future__ import annotations

import json
import sys

import pytest
from support.paths import QML_MAIN
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
        if (name !== "" && o.activeFocusOnTab === true && o.visible !== false && o.width > 0) {
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
    """The scenario proves the metadata; this pins the handlers it cannot
    drive (the harness sends no key events). Every press action has its own
    Return/Enter/Space handler, each accepts the event and ignores
    auto-repeat, and the two extra keys (Down opens the chooser, Escape
    clears the search box, Delete cancels a queued row) are present."""
    qml = QML_MAIN.read_text(encoding="utf-8")
    press_actions = qml.count("Accessible.onPressAction")
    assert press_actions >= 5, "the primary controls lost their press actions"
    for key in ("Return", "Enter", "Space"):
        handlers = qml.count(f"Keys.on{key}Pressed")
        assert handlers >= press_actions, f"only {handlers} {key} handlers for {press_actions} press actions"
    for needle in (
        "if (!event.isAutoRepeat)",
        "event.accepted = true",
        "Keys.onDownPressed: function(event) { if (db.chooserReachable())",
        "Keys.onDeletePressed: function(event) {",
        "Keys.onEscapePressed: function(event) {",
        "Accessible.checkable: true",
        "function cancel() {",
        # The Chooser's own rows (issue #284): each drawn option's key handlers
        # call the one pick/toggle path the pointer and the reader use, and the
        # confirm carries its press action like every other action.
        "db.chooserPickTier(modelData.word)",
        "db.chooserPickAudio(modelData)",
        'db.chooserToggle("lyrics_ttml_file")',
        "Accessible.onPressAction: function() { db.confirmChooser() }",
        # The gate card's spoken name carries its chip (issue #284).
        'Accessible.name: gcard.title + (gcard.chip !== ""',
        # The queue's repeated actions name their own section (issue #284).
        '"Retry all " + root.queueSectionWord(secItem.section)',
        '"Clear " + root.queueSectionWord(secItem.section)',
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


def _scenario_body() -> int:  # noqa: C901 (one straight scenario)
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
    if not search or not any(field["name"] for field in search):
        problems.append("the search field carries no accessible name")
    _check_buttons(
        problems,
        _buttons(q, "function (o) { return o.chooserKind !== undefined && ('' + o.mediaId) === 't1'; }"),
        "the search result's download button",
    )

    # --- The Chooser (issue #284): its rows are named, tab-reachable controls,
    # and a keyboard user's picks reach the queue through the shared paths.
    opened = q(scene_js("""
        var b = findFirst(root, function (o) { return o.chooserKind !== undefined && ('' + o.mediaId) === 't1'; });
        if (!b) return false;
        b.openChooser();
        return true;
    """))
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
    if not any(t["checked"] for t in tiers):
        problems.append("no Chooser tier row reports itself as picked")
    if len(audio) < 1:
        problems.append("the Chooser's audio rows are not exposed as pickers")
    if len(toggles) < 1:
        problems.append("the Chooser's lyrics/art toggles are not exposed as checkboxes")
    if len(actions) < 2:
        problems.append(f"the Chooser's actions are not both reachable ({len(actions)} found)")
    names = [r["name"] for r in rows]
    if len(names) != len(set(names)):
        problems.append(f"the Chooser's rows repeat a spoken name: {names}")

    # The pick/confirm paths the handlers call (the key handlers themselves are
    # pinned by the companion source test): choose a tier and an audio word and
    # flip a toggle, confirm, and read the parked click's ask.
    q(scene_js("""
        var b = findFirst(root, function (o) { return o.chooserKind !== undefined && ('' + o.mediaId) === 't1'; });
        if (!b) return false;
        b.chooserPickTier("LOSSLESS");
        b.chooserPickAudio("atmos");
        b.chooserToggle("cover_file");
        b.confirmChooser();
        return true;
    """))
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
    if not any("Retry all" in name for name in drawer_names):
        problems.append(f"the queue's RETRY ALL control does not name its section: {drawer_names}")

    # No tab stop may sit behind a closed popup (issue #284's third item, for
    # the Chooser): after confirming, nothing in the popover keeps
    # activeFocusOnTab.
    q("queueDrawer.close()")
    settle(250)
    hidden = list(json.loads(q(scene_js("""
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
    """))))
    if hidden:
        problems.append(f"controls inside the closed Chooser keep a tab stop: {hidden}")

    if problems:
        for line in problems:
            print(f"REGRESSED: {line}", file=sys.stderr)
        return EXIT_REGRESSED
    print("ok")
    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    sys.exit(_run_scenario())
