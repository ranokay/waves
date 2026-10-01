"""Collapsible provider groups in Search.

Each provider header (TIDAL / APPLE MUSIC, and any later provider) collapses
its whole result group; the fold defaults to expanded, persists per session
and across restarts via waves prefs, per provider. Filter chips keep filtering
rows independently of the fold. The groups render through one
shared component (SearchProviderGroup), so this scenario reads them through
root.searchGroupFor(provider).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from support.paths import QML_MAIN
from support.qml import run_scenario


def _album(media_id: str) -> dict:
    return {
        "id": media_id,
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
        "explicit": False,
        "added": "",
    }


def _track(media_id: str) -> dict:
    return {
        "id": media_id,
        "title": "Xtal",
        "artist": "Aphex Twin",
        "artist_id": "",
        "artists": [],
        "album": "Selected Ambient Works 85-92",
        "album_id": "",
        "num": 1,
        "vol": 1,
        "art": "",
        "year": "1992",
        "date": "1992-02-12",
        "duration": "4:53",
        "duration_sec": 293,
        "quality": "LOSSLESS",
        "popularity": -1,
        "explicit": False,
        "added": "",
    }


def _payload() -> dict:
    return {
        "groups": [
            {
                "provider": "tidal",
                "artists_layout": "strip",
                "head_when_alone": False,
                "artists": [],
                "albums": [_album("tidal:1")],
                "tracks": [_track("tidal:2")],
                "videos": [],
                "playlists": [],
                "mixes": [],
                "top": None,
                "error": "",
            },
            {
                "provider": "apple",
                "artists_layout": "flow",
                "artists": [],
                "albums": [_album("apple:1")],
                "tracks": [_track("apple:2")],
                "playlists": [],
                "top": None,
                "error": "",
            },
        ]
    }


def _scenario() -> int:
    from PySide6.QtCore import QEventLoop, QTimer, QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine, QQmlEngine, QQmlExpression

    app = QGuiApplication.instance() or QGuiApplication([])
    from support.offline import PARK_LOGIN_QML, patch_offline

    patch_offline()
    from waves.desktop.app import _load_mono
    from waves.desktop.backend import WavesBridge

    engine = QQmlApplicationEngine()
    bridge = WavesBridge(tidal=None)
    engine.rootContext().setContextProperty("waves", bridge)
    engine.rootContext().setContextProperty("monoFont", _load_mono())
    engine.rootContext().setContextProperty("uiFontFamily", app.font().family())
    engine.load(QUrl.fromLocalFile(str(QML_MAIN)))
    if not engine.rootObjects():
        raise RuntimeError("Main.qml loaded no root object")
    root = engine.rootObjects()[0]
    root.setProperty("width", 1100)
    root.setProperty("height", 900)

    def q(expression: str, obj=None):
        context = QQmlEngine.contextForObject(root)
        value = QQmlExpression(context, obj or root, expression)
        result = value.evaluate()
        if value.hasError():
            raise RuntimeError(value.error().toString())
        return result[0] if isinstance(result, tuple) else result

    def settle(timeout_ms: int = 300) -> None:
        loop = QEventLoop()
        QTimer.singleShot(timeout_ms, loop.quit)
        loop.exec()

    settle()
    q(PARK_LOGIN_QML)
    q("openSearch()")
    settle()

    tidal = "root.searchGroupFor('tidal')"
    apple = "root.searchGroupFor('apple')"

    # Both groups start expanded with their rows on screen.
    q("_searchSeq = _navSeq")
    bridge.searchResults.emit(_payload())
    settle(500)
    expanded_ok = (
        q(tidal + ".headVisible")
        and q(apple + ".headVisible")
        and q(tidal + ".y") < q(apple + ".y")
        and q(tidal + ".sectionVisible('albums')")
        and q(apple + ".sectionVisible('albums')")
        and q(tidal + ".sectionVisible('tracks')")
        and q(apple + ".sectionVisible('tracks')")
        and not q(tidal + ".collapsed")
        and not q(apple + ".collapsed")
    )

    # Collapsing Apple hides its rows but keeps its header; TIDAL is
    # untouched and the build veil still settles (hidden Loaders tick).
    q(apple + ".toggleCollapsed()")
    settle(100)
    apple_collapsed_ok = (
        q(apple + ".headVisible")
        and not q(apple + ".sectionVisible('albums')")
        and not q(apple + ".sectionVisible('tracks')")
        and q(tidal + ".sectionVisible('albums')")
        and q(tidal + ".sectionVisible('tracks')")
        and q(tidal + ".y") < q(apple + ".y")
        and not q("searchBuilding")
    )

    # Collapsing TIDAL hides its rows too, header included in neither case.
    q(tidal + ".toggleCollapsed()")
    settle(100)
    tidal_collapsed_ok = (
        q(tidal + ".headVisible")
        and not q(tidal + ".sectionVisible('albums')")
        and not q(apple + ".sectionVisible('albums')")
    )

    # Expanding restores both groups.
    q(apple + ".toggleCollapsed()")
    q(tidal + ".toggleCollapsed()")
    settle(100)
    expanded_again_ok = q(tidal + ".sectionVisible('albums')") and q(apple + ".sectionVisible('albums')")

    # Filter chips still filter rows independently of the fold: with Apple
    # collapsed, the albums chip keeps both heads (both have albums) while
    # Apple's rows stay hidden; tracks keeps both heads too.
    q(apple + ".toggleCollapsed()")
    settle(50)
    q('filterType = "albums"')
    settle(50)
    chips_ok = (
        q(tidal + ".headVisible")
        and q(apple + ".headVisible")
        and q(tidal + ".sectionVisible('albums')")
        and not q(apple + ".sectionVisible('albums')")
        and not q(tidal + ".sectionVisible('tracks')")
        and not q(apple + ".sectionVisible('tracks')")
    )
    q('filterType = "all"')
    settle(50)
    chips_ok = chips_ok and q(tidal + ".sectionVisible('albums')") and not q(apple + ".sectionVisible('albums')")
    q(apple + ".toggleCollapsed()")
    settle(50)

    # The fold reached the persisted prefs and the file on disk...
    bridge._config_writer.flush()
    settle(100)
    prefs_ok = not bridge._waves_prefs.get("search_provider_apple_collapsed") and not bridge._waves_prefs.get(
        "search_provider_tidal_collapsed"
    )
    q(apple + ".toggleCollapsed()")
    settle(50)
    bridge._config_writer.flush()
    settle(100)
    with open(bridge._waves_prefs_path, encoding="utf-8") as handle:
        stored = json.load(handle)
    prefs_ok = (
        prefs_ok
        and bridge._waves_prefs.get("search_provider_apple_collapsed")
        and stored.get("search_provider_apple_collapsed")
        and not stored.get("search_provider_tidal_collapsed")
    )

    # ...so a fresh root starts with Apple still collapsed (the restart read).
    engine.load(QUrl.fromLocalFile(str(QML_MAIN)))
    settle(300)
    roots = engine.rootObjects()
    second = roots[1]
    q("openSearch()", second)
    q("_searchSeq = _navSeq", second)
    bridge.searchResults.emit(_payload())
    settle(500)
    restart_ok = len(roots) == 2 and q("searchGroupFor('apple').collapsed", second)
    restart_ok = restart_ok and not q("searchGroupFor('tidal').collapsed", second)

    ok = expanded_ok and apple_collapsed_ok and tidal_collapsed_ok and expanded_again_ok and chips_ok and prefs_ok
    return 0 if ok and restart_ok else 1


@pytest.mark.qml
def test_search_provider_groups_collapse_fold_and_persist():
    run_scenario(Path(__file__), "--run-scenario", timeout=120, sandbox_prefix="waves-search-collapse-test-")


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_scenario())
