"""Official provider logos live in qml/assets/providers/ and are the marks in use.

The asset placement test stays; the rendered scenario drives the real
Main.qml and asserts each mark is a visible image with a real size on its own
surface: the Settings Providers card's dual-logo tile, both search group
headers and the Chooser's provider segments. A mark that is hidden,
zero-sized or left off its surface fails.
"""

from __future__ import annotations

import json
import sys

import pytest
from support.paths import QML_DIR, REPO_ROOT
from support.qml import EXIT_OK, EXIT_REGRESSED, boot_main_qml, run_scenario
from support.qml_probe import scene_js

PROVIDERS = QML_DIR / "assets" / "providers"
TIDAL = PROVIDERS / "tidal.png"
APPLE = PROVIDERS / "apple-music.png"
TIDAL_DARK = PROVIDERS / "tidal-dark.png"
APPLE_DARK = PROVIDERS / "apple-music-dark.png"
_PNG_SIG = b"\x89PNG\r\n\x1a\n"


def test_logos_live_in_the_providers_asset_dir_and_not_at_the_root():
    for logo in (TIDAL, APPLE, TIDAL_DARK, APPLE_DARK):
        assert logo.is_file() and logo.stat().st_size > 0
        assert logo.read_bytes()[:8] == _PNG_SIG
    for stray in (
        "tidal-logo.png",
        "apple-music-logo.png",
        "tidal-logo-dark.png",
        "apple-music-logo-dark.png",
    ):
        assert not (REPO_ROOT / stray).exists()


@pytest.mark.qml
def test_provider_marks_render_in_settings_search_and_chooser():
    run_scenario(
        __file__,
        "--run-scenario",
        timeout=180,
        sandbox_prefix="waves-provider-logos-test-",
        failure_message="a provider mark is not rendered where it belongs",
    )


# Every Image under the scope expression whose source names a provider asset,
# as [source, visible, width, height]. Walking the live tree means a surface
# that stopped drawing its mark cannot pass on the source string alone.
_MARKS_BODY = """
    function marks(it) {
        var out = [];
        function walk(o) {
            if (!o) return;
            if (o.source !== undefined) {
                var s = "" + o.source;
                if (s.indexOf("assets/providers/") !== -1)
                    out.push([s, !!o.visible, o.width, o.height]);
            }
            if (o.contentItem) walk(o.contentItem);
            if (o.item) walk(o.item);
            var kids = o.children || [];
            for (var i = 0; i < kids.length; i++) walk(kids[i]);
        }
        walk(it);
        return JSON.stringify(out);
    }
    return marks(SCOPE);
"""

# The Providers card's dual-logo tile: the one Rectangle carrying both marks.
_SETTINGS_TILE_JS = "findFirst(settingsPage, function (o) { return o.dualLogo === true; })"

# The search row's Chooser button, opened through the control's own action. No
# other state is set up here: openChooser() builds and refreshes the chooser
# itself, exactly as the chevron's click does.
_OPEN_CHOOSER_BODY = """
    var db = findFirst(root.contentItem, function (o) {
        return o.chooserKind !== undefined && ("" + o.mediaId) === "t1";
    });
    if (!db) return "no-button";
    if (!db.showChooser) return "hidden:" + db.st + ":" + db.waiting;
    db.openChooser();
    return "opened";
"""

_POPOVER_JS = "findObject(root.contentItem, 'chooserPopover')"


_js = scene_js


def _marks_expr(scope: str) -> str:
    return _js(_MARKS_BODY.replace("SCOPE", scope))


def _run_scenario() -> int:
    booted = boot_main_qml()
    if isinstance(booted, int):
        return booted
    _, q, settle, bridge = booted

    q("legalSettings.termsAcceptedVersion = root.termsVersion")
    q("legalSettings.termsAccepted = true")
    q("setupSettings.providerPickerDone = true")
    settle(200)

    # Apple on: the Apple search group and the Chooser only exist with it.
    q("waves.applySettings({'apple_enabled': true})")
    q("root.refreshAppleEnabled()")
    settle(300)

    problems: list[str] = []

    def visible_mark(scope: str, asset: str) -> list:
        found = [m for m in json.loads(q(_marks_expr(scope))) if asset in m[0]]
        return [m for m in found if m[1] and m[2] > 0 and m[3] > 0]

    # 1. Settings: the Providers card's dual-logo tile, scoped to the tile so
    # the card's provider bands cannot stand in for it.
    q("settingsOpen = true")
    settle(300)
    q("settingsPage.jumpToCard('providers')")
    settle(500)
    for name, asset in (("TIDAL", "tidal.png"), ("APPLE MUSIC", "apple-music.png")):
        if not visible_mark(_SETTINGS_TILE_JS, asset):
            problems.append(f"the Settings Providers tile shows no visible {name} mark")

    # 2. Search group headers, one per provider.
    q("openSearch()")
    settle(200)
    track = {
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
    payload = {
        "artists": [],
        "albums": [],
        "tracks": [track],
        "videos": [],
        "playlists": [],
        "mixes": [],
        "top": None,
        "apple": {
            "artists": [],
            "albums": [],
            "tracks": [{**track, "id": "apple:t1"}],
            "videos": [],
            "playlists": [],
            "mixes": [],
            "top": None,
        },
    }
    q("root._searchSeq = root._navSeq")
    bridge.searchResults.emit(payload)
    settle(500)
    if not bool(q("tidalGroupHead.visible")):
        problems.append("the TIDAL search group header did not appear")
    if not bool(q("appleGroupHead.visible")):
        problems.append("the Apple search group header did not appear")
    for scope, name, asset in (
        ("tidalGroupHead", "TIDAL", "tidal.png"),
        ("appleGroupHead", "APPLE MUSIC", "apple-music.png"),
    ):
        if not visible_mark(scope, asset):
            problems.append(f"the {name} search header shows no visible mark")

    # 3. The Chooser's provider segments.
    chooser = str(q(_js(_OPEN_CHOOSER_BODY)))
    if chooser != "opened":
        problems.append(f"the Chooser button would not open ({chooser})")
    else:
        settle(400)
        if q(_js("    return findObject(root.contentItem, 'chooserPopover');")) is None:
            problems.append("the Chooser popover did not open")
        else:
            for name, asset in (("TIDAL", "tidal.png"), ("APPLE MUSIC", "apple-music.png")):
                if not visible_mark(_POPOVER_JS, asset):
                    problems.append(f"the Chooser shows no visible {name} mark")

    if problems:
        for line in problems:
            print(f"REGRESSED: {line}", file=sys.stderr)
        return EXIT_REGRESSED
    print("ok")
    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    sys.exit(_run_scenario())
