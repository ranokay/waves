"""Apple and TIDAL answer one unified search page as two sources.

WHAT THIS FENCES OFF
--------------------
The search page used to render one provider group per provider, with a head
per group and per-group folds. The unified surface folds every provider's
rows into single sections and lists the sources that took part in
``root.searchSources``: both sources render their rows, the type chips
filter the sections, a second Search press clears the whole page, and a
source switched off leaves both the source list and its rows.

This drives the bridge's real fan-out with both providers stubbed, so the
payload is composed exactly as the worker composes it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from support.paths import QML_MAIN
from support.qml import (
    EXIT_OK,
    EXIT_PRECONDITION,
    EXIT_REGRESSED,
    run_scenario,
    sandbox_qml_settings,
)


class _TidalAlbum:
    id = "tidal-al1"
    name = "Tidal Album"


class _TidalVideo:
    id = "tidal-vd1"
    name = "Tidal Video"
    artists = ()


_TIDAL_ALBUM_ROW = {
    "title": "Tidal Album",
    "artist": "Tidal Artist",
    "artist_id": "",
    "artists": [],
    "art": "",
    "year": "2026",
    "date": "2026-01-01",
    "listed": "",
    "tracks": 3,
    "duration_sec": 900,
    "quality": "LOSSLESS",
    "popularity": -1,
    "explicit": False,
    "added": "",
}

_TIDAL_VIDEO_ROW = {
    "title": "Tidal Video",
    "artist": "Tidal Artist",
    "art": "",
    "art_big": "",
    "duration": "5:10",
    "explicit": False,
    "added": "",
    "date": "2018-08-07",
    "quality": "1080p",
}

_APPLE_ALBUM_ROW = {
    "id": "apple-al1",
    "title": "Apple Album",
    "artist": "Apple Artist",
    "artist_id": "apple-ar1",
    "artists": [],
    "art": "",
    "year": "2026",
    "date": "2026-01-01",
    "tracks": 2,
    "duration_sec": 600,
    "quality": "LOSSLESS",
    "popularity": -1,
    "explicit": False,
    "added": "",
}


def _settle_until(q, settle, predicate, *, timeout_ms: int = 5000, step_ms: int = 20) -> bool:
    waited = 0
    while not predicate():
        if waited >= timeout_ms:
            return False
        settle(step_ms)
        waited += max(step_ms, 1)
    return True


def _sources(q) -> str:
    return q("(root.searchSources || []).map(function (s) { return s.provider }).join(',')")


def _album_ids(q) -> list:
    model = "searchResultsView.modelFor('albums')"
    return [q(f"{model}.get({i}).id") for i in range(int(q(f"{model}.count")))]


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

    # Both provider gates open: TIDAL's session flag and Apple's switch. The
    # replies are stubbed at the providers (TIDAL's engine objects through
    # the bridge's own row builders, Apple's dicts as its provider answers).
    bridge._logged_in = True
    bridge.loggedInChanged.emit()
    bridge.settings.data.apple_enabled = True
    bridge.appleStatusChanged.emit()
    settle(300)

    bridge.providers["tidal"].search = lambda needle: {
        "albums": [_TidalAlbum()],
        "videos": [_TidalVideo()],
        "top_hit": None,
    }
    bridge._album_dict = lambda album: dict(_TIDAL_ALBUM_ROW, id=str(album.id), title=str(album.name))
    bridge._video_dict = lambda video: dict(_TIDAL_VIDEO_ROW, id=str(video.id), title=str(video.name))
    bridge.providers["apple"].search = lambda needle: {
        "artists": [],
        "albums": [dict(_APPLE_ALBUM_ROW)],
        "tracks": [],
        "playlists": [],
        "mixes": [],
        "top": None,
    }

    q("root.submitSearch('groups')")
    landed = _settle_until(q, settle, lambda: _sources(q) == "tidal,apple" and len(_album_ids(q)) == 2)
    if not landed:
        print(f"the two sources never landed ({_sources(q)}, albums={_album_ids(q)})", file=sys.stderr)
        return EXIT_PRECONDITION

    # Both sources are listed in registry order, their rows share the unified
    # sections, and each row carries its own source.
    grouped_ok = (
        q("root.sourceMarksOn")
        and len(_album_ids(q)) == 2
        and q("searchResultsView.countFor('videos')") == 1
        and json.loads(q("JSON.stringify(searchResultsView.rowSources('tidal-al1'))"))
        == [{"provider": "tidal", "id": "tidal-al1"}]
        and json.loads(q("JSON.stringify(searchResultsView.rowSources('apple-al1'))"))
        == [{"provider": "apple", "id": "apple-al1"}]
    )

    # Filtered views show only the sections that still have rows: albums
    # keeps both sources' rows, tracks has none anywhere, and videos belongs
    # to TIDAL alone in this slice.
    q('filterType = "albums"')
    settle(50)
    filter_ok = (
        q("searchResultsView.sectionVisible('albums')")
        and not q("searchResultsView.sectionVisible('videos')")
        and q("root.filteredResultCount") == 2
    )
    q('filterType = "tracks"')
    settle(50)
    filter_ok = (
        filter_ok
        and not q("searchResultsView.sectionVisible('albums')")
        and not q("searchResultsView.sectionVisible('videos')")
        and q("root.filteredResultCount") == 0
    )
    q('filterType = "videos"')
    settle(50)
    filter_ok = (
        filter_ok
        and q("searchResultsView.sectionVisible('videos')")
        and not q("searchResultsView.sectionVisible('albums')")
        and q("root.filteredResultCount") == 1
    )
    q('filterType = "all"')
    settle(50)
    filter_ok = (
        filter_ok
        and q("searchResultsView.sectionVisible('albums')")
        and q("searchResultsView.sectionVisible('videos')")
    )

    # A second Search press is the blank page: the sections and the sources
    # of the query being cleared go with it.
    q("openSearch()")
    settle(200)
    blank_ok = (
        q("root.searchSources.length") == 0
        and q("Object.keys(root.searchSections).length") == 0
        and not q("root.hasResults")
        and int(q("searchResultsView.countFor('albums')")) == 0
    )

    # Repaint the page (the identical query is served from the bridge's short
    # cache), then switch Apple off: its source and its rows leave the page
    # while TIDAL's stay.
    q("root.submitSearch('groups')")
    if not _settle_until(q, settle, lambda: _sources(q) == "tidal,apple" and len(_album_ids(q)) == 2):
        print("the page did not repaint before the Apple switch-off", file=sys.stderr)
        return EXIT_PRECONDITION
    bridge.settings.data.apple_enabled = False
    bridge.appleStatusChanged.emit()
    bridge.providerStateChanged.emit("apple")
    settle(300)
    tidal_only_ok = (
        not q("root.sourceMarksOn")
        and _sources(q) == "tidal"
        and _album_ids(q) == ["tidal-al1"]
        and q("searchResultsView.countFor('videos')") == 1
    )

    if not (grouped_ok and filter_ok and blank_ok and tidal_only_ok):
        print(
            f"legs grouped={grouped_ok} filter={filter_ok} blank={blank_ok} tidal_only={tidal_only_ok}",
            file=sys.stderr,
        )
    return EXIT_OK if grouped_ok and filter_ok and blank_ok and tidal_only_ok else EXIT_REGRESSED


@pytest.mark.qml
def test_unified_search_lists_both_sources_and_disabled_apple_drops_its_rows():
    run_scenario(Path(__file__), "--run-scenario", timeout=120, sandbox_prefix="waves-apple-search-test-")


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_scenario())
