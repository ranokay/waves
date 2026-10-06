"""Realtime logs console: bottom-bar button, live tail, filter,
follow, copy, export.

Offscreen scenario against the real bridge and the real log file: log
records written through the logging tree show up in the drawer, the level
filter narrows them, copy lands on the clipboard, and export produces a
bundle on disk.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pytest
from support.paths import QML_MAIN
from support.qml import run_scenario, scoped_q

# The heaviest QML boot: excluded from the quick QML pass.
pytestmark = pytest.mark.slow


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
    """Two sources in one unified page: TIDAL and Apple each answer one
    album and one track."""
    from search.fakes import qml_search_payload

    tidal = qml_search_payload(provider="tidal", albums=[_album("tidal:1")], tracks=[_track("tidal:2")])
    apple = qml_search_payload(provider="apple", albums=[_album("apple:1")], tracks=[_track("apple:2")])
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
    from waves.desktop.diagnostics import export as diagnostics

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

    # The log view and its follow-scroll live inside LogsDrawer.qml;
    # evaluate their expressions in that file's own scope.
    qd = scoped_q(q, "logsDrawer.background")

    settle()
    q(PARK_LOGIN_QML)
    settle()

    # The bottom-bar button is up, labelled, and clickable where it reads;
    # its handler opens the drawer (synthetic clicks do not deliver
    # offscreen, so the hit area is asserted geometrically instead).
    button_ok = q("logsBtn.visible") and q("logsBtn.text") == "LOGS"
    button_ok = (
        button_ok
        and q("logsBtnMa.enabled")
        and q("logsBtnMa.contains(Qt.point(logsBtn.width / 2, logsBtn.height / 2))")
    )
    q("logsDrawer.open()")
    settle(700)
    button_ok = button_ok and q("logsDrawer.opened")

    # Records written through the logging tree stream into the view.
    log = logging.getLogger("waves.test-console")
    log.error("console-marker-error-1")
    diagnostics.wait_for_disk_log()
    q("logsDrawer.logsRefresh()")
    settle(100)
    stream_ok = "console-marker-error-1" in qd("logsText.text")

    # The level filter narrows to errors; INFO needs verbose on disk.
    diagnostics.set_verbose(True)
    log.info("console-marker-info-1")
    log.error("console-marker-error-2")
    diagnostics.wait_for_disk_log()
    q("logsDrawer.logsRefresh()")
    settle(100)
    both_ok = "console-marker-info-1" in qd("logsText.text") and "console-marker-error-2" in qd("logsText.text")
    q("logsDrawer.logsMinLevel = 2")
    settle(100)
    filter_ok = both_ok and "console-marker-error-2" in qd("logsText.text")
    filter_ok = filter_ok and "console-marker-info-1" not in qd("logsText.text")
    q("logsDrawer.logsMinLevel = 0")
    settle(100)

    # The type chips keep filtering rows independently of a section's SHOW
    # ALL state, on the unified page beside the logs drawer.
    q("openSearch()")
    settle()
    q("_searchSeq = _navSeq")
    bridge.searchResults.emit(_payload())
    settle(500)
    q("searchResultsView.toggleExpanded('tracks')")
    settle(50)
    q('filterType = "albums"')
    settle(50)
    chips_ok = (
        q("searchResultsView.sectionVisible('albums')")
        and not q("searchResultsView.sectionVisible('tracks')")
        and q("root.filteredResultCount") == 2
    )
    q('filterType = "all"')
    settle(50)
    chips_ok = (
        chips_ok and q("searchResultsView.sectionVisible('tracks')") and q("searchResultsView.isExpanded('tracks')")
    )
    q("searchResultsView.toggleExpanded('tracks')")
    settle(50)

    # Follow sticks to the bottom; a manual scroll up takes over.
    for i in range(200):
        log.error(f"console-flood-{i:03d}")
    diagnostics.wait_for_disk_log()
    q("logsDrawer.logsRefresh()")
    settle(200)
    follow_ok = qd("logsFlick.contentY") > 0
    qd("logsFlick.contentY = 0")
    settle(100)
    follow_ok = follow_ok and not q("logsDrawer.logsFollow")
    q("logsDrawer.logsFollow = true")
    settle(100)

    # Copy lands the tail on the clipboard and says so.
    q("waves.copyLogs()")
    settle(100)
    try:
        clipped = QGuiApplication.clipboard().text()
    except Exception:
        clipped = ""
    copy_ok = "console-marker-error-2" in clipped and q("waves.status") == "Logs copied"

    # Export produces a bundle on disk and the drawer reports it.
    q("waves.exportDiagnostics()")
    settle(5000)
    export_path = q("logsDrawer.logsExportPath")
    export_ok = (
        not q("logsDrawer.logsExportBusy")
        and isinstance(export_path, str)
        and bool(export_path)
        and Path(export_path).is_file()
    )

    q("logsDrawer.close()")
    settle(500)
    close_ok = not q("logsDrawer.opened")
    diagnostics.set_verbose(False)

    # The section's SHOW ALL state reached the persisted prefs and the file
    # on disk...
    q("searchResultsView.toggleExpanded('tracks')")
    settle(50)
    bridge._config_writer.flush()
    settle(100)
    with open(bridge._waves_prefs_path, encoding="utf-8") as handle:
        stored = json.load(handle)
    prefs_ok = (
        bridge._waves_prefs.get("search_section_tracks_expanded")
        and stored.get("search_section_tracks_expanded")
        and not stored.get("search_section_albums_expanded")
    )

    # ...so a fresh root starts with the section still expanded (the restart
    # read).
    engine.load(QUrl.fromLocalFile(str(QML_MAIN)))
    settle(300)
    roots = engine.rootObjects()
    second = roots[1]
    q("openSearch()", second)
    q("_searchSeq = _navSeq", second)
    bridge.searchResults.emit(_payload())
    settle(500)
    restart_ok = len(roots) == 2 and q("searchResultsView.isExpanded('tracks')", second)

    ok = (
        button_ok
        and stream_ok
        and filter_ok
        and chips_ok
        and follow_ok
        and copy_ok
        and export_ok
        and close_ok
        and prefs_ok
        and restart_ok
    )
    return 0 if ok else 1


@pytest.mark.qml
def test_logs_console_streams_filters_and_exports():
    run_scenario(Path(__file__), "--run-scenario", timeout=180, sandbox_prefix="waves-logs-console-test-")


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_scenario())
