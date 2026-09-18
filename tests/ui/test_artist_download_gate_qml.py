"""The artist page offers a discography control only where one can run (#288).

An Apple artist page used to render the same DOWNLOAD DISCOGRAPHY button as a
TIDAL one, and the click could only refuse ("Not available for Apple Music
yet", #242). The control now renders from the provider's own capability
answer (``Capability.ARTIST_DOWNLOAD``), so this scenario drives both pages:
the TIDAL one keeps the control, the Apple one shows none at all.

Runs in a subprocess like the other artist-page scenarios (building the bridge
installs process-global handlers), offscreen, with the canned ``artistLoaded``
payloads the real page would get.
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
from support.qml_probe import scene_js

_WIN_W, _WIN_H = 1100, 720

# The control is present, visible and laid out; a hidden one is neither.
_FIND_CONTROL = scene_js("""
    var hit = findObject(root, "artistDownload");
    return hit !== null && hit.visible === true && hit.width > 0;
""")


@pytest.mark.qml
def test_the_artist_page_gates_the_discography_control():
    run_scenario(
        Path(__file__),
        "--run-scenario",
        timeout=120,
        sandbox_prefix="waves-artistgate-test-",
        failure_message="the artist page's discography gate regressed",
    )


def _artist(ident: str, name: str) -> dict:
    """An artistLoaded payload, the shape the bridge emits."""

    def album(i: int) -> dict:
        return {
            "id": f"{ident}:album-{i}",
            "title": f"{name} Album {i}",
            "artist": name,
            "artist_id": ident,
            "art": "",
            "year": "2020",
            "date": "2020-01-01",
            "tracks": 10,
            "quality": "LOSSLESS",
            "popularity": 50,
        }

    def track(i: int) -> dict:
        return {
            "id": f"{ident}:track-{i}",
            "title": f"{name} Track {i}",
            "artist": name,
            "artist_id": ident,
            "album": f"{name} Album 0",
            "album_id": f"{ident}:album-0",
            "art": "",
            "year": "2020",
            "date": "2020-01-01",
            "duration": "3:20",
            "quality": "LOSSLESS",
            "popularity": 50,
        }

    return {
        "id": ident,
        "name": name,
        "art": "",
        "bio": f"About {name}.",
        "albums": [album(i) for i in range(2)],
        "eps": [],
        "tracks": [track(i) for i in range(2)],
        "videos": [],
    }


def _run_scenario() -> int:  # noqa: C901 (one straight scenario)
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
        from support.offline import PARK_LOGIN_QML, patch_offline

        patch_offline()
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

    def settle(ms: int = 300) -> None:
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    settle(3000)
    q(PARK_LOGIN_QML)
    q("openSearch()")
    settle()

    problems: list[str] = []

    # The verdicts the page's binding reads: TIDAL answers an artist sweep,
    # Apple does not.
    if not bool(q('waves.artistDownloadSupported("artist-1")')):
        problems.append("a TIDAL artist was not offered the discography verb")
    if bool(q('waves.artistDownloadSupported("apple:artist-1")')):
        problems.append("an Apple artist was offered the discography verb")

    # A TIDAL artist page: the control is rendered and visible.
    bridge.artistLoaded.emit(_artist("artist-1", "Tidal Artist"))
    settle()
    if not q("artistOpen") or q("artistData.name") != "Tidal Artist":
        problems.append("the TIDAL artist page never rendered")
    elif not bool(q(_FIND_CONTROL)):
        problems.append("the TIDAL artist page lost its discography control")

    # An Apple artist page: the page renders, the control does not exist.
    bridge.artistLoaded.emit(_artist("apple:artist-1", "Apple Artist"))
    settle()
    if not q("artistOpen") or q("artistData.name") != "Apple Artist":
        problems.append("the Apple artist page never rendered")
    elif bool(q(_FIND_CONTROL)):
        problems.append("the Apple artist page still offers a discography control")

    for problem in problems:
        print(problem, file=sys.stderr)
    return EXIT_REGRESSED if problems else EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_run_scenario())
