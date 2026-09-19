"""#214: a provider the page has never heard of still renders and acts.

WHAT THIS FENCES OFF
--------------------
The descriptor contract's paper test, on the rendered page rather than the
schema alone: a provider registered after the Settings page was written must
produce a card (its name, its descriptor mark), a generated session status
row and working action dispatch through the bridge's one provider-action
slot — with zero QML edits. The provider is injected into the real bridge
before Settings opens, the page is scrolled until the card is on screen, and
the pill's action is driven through the very handler its MouseArea calls.

The physical-click path over settings pills is covered by the account
journey suite; this test owns the descriptor rendering and the generic
dispatch, which a synthetic click into a scrolled flickable cannot prove
reliably offscreen.
"""

from __future__ import annotations

import json
import sys

import pytest
from support.qml import EXIT_OK, EXIT_REGRESSED, boot_main_qml, run_scenario
from support.qml_probe import scene_js

from waves.providers.base import ProviderDescriptor, StatusKind

# Every case here boots the real Main.qml in a child interpreter.
pytestmark = pytest.mark.qml

_TEXT_POINT_JS = """
    function pointOfText(needle) {
        var hit = findFirst(root, function (o) {
            return o.text !== undefined && String(o.text) === needle;
        });
        if (!hit) return "";
        var p = hit.mapToItem(null, hit.width / 2, hit.height / 2);
        // Off-screen at this scroll position is not a rendered, clickable mark.
        if (p.x < 0 || p.y < 0 || p.x > root.width || p.y > root.height) return "";
        return JSON.stringify([p.x, p.y]);
    }
"""

_CARD_POINT = scene_js(
    _TEXT_POINT_JS
    + """
    return pointOfText("NewCo");
"""
)

_SCROLL_TO_CARD = scene_js("""
    var hit = findFirst(root, function (o) {
        return o.text !== undefined && String(o.text) === "NewCo";
    });
    if (!hit) return "";
    var holder = settingsPage.scrollViewport;
    var y = hit.mapToItem(holder.contentItem, 0, hit.height / 2).y;
    settingsPage.scrollY = Math.max(0, y - holder.height / 2);
    return "scrolled";
""")

_PILL = scene_js("""
    var hit = findFirst(root, function (o) {
        return o.actKey !== undefined && String(o.actKey) === "newco_signout"
            && o.visible !== false && o.width > 0;
    });
    if (!hit) return "";
    var p = hit.mapToItem(null, hit.width / 2, hit.height / 2);
    return JSON.stringify({
        providerId: String(hit.providerId),
        actKey: String(hit.actKey),
        onScreen: p.x >= 0 && p.y >= 0 && p.x <= root.width && p.y <= root.height
    });
""")

_RUN_PILL = scene_js("""
    var hit = findFirst(root, function (o) {
        return o.actKey !== undefined && String(o.actKey) === "newco_signout";
    });
    if (hit) hit.runAction();
    return hit ? "called" : "";
""")


def test_a_third_provider_card_renders_and_acts():
    run_scenario(
        __file__,
        "--run-scenario",
        timeout=180,
        sandbox_prefix="waves-provider-card-",
        failure_message="a third provider does not render or act through the descriptor contract",
    )


def _run_scenario() -> int:
    booted = boot_main_qml()
    if isinstance(booted, int):
        return booted
    _root, q, settle, bridge = booted

    calls: list[str] = []

    class NewCo:
        """A provider registered after every QML surface was written."""

        id = "newco"
        name = "NewCo"
        is_logged_in = True

        @staticmethod
        def descriptor() -> ProviderDescriptor:
            return ProviderDescriptor(
                id="newco",
                name="NewCo",
                logo="assets/providers/tidal.png",  # any real asset: rendering only
                card_desc="NewCo's card, rendered from its descriptor.",
                status_kind=StatusKind.SESSION,
            )

        def logout(self) -> None:
            calls.append("logout")

    bridge.providers["newco"] = NewCo()

    q("settingsOpen = true")
    q("scrollDressing.visible = false")  # the page's scroll overlay swallows synthetic clicks
    settle(300)
    q("settingsPage.refreshSchema()")
    settle(300)

    # The card and its generated action render in the live page, on screen.
    if q(_SCROLL_TO_CARD) == "":
        print("the third provider's card did not render (no 'NewCo' text)", file=sys.stderr)
        return EXIT_REGRESSED
    settle(300)
    if q(_CARD_POINT) in ("", None):
        print("the third provider's card never came on screen", file=sys.stderr)
        return EXIT_REGRESSED

    pill = q(_PILL)
    if pill in ("", None):
        print("the generated session row's Sign out pill did not render", file=sys.stderr)
        return EXIT_REGRESSED
    state = json.loads(pill)
    if state["providerId"] != "newco" or not state["onScreen"]:
        print(f"the pill is not the third provider's, or is off screen: {state}", file=sys.stderr)
        return EXIT_REGRESSED

    # The pill's own handler (the MouseArea calls it) reaches the bridge's one
    # provider-action slot, which dispatches to the provider's sign-out.
    if q(_RUN_PILL) != "called":
        print("the pill's handler is missing", file=sys.stderr)
        return EXIT_REGRESSED
    settle(200)
    if calls != ["logout"]:
        print(f"the pill's action did not reach the provider: {calls}", file=sys.stderr)
        return EXIT_REGRESSED

    print("ok")
    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    sys.exit(_run_scenario())
