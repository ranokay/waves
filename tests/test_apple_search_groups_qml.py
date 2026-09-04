from __future__ import annotations

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


def _payload(grouped: bool) -> dict:
    payload = {
        "artists": [],
        "albums": [_album("tidal:1")],
        "tracks": [],
        "videos": [],
        "playlists": [],
        "mixes": [],
        "top": None,
    }
    if grouped:
        payload["apple"] = {
            "artists": [],
            "albums": [_album("apple:1")],
            "tracks": [],
            "videos": [],
            "playlists": [],
            "mixes": [],
            "top": None,
        }
    return payload


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
    grouped_ok = (
        q("tidalGroupHead.visible")
        and q("appleGroupHead.visible")
        and q("tidalGroupHead.y") < q("appleGroupHead.y")
        and q("albumsModel.count") == 1
        and q("appleAlbumsModel.count") == 1
    )

    q("_searchSeq = _navSeq")
    bridge.searchResults.emit(_payload(grouped=False))
    settle(500)
    tidal_only_ok = (
        not q("tidalGroupHead.visible")
        and not q("appleGroupHead.visible")
        and q("albumsModel.count") == 1
        and q("appleAlbumsModel.count") == 0
    )
    return 0 if grouped_ok and tidal_only_ok else 1


def test_enabled_apple_search_renders_provider_groups_and_disabled_apple_keeps_the_old_page():
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="waves-apple-search-test-")
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
