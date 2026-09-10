"""Collapsible provider groups in Search (issue #67).

Each provider header (TIDAL / APPLE MUSIC) collapses its whole result
group; the fold defaults to expanded, persists per session and across
restarts via waves prefs, per provider. Filter chips keep filtering rows
independently of the fold.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

QML_MAIN = Path(__file__).resolve().parent.parent / "waves" / "waves_ui" / "qml" / "Main.qml"
_EXIT_NO_QT = 77
_EXIT_PRECONDITION = 78


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
        "artists": [],
        "albums": [_album("tidal:1")],
        "tracks": [_track("tidal:2")],
        "videos": [],
        "playlists": [],
        "mixes": [],
        "top": None,
        "apple": {
            "artists": [],
            "albums": [_album("apple:1")],
            "tracks": [_track("apple:2")],
            "videos": [],
            "playlists": [],
            "mixes": [],
            "top": None,
        },
    }


def _scenario() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    try:
        from PySide6.QtCore import QEventLoop, QTimer, QUrl
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtQml import QQmlApplicationEngine, QQmlEngine, QQmlExpression
    except Exception:
        return _EXIT_NO_QT

    app = QGuiApplication.instance() or QGuiApplication([])
    try:
        from _qml_offline import PARK_LOGIN_QML, patch_offline

        patch_offline()
        from waves.waves_ui.app import _load_mono
        from waves.waves_ui.backend import WavesBridge
    except Exception:
        return _EXIT_NO_QT

    engine = QQmlApplicationEngine()
    bridge = WavesBridge(tidal=None)
    engine.rootContext().setContextProperty("waves", bridge)
    engine.rootContext().setContextProperty("monoFont", _load_mono())
    engine.rootContext().setContextProperty("uiFontFamily", app.font().family())
    engine.load(QUrl.fromLocalFile(str(QML_MAIN)))
    if not engine.rootObjects():
        return _EXIT_PRECONDITION
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

    # Both groups start expanded with their rows on screen.
    q("_searchSeq = _navSeq")
    bridge.searchResults.emit(_payload())
    settle(500)
    expanded_ok = (
        q("tidalGroupHead.visible")
        and q("appleGroupHead.visible")
        and q("tidalGroupHead.y") < q("appleGroupHead.y")
        and q("albumsHead.visible")
        and q("appleAlbumsHead.visible")
        and q("tracksHead.visible")
        and q("appleTracksHead.visible")
        and not q("tidalSearchGroupCollapsed")
        and not q("appleSearchGroupCollapsed")
    )

    # Collapsing Apple hides its rows but keeps its header; TIDAL is
    # untouched and the build veil still settles (hidden Loaders tick).
    q("toggleSearchProviderGroup(true)")
    settle(100)
    apple_collapsed_ok = (
        q("appleGroupHead.visible")
        and not q("appleAlbumsHead.visible")
        and not q("appleTracksHead.visible")
        and q("albumsHead.visible")
        and q("tracksHead.visible")
        and q("tidalGroupHead.y") < q("appleGroupHead.y")
        and not q("searchBuilding")
    )

    # Collapsing TIDAL hides its rows too, header included in neither case.
    q("toggleSearchProviderGroup(false)")
    settle(100)
    tidal_collapsed_ok = (
        q("tidalGroupHead.visible") and not q("albumsHead.visible") and not q("appleAlbumsHead.visible")
    )

    # Expanding restores both groups.
    q("toggleSearchProviderGroup(true)")
    q("toggleSearchProviderGroup(false)")
    settle(100)
    expanded_again_ok = q("albumsHead.visible") and q("appleAlbumsHead.visible")

    # Filter chips still filter rows independently of the fold: with Apple
    # collapsed, the albums chip keeps both heads (both have albums) while
    # Apple's rows stay hidden; tracks keeps both heads too.
    q("toggleSearchProviderGroup(true)")
    settle(50)
    q('filterType = "albums"')
    settle(50)
    chips_ok = (
        q("tidalGroupHead.visible")
        and q("appleGroupHead.visible")
        and q("albumsHead.visible")
        and not q("appleAlbumsHead.visible")
        and not q("tracksHead.visible")
        and not q("appleTracksHead.visible")
    )
    q('filterType = "all"')
    settle(50)
    chips_ok = chips_ok and q("albumsHead.visible") and not q("appleAlbumsHead.visible")
    q("toggleSearchProviderGroup(true)")
    settle(50)

    # The fold reached the persisted prefs and the file on disk...
    bridge._config_writer.flush()
    settle(100)
    prefs_ok = not bridge._waves_prefs.get("search_provider_apple_collapsed") and not bridge._waves_prefs.get(
        "search_provider_tidal_collapsed"
    )
    q("toggleSearchProviderGroup(true)")
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
    restart_ok = len(roots) == 2 and q("appleSearchGroupCollapsed", roots[1])
    restart_ok = restart_ok and not q("tidalSearchGroupCollapsed", roots[1])

    ok = expanded_ok and apple_collapsed_ok and tidal_collapsed_ok and expanded_again_ok and chips_ok and prefs_ok
    return 0 if ok and restart_ok else 1


def test_search_provider_groups_collapse_fold_and_persist():
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="waves-search-collapse-test-")
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--run-scenario"],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode == _EXIT_NO_QT:
        pytest.skip("PySide6 / offscreen Qt unavailable")
    if proc.returncode == _EXIT_PRECONDITION:
        pytest.skip("could not load Main.qml in this environment")
    assert proc.returncode == 0, proc.stdout + proc.stderr


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_scenario())
