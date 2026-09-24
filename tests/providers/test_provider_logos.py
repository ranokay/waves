"""Official provider logos live in qml/assets/providers/ and are the marks in use.

The asset placement test stays; the rendered scenario drives the real
Main.qml and asserts each mark is a visible image with a real size on its own
surface: the Settings Providers card's dual-logo tile, both search group
headers and the Chooser's provider chip. A mark that is hidden, zero-sized or
left off its surface fails.
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

# A search row's Chooser button, opened through the control's own action. No
# other state is set up here: openChooser() builds and refreshes the chooser
# itself, exactly as the chevron's click does.
_OPEN_CHOOSER_BODY = """
    var db = findFirst(root.contentItem, function (o) {
        return o.chooserKind !== undefined && ("" + o.mediaId) === "__MEDIA_ID__";
    });
    if (!db) return "no-button";
    if (!db.showChooser) return "hidden:" + db.st + ":" + db.waiting;
    db.openChooser();
    return "opened";
"""

# The same row's popover, closed again so the next row's chip is read from
# the popover that row opened, never from a neighbour's stale one.
_CLOSE_CHOOSER_BODY = """
    var db = findFirst(root.contentItem, function (o) {
        return o.chooserKind !== undefined && ("" + o.mediaId) === "__MEDIA_ID__";
    });
    if (db) db.closeChooser();
    return true;
"""

# The OPEN popover: rows keep their built (hidden) popovers alive, so a
# walk must not read a closed neighbour's chip.
_POPOVER_JS = (
    "findFirst(root.contentItem, function (o) { return o.objectName === 'chooserPopover' && o.visible === true; })"
)

_js = scene_js


def _chooser_js(body: str, media_id: str) -> str:
    return _js(body.replace("__MEDIA_ID__", media_id))


def _marks_expr(scope: str) -> str:
    return _js(_MARKS_BODY.replace("SCOPE", scope))


def _run_scenario() -> int:
    booted = boot_main_qml()
    if isinstance(booted, int):
        return booted
    _, q, settle, bridge = booted

    q("legalSettings.termsAcceptedVersion = root.termsVersion")
    q("legalSettings.termsAccepted = true")
    q("setupSettings.firstRunAnswered = true")
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
        "groups": [
            {
                "provider": "tidal",
                "artists_layout": "strip",
                "head_when_alone": False,
                "artists": [],
                "albums": [],
                "tracks": [track],
                "videos": [],
                "playlists": [],
                "mixes": [],
                "top": None,
                "error": "",
            },
            {
                "provider": "apple",
                "artists_layout": "flow",
                "head_when_alone": True,
                "artists": [],
                "albums": [],
                "tracks": [{**track, "id": "apple:t1"}],
                "playlists": [],
                "top": None,
                "error": "",
            },
        ]
    }
    q("root._searchSeq = root._navSeq")
    bridge.searchResults.emit(payload)
    settle(500)
    if not bool(q("root.searchGroupFor('tidal').headVisible")):
        problems.append("the TIDAL search group header did not appear")
    if not bool(q("root.searchGroupFor('apple').headVisible")):
        problems.append("the Apple search group header did not appear")
    for scope, name, asset in (
        ("root.searchGroupFor('tidal')", "TIDAL", "tidal.png"),
        ("root.searchGroupFor('apple')", "APPLE MUSIC", "apple-music.png"),
    ):
        if not visible_mark(scope, asset):
            problems.append(f"the {name} search header shows no visible mark")

    # 3. The Chooser's provider chip: one static mark, the row's own. A TIDAL
    # row and an Apple row in turn prove the chip follows the row; each
    # popover must show its own mark and never the other provider's.
    if not bool(q("root.searchGroupFor('apple').isExpanded('tracks')")):
        q("root.searchGroupFor('apple').toggleExpanded('tracks')")
        settle(250)
    for media_id, own_name, own_asset, other_name, other_asset in (
        ("t1", "TIDAL", "tidal.png", "APPLE MUSIC", "apple-music.png"),
        ("apple:t1", "APPLE MUSIC", "apple-music.png", "TIDAL", "tidal.png"),
    ):
        chooser = str(q(_chooser_js(_OPEN_CHOOSER_BODY, media_id)))
        if chooser != "opened":
            problems.append(f"the Chooser button for {media_id} would not open ({chooser})")
            continue
        settle(400)
        if q(_js("    return " + _POPOVER_JS + ";")) is None:
            problems.append(f"the Chooser popover for {media_id} did not open")
        else:
            if not visible_mark(_POPOVER_JS, own_asset):
                problems.append(f"the Chooser for {media_id} shows no visible {own_name} mark")
            if visible_mark(_POPOVER_JS, other_asset):
                problems.append(f"the Chooser for {media_id} shows another provider's mark ({other_name})")
        q(_chooser_js(_CLOSE_CHOOSER_BODY, media_id))
        settle(200)

    if problems:
        for line in problems:
            print(f"REGRESSED: {line}", file=sys.stderr)
        return EXIT_REGRESSED
    print("ok")
    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    sys.exit(_run_scenario())
