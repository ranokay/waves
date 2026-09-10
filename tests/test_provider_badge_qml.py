"""Provider badge on drill headers (issue #69).

Album/song drill headers (browseItemHeader) and the artist header carry
the official provider logo top-right of the artwork, read off the
namespaced page id ("apple:…" vs bare TIDAL ids). The skeleton names its
provider from the page key, so no wrong badge flashes before the payload.
"""

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

    header = (
        "{kind: 'album', id: '%s', title: 'Selected Ambient Works', subtitle: 'By Aphex Twin', "
        "desc: '', stats: '', artist_id: '', artist: '', year: '', num_tracks: 1, duration_sec: 1, "
        "quality: '', art: ''}"
    )
    q("browseOpen = true")

    # Apple album page badges Apple...
    q("browsePageKey = 'item:album:apple:1'")
    q("browsePage = ({header: %s})" % (header % "apple:1"))
    settle(200)
    apple_ok = (
        q("browseItemHeader.visible") and q("bihProviderBadge.visible") and q("bihProviderBadge.provider") == "apple"
    )

    # ...TIDAL album page badges TIDAL.
    q("browsePageKey = 'item:album:123'")
    q("browsePage = ({header: %s})" % (header % "123"))
    settle(200)
    tidal_ok = q("bihProviderBadge.visible") and q("bihProviderBadge.provider") == "tidal"

    # Skeleton names its provider from the key: no wrong flash.
    q("browsePage = null")
    q("browsePageKey = 'item:album:apple:9'")
    q("browseTitleHint = 'Hint Album'")
    q("browseHighlightId = ''")
    settle(200)
    skeleton_ok = q("browseItemHeader.visible") and q("bihProviderBadge.provider") == "apple"
    q("browseTitleHint = ''")
    q("browsePageKey = ''")

    # Track drills land on the album header, which badges the album's owner.
    q("browsePageKey = 'item:album:apple:7'")
    q("browsePage = ({header: %s})" % (header % "apple:7"))
    settle(200)
    track_ok = q("bihProviderBadge.visible") and q("bihProviderBadge.provider") == "apple"
    q("browsePage = null")
    q("browsePageKey = ''")
    q("browseOpen = false")
    settle(100)

    # Artist page badges per id, hidden until the id is known.
    q("artistOpen = true")
    q("artistData = ({id: 'apple:artist-1', name: 'Aphex Twin', art: '', bio: ''})")
    settle(200)
    artist_apple_ok = q("artistProviderBadge.visible") and q("artistProviderBadge.provider") == "apple"
    q("artistData = ({id: '42', name: 'Aphex Twin', art: '', bio: ''})")
    settle(200)
    artist_tidal_ok = q("artistProviderBadge.visible") and q("artistProviderBadge.provider") == "tidal"
    q("artistData = ({})")
    settle(200)
    artist_hidden_ok = not q("artistProviderBadge.visible")

    ok = apple_ok and tidal_ok and skeleton_ok and track_ok and artist_apple_ok and artist_tidal_ok
    return 0 if ok and artist_hidden_ok else 1


def test_provider_badge_on_drill_headers():
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="waves-provider-badge-test-")
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
