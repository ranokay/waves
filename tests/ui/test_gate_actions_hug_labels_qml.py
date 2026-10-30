"""Dialog actions hug their labels, singly or in a centred pair.

WHAT THIS FENCES OFF
--------------------
Every dialog and in-page call to action used to be a full-width tinted card
with the label hard against the left edge and an arrow at the right, so a
short "Cancel" stretched across the whole card and a pair of them sat in a
stretched row. The converted actions are the same ``ActionButton`` the rest
of the app uses: as wide as the label plus its padding, centred in the card,
and a pair in one centred row.

The claim under test is geometry, which only the laid-out tree can show, so
the scenario boots the real ``Main.qml`` at the 880x560 minimum window and
measures every converted action with ``mapToItem``: hug width, centring,
containment in its card or its padded content column, and a pair's shared row
and non-overlap. A provider-supplied
label (the welcome, browse and search-empty CTAs) can be longer than its
container; the button must stop at the container and elide the word instead
of drawing outside it.

It also drives the disabled terms action: while its checkbox is clear it is
no tab stop, and a real click, a Return press and the platform Press action
must none of them accept the terms. Ticking the box arms it and Return
accepts, so the enabled path still fires.

The child installs a Qt message handler before the engine exists and fails on
any binding loop: the label's width is tied to the button's width, and a loop
there would ship as a broken layout warning in every dialog.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from support.qml import EXIT_OK, EXIT_REGRESSED, boot_main_qml, checkpoint, run_scenario
from support.qml_probe import scene_js

pytestmark = [pytest.mark.qml, pytest.mark.slow]

MIN_WIDTH = 880
MIN_HEIGHT = 560

# One measurement pass over every ActionButton in scope: the button's own
# width against its natural width, its position mapped into the card (the
# nearest rounded ancestor, or an explicit container for the in-page CTAs),
# and the label's drawn width/truncated state.
_MEASURE = """
    var scope = ARG_SCOPE;
    var container = ARG_CONTAINER;
    var buttons = [];
    function walk(o) {
        if (!o) return;
        // ActionButton's own marker properties: no other gate control
        // carries primary/warn/compact together with a label and clicked.
        if (o.primary !== undefined && o.warn !== undefined && o.compact !== undefined
                && o.label !== undefined && o.clicked !== undefined
                && o.visible === true && o.width > 0)
            buttons.push(o);
        var kids = o.children || [];
        for (var i = 0; i < kids.length; i++) walk(kids[i]);
        if (o.contentItem) walk(o.contentItem);
        if (o.item) walk(o.item);
    }
    walk(scope);
    function cardFor(b) {
        if (container) return container;
        var c = b.parent;
        while (c && !(c.radius !== undefined && c.radius >= 10)) c = c.parent;
        return c || b.parent;
    }
    var out = [];
    for (var j = 0; j < buttons.length; j++) {
        var b = buttons[j];
        var card = cardFor(b);
        var p = b.mapToItem(card, 0, 0);
        var text = null;
        var kids = b.children || [];
        for (var k = 0; k < kids.length; k++) {
            var kid = kids[k];
            if (kid.implicitWidth !== undefined && kid.text === b.label) text = kid;
        }
        out.push({object: "" + (b.objectName || ""),
                  label: "" + b.label,
                  width: b.width, implicitWidth: b.implicitWidth, height: b.height,
                  x: p.x, y: p.y,
                  cardWidth: card.width, cardHeight: card.height,
                  textWidth: text ? text.width : -1,
                  truncated: text ? text.truncated === true : false,
                  focusable: b.activeFocusOnTab === true,
                  enabled: b.enabled === true});
    }
    return JSON.stringify(out);
"""

# The gate dialogs: show the gate's own flag, measure its visible actions,
# then clear it. The FFmpeg gate's managed face carries the single CONTINUE;
# its CANCEL is the mutually exclusive installing face.
_GATE_CASES = (
    ("folder gate", "root.folderGateBlocking = true", "root.folderGateBlocking = false", "folderGate", 1),
    ("folder nudge", "root.folderNudge = true", "root.folderNudge = false", "folderNudge", 2),
    (
        "category download",
        "root.catDlPrompt = {path: 'x', provider: 'tidal', title: 'Mix', count: 3}",
        "root.catDlPrompt = null",
        "catDlGate",
        2,
    ),
    ("settings reset", "root.confirmSettingsReset = true", "root.confirmSettingsReset = false", "settingsResetGate", 2),
    ("factory reset", "root.confirmFactoryReset = true", "root.confirmFactoryReset = false", "factoryResetGate", 2),
    (
        "folder unreachable",
        "root.folderUnreachable = true",
        "root.folderUnreachable = false",
        "folderUnreachableGate",
        2,
    ),
    ("ffmpeg block", "root.ffmpegBlocked = true", "root.ffmpegBlocked = false", "ffmpegBlockGate", 2),
    ("terms gate", "termsGate.visible = true", "termsGate.visible = false", "termsGate", 1),
    (
        "ffmpeg gate",
        "appFfmpeg.status = {state: 'managed'}; ffmpegGate.visible = true",
        "ffmpegGate.visible = false; appFfmpeg.status = {state: 'missing'}",
        "ffmpegGate",
        1,
    ),
    (
        "ffmpeg gate installing",
        "appFfmpeg.lifeState = 'downloading'; ffmpegGate.visible = true",
        "ffmpegGate.visible = false; appFfmpeg.lifeState = ''",
        "ffmpegGate",
        1,
    ),
)


def test_dialog_actions_hug_their_labels_singly_and_in_pairs():
    run_scenario(
        Path(__file__),
        "--run-scenario",
        timeout=240,
        sandbox_prefix="waves-gate-button-layout-",
        failure_message="a dialog action stopped hugging its label or left its card.",
    )


def _measure(q, scope: str, container: str = "null") -> list[dict]:
    body = _MEASURE.replace("ARG_SCOPE", scope).replace("ARG_CONTAINER", container)
    return list(json.loads(q(scene_js(body))))


def _check_surface(
    problems: list[str],
    name: str,
    buttons: list[dict],
    expected: int,
    *,
    capped: bool = False,
    centred: bool | None = None,
) -> None:
    """One surface's geometry: hug, centre, containment, and pair shape."""
    if len(buttons) != expected:
        problems.append(f"{name}: {len(buttons)} actions measured, expected {expected}")
        return
    if centred is None:
        centred = expected == 1
    for b in buttons:
        _check_button(problems, name, b, capped=capped, centred=centred)
    if expected == 2:
        _check_pair(problems, name, buttons)


def _check_button(problems: list[str], name: str, b: dict, *, capped: bool, centred: bool) -> None:
    where = f"{name} [{b['object'] or b['label']}]"
    if abs(b["width"] - b["implicitWidth"]) > 1.0:
        problems.append(f"{where} does not hug its label: width {b['width']} vs implicit {b['implicitWidth']}")
    if capped:
        if b["width"] > b["cardWidth"] + 0.5:
            problems.append(f"{where} outgrew its container: {b['width']} > {b['cardWidth']}")
    elif b["width"] >= b["cardWidth"] - 0.5:
        problems.append(f"{where} fills its card instead of hugging: {b['width']} of {b['cardWidth']}")
    if centred and abs(b["x"] + b["width"] / 2 - b["cardWidth"] / 2) > 1.0:
        problems.append(f"{where} is not centred: centre {b['x'] + b['width'] / 2} in {b['cardWidth']}")
    if b["x"] < -0.5 or b["x"] + b["width"] > b["cardWidth"] + 0.5:
        problems.append(f"{where} leaves its card horizontally: x {b['x']} width {b['width']}")
    if b["y"] < -0.5 or b["y"] + b["height"] > b["cardHeight"] + 0.5:
        problems.append(f"{where} leaves its card vertically: y {b['y']} height {b['height']}")
    if b["textWidth"] > b["width"] + 0.5:
        problems.append(f"{where} draws its label past the button: {b['textWidth']} > {b['width']}")


def _check_pair(problems: list[str], name: str, buttons: list[dict]) -> None:
    ordered = sorted(buttons, key=lambda item: item["x"])
    left, right = ordered
    if abs(left["y"] - right["y"]) > 0.5:
        problems.append(f"{name} puts its pair on two rows: y {left['y']} vs {right['y']}")
    if left["x"] + left["width"] > right["x"] + 0.5:
        problems.append(f"{name} overlaps its pair: {left['x'] + left['width']} > {right['x']}")
    group_centre = (left["x"] + right["x"] + right["width"]) / 2
    if abs(group_centre - left["cardWidth"] / 2) > 1.0:
        problems.append(f"{name} does not centre its pair: centre {group_centre} in {left['cardWidth']}")


def _check_containment(problems: list[str], name: str, buttons: list[dict]) -> None:
    """The button sits inside its real card (the nearest rounded ancestor)."""
    for b in buttons:
        where = f"{name} [{b['object'] or b['label']}]"
        if b["x"] < -0.5 or b["x"] + b["width"] > b["cardWidth"] + 0.5:
            problems.append(f"{where} leaves its card horizontally: x {b['x']} width {b['width']}")
        if b["y"] < -0.5 or b["y"] + b["height"] > b["cardHeight"] + 0.5:
            problems.append(f"{where} leaves its card vertically: y {b['y']} height {b['height']}")


def _check_long_label(problems: list[str], name: str, buttons: list[dict]) -> None:
    """A label longer than the container stops at it and elides."""
    if len(buttons) != 1:
        problems.append(f"{name}: {len(buttons)} capped actions measured, expected 1")
        return
    b = buttons[0]
    where = f"{name} [{b['object'] or b['label']}]"
    if b["width"] > b["cardWidth"] + 0.5:
        problems.append(f"{where} outgrew its container: {b['width']} > {b['cardWidth']}")
    if b["width"] >= b["implicitWidth"] - 0.5:
        problems.append(f"{where} was not capped: width {b['width']} implicit {b['implicitWidth']}")
    if not b["truncated"]:
        problems.append(f"{where} did not elide its long label")
    if b["textWidth"] > b["width"] + 0.5:
        problems.append(f"{where} draws its long label past the button: {b['textWidth']} > {b['width']}")


def _run_scenario() -> int:
    # A binding loop is a layout bug, not a style warning: collect it from the
    # first QML object onwards (before boot builds the engine).
    from PySide6.QtCore import qInstallMessageHandler

    loops: list[str] = []

    def on_message(_mode, _context, message: str) -> None:
        if "binding loop" in message.lower():
            loops.append(message)

    qInstallMessageHandler(on_message)

    try:
        return _scenario_body(loops)
    except Exception:
        import traceback

        print(traceback.format_exc(), file=sys.stderr)
        return EXIT_REGRESSED


def _scenario_body(loops: list[str]) -> int:  # noqa: C901 (one straight scenario)
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QAccessible
    from PySide6.QtTest import QTest

    booted = boot_main_qml()
    if isinstance(booted, int):
        return booted
    root, q, settle, _bridge = booted

    problems: list[str] = []

    q(f"root.width = {MIN_WIDTH}; root.height = {MIN_HEIGHT}")
    settle(250)
    checkpoint("minimum window", f"{int(q('root.width'))}x{int(q('root.height'))}")

    # --- The gate dialogs -------------------------------------------------
    for name, show, hide, gate, expected in _GATE_CASES:
        q(show)
        settle(220)
        _check_surface(problems, name, _measure(q, gate), expected)
        q(hide)
        settle(120)

    # --- The in-page CTAs ------------------------------------------------
    q(
        "root.browseNav = {available: true, signed_in: false, message: 'Browse', "
        "action: 'signin', provider: 'tidal', action_label: 'SIGN IN TO TIDAL'}"
    )
    q("root.openBrowse()")
    settle(300)
    _check_surface(
        problems,
        "browse sign-in CTA",
        _measure(q, "findObject(root, 'browseSignInAction')", "findObject(root, 'browseSignInAction').parent"),
        1,
    )

    q("root.searchOpportunities = [{provider: 'tidal', action: 'signin', action_label: 'SIGN IN TO TIDAL'}]")
    q("root.openSearch()")
    settle(300)
    _check_surface(problems, "search empty CTA", _measure(q, "emptyCtaCol"), 1)

    # --- Library and provider surfaces -----------------------------------
    q("root.libraryOpen = true; root.myMusicLibrary = {configured: false, views: []}")
    settle(300)
    _check_surface(
        problems,
        "library configure CTA",
        _measure(q, "findFirst(libSection, function (o) { return o.objectName === 'libConfigureAction'; }).parent"),
        1,
    )

    q("root.myMusicLibrary = {configured: true, views: [{id: 'saved', label: 'Saved'}]}")
    q("libSection.counts = {saved: -1}")
    settle(300)
    _check_surface(
        problems,
        "library retry CTA",
        _measure(q, "findFirst(libSection, function (o) { return o.objectName === 'libRetryAction'; }).parent"),
        1,
    )

    q("root.myMusicEmpty = {message: 'Sign in to listen', detail: 'Provider copy.', action_label: 'SIGN IN'}")
    q("root.myMusicSources = []")
    settle(200)
    _check_surface(problems, "library sign-in CTA", _measure(q, "libCtaCol"), 1)

    long_library = "SIGN IN WITH THE PROVIDER WHOSE DISPLAY NAME DOES NOT FIT THE EMPTY STATE"
    q(f"root.myMusicEmpty = {{message: 'Sign in to listen', detail: 'Provider copy.', action_label: '{long_library}'}}")
    settle(250)
    _check_long_label(problems, "library sign-in CTA long label", _measure(q, "libCtaCol"))

    q(
        "root.providerCards = [{id: 'tidal', name: 'TIDAL', summary: 'Hi-res streaming.', "
        "action: 'Continue with TIDAL', state: 'signed_out'}]"
    )
    q("root.setupOpen = true; root.setupMode = 'cards'")
    settle(350)
    provider_scope = "findFirst(setupPane, function (o) { return o.objectName === 'welcomeProviderAction' && o.visible === true; }).parent"
    _check_surface(problems, "welcome provider CTA", _measure(q, provider_scope, provider_scope), 1)
    _check_containment(problems, "welcome provider CTA", _measure(q, provider_scope))

    q("root.setupMode = 'tidal'; root.setupUrlOpened = true")
    settle(350)
    _check_surface(
        problems,
        "welcome sign-in actions",
        _measure(q, "findFirst(setupPane, function (o) { return o.objectName === 'welcomeSignIn'; })"),
        3,
        centred=True,
    )

    # --- Provider-supplied labels longer than their container ------------
    long_browse = "SIGN IN WITH THE PROVIDER THAT HAS A VERY LONG DISPLAY NAME INDEED"
    q(
        f"root.browseNav = {{available: true, signed_in: false, message: 'Browse', action: 'signin', provider: 'tidal', action_label: '{long_browse}'}}"
    )
    q("root.openBrowse()")
    settle(300)
    _check_long_label(
        problems,
        "browse sign-in CTA long label",
        _measure(q, "findObject(root, 'browseSignInAction')", "findObject(root, 'browseSignInAction').parent"),
    )

    long_empty = "SIGN IN WITH THE OTHER PROVIDER THAT ALSO HAS A VERY LONG DISPLAY NAME"
    q(f"root.searchOpportunities = [{{provider: 'tidal', action: 'signin', action_label: '{long_empty}'}}]")
    q("root.openSearch()")
    settle(300)
    _check_long_label(problems, "search empty CTA long label", _measure(q, "emptyCtaCol"))

    long_welcome = "Continue with the provider whose display name is far too long to fit"
    q(
        "root.providerCards = [{id: 'tidal', name: 'TIDAL', summary: 'Hi-res streaming.', "
        f"action: '{long_welcome}', state: 'signed_out'}}]"
    )
    q("root.setupOpen = true; root.setupMode = 'cards'")
    settle(350)
    _check_long_label(
        problems,
        "welcome provider CTA long label",
        _measure(q, provider_scope, provider_scope),
    )

    # --- Hover, the focus ring and the three keys on a converted action --
    q("root.ffmpegBlocked = true")
    settle(300)
    find_continue = (
        "findFirst(ffmpegBlockGate, function (o) {"
        " return o.objectName === 'ffmpegGateContinue' && o.visible === true; })"
    )
    hover_button = q(scene_js(f"return {find_continue};"))
    if hover_button is None:
        problems.append("the FFmpeg block gate's continue action is not in the tree")
    else:
        label = next(
            (child for child in hover_button.childItems() if child.property("text") == "Continue anyway"),
            None,
        )
        if label is None:
            problems.append("the FFmpeg continue action lost its label")
        else:
            QTest.mouseMove(root, QPoint(2, 2))
            settle(180)
            idle = label.property("color").name()
            point = q(scene_js(f"var b = {find_continue}; return b.mapToItem(null, b.width / 2, b.height / 2);"))
            QTest.mouseMove(root, QPoint(int(point.x()), int(point.y())))
            settle(200)
            hovered = label.property("color").name()
            if hovered == idle:
                problems.append("hovering a converted action drew no hover feedback")

    root.requestActivate()
    settle(80)
    for key, word in ((Qt.Key_Return, "Return"), (Qt.Key_Enter, "Enter"), (Qt.Key_Space, "Space")):
        if not bool(q("root.ffmpegBlocked")):
            q("root.ffmpegBlocked = true")
            settle(220)
        target = q(scene_js(f"return {find_continue};"))
        if target is None:
            problems.append(f"the FFmpeg block gate's converted action vanished before {word}")
            break
        target.forceActiveFocus()
        settle(120)
        ring = q(
            scene_js(
                f"var b = {find_continue};"
                " return findFirst(b, function (o) { return o.border !== undefined"
                " && o.border.width === 2 && o.visible === true; }) !== null;"
            )
        )
        if not bool(ring):
            problems.append(f"the converted action drew no focus ring for {word}")
        QTest.keyClick(root, key)
        settle(250)
        if bool(q("root.ffmpegBlocked")):
            problems.append(f"{word} on the converted FFmpeg continue action never fired")

    # --- A disabled action cannot fire by pointer, key or AX press --------
    q("root.setupOpen = false")
    q("termsGate.visible = true")
    settle(300)
    ack = q(scene_js('var b = findObject(termsGate, "termsAckAction"); return b;'))
    if ack is None:
        problems.append("the terms gate's ACKNOWLEDGE action is not in the tree")
    else:
        if bool(ack.property("activeFocusOnTab")):
            problems.append("the disabled terms action is still a tab stop")
        accepted = bool(q("legalSettings.termsAccepted"))

        point = q(
            scene_js(
                'var b = findObject(termsGate, "termsAckAction"); return b.mapToItem(null, b.width / 2, b.height / 2);'
            )
        )
        QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, QPoint(int(point.x()), int(point.y())))
        settle(200)
        if bool(q("legalSettings.termsAccepted")) != accepted:
            problems.append("a pointer click fired the disabled terms action")

        for key, word in ((Qt.Key_Return, "Return"), (Qt.Key_Enter, "Enter"), (Qt.Key_Space, "Space")):
            ack.forceActiveFocus()
            settle(80)
            QTest.keyClick(root, key)
            settle(200)
            if bool(q("legalSettings.termsAccepted")) != accepted:
                problems.append(f"{word} fired the disabled terms action")

        iface = QAccessible.queryAccessibleInterface(ack)
        actions = iface.actionInterface() if iface is not None and iface.isValid() else None
        if actions is None or "Press" not in list(actions.actionNames()):
            problems.append("the terms action advertises no platform Press action")
        else:
            actions.doAction("Press")
            settle(200)
            if bool(q("legalSettings.termsAccepted")) != accepted:
                problems.append("the platform Press action fired the disabled terms action")

        # Ticking the box arms it, and Return then accepts: the enabled path
        # the conversion must preserve.
        q("ackChk.checked = true")
        settle(200)
        if not bool(ack.property("enabled")) or not bool(ack.property("activeFocusOnTab")):
            problems.append("ticking the terms box never armed its action")
        ack.forceActiveFocus()
        settle(80)
        QTest.keyClick(root, Qt.Key_Return)
        settle(300)
        if not bool(q("legalSettings.termsAccepted")):
            problems.append("Return on the armed terms action never accepted")

    checkpoint("binding loops", f"{len(loops)} collected")
    problems.extend(f"binding loop in the dialog layout: {loop}" for loop in loops)

    for problem in problems:
        print(f"regressed: {problem}", file=sys.stderr)
    print(f"{'OK' if not problems else 'FAILED'}: {len(problems)} layout problems", flush=True)
    return EXIT_OK if not problems else EXIT_REGRESSED


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_run_scenario())
