"""Playlist-folder drill-in (issue #11): the QML state machine end to end.

Boots the REAL Main.qml with the real bridge (no login) and drives the folder
navigation through the same signals the backend uses:

* folder rows land in the playlists list (kind role present),
* openPlFolder shows the folder view (root list hidden, state intact) and
  fills it from playlistFolderLoaded,
* a stale playlistFolderLoaded (another folder's answer) is dropped,
* the breadcrumb pops back to the root list,
* folderRemaining updates the badge map, and the folder button's live state
  flows through the ordinary downloadState channel.

Runs in a SUBPROCESS for the same reason as test_browse_back_scroll.py: the
bridge installs process-global handlers.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from support.paths import QML_MAIN
from support.qml import (
    EXIT_NO_QT,
    EXIT_OK,
    EXIT_PRECONDITION,
    EXIT_REGRESSED,
    run_scenario,
    sandbox_qml_settings,
)

_WIN_W, _WIN_H = 1100, 720


@pytest.mark.qml
def test_playlist_folder_drill_in_and_badge_state():
    run_scenario(
        Path(__file__),
        "--run-scenario",
        timeout=120,
        sandbox_prefix="waves-folderqml-test-",
        failure_message="folder drill-in scenario failed",
    )


def _rows_root() -> list:
    folder = {
        "id": "f1",
        "title": "Country",
        "art": "",
        "tracks": 0,
        "creator": "",
        "added": "",
        "kind": "folder",
        "sub": "1 folder · 1 playlist",
        "path": "Country",
        "plCount": 3,
    }
    playlist = {
        "id": "p9",
        "title": "Root Playlist",
        "art": "",
        "tracks": 12,
        "creator": "me",
        "added": "",
        "kind": "playlist",
        "sub": "",
        "path": "",
        "plCount": 0,
    }
    return [folder, playlist]


def _rows_folder() -> list:
    return [
        {
            "id": "p1",
            "title": "Road Songs",
            "art": "",
            "tracks": 9,
            "creator": "me",
            "added": "",
            "kind": "playlist",
            "sub": "",
            "path": "",
            "plCount": 0,
        }
    ]


def _run_scenario() -> int:
    try:
        from PySide6.QtCore import QEventLoop, QTimer, QUrl
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtQml import QQmlApplicationEngine, QQmlEngine, QQmlExpression
    except Exception as exc:
        print(f"Qt unavailable: {exc}", file=sys.stderr)
        return EXIT_NO_QT

    app = QGuiApplication.instance() or QGuiApplication([])
    sandbox_qml_settings()
    try:
        from waves.waves_ui.app import _load_mono
        from waves.waves_ui.backend import WavesBridge
    except Exception as exc:
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
    root.setProperty("width", _WIN_W)
    root.setProperty("height", _WIN_H)

    def q(expr: str):
        ctx = QQmlEngine.contextForObject(root)
        e = QQmlExpression(ctx, root, expr)
        r = e.evaluate()
        if e.hasError():
            raise RuntimeError(e.error().toString())
        return r[0] if isinstance(r, tuple) else r

    def settle(ms: int = 150) -> None:
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def fail(msg: str) -> int:
        print(msg, file=sys.stderr)
        return EXIT_REGRESSED

    # 1. Land on the playlists tab with a folder row + a playlist row.
    root.setProperty("libraryOpen", True)
    root.setProperty("libraryCategory", "playlists")
    bridge.libraryLoaded.emit("playlists", _rows_root(), False)
    settle()
    if q("libPlaylistsModel.count") != 2:
        return fail("root rows did not land")
    if q("libPlaylistsModel.get(0).kind") != "folder" or q("libPlaylistsModel.get(0).plCount") != 3:
        return fail("folder row lost its kind/plCount roles")
    if not q("libPlaylistsList.visible"):
        return fail("root list should be visible before drill-in")

    # 2. Drill in; the folder's rows arrive under its id.
    q('openPlFolder("f1", "Country")')
    bridge.playlistFolderLoaded.emit("f1", _rows_folder(), "Country")
    settle()
    if q("plCurrentFolder") != "f1" or q("plFolderStack.length") != 1:
        return fail("drill-in did not push the stack")
    if q("libPlaylistsList.visible"):
        return fail("root list still visible while drilled in")
    if q("libFolderModel.count") != 1 or q("libFolderModel.get(0).id") != "p1":
        return fail("folder rows did not fill the folder model")

    # 3. A stale answer for a folder the user is no longer in must be dropped.
    bridge.playlistFolderLoaded.emit("f2", [], "Elsewhere")
    settle(50)
    if q("libFolderModel.count") != 1:
        return fail("stale playlistFolderLoaded wiped the open folder")

    # 4. Badge plumbing: countdown map + live state under the folder id.
    bridge.folderRemaining.emit("f1", 2, 3)
    bridge.downloadState.emit("f1", "running")
    settle(50)
    if q('folderRemainMap["f1"]') != 2:
        return fail("folderRemaining did not update the badge map")
    if q('dlSt("f1")') != "running":
        return fail("folder state did not flow through downloadState")

    # 5. Crumb back to the root list: state intact, folder view gone.
    q("plCrumbTo(-1)")
    settle(50)
    if q("plFolderStack.length") != 0 or q("plCurrentFolder") != "":
        return fail("crumb-to-root did not clear the stack")
    if not q("libPlaylistsList.visible"):
        return fail("root list did not come back")
    if q("libPlaylistsModel.count") != 2:
        return fail("root rows were lost while drilled in")

    print("folder drill-in scenario ok", flush=True)
    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_run_scenario())
