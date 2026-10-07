"""Search sections expand and persist; the source filter narrows rows.

The unified surface keeps one SHOW ALL state per section (pref-backed, so it
survives a restart) and one source chip row (All default, one per provider
that answered). Choosing a source narrows the sections and the counts to
that provider's rows; the type chips keep filtering kinds independently.
The old per-provider folds retired with the grouped page.
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
    """Two sources in one page: TIDAL answers six tracks, Apple four rows."""
    from search.fakes import qml_search_payload

    tidal = qml_search_payload(
        provider="tidal",
        albums=[_album("tidal:1")],
        tracks=[_track(f"tidal:t{i}") for i in range(6)],
    )
    apple = qml_search_payload(
        provider="apple",
        albums=[_album("apple:1")],
        tracks=[_track("apple:t1")],
    )
    return {
        "sources": [*tidal["sources"], *apple["sources"]],
        "sections": {
            **tidal["sections"],
            **{name: [*tidal["sections"].get(name, []), *rows] for name, rows in apple["sections"].items()},
        },
        "top": None,
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

    # Both sources start listed and every section shows its rows.
    q("_searchSeq = _navSeq")
    bridge.searchResults.emit(_payload())
    settle(500)
    landed_ok = (
        q("(root.searchSources || []).map(function (s) { return s.provider }).join(',')") == "tidal,apple"
        and q("root.sourceMarksOn") is True
        and q("searchResultsView.countFor('albums')") == 2
        and q("searchResultsView.countFor('tracks')") == 7
        and q("searchResultsView.sectionVisible('albums')")
        and q("searchResultsView.sectionVisible('tracks')")
        and not q("searchBuilding")
    )

    # The type chips keep filtering kinds on their own.
    q('filterType = "albums"')
    settle(50)
    chips_ok = (
        q("searchResultsView.sectionVisible('albums')")
        and not q("searchResultsView.sectionVisible('tracks')")
        and q("root.filteredResultCount") == 2
    )
    q('filterType = "all"')
    settle(50)

    # The source chip narrows the sections and the counts to that provider's
    # rows: Apple has one album and one track here. The choice is
    # remember-last, so it is written to the prefs and survives a restart.
    q('root.searchSourceFilter = "apple"')
    settle(50)
    source_ok = (
        q("root.filteredResultCount") == 2
        and q("searchResultsView.sectionVisible('albums')")
        and q("searchResultsView.sectionVisible('tracks')")
        and not q("searchResultsView.sectionVisible('artists')")
    )
    bridge._config_writer.flush()
    settle(100)
    with open(bridge._waves_prefs_path, encoding="utf-8") as handle:
        filter_stored = json.load(handle)
    remember_ok = (
        bridge._waves_prefs.get("search_source_filter") == "apple"
        and filter_stored.get("search_source_filter") == "apple"
    )
    q('root.searchSourceFilter = "all"')
    settle(50)
    restored_ok = q("root.filteredResultCount") == 9 and q("searchResultsView.sectionVisible('tracks')")

    # SHOW ALL: the tracks section is capped at five until expanded, and the
    # state is pref-backed.
    capped_ok = not q("searchResultsView.isExpanded('tracks')") and q("searchResultsView.countFor('tracks')") == 7
    q("searchResultsView.toggleExpanded('tracks')")
    settle(100)
    bridge._config_writer.flush()
    settle(100)
    with open(bridge._waves_prefs_path, encoding="utf-8") as handle:
        stored = json.load(handle)
    prefs_ok = (
        q("searchResultsView.isExpanded('tracks')")
        and bridge._waves_prefs.get("search_section_tracks_expanded")
        and stored.get("search_section_tracks_expanded")
        and not stored.get("search_section_albums_expanded")
    )

    # A fresh search resets the lifted source map: an id the new payload does
    # not carry cannot keep the previous page's marks or source-filter match.
    from search.fakes import qml_search_payload

    q("_searchSeq = _navSeq")
    bridge.searchResults.emit(qml_search_payload(provider="tidal", albums=[_album("tidal:1")]))
    settle(400)
    stale_ok = (
        q("searchResultsView.rowSources('apple:1').length") == 0
        and q("root.rowSourcesById['apple:1'] === undefined") is True
        and q("searchResultsView.countFor('albums')") == 1
    )

    # ...so a fresh root starts with the section still expanded (the restart
    # read) and the last source filter remembered while its provider is in
    # the search; a payload without that provider falls back to All.
    q('root.searchSourceFilter = "apple"')
    bridge._config_writer.flush()
    settle(100)
    engine.load(QUrl.fromLocalFile(str(QML_MAIN)))
    settle(300)
    roots = engine.rootObjects()
    second = roots[1]
    q("openSearch()", second)
    q("_searchSeq = _navSeq", second)
    bridge.searchResults.emit(_payload())
    settle(500)
    restart_ok = (
        len(roots) == 2
        and q("searchResultsView.isExpanded('tracks')", second)
        and q("root.searchSourceFilter", second) == "apple"
    )
    q("_searchSeq = _navSeq", second)
    bridge.searchResults.emit(qml_search_payload(provider="tidal", albums=[_album("tidal:1")]))
    settle(400)
    bridge._config_writer.flush()
    settle(100)
    with open(bridge._waves_prefs_path, encoding="utf-8") as handle:
        filter_stored = json.load(handle)
    fallback_ok = q("root.searchSourceFilter", second) == "all" and filter_stored.get("search_source_filter") == "all"

    ok = landed_ok and chips_ok and source_ok and restored_ok and remember_ok and capped_ok and prefs_ok and stale_ok
    return 0 if ok and restart_ok and fallback_ok else 1


@pytest.mark.qml
def test_search_sections_expand_and_the_source_filter_narrows():
    run_scenario(Path(__file__), "--run-scenario", timeout=120, sandbox_prefix="waves-search-sections-test-")


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_scenario())
