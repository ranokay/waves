"""The welcome inline sign-in must never submit a stale or scrambled link.

WHAT THIS FENCES OFF
--------------------
The redirect field's paste animation (DecodeController) rewrites the field
to scrambled glyphs for ~0.6 s while it settles. Two gaps sent the wrong
link, both in the login caller honouring the decoder's contract:

* a submit inside the decode window (Enter's onAccepted, or the COMPLETE
  SIGN-IN action) read the scrambled field, so the bridge refused it with
  "that isn't the sign-in link" before the real submit landed;
* the paste glyph cleared without cancelling the in-flight decode, whose
  timer kept the OLD link, rewrote the field back to it and auto-submitted
  it: pasting a second link during the first link's decode signed in with
  the first.

Both are pinned here with a REAL decode (``run()``), not the pinned
``decoding`` flag the other sign-in scenarios hold: the flag alone cannot
tell a held decoder from a running one.

Runs in a SUBPROCESS for the same reason as the other Main.qml scenarios:
building the bridge installs process-global handlers that must not leak
into the rest of the suite.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from support.qml import (
    EXIT_OK,
    EXIT_PRECONDITION,
    EXIT_REGRESSED,
    boot_main_qml,
    run_scenario,
)

LINK_A = "https://tidal.test/redirect-a"
LINK_B1 = "https://tidal.test/redirect-b1"
LINK_B2 = "https://tidal.test/redirect-b2"

_FIND = """
function findFirst(item, pred) {
    if (!item) return null
    var kids = item.children || []
    for (var i = 0; i < kids.length; i++) {
        var k = kids[i].item || kids[i]
        if (!k) continue
        if (pred(k)) return k
        var hit = findFirst(k, pred)
        if (hit) return hit
    }
    return null
}
"""


@pytest.mark.qml
def test_welcome_signin_never_submits_a_stale_or_scrambled_link():
    run_scenario(
        Path(__file__),
        "--run-scenario",
        timeout=240,
        sandbox_prefix="waves-welcome-decode-gaps-",
        failure_message="the welcome inline sign-in submitted a stale or scrambled link.",
    )


def _run_scenario() -> int:  # noqa: C901 (one straight scenario, two legs)
    booted = boot_main_qml()
    if isinstance(booted, int):
        return booted
    _root, q, settle, bridge = booted

    # boot_main_qml parks the first-run gate by assigning visible=false,
    # which breaks the gate's binding; re-arm it for this scenario (the
    # onboarding scenario owns this pattern) and reset the profile to a
    # fresh signed-out one with Apple off.
    q("providerPicker.visible = Qt.binding(function() { return root.welcomeDue })")
    q(
        "setupSettings.firstRunAnswered = false; setupSettings.setupChipDismissed = false;"
        " setupSettings.providerPickerDone = false"
    )
    q("root.setupMode = 'cards'; root.setupUrlOpened = false")
    q('waves.applySettings({"apple_enabled": false})')
    q("scrollDressing.visible = false")
    settle(150)

    # The account service is faked at the provider boundary: every link is
    # recorded, none signs in, so the surface stays open for both legs and
    # the submitted links are exactly what the test reads back.
    calls: list[str] = []
    tidal = bridge.providers["tidal"]
    tidal.login_begin = lambda: "https://tidal.test/authorize"

    def fake_complete(url) -> bool:
        calls.append(str(url))
        return False

    tidal.login_complete = fake_complete
    bridge._session_resolved = True
    bridge.sessionResolvedChanged.emit()
    settle(250)
    if not q("providerPicker.visible"):
        print("the welcome did not appear on a fresh profile", file=sys.stderr)
        return EXIT_PRECONDITION

    finders = _FIND + "\n"
    box_call = "findFirst(providerPicker, function (o) { return o.objectName === 'signInPaste'; })"
    status = lambda: str(q("String(waves.status || '')"))

    def js(body: str) -> str:
        return "(function(){\n" + finders + body + "\n})()"

    def emit_clicked(label: str) -> None:
        q(
            js(
                f"var g = findFirst(providerPicker, function (o) {{ return o.label !== undefined && String(o.label) === {label!r}; }});\n"
                + "if (!g) throw new Error('missing action');\ng.clicked();\n"
            )
        )

    def emit_clicked_object(name: str) -> None:
        q(
            js(
                f"var g = findFirst(providerPicker, function (o) {{ return o.objectName === {name!r}; }});\n"
                + "if (!g) throw new Error('missing action');\ng.clicked();\n"
            )
        )

    def decoder_running() -> bool:
        return bool(q(js("var box = " + box_call + ";\nreturn box.pasteDecoder.decoding;")))

    def field_text() -> str:
        return str(
            q(
                js(
                    "var box = " + box_call + ";\n"
                    "var f = findFirst(box, function (o) { return o.objectName === 'signInField'; });\n"
                    "return String(f.text);\n"
                )
            )
        )

    def pump_until(pred, timeout_ms: int = 6000) -> bool:
        waited = 0
        while waited < timeout_ms:
            if pred():
                return True
            settle(100)
            waited += 100
        return pred()

    # The real path onto the steps: the TIDAL card, then the explicit
    # browser-login click. No direct property sets: the test opens the
    # surface the way a user does.
    emit_clicked("CONTINUE WITH TIDAL")
    settle(300)
    if q("root.setupMode") != "tidal":
        print("the TIDAL card did not open the inline sign-in steps", file=sys.stderr)
        return EXIT_PRECONDITION
    emit_clicked_object("welcomeSignInOpen")
    if not pump_until(lambda: bool(q("root.setupUrlOpened"))):
        print("OPEN BROWSER LOGIN did not start the sign-in flow", file=sys.stderr)
        return EXIT_PRECONDITION
    if not q(
        js(
            "var b = findFirst(providerPicker, function (o) { return o.objectName === 'signInPaste'; });\nreturn b ? 'found' : '';"
        )
    ):
        print("the sign-in steps expose no paste field", file=sys.stderr)
        return EXIT_PRECONDITION

    bad: list[str] = []

    # ---- leg 1: a submit inside the decode window stays quiet ------------
    q(js("var box = " + box_call + ";\nbox.pasteDecoder.run(" + repr(LINK_A) + ");"))
    settle(200)
    if not decoder_running():
        print("the decode did not start: no decode window to submit inside", file=sys.stderr)
        return EXIT_PRECONDITION
    if field_text() == LINK_A:
        print("the field was never scrambled: no decode window to submit inside", file=sys.stderr)
        return EXIT_PRECONDITION
    baseline = status()
    # Both submit paths, driven the way the UI drives them: the action's
    # own signal and the field's accepted signal.
    emit_clicked_object("welcomeSignInComplete")
    q(
        js(
            "var box = " + box_call + ";\n"
            "var f = findFirst(box, function (o) { return o.objectName === 'signInField'; });\n"
            "f.accepted();\n"
        )
    )
    settle(150)
    if calls:
        bad.append(f"a mid-decode submit reached the account service with {calls!r}")
    if status() != baseline:
        bad.append(f"a mid-decode submit errored spuriously (status {status()!r})")
    # The decode's own submit still carries the settled link: the quiet
    # press above must not lose the sign-in.
    if not pump_until(lambda: not decoder_running()):
        print("the decode never settled", file=sys.stderr)
        return EXIT_PRECONDITION
    if not pump_until(lambda: len(calls) >= 1):
        bad.append("the settled decode never submitted its link")
    elif calls != [LINK_A]:
        bad.append(f"the settled decode submitted {calls!r}, wanted {[LINK_A]!r}")

    # ---- leg 2: a second paste cancels the first decode ------------------
    calls.clear()
    from PySide6.QtGui import QGuiApplication

    clipboard = QGuiApplication.clipboard()
    clipboard.setText(LINK_B1)
    q(
        js(
            "var b = findFirst(providerPicker, function (o) { return o.objectName === 'signInPaste'; });\n"
            "var g = findFirst(b, function (o) { return o.fillT !== undefined && o.clicked !== undefined; });\n"
            "if (!g) throw new Error('no paste glyph');\ng.clicked();\n"
        )
    )
    settle(200)
    if not decoder_running():
        print("the glyph paste started no decode (clipboard paste inert offscreen?)", file=sys.stderr)
        return EXIT_PRECONDITION
    clipboard.setText(LINK_B2)
    q(
        js(
            "var b = findFirst(providerPicker, function (o) { return o.objectName === 'signInPaste'; });\n"
            "var g = findFirst(b, function (o) { return o.fillT !== undefined && o.clicked !== undefined; });\n"
            "if (!g) throw new Error('no paste glyph');\ng.clicked();\n"
        )
    )
    if not pump_until(lambda: not decoder_running()):
        print("the second decode never settled", file=sys.stderr)
        return EXIT_PRECONDITION
    if not pump_until(lambda: len(calls) >= 1):
        bad.append("the second paste never submitted its link")
    elif calls != [LINK_B2]:
        bad.append(f"the second paste submitted {calls!r}, wanted {[LINK_B2]!r} (the first decode won)")
    if field_text() != LINK_B2:
        bad.append(f"the field settled on {field_text()!r}, wanted {LINK_B2!r} (the first decode rewrote it)")

    if bad:
        print("\n".join(bad), file=sys.stderr)
        return EXIT_REGRESSED
    print(f"ok: mid-decode submits quiet, second paste wins ({LINK_A}, {LINK_B2})")
    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_run_scenario())
