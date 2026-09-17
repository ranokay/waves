"""Regression: reopening an already-keyed browse page still records history.

THE BUG WE ARE FENCING OFF
--------------------------
``browsePageKey`` survives leaving Browse via the nav tabs. ``openBrowseItem``
treated a matching key as "already there" and returned before ``navPush()``,
so reopening that page from ANOTHER surface (a playlist inside a My Music
folder, a Home shelf card) switched to the cached page without recording
where the user came from. Back then skipped the folder entirely and fell
through to whatever sat under it in the history (Search, typically), which
is exactly how it surfaced in livetesting issue #11's folder view.

HOW THIS STAYS FIXED
--------------------
The guard now pushes a snapshot whenever Browse is not the active surface
(the cached page is still reused, nothing is re-fetched). This scenario boots
the REAL Main.qml and walks the reported flow: open a playlist page, leave it
via the My Music tab, drill into a playlist folder, reopen the same playlist,
then assert one snapshot was pushed and that Back returns to the folder.

Runs in a SUBPROCESS for the same reason as test_browse_back_scroll: building
the bridge installs process-global handlers that must not leak into the rest
of the suite.
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
    make_tidal_my_music_source,
    run_scenario,
    sandbox_qml_settings,
)


@pytest.mark.qml
def test_reopening_keyed_page_from_folder_pushes_history():
    run_scenario(
        Path(__file__),
        "--run-scenario",
        timeout=120,
        sandbox_prefix="waves-folderback-test-",
        failure_message="Back from a reopened playlist page skipped the folder again.",
    )


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

    def q(expr: str):
        ctx = QQmlEngine.contextForObject(root)
        e = QQmlExpression(ctx, root, expr)
        r = e.evaluate()
        if e.hasError():
            raise RuntimeError(e.error().toString())
        return r[0] if isinstance(r, tuple) else r

    def settle(ms: int = 120) -> None:
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    settle()
    # 1. Open a playlist page, then leave it via the My Music nav tab: the
    #    browse key stays behind, which is the bug's precondition.
    q('openPlaylistPage("p1")')
    settle()
    q("openLibrary()")
    settle()
    if q("browsePageKey") != "item:playlist:p1":
        print("precondition lost: browsePageKey did not survive the tab switch", file=sys.stderr)
        return EXIT_PRECONDITION

    # 2. Playlists -> a folder -> the SAME playlist again. My Music renders
    #    one group per live source (issue #259), so the scenario seeds the
    #    session and pins the group's visible category.
    make_tidal_my_music_source(root, q, settle, bridge)
    q('root.libGroupFor("tidal").category = "playlists"')
    q('root.libGroupFor("tidal").openFolder("f1", "Some Music")')
    settle()
    before = q("navHistory.length")
    q('openPlaylistPage("p1")')
    settle()
    pushed = q("navHistory.length") - before
    label = q("navBackLabel()")

    # 3. Back must land in the folder, not fall through the skipped snapshot.
    q("navBack()")
    settle()
    in_folder = (
        bool(q("libraryOpen"))
        and q('root.libGroupFor("tidal").currentFolder') == "f1"
        and q("libraryCategory") == "playlists"
    )

    print(f"pushed={pushed} backLabel={label!r} backInFolder={in_folder}", flush=True)
    return EXIT_OK if pushed == 1 and label == "My Music" and in_folder else EXIT_REGRESSED


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_run_scenario())
