"""Official provider logos live in qml/assets/providers/ and are the marks in use.

Issue #58, extended from source spelling to rendered behavior (T6): the asset
placement test stays, and the marks themselves are checked where the user sees
them -- the Settings Providers tile, both search group headers and the
Chooser's provider segments -- as visible images with a real size and the
provider asset source. A surface that kept the string but drew nothing (a
hidden image, a zero size, a mark on the wrong row) now fails. The scenario
runs in a SUBPROCESS like the other Main.qml scenarios.
"""

from __future__ import annotations

import json
import sys

import pytest
from support.paths import QML_DIR, QML_MAIN, REPO_ROOT
from support.qml import (
    EXIT_NO_QT,
    EXIT_OK,
    EXIT_PRECONDITION,
    EXIT_REGRESSED,
    run_scenario,
    sandbox_qml_settings,
)

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
_MARKS_JS = """
(function () {
    function findObject(it, name) {
        if (!it) return null;
        if (it.objectName === name) return it;
        if (it.item && it.item.objectName === name) return it.item;
        var kids = it.children || [];
        for (var i = 0; i < kids.length; i++) {
            var hit = findObject(kids[i], name);
            if (hit) return hit;
        }
        return null;
    }
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
})()
"""

_FIND_OBJECT_JS = """
function findObject(it, name) {
    if (!it) return null;
    if (it.objectName === name) return it;
    if (it.item && it.item.objectName === name) return it.item;
    var kids = it.children || [];
    for (var i = 0; i < kids.length; i++) {
        var hit = findObject(kids[i], name);
        if (hit) return hit;
    }
    return null;
}
"""

# The search row's Chooser button: open it through the control's own action
# (chooserBuilt -> refreshChooser -> openChooser), so the popover under test is
# the one a click would show.
_OPEN_CHOOSER_JS = """
(function () {
    function find(it) {
        if (!it) return null;
        if (it.chooserKind !== undefined && ("" + it.mediaId) === "t1") return it;
        var kids = it.children || [];
        for (var i = 0; i < kids.length; i++) {
            var hit = find(kids[i]);
            if (hit) return hit;
        }
        return null;
    }
    var db = find(root.contentItem);
    if (!db) return "no-button";
    if (!db.showChooser) return "hidden:" + db.st + ":" + db.waiting;
    db.chooserBuilt = true;
    db.refreshChooser();
    db.openChooser();
    return "opened";
})()
"""

_POPOVER_JS = "findObject(root.contentItem, 'chooserPopover')"


def _find_object_expr(name: str) -> str:
    return "(function () {" + _FIND_OBJECT_JS + f"  return findObject(root.contentItem, '{name}');" + "})()"


def _marks_expr(scope: str) -> str:
    return _MARKS_JS.replace("SCOPE", scope)


def _run_scenario() -> int:
    try:
        from PySide6.QtCore import QEventLoop, QTimer, QUrl
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtQml import QQmlApplicationEngine, QQmlEngine, QQmlExpression
    except Exception as exc:  # pragma: no cover - environment guard
        print(f"Qt unavailable: {exc}", file=sys.stderr)
        return EXIT_NO_QT

    from support.offline import PARK_LOGIN_QML, patch_offline

    patch_offline()
    app = QGuiApplication.instance() or QGuiApplication([])
    sandbox_qml_settings()
    try:
        from waves.waves_ui.app import _load_mono
        from waves.waves_ui.backend import WavesBridge
    except Exception as exc:  # pragma: no cover - environment guard
        print(f"Qt platform/backend unavailable: {exc}", file=sys.stderr)
        return EXIT_NO_QT

    engine = QQmlApplicationEngine()
    bridge = WavesBridge(tidal=None)
    engine.rootContext().setContextProperty("waves", bridge)
    engine.rootContext().setContextProperty("monoFont", _load_mono())
    engine.rootContext().setContextProperty("uiFontFamily", app.font().family())
    engine.load(QUrl.fromLocalFile(str(QML_MAIN)))
    roots = engine.rootObjects()
    if not roots:
        print("Main.qml failed to load", file=sys.stderr)
        return EXIT_PRECONDITION
    root = roots[0]

    def q(expr: str):
        e = QQmlExpression(QQmlEngine.contextForObject(root), root, expr)
        r = e.evaluate()
        if e.hasError():
            raise RuntimeError(e.error().toString())
        return r[0] if isinstance(r, tuple) else r

    def settle(ms: int = 200) -> None:
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def visible_mark(scope: str, asset: str) -> tuple[bool, list]:
        found = [m for m in json.loads(q(_marks_expr(scope))) if asset in m[0]]
        return any(m[1] and m[2] > 0 and m[3] > 0 for m in found), found

    root.setProperty("width", 1200)
    root.setProperty("height", 900)
    settle()
    q("bootOverlay.done = true")
    q("bootContentShown = 1")
    q("legalSettings.termsAcceptedVersion = root.termsVersion")
    q("legalSettings.termsAccepted = true")
    q("setupSettings.providerPickerDone = true")
    q(PARK_LOGIN_QML)
    settle(200)

    # Apple on: the Apple search group and the Chooser only exist with it.
    q("waves.applySettings({'apple_enabled': true})")
    q("root.refreshAppleEnabled()")
    settle(300)

    problems: list[str] = []

    # 1. Settings: the Providers card's dual-logo tile.
    q("settingsOpen = true")
    settle(300)
    q("settingsPage.jumpToCard('providers')")
    settle(500)
    for name, asset in (("TIDAL", "tidal.png"), ("APPLE MUSIC", "apple-music.png")):
        ok, found = visible_mark("settingsPage", asset)
        if not ok:
            problems.append(f"Settings shows no visible {name} mark (found {found})")

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
        ok, found = visible_mark(scope, asset)
        if not ok:
            problems.append(f"the {name} search header shows no visible mark (found {found})")

    # 3. The Chooser's provider segments, opened through the row's own control.
    chooser = str(q(_OPEN_CHOOSER_JS))
    if chooser != "opened":
        problems.append(f"the Chooser button would not open ({chooser})")
    else:
        settle(400)
        if q(_find_object_expr("chooserPopover")) is None:
            problems.append(f"the Chooser popover did not open ({chooser})")
        else:
            ok, found = visible_mark(_POPOVER_JS, "tidal.png")
            if not ok:
                problems.append(f"the Chooser shows no visible TIDAL mark (found {found})")
            ok, found = visible_mark(_POPOVER_JS, "apple-music.png")
            if not ok:
                problems.append(f"the Chooser shows no visible APPLE MUSIC mark (found {found})")

    if problems:
        for line in problems:
            print(f"REGRESSED: {line}", file=sys.stderr)
        return EXIT_REGRESSED
    print("ok")
    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    sys.exit(_run_scenario())
