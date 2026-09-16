"""Issue #219: the Apple setup path from the welcome card to the wizard step.

WHAT THIS FENCES OFF
--------------------
1. A card that offers a sign-in where a one-time setup is meant, or card copy
   the QML authors rather than the descriptors: the Apple card's action is
   the descriptor's own words, and its live status row comes from the same
   bridge answer the header marks read.

2. Choosing Apple without enabling it, without opening the in-place wizard,
   or with the wizard's tiers out of order: search must work before setup
   completes, and the cookies tier sits before the full tier's steps.

3. "Skip for now" undoing the choice. Skipping defers setup, never disables
   Apple: the session stays enabled, the app lands on Search, and the
   wizard's live status keeps reporting the truth.

4. A pre-setup download click opening the wizard at the top: the click
   carries the step that would have made it work (cookies / runtime), and
   the page marks that step.

Runs in a SUBPROCESS like the other Main.qml scenarios: building the bridge
installs process-global handlers that must not leak into the suite.
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
        f"  var hit = findFirst({scope}, function (o) {{ return o.objectName === {json.dumps(name)}"
        " && o.visible === true; });\n"
        "  if (!hit || hit.width <= 0 || hit.height <= 0) return null;\n"
        "  var p = hit.mapToItem(null, hit.width / 2, hit.height / 2);\n"
        "  if (p.x < 0 || p.y < 0 || p.x > root.width || p.y > root.height) return null;\n"
        "  return JSON.stringify([p.x, p.y]);\n"
    )


def _text_point(scope: str, text: str) -> str:
    """Scene coordinates of the first visible Text with exactly this string."""
    return scene_js(
        f"  var hit = findFirst({scope}, function (o) {{ return o.visible === true"
        f" && o.text !== undefined && String(o.text) === {json.dumps(text)}; }});\n"
        "  if (!hit || hit.width <= 0 || hit.height <= 0) return null;\n"
        "  var p = hit.mapToItem(null, hit.width / 2, hit.height / 2);\n"
        "  if (p.x < 0 || p.y < 0 || p.x > root.width || p.y > root.height) return null;\n"
        "  return JSON.stringify([p.x, p.y]);\n"
    )


def _visible_text(scope: str, text: str) -> str:
    """Whether a VISIBLE Text with this exact string exists under the scope."""
    return scene_js(
        f"  var hit = findFirst({scope}, function (o) {{ return o.visible === true"
        f" && o.text !== undefined && String(o.text) === {json.dumps(text)}; }});\n"
        "  return hit !== null;\n"
    )


def _visible(scope: str, name: str) -> str:
    """Whether a VISIBLE object with this objectName exists under the scope.

    The settings schema renders every field's type-columns in every field
    delegate (each gated by `visible: modelData.type === ...`), so a name can
    match many hidden copies: the visible instance is the one under test.
    """
    return scene_js(
        f"  var hit = findFirst({scope}, function (o) {{ return o.objectName === {json.dumps(name)}"
        " && o.visible === true; });\n"
        "  return hit !== null;\n"
    )


def _scroll_to(scope: str, name: str) -> str:
    """Scroll the Settings viewport until the visible named object is centred."""
    return scene_js(
        f"  var hit = findFirst({scope}, function (o) {{ return o.objectName === {json.dumps(name)}"
        " && o.visible === true; });\n"
        "  if (!hit) return null;\n"
        "  var holder = settingsPage.scrollViewport;\n"
        "  var y = hit.mapToItem(holder.contentItem, 0, hit.height / 2).y;\n"
        "  settingsPage.scrollY = Math.max(0, y - holder.height / 2);\n"
        "  return String(settingsPage.scrollY);\n"
    )


def _step_y(key: str) -> str:
    """The visible wizard step label's y inside the Settings content, or -1."""
    return scene_js(
        f"  var hit = findFirst(settingsPage, function (o) {{"
        f" return o.objectName === 'appleStepLabel_' + {json.dumps(key)} && o.visible === true; }});\n"
        "  if (!hit) return -1;\n"
        "  return hit.mapToItem(settingsPage.scrollViewport.contentItem, 0, 0).y;\n"
    )


def _download_tap_point(media_id: str) -> str:
    """Scene coordinates of one rendered row's real download tap area."""
    return scene_js(
        "  var hit = findFirst(root, function (o) {"
        f" return o.objectName === 'dbTapArea' && o.visible === true"
        f" && o.parent && String(o.parent.mediaId) === {json.dumps(media_id)}; }});\n"
        "  if (!hit || hit.width <= 0 || hit.height <= 0) return null;\n"
        "  var p = hit.mapToItem(null, hit.width / 2, hit.height / 2);\n"
        "  if (p.x < 0 || p.y < 0 || p.x > root.width || p.y > root.height) return null;\n"
        "  return JSON.stringify([p.x, p.y]);\n"
    )


_APPLE_TRACK_ROW = {
    "id": "apple:900",
    "title": "Selected Ambient Works",
    "artist": "Aphex Twin",
    "artist_id": "",
    "artists": [],
    "art": "",
    "album": "Selected Ambient Works 85-92",
    "album_id": "",
    "num": 1,
    "vol": 1,
    "duration": "5:57",
    "duration_sec": 357,
    "year": "1992",
    "date": "1992-02-12",
    "quality": "LOSSLESS",
    "popularity": -1,
    "explicit": False,
    "added": "",
}


def _apple_only_payload() -> dict:
    """An answer carrying Apple's own group and no TIDAL rows."""
    return {
        "artists": [],
        "albums": [],
        "tracks": [],
        "videos": [],
        "playlists": [],
        "mixes": [],
        "top": None,
        "apple": {
            "artists": [],
            "albums": [],
            "tracks": [_APPLE_TRACK_ROW],
            "videos": [],
            "playlists": [],
            "mixes": [],
            "top": None,
        },
    }


@pytest.mark.qml
def test_the_apple_path_enables_opens_the_wizard_skips_and_routes():
    run_scenario(
        Path(__file__),
        "--run-scenario",
        timeout=180,
        sandbox_prefix="waves-apple-setup-",
        failure_message="the Apple setup path regressed",
        drop=("waves.qt",),
    )


def _click(root, q, settle, point_expr: str, done_expr: str) -> bool:
    """Click where the expression says until the done predicate holds.

    The first activation resolves font aliases and can shift the layout, and
    a synthetic click can land on the control the hover moved out from under
    it; a fresh point per attempt keeps the scenario about the wiring.
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


def _run_scenario() -> int:  # noqa: C901 (one straight journey)
    booted = boot_main_qml()
    if isinstance(booted, int):
        return booted
    root, q, settle, bridge = booted

    failures: list[str] = []

    # A fresh first-run profile: signed out, Apple off, nothing answered. The
    # harness parks the welcome gate; re-arm it and reset the flags (the QML
    # store can survive the harness's clear on macOS).
    q("providerPicker.visible = Qt.binding(function() { return root.welcomeDue })")
    q(
        "setupSettings.firstRunAnswered = false; setupSettings.setupChipDismissed = false;"
        " setupSettings.providerPickerDone = false"
    )
    q("root.setupMode = 'cards'; root.setupUrlOpened = false")
    q('waves.applySettings({"apple_enabled": false})')
    q("scrollDressing.visible = false")
    bridge._session_resolved = True
    bridge.sessionResolvedChanged.emit()
    settle(400)

    if not q("providerPicker.visible"):
        print("the welcome surface did not show on a fresh profile", file=sys.stderr)
        return 78

    # 1. The cards carry the descriptors' copy and live status. The Apple card
    #    offers the setup (never a sign-in); the TIDAL card reports its
    #    session, and Apple (off) reports nothing to report.
    if not q(_visible_text("providerPicker", "SET UP APPLE MUSIC")):
        failures.append("the Apple card does not offer its setup action")
    if q(_visible_text("providerPicker", "SIGN IN TO APPLE MUSIC")):
        failures.append("the Apple card offers a sign-in where a setup is meant")
    if not q(_visible_text("providerPicker", "CONTINUE WITH TIDAL")):
        failures.append("the TIDAL card lost its descriptor action")
    if not q(_visible_text("providerPicker", "Signed out")):
        failures.append("the welcome cards do not show the TIDAL session state")
    if q(_visible_text("providerPicker", "Not set up")):
        failures.append("a disabled Apple provider reported a setup state")

    # 2. Choosing Apple enables it and opens the in-place wizard at the top.
    if not _click(root, q, settle, _text_point("providerPicker", "SET UP APPLE MUSIC"), "waves.appleEnabled === true"):
        failures.append("the Apple card did not enable the provider")
    settle(400)
    if bridge.settings.data.apple_enabled is not True:
        failures.append("choosing Apple did not persist the enable")
    if q("providerPicker.visible"):
        failures.append("the welcome stayed up after choosing Apple")
    if not q("root.settingsOpen"):
        failures.append("choosing Apple did not open the setup wizard")
    if q("settingsPage.appleFocusStep") != "":
        failures.append("the enable path marked a step instead of the wizard top")

    # The wizard's tiers walk cookies first, then the full tier's steps; the
    # steps are the bridge's contract, rendered in order.
    cookies_y = float(q(_step_y("cookies")))
    runtime_y = float(q(_step_y("runtime")))
    login_y = float(q(_step_y("login")))
    if cookies_y < 0 or runtime_y < 0 or login_y < 0:
        failures.append(f"the wizard did not render its steps: {cookies_y}/{runtime_y}/{login_y}")
    elif not (cookies_y < runtime_y < login_y):
        failures.append(f"the wizard's tiers are out of order: {cookies_y}/{runtime_y}/{login_y}")

    # The card reflects the live setup status (the same word appleStatus()
    # gives), and the full tier's sign-in step exists as an in-place upgrade.
    apple_status = bridge.appleStatus()
    if not q(_visible_text("settingsPage", apple_status["word"])):
        failures.append(f"the Apple card does not show its live status: {apple_status['word']}")
    if not q(_visible_text("settingsPage", "Apple ID sign-in (full tier)")):
        failures.append("the wizard does not present the full tier as an upgrade")

    # 3. SKIP FOR NOW: setup is deferred, not undone. Apple stays enabled and
    #    the app lands on Search with the field focused.
    if q(_scroll_to("settingsPage", "appleSetupSkip")) in ("", None):
        failures.append("the wizard exposes no skip action")
    elif not _click(root, q, settle, _point("settingsPage", "appleSetupSkip"), "root.settingsOpen === false"):
        failures.append("SKIP FOR NOW did not leave the setup surface")
    settle(300)
    if not bool(q("root.appleEnabled")) or bool(q("root.signedIn")):
        failures.append("the scenario never reached the Apple-only state")
    if bridge.settings.data.apple_enabled is not True:
        failures.append("SKIP FOR NOW disabled Apple")
    if q("root.navOrigin") != "search" or not bool(q("searchField.activeFocus")):
        failures.append("SKIP FOR NOW did not land on Search with the field focused")
    lights = q("root.providerLights") or []
    apple_light = next((light for light in lights if str(light.get("id", "")) == "apple"), None)
    if apple_light is None or not str(apple_light.get("word", "")):
        failures.append(f"the header lost the Apple light after skipping: {lights}")
    if q("settingsPage.appleFocusStep") != "":
        failures.append("the wizard's step mark survived leaving the page")

    # Re-opened welcome page, Apple already enabled (the state Skip leaves
    # behind): choosing the card still opens the wizard, or the re-open is a
    # dead end that closes the surface and opens nothing.
    q("waves.showSetup()")
    settle(400)
    if not q("setupPane.visible"):
        failures.append("the Settings pill did not re-open the welcome page")
    elif not _click(root, q, settle, _text_point("setupPane", "SET UP APPLE MUSIC"), "root.settingsOpen === true"):
        failures.append("choosing an already-enabled Apple did not open the wizard")
    else:
        if q("setupPane.visible"):
            failures.append("the re-opened welcome page stayed up after choosing Apple")
        if q("settingsPage.appleFocusStep") != "":
            failures.append("the re-open's Apple choice marked a step instead of the wizard top")
    q("root.openSearch()")
    settle(300)

    # Search works before setup completes: an Apple-only answer renders its
    # group with no TIDAL session in the picture.
    q("root._searchSeq = root._navSeq; root.lastSearchQuery = 'ambient'")
    bridge.searchResults.emit(_apple_only_payload())
    settle(500)
    if not bool(q("appleGroupHead.visible")):
        failures.append("an Apple-only signed-out search showed no Apple group")
    if bool(q("emptyHint.visible")):
        failures.append("the Search empty state stayed over an answered search")

    # 4. A pre-setup download click routes to the step that was missing. This
    #    is the REAL click: the row's tap area calls waves.downloadTrack, the
    #    bridge's setup gate finds no account and asks for the cookies step.
    apple_provider = bridge.providers["apple"]
    apple_provider.cached = lambda kind, raw_id: {"id": raw_id} if str(raw_id) == "apple:900" else None
    apple_provider.row_for = lambda kind, raw: dict(_APPLE_TRACK_ROW)
    if not _click(root, q, settle, _download_tap_point("apple:900"), "root.settingsOpen === true"):
        failures.append("the pre-setup download click did not open the setup surface")
    settle(400)
    if q("settingsPage.appleFocusStep") != "cookies":
        failures.append(f"the pre-setup click did not name the cookies step: {q('settingsPage.appleFocusStep')}")
    if not q(_visible("settingsPage", "appleStepMark_cookies")):
        failures.append("the cookies step is not marked for the pre-setup click")
    if q(_visible("settingsPage", "appleStepMark_runtime")):
        failures.append("an unrelated step is marked for the pre-setup click")

    # The missing fetch binary routes the next click to the runtime step: the
    # account gate opens (a real cookies export), the binary gate asks for the
    # managed runtime instead.
    import tempfile

    cookies = Path(tempfile.mkdtemp(prefix="waves-apple-journey-")) / "cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    bridge.settings.data.apple_cookies_path = str(cookies)
    bridge._configure_apple_provider()
    # The fetch-binary probe is the host's to answer (this machine's PATH may
    # already carry N_m3u8DL-RE); the scenario owns it so the missing-binary
    # route is what is under test, not the host's toolchain.
    bridge._apple_fetch_binary_ready = lambda: False
    q("root.openSearch()")
    settle(300)
    if not _click(root, q, settle, _download_tap_point("apple:900"), "root.settingsOpen === true"):
        failures.append("the missing-binary click did not open the setup surface")
    settle(400)
    if q("settingsPage.appleFocusStep") != "runtime":
        failures.append(f"the missing-binary click did not name the runtime step: {q('settingsPage.appleFocusStep')}")
    if not q(_visible("settingsPage", "appleStepMark_runtime")):
        failures.append("the runtime step is not marked for the missing-binary click")

    # Leaving the page retires the mark; the next visit starts unmarked.
    q("root.settingsOpen = false")
    settle(300)
    if q("settingsPage.appleFocusStep") != "":
        failures.append("the step mark survived leaving the page")

    for line in failures:
        print(f"REGRESSED: {line}", file=sys.stderr)
    return EXIT_REGRESSED if failures else EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_run_scenario())
