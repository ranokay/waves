"""Official provider logos live in qml/assets/providers/ and are the marks in use.

The asset placement test stays; the rendered scenario drives the real
Main.qml and asserts each mark is a visible image with a real size on its own
surface: the Settings Providers card's dual-logo tile, the search page's
source chips and its compact row marks, and the Chooser's provider chip. A
mark that is hidden, zero-sized or left off its surface fails.
"""

from __future__ import annotations

import json
import sys

import pytest
from search.fakes import qml_search_payload
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

# The visible source chips' reader-facing names (All plus one per source),
# over the live tree so a hidden chip cannot answer.
_CHIP_NAMES_BODY = """
    var out = [];
    function walk(o) {
        if (!o) return;
        if (o.objectName === "searchSourceChip" && o.visible)
            out.push("" + o.Accessible.name);
        if (o.contentItem) walk(o.contentItem);
        if (o.item) walk(o.item);
        var kids = o.children || [];
        for (var i = 0; i < kids.length; i++) walk(kids[i]);
    }
    walk(root);
    return JSON.stringify(out);
"""

# The source chips row itself: the scope whose ProviderLogos are the chips'
# own marks (the surface that used to be the per-provider group heads).
_CHIP_LOGO_SCOPE = "findFirst(root, function (o) { return o.objectName === 'searchSourceChips'; })"

# Every visible row mark, as [reader-facing name, [[logo source, visible,
# width, height], ...]]: the mark's own ProviderLogo is checked in place, so
# a name without a drawn asset cannot pass.
_ROW_MARKS_BODY = """
    var out = [];
    function walkLogo(o, logos) {
        if (!o) return;
        if (o.source !== undefined)
            logos.push(["" + o.source, !!o.visible, o.width, o.height]);
        if (o.contentItem) walkLogo(o.contentItem, logos);
        if (o.item) walkLogo(o.item, logos);
        var kids = o.children || [];
        for (var i = 0; i < kids.length; i++) walkLogo(kids[i], logos);
    }
    function walk(o) {
        if (!o) return;
        if (o.objectName === "searchSourceMark" && o.visible) {
            var logos = [];
            walkLogo(o, logos);
            out.push(["" + o.Accessible.name, logos]);
        }
        if (o.contentItem) walk(o.contentItem);
        if (o.item) walk(o.item);
        var kids = o.children || [];
        for (var i = 0; i < kids.length; i++) walk(kids[i]);
    }
    walk(searchResultsView);
    return JSON.stringify(out);
"""

# The Providers card's dual-logo tile: the one Rectangle carrying both marks.
_SETTINGS_TILE_JS = "findFirst(settingsPage, function (o) { return o.dualLogo === true; })"

# A search row's Chooser button, opened through the control's own action. No
# other state is set up here: openChooser() builds and refreshes the chooser
# itself, exactly as the chevron's click does. The two drivers share the one
# row lookup.
_ROW_JS = """
    var db = findFirst(root.contentItem, function (o) {
        return o.chooserKind !== undefined && ("" + o.mediaId) === "__MEDIA_ID__";
    });
"""

_OPEN_CHOOSER_BODY = (
    _ROW_JS
    + """
    if (!db) return "no-button";
    if (!db.showChooser) return "hidden:" + db.st + ":" + db.waiting;
    db.openChooser();
    return "opened";
"""
)

# The same row's popover, closed again so the next row's chip is read from
# the popover that row opened, never from a neighbour's stale one.
_CLOSE_CHOOSER_BODY = (
    _ROW_JS
    + """
    if (db) db.closeChooser();
    return true;
"""
)

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

    # 2. Search: two sources answer, so the header draws the source chips
    # (All + one per provider) and every row carries its provider's compact
    # mark. Each chip's ProviderLogo and each row mark draw the descriptor's
    # asset; both name their provider for a reader. The per-provider group
    # heads are gone; the chips and the row marks are where the logos live.
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
    tidal_payload = qml_search_payload(provider="tidal", tracks=[track])
    apple_payload = qml_search_payload(provider="apple", tracks=[{**track, "id": "apple:t1"}])
    section_names = sorted(set(tidal_payload["sections"]) | set(apple_payload["sections"]))
    payload = {
        "sources": tidal_payload["sources"] + apple_payload["sources"],
        "sections": {
            name: list(tidal_payload["sections"].get(name, [])) + list(apple_payload["sections"].get(name, []))
            for name in section_names
        },
        "top": None,
    }
    q("root._searchSeq = root._navSeq")
    bridge.searchResults.emit(payload)
    settle(500)
    if not bool(q("root.sourceMarksOn")):
        problems.append("two sources did not turn the source marks on")
    source_order = str(q("(root.searchSources || []).map(function (s) { return s.provider }).join(',')"))
    if source_order != "tidal,apple":
        problems.append(f"the two sources did not land in payload order ({source_order!r})")

    chip_names = json.loads(q(_js(_CHIP_NAMES_BODY)))
    missing_chips = [
        wanted for wanted in ("Show TIDAL results", "Show Apple Music results") if wanted not in chip_names
    ]
    if missing_chips:
        problems.append(f"source chips missing their reader-facing names ({missing_chips}; got {chip_names})")

    # The chips' own ProviderLogos: each descriptor's asset, visible and
    # sized, on the surface that replaced the group heads.
    for name, asset in (("TIDAL", "tidal.png"), ("APPLE MUSIC", "apple-music.png")):
        if not visible_mark(_CHIP_LOGO_SCOPE, asset):
            problems.append(f"the {name} source chip shows no visible mark")

    # Each row's compact mark: the reader-facing name plus the descriptor's
    # logo drawn by that mark's own ProviderLogo.
    row_marks = json.loads(q(_js(_ROW_MARKS_BODY)))
    for name, asset, wanted in (
        ("TIDAL", "tidal.png", "Available on TIDAL"),
        ("APPLE MUSIC", "apple-music.png", "Available on Apple Music"),
    ):
        hits = [m for m in row_marks if m[0] == wanted]
        if not hits:
            problems.append(f"no search row carries the {name} mark ({row_marks})")
        elif not any(asset in logo[0] and logo[1] and logo[2] > 0 and logo[3] > 0 for m in hits for logo in m[1]):
            problems.append(f"the {name} row mark draws no visible {asset} logo ({hits})")

    # 3. The selected offer's mark follows its provider. Both rows sit inside
    # the mixed view's first five and render without expanding anything; other
    # offers now carry their own marks, so inspect only the selected row.
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
            selected_scope = f"findFirst({_POPOVER_JS}.contentItem, function(o) {{ return o.selected === true && o.descriptor !== undefined; }})"
            if not visible_mark(selected_scope, own_asset):
                problems.append(f"the Chooser for {media_id} shows no visible {own_name} mark")
            if visible_mark(selected_scope, other_asset):
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
