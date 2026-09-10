"""Realtime logs console (issue #68): bottom-bar button, live tail, filter,
follow, copy, export.

Offscreen scenario against the real bridge and the real log file: log
records written through the logging tree show up in the drawer, the level
filter narrows them, copy lands on the clipboard, and export produces a
bundle on disk.
"""

from __future__ import annotations

import json
import logging
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
        from waves.waves_ui import diagnostics
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
    diagnostics.flush_disk_log()
    q("logsDrawer.logsRefresh()")
    settle(100)
    stream_ok = "console-marker-error-1" in q("logsText.text")

    # The level filter narrows to errors; INFO needs verbose on disk.
    diagnostics.set_verbose(True)
    log.info("console-marker-info-1")
    log.error("console-marker-error-2")
    diagnostics.flush_disk_log()
    q("logsDrawer.logsRefresh()")
    settle(100)
    both_ok = "console-marker-info-1" in q("logsText.text") and "console-marker-error-2" in q("logsText.text")
    q("logsDrawer.logsMinLevel = 2")
    settle(100)
    filter_ok = both_ok and "console-marker-error-2" in q("logsText.text")
    filter_ok = filter_ok and "console-marker-info-1" not in q("logsText.text")
    q("logsDrawer.logsMinLevel = 0")
    settle(100)

    # Filter chips still filter rows independently of the fold: with Apple
    # collapsed, the albums chip keeps both heads (both have albums) while
    # Apple's rows stay hidden.
    q("openSearch()")
    settle()
    q("_searchSeq = _navSeq")
    bridge.searchResults.emit(_payload())
    settle(500)
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

    # Follow sticks to the bottom; a manual scroll up takes over.
    for i in range(200):
        log.error(f"console-flood-{i:03d}")
    diagnostics.flush_disk_log()
    q("logsDrawer.logsRefresh()")
    settle(200)
    follow_ok = q("logsFlick.contentY") > 0
    q("logsFlick.contentY = 0")
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

    # The fold reached the persisted prefs and the file on disk...
    q("toggleSearchProviderGroup(true)")
    settle(50)
    bridge._config_writer.flush()
    settle(100)
    with open(bridge._waves_prefs_path, encoding="utf-8") as handle:
        stored = json.load(handle)
    prefs_ok = (
        bridge._waves_prefs.get("search_provider_apple_collapsed")
        and stored.get("search_provider_apple_collapsed")
        and not stored.get("search_provider_tidal_collapsed")
    )

    # ...so a fresh root starts with Apple still collapsed (the restart read).
    engine.load(QUrl.fromLocalFile(str(QML_MAIN)))
    settle(300)
    roots = engine.rootObjects()
    restart_ok = len(roots) == 2 and q("appleSearchGroupCollapsed", roots[1])
    restart_ok = restart_ok and not q("tidalSearchGroupCollapsed", roots[1])

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


def test_logs_console_streams_filters_and_exports():
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="waves-logs-console-test-")
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--run-scenario"],
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if proc.returncode == _EXIT_NO_QT:
        pytest.skip("PySide6 / offscreen Qt unavailable")
    if proc.returncode == _EXIT_PRECONDITION:
        pytest.skip("could not load Main.qml in this environment")
    assert proc.returncode == 0, proc.stdout + proc.stderr


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_scenario())
