"""Every empty state a provider could fill offers the one click.

WHAT THIS FENCES OFF
--------------------
1. The blank signed-out Search. The invitation was gated on a TIDAL session,
   so an Apple-only user's Search pane was empty chrome; it now shows the
   invitation and the setup actions.

2. Dead-end empty states. Search offers "Enable Apple Music - search works
   without an account" (the bridge's own enable flow) and "Sign in to TIDAL"
   (the welcome surface's inline steps); Browse and My Music name TIDAL and
   offer the same sign-in click instead of rendering blank.

3. CTAs that outlive their provider. Enabling Apple retires the Apple action;
   a completed sign-in retires every TIDAL action and brings the My Music
   category tabs back.

Runs in a SUBPROCESS like the other Main.qml scenarios: building the bridge
installs process-global handlers that must not leak into the suite. The
account service is faked at the provider boundary, everything around it is
the real bridge, and the CTA clicks are real mouse events.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from support.qml import EXIT_OK, EXIT_REGRESSED, boot_main_qml, run_scenario
from support.qml_probe import scene_js


def _point(scope: str, name: str) -> str:
    """Scene coordinates of the first visible item with this objectName."""
    return scene_js(
        f"  var hit = findFirst({scope}, function (o) {{ return o.objectName === {json.dumps(name)}; }});\n"
        "  if (!hit || hit.visible !== true || hit.width <= 0 || hit.height <= 0) return null;\n"
        "  var p = hit.mapToItem(null, hit.width / 2, hit.height / 2);\n"
        "  if (p.x < 0 || p.y < 0 || p.x > root.width || p.y > root.height) return null;\n"
        "  return JSON.stringify([p.x, p.y]);\n"
    )


def _text_point(scope: str, text: str) -> str:
    """Scene coordinates of the first visible Text with exactly this string."""
    return scene_js(
        f"  var hit = findFirst({scope}, function (o) {{ return o.text !== undefined && String(o.text) === {json.dumps(text)}; }});\n"
        "  if (!hit || hit.visible !== true || hit.width <= 0 || hit.height <= 0) return null;\n"
        "  var p = hit.mapToItem(null, hit.width / 2, hit.height / 2);\n"
        "  if (p.x < 0 || p.y < 0 || p.x > root.width || p.y > root.height) return null;\n"
        "  return JSON.stringify([p.x, p.y]);\n"
    )


def _visible(scope: str, name: str) -> str:
    """Whether a named object exists under the scope and is itself visible."""
    return scene_js(
        f"  var hit = findFirst({scope}, function (o) {{ return o.objectName === {json.dumps(name)}; }});\n"
        "  return hit !== null && hit.visible === true;\n"
    )


def _text_visible(scope: str, text: str) -> str:
    """Whether a Text with this exact string is rendered and visible."""
    return scene_js(
        f"  var hit = findFirst({scope}, function (o) {{ return o.text !== undefined && String(o.text) === {json.dumps(text)}; }});\n"
        "  return hit !== null && hit.visible === true;\n"
    )


def _visible_text(scope: str, text: str) -> str:
    """Whether a VISIBLE Text with this exact string exists under the scope.

    ``_text_visible`` below returns the first text match, which is the
    hidden metric inside a NavTab; the predicate here skips invisible nodes
    so a nav label is pinned by what the user can actually see.
    """
    return scene_js(
        f"  var hit = findFirst({scope}, function (o) {{ return o.visible === true"
        f" && o.text !== undefined && String(o.text) === {json.dumps(text)}; }});\n"
        "  return hit !== null;\n"
    )


def _pin_paste(scope: str, text: str) -> str:
    """Hold the paste box's decoder busy, then set the field's text.

    The decoder is a non-visual QtObject reached through the box; pinning
    ``decoding`` stops a programmatic text set from auto-completing, so the
    visible COMPLETE SIGN-IN action drives the step. The hold is released
    before returning: a submit while decoding stays quiet by contract, so
    the pinned flag must not survive into the driven click.
    """
    return scene_js(
        f"  var box = findFirst({scope}, function (o) {{ return o.objectName === 'signInPaste'; }});\n"
        "  if (!box) return false;\n"
        "  box.pasteDecoder.decoding = true;\n"
        "  var field = findFirst(box, function (o) { return o.objectName === 'signInField'; });\n"
        "  if (!field) return false;\n"
        f"  field.text = {json.dumps(text)};\n"
        "  box.pasteDecoder.cancel();\n"
        "  return true;\n"
    )


_APPLE_LABEL = "Enable Apple Music — search works without an account"
_APPLE_ROW = {
    "id": "apple:1",
    "title": "Selected Ambient Works 85-92",
    "artist": "Aphex Twin",
    "artist_id": "",
    "artists": [],
    "art": "",
    "year": "1992",
    "date": "1992-02-12",
    "tracks": 13,
    "duration_sec": 4455,
    "quality": "LOSSLESS",
    "popularity": -1,
}


def _search_payload_with_apple() -> dict:
    return {
        "groups": [
            {
                "provider": "apple",
                "artists_layout": "flow",
                "artists": [],
                "albums": [_APPLE_ROW],
                "tracks": [],
                "playlists": [],
                "top": None,
                "error": "",
            }
        ]
    }


def _boot():
    """Boot the real Main.qml with the first-run gate parked, signed out.

    Returns ``(root, q, settle, bridge, failures)`` or an exit code when Qt
    cannot host the scenario.
    """
    booted = boot_main_qml()
    if isinstance(booted, int):
        return booted
    root, q, settle, bridge = booted
    q("providerPicker.visible = false; root.setupMode = 'cards'; root.setupUrlOpened = false")
    q('waves.applySettings({"apple_enabled": false})')
    bridge._session_resolved = True
    bridge.sessionResolvedChanged.emit()
    settle(300)
    return root, q, settle, bridge, []


def _click(root, q, settle, point_expr: str, done_expr: str) -> bool:
    """Click where the expression says until the done predicate holds.

    The first activation resolves font aliases and can shift the layout, and
    a synthetic click can land on the control the hover moved out from under
    it; a fresh point per attempt keeps the scenario about the CTA wiring.
    """
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    root.requestActivate()
    settle(150)
    for _ in range(3):
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
        settle(350)
        if q(done_expr):
            return True
    return False


def _open_search(q, settle) -> None:
    q("root.openSearch()")
    settle(300)
    # The scroll dressing floats over the page and swallows synthetic clicks.
    q("scrollDressing.visible = false")
    settle(120)


def _run_apple_cta_scenario() -> int:
    booted = _boot()
    if isinstance(booted, int):
        return booted
    root, q, settle, bridge, failures = booted

    if bool(q("root.signedIn")) or bool(q("root.appleEnabled")):
        return 78  # the scenario needs a fresh signed-out, Apple-off profile

    # Search, signed out with both providers off: the invitation is on
    # screen (the gate fix) and both one-click actions are offered.
    _open_search(q, settle)
    if not bool(q("emptyHint.visible")):
        failures.append("the signed-out empty Search showed no invitation")
    if not q(_visible("results", "emptySetupCtas")):
        failures.append("the empty Search offered no setup actions")
    if not q(_text_visible("results", _APPLE_LABEL)):
        failures.append("the empty Search offered no Apple enable action")
    if not q(_text_visible("results", "Sign in to TIDAL")):
        failures.append("the empty Search offered no TIDAL sign-in action")

    # The TIDAL action opens the welcome surface's inline steps, and nothing
    # opens a browser on its own.
    if not _click(root, q, settle, _point("results", "emptyTidalCta"), "root.setupOpen === true"):
        failures.append("the Search TIDAL action did not open the sign-in surface")
    else:
        if q("root.setupMode") != "tidal":
            failures.append("the Search TIDAL action did not open the sign-in steps")
        if not q(_visible("setupPane", "welcomeSignIn")):
            failures.append("the welcome surface showed no inline sign-in steps")
        if not q(_text_visible("setupPane", "OPEN BROWSER LOGIN")):
            failures.append("the sign-in steps exposed no browser-login action")
        if q("root.setupUrlOpened"):
            failures.append("the Search TIDAL action opened the browser on its own")
    q("root.cancelSetupSignIn()")
    settle(150)

    # One click enables Apple from the empty state; the bridge's own flow
    # (search row, status light, in-place wizard) takes over from there.
    _open_search(q, settle)
    if not _click(root, q, settle, _point("results", "emptyAppleCta"), "root.appleEnabled === true"):
        failures.append("the Search Apple action did not enable the provider")
    else:
        if bridge.settings.data.apple_enabled is not True:
            failures.append("the Search Apple action did not persist the enable")
        if q(_visible("results", "emptyAppleCta")):
            failures.append("the Apple action outlived the provider it set up")

    # Apple enabled, TIDAL still signed out: the Apple action is gone, the
    # TIDAL one is not, and a search answer now carries Apple's own group.
    _open_search(q, settle)
    if q(_visible("results", "emptyAppleCta")):
        failures.append("the Apple action came back after the enable")
    if not q(_visible("results", "emptyTidalCta")):
        failures.append("enabling Apple retired the TIDAL action too")
    q("root._searchSeq = root._navSeq; root.lastSearchQuery = 'ambient'")
    bridge.searchResults.emit(_search_payload_with_apple())
    settle(500)
    if not bool(q("root.searchGroupFor('apple').headVisible")):
        failures.append("an Apple-only signed-out search showed no Apple group")
    if not q(_text_visible("results", "APPLE MUSIC")):
        failures.append("the Apple group rendered no provider header")
    if bool(q("emptyHint.visible")) or q(_visible("results", "emptySetupCtas")):
        failures.append("the setup actions stayed over a search that returned rows")

    for line in failures:
        print(f"REGRESSED: {line}", file=sys.stderr)
    return EXIT_REGRESSED if failures else EXIT_OK


def _run_tidal_cta_scenario() -> int:
    booted = _boot()
    if isinstance(booted, int):
        return booted
    root, q, settle, bridge, failures = booted

    if bool(q("root.signedIn")):
        return 78  # the scenario needs a signed-out profile

    # The nav tab reads My Music.
    if not q(_visible_text("headerRow", "My Music")):
        failures.append("the nav tab does not read My Music")

    # Browse, signed out: the pane names TIDAL and offers the sign-in click
    # instead of staying blank.
    q("root.openBrowse()")
    settle(300)
    q("scrollDressing.visible = false")
    settle(120)
    if not q(_visible("browseLanding", "browseSignInCta")):
        failures.append("the signed-out Browse pane showed no sign-in call to action")
    if not q(_text_visible("browseLanding", "Sign in to TIDAL")):
        failures.append("the Browse empty state did not name the sign-in action")
    if not _click(root, q, settle, _point("browseLanding", "browseSignInAction"), "root.setupOpen === true"):
        failures.append("the Browse action did not open the sign-in surface")
    elif q("root.setupMode") != "tidal" or not q(_visible("setupPane", "welcomeSignIn")):
        failures.append("the Browse action did not open the inline sign-in steps")
    q("root.cancelSetupSignIn()")
    settle(150)

    # My Music, signed out: one provider-named empty state, no category tabs
    # left as dead ends.
    q("root.openLibrary()")
    settle(300)
    q("scrollDressing.visible = false")
    settle(120)
    if not q(_text_visible("libraryPane", "My Music")):
        failures.append("the pane title does not read My Music")
    if not q(_visible("libArea", "libSignInCta")):
        failures.append("the signed-out My Music pane showed no empty state")
    if q(_visible("libraryPane", "libTabsFlow")):
        failures.append("the signed-out My Music pane left its category tabs up")
    if not q(_text_visible("libCtaCol", "Sign in to TIDAL")):
        failures.append("the My Music empty state did not offer the sign-in action")
    if not _click(root, q, settle, _point("libArea", "libSignInAction"), "root.setupOpen === true"):
        failures.append("the My Music action did not open the sign-in surface")
    elif q("root.setupMode") != "tidal" or not q(_visible("setupPane", "welcomeSignIn")):
        failures.append("the My Music action did not open the inline sign-in steps")

    # Complete the sign-in through the visible steps; the account service is
    # the fake, everything around it is the real bridge.
    tidal = bridge.providers["tidal"]
    tidal.login_begin = lambda: "https://tidal.test/authorize"
    tidal.login_complete = lambda url: str(url).startswith("https://tidal.test/")
    if not _click(root, q, settle, _text_point("setupPane", "OPEN BROWSER LOGIN"), "root.setupUrlOpened === true"):
        failures.append("the sign-in steps exposed no working browser-login action")
    else:
        if not q(_pin_paste("setupPane", "https://tidal.test/redirect")):
            failures.append("the sign-in surface exposed no paste field to drive")
        elif not _click(root, q, settle, _text_point("setupPane", "COMPLETE SIGN-IN"), "root.signedIn === true"):
            failures.append("completing the paste did not sign the session in")

    # Signed in: every TIDAL action retires, and My Music's categories return.
    if not bool(q("root.signedIn")):
        failures.append("the scenario never reached a signed-in session")
    else:
        if q(_visible("results", "emptyTidalCta")):
            failures.append("the TIDAL action outlived the sign-in")
        q("root.openBrowse()")
        settle(300)
        q("scrollDressing.visible = false")
        settle(120)
        if q(_visible("browseLanding", "browseSignInCta")):
            failures.append("the Browse sign-in call to action outlived the sign-in")
        q("root.openLibrary()")
        settle(300)
        q("scrollDressing.visible = false")
        settle(120)
        if q(_visible("libArea", "libSignInCta")):
            failures.append("the My Music sign-in empty state outlived the sign-in")
        if not q(_visible("libraryPane", "libTabsFlow")):
            failures.append("the My Music category tabs did not come back after sign-in")
        # One saved-shelf source (TIDAL signed in): no source label over the
        # shelves. The rule is the bridge's; a second source qualifies it
        # (tests/providers/test_my_music_shelves.py drives that data rule).
        if q("root.myMusicSources.length") != 1 or q("String(root.myMusicSources[0].label)") != "":
            failures.append("a lone saved-shelf source grew a source label")
        if q(_visible("libraryPane", "libSourceLabel")):
            failures.append("the My Music source label rendered with one source")

    for line in failures:
        print(f"REGRESSED: {line}", file=sys.stderr)
    return EXIT_REGRESSED if failures else EXIT_OK


@pytest.mark.qml
def test_the_empty_search_offers_the_apple_and_tidal_setup_actions():
    run_scenario(
        Path(__file__),
        "--run-apple-cta",
        timeout=180,
        sandbox_prefix="waves-setup-ctas-apple-",
        failure_message="the Search setup actions regressed",
    )


@pytest.mark.qml
def test_browse_and_my_music_offer_tidal_sign_in_until_signed_in():
    run_scenario(
        Path(__file__),
        "--run-tidal-cta",
        timeout=180,
        sandbox_prefix="waves-setup-ctas-tidal-",
        failure_message="the Browse / My Music setup actions regressed",
    )


if __name__ == "__main__" and "--run-apple-cta" in sys.argv:
    raise SystemExit(_run_apple_cta_scenario())

if __name__ == "__main__" and "--run-tidal-cta" in sys.argv:
    raise SystemExit(_run_tidal_cta_scenario())
