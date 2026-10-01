from __future__ import annotations

import sys
from pathlib import Path

import pytest
from support.paths import QML_MAIN
from support.qml import run_scenario, sandbox_qml_settings


def _video(media_id: str) -> dict:
    return {
        "id": media_id,
        "title": "T69 Collapse",
        "artist": "Aphex Twin",
        "artists": [],
        "art": "",
        "art_big": "",
        "duration": "5:10",
        "explicit": False,
        "added": "",
        "date": "2018-08-07",
        "quality": "1080p",
    }


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


def _payload(grouped: bool) -> dict:
    groups = [
        {
            "provider": "tidal",
            "artists_layout": "strip",
            "head_when_alone": False,
            "artists": [],
            "albums": [_album("tidal:1")],
            "tracks": [],
            "videos": [_video("tidal:2")],
            "playlists": [],
            "mixes": [],
            "top": None,
            "error": "",
        }
    ]
    if grouped:
        groups.append(
            {
                "provider": "apple",
                "artists_layout": "flow",
                "artists": [],
                "albums": [_album("apple:1")],
                "tracks": [],
                "playlists": [],
                "top": None,
                "error": "",
            }
        )
    return {"groups": groups}


def _scenario() -> int:
    from PySide6.QtCore import QEventLoop, QTimer, QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine, QQmlEngine, QQmlExpression

    app = QGuiApplication.instance() or QGuiApplication([])
    sandbox_qml_settings()
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

    def q(expression: str):
        context = QQmlEngine.contextForObject(root)
        value = QQmlExpression(context, root, expression)
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

    q("_searchSeq = _navSeq")
    bridge.searchResults.emit(_payload(grouped=True))
    settle(500)
    tidal = "root.searchGroupFor('tidal')"
    apple = "root.searchGroupFor('apple')"
    grouped_ok = (
        q(tidal + ".headVisible")
        and q(apple + ".headVisible")
        and q(tidal + ".y") < q(apple + ".y")
        and q(tidal + ".modelFor('albums').count") == 1
        and q(apple + ".modelFor('albums').count") == 1
    )

    # Filtered views show a provider header only when that provider still has
    # rows under the filter: albums keeps both, tracks has none anywhere, and
    # videos belongs to TIDAL alone in this slice.
    q('filterType = "albums"')
    settle(50)
    filter_ok = q(tidal + ".headVisible") and q(apple + ".headVisible")
    q('filterType = "tracks"')
    settle(50)
    filter_ok = filter_ok and not q(tidal + ".headVisible") and not q(apple + ".headVisible")
    q('filterType = "videos"')
    settle(50)
    filter_ok = filter_ok and q(tidal + ".headVisible") and not q(apple + ".headVisible")
    q('filterType = "all"')
    settle(50)
    filter_ok = filter_ok and q(tidal + ".headVisible") and q(apple + ".headVisible")

    q(apple + ".toggleExpanded('albums')")
    expansion_ok = not q(tidal + ".isExpanded('albums')") and q(apple + ".isExpanded('albums')")
    q(apple + ".toggleExpanded('albums')")

    q("openSearch()")
    settle(200)
    blank_ok = (
        q("root.searchGroupList().length") == 0
        and q("root.searchGroupFor('apple')") is None
        and not q(apple + " ? " + apple + ".headVisible : false")
    )

    q("_searchSeq = _navSeq")
    bridge.searchResults.emit(_payload(grouped=True))
    settle(500)
    bridge.settings.data.apple_enabled = False
    bridge.appleStatusChanged.emit()
    settle(500)
    # A TIDAL-only page is the search page itself: the group head (which
    # exists to separate providers) goes with Apple, the rows stay.
    tidal_only_ok = (
        q("root.searchGroupFor('apple')") is None
        and not q(tidal + ".headVisible")
        and q(tidal + ".modelFor('albums').count") == 1
    )
    if not (grouped_ok and filter_ok and expansion_ok and blank_ok and tidal_only_ok):
        print(
            f"legs grouped={grouped_ok} filter={filter_ok} expansion={expansion_ok} blank={blank_ok} tidal_only={tidal_only_ok}",
            file=sys.stderr,
        )
    return 0 if grouped_ok and filter_ok and expansion_ok and blank_ok and tidal_only_ok else 1


@pytest.mark.qml
def test_enabled_apple_search_renders_provider_groups_and_disabled_apple_keeps_the_old_page():
    run_scenario(Path(__file__), "--run-scenario", timeout=120, sandbox_prefix="waves-apple-search-test-")


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_scenario())
