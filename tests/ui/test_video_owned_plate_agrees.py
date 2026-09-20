"""A video cell's owned plate agrees with its DownloadButton.

WHAT THIS FENCES OFF
--------------------
One verdict per cell: VideoCell binds the plate from its own
DownloadButton, so the plate shows the button's answer and words itself
from the same record.

Runs in a SUBPROCESS like the other Main.qml scenarios: building the bridge
installs process-global handlers that must not leak into the suite.
"""

from __future__ import annotations

import json
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
    seed_tidal_search,
)

_VIDEO = (
    '{"id":"v1","title":"Let The Good Times Roll","artist":"Electric Callboy","artists":[],'
    '"art":"","art_big":"","duration":"3:37","explicit":false,"added":"",'
    '"date":"2026-06-06","quality":"1080p"}'
)


@pytest.mark.qml
def test_video_owned_plate_agrees_with_its_button():
    run_scenario(
        Path(__file__),
        "--run-scenario",
        timeout=180,
        sandbox_prefix="waves-video-plate-test-",
        failure_message="the video cell's owned plate disagrees with its DownloadButton again",
    )


def _run_scenario() -> int:  # noqa: C901 (one straight scenario)
    try:
        from PySide6.QtCore import QEventLoop, QTimer, QUrl
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtQml import QQmlApplicationEngine, QQmlEngine, QQmlExpression
        from PySide6.QtQuick import QQuickWindow
    except Exception as exc:  # pragma: no cover - environment guard
        print(f"Qt unavailable: {exc}", file=sys.stderr)
        return EXIT_NO_QT

    app = QGuiApplication.instance() or QGuiApplication([])
    sandbox_qml_settings()
    try:
        from waves.desktop.app import _load_mono
        from waves.desktop.backend import WavesBridge
    except Exception as exc:  # pragma: no cover - environment guard
        print(f"Qt platform/backend unavailable: {exc}", file=sys.stderr)
        return EXIT_NO_QT

    from support.offline import PARK_LOGIN_QML, patch_offline

    patch_offline()  # BEFORE the bridge: its __init__ fires the sign-in check
    bridge = WavesBridge(tidal=None)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("waves", bridge)
    engine.rootContext().setContextProperty("monoFont", _load_mono())
    engine.rootContext().setContextProperty("uiFontFamily", app.font().family())
    engine.load(QUrl.fromLocalFile(str(QML_MAIN)))
    roots = engine.rootObjects()
    if not roots:
        print("Main.qml failed to load", file=sys.stderr)
        return EXIT_PRECONDITION
    root = roots[0]
    if not isinstance(root, QQuickWindow):
        print("root object is not a window", file=sys.stderr)
        return EXIT_PRECONDITION

    def q(expr: str):
        r = QQmlExpression(QQmlEngine.contextForObject(root), root, expr).evaluate()
        return r[0] if isinstance(r, tuple) else r

    def settle(ms: int = 120) -> None:
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    root.resize(1280, 900)
    root.show()
    settle(400)
    q("bootOverlay.done = true")
    q("bootContentShown = 1")
    q(PARK_LOGIN_QML)
    q("root.openSearch()")
    seed_tidal_search(q, bridge, videos=[json.loads(_VIDEO)], expanded=("videos",))
    q("root.searchReveal = 1")
    q("root.searchBuilding = false")
    settle(700)

    # The first video cell: [BigVideoThumb, meta Item]; the meta Item is
    # [meta Column, DownloadButton]. The thumb is found by its videoId, the
    # button by its mediaId, so the walk survives layout moves.
    _FIND = (
        "var grid = root.searchGroupFor('tidal').videoGridItem;"
        "var thumb = null, dl = null;"
        "for (var i = 0; i < grid.children.length; i++) {"
        " var cell = grid.children[i];"
        " if (!cell || !cell.item) continue;"
        " var t = cell.item.children[0];"
        " if (!t || t.videoId === undefined || t.videoId !== 'v1') continue;"
        " var meta = cell.item.children[1];"
        " if (!meta || meta.children.length < 2) continue;"
        " var b = meta.children[1];"
        " if (!b || b.mediaId === undefined || b.mediaId !== 'v1') continue;"
        " thumb = t; dl = b; break;"
        "}"
    )

    def have_cell() -> bool:
        return str(q("(function(){" + _FIND + " return thumb && dl ? 'yes' : 'no';})()")) == "yes"

    found = False
    for _ in range(40):
        if have_cell():
            found = True
            break
        settle(100)
    if not found:
        print("could not locate the video cell's thumb and button", file=sys.stderr)
        return EXIT_PRECONDITION

    def get(expr: str) -> str:
        return str(q("(function(){" + _FIND + " return " + expr + ";})()"))

    def plate_text() -> str:
        return get(
            "(function(){ function ft(it){ if (!it) return null;"
            " if (it.objectName === 'bvtOwnText') return it;"
            " for (var i = 0; i < it.children.length; i++) {"
            "  var hit = ft(it.children[i].item || it.children[i]);"
            "  if (hit) return hit; } return null; }"
            " var t = ft(thumb); return t ? t.text : 'missing'; })()"
        )

    def button_face() -> str:
        return get(
            "(function(){ function ft(it){ if (!it) return null;"
            " if (it.objectName === 'dbFaceText') return it;"
            " for (var i = 0; i < it.children.length; i++) {"
            "  var hit = ft(it.children[i].item || it.children[i]);"
            "  if (hit) return hit; } return null; }"
            " var t = ft(dl); return t ? t.text : 'missing'; })()"
        )

    verdicts: dict[str, bool] = {}

    # The plate follows the button without its own query: setting the
    # button's verdict moves the plate, which a second independent
    # ownershipOf reduction would not do.
    q("(function(){" + _FIND + " dl.owned = false; dl.ownInLibrary = false; })()")
    settle(80)
    verdicts["plate_starts_hidden_with_a_live_button"] = (
        get("'' + thumb.owned") == "false"
        and get("'' + dl.owned") == "false"
        and get("dl.st === '' ? 'live' : dl.st") == "live"
    )

    q("(function(){" + _FIND + " dl.owned = true; dl.ownInLibrary = false; })()")
    settle(80)
    verdicts["plate_follows_the_button_verdict"] = get("'' + thumb.owned") == "true"

    # The wording follows the recorded copy, not the download folder: a
    # copy outside the library reads DOWNLOADED even while downloads now
    # land inside it, and IN LIBRARY once the copy itself is inside.
    q("root.libraryOn = true")
    q("root.dlInLibrary = true")
    q("(function(){" + _FIND + " dl.owned = true; dl.ownInLibrary = false; })()")
    settle(80)
    verdicts["outside_copy_reads_downloaded_on_both"] = (
        plate_text() == "DOWNLOADED" and button_face() == "VIDEO DOWNLOADED"
    )

    q("(function(){" + _FIND + " dl.ownInLibrary = true; })()")
    settle(80)
    verdicts["inside_copy_reads_in_library_on_both"] = (
        get("'' + thumb.ownInLibrary") == "true"
        and plate_text() == "IN LIBRARY"
        and button_face() == "VIDEO IN LIBRARY"
    )

    # The globals disagreeing with the record must not split the cell:
    # downloads landing outside still read IN LIBRARY for an inside copy,
    # and downloads landing inside still read DOWNLOADED for an outside one.
    q("root.dlInLibrary = false")
    settle(80)
    verdicts["record_wins_over_the_download_folder_outside"] = (
        plate_text() == "IN LIBRARY" and button_face() == "VIDEO IN LIBRARY"
    )

    q("(function(){" + _FIND + " dl.ownInLibrary = false; })()")
    q("root.dlInLibrary = true")
    settle(80)
    verdicts["record_wins_over_the_download_folder_inside"] = (
        plate_text() == "DOWNLOADED" and button_face() == "VIDEO DOWNLOADED"
    )

    # Not owned: the plate hides and the button goes live again (the stale
    # `owned && !up_to_date` shape settles the button to DOWNLOAD, and the
    # plate must not linger as DOWNLOADED over it).
    q("(function(){" + _FIND + " dl.owned = false; })()")
    settle(80)
    verdicts["unowned_hides_the_plate_and_livens_the_button"] = (
        get("'' + thumb.owned") == "false" and get("dl.st === '' ? 'live' : dl.st") == "live"
    )

    print(f"verdicts={verdicts} plate={plate_text()} face={button_face()}", flush=True)
    return EXIT_OK if all(verdicts.values()) else EXIT_REGRESSED


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_run_scenario())
