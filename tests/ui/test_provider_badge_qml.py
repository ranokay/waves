"""Provider badges on drill headers (issue #69), descriptor-driven (issue #278).

Album/song drill headers (browseItemHeader) and the artist header carry the
official provider mark top-right of the artwork, rendered from the descriptor
``waves.providerDescriptor`` answers for the page's id -- no id prefix parsed
here, no provider asset path in QML. The skeleton names its provider from the
page key, so no wrong badge flashes before the payload; and a third provider
registered with a descriptor badges like the first two with no QML change.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from support.paths import QML_MAIN
from support.qml import run_scenario, sandbox_qml_settings


def _scenario() -> int:
    from PySide6.QtCore import QEventLoop, QTimer, QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine, QQmlEngine, QQmlExpression

    app = QGuiApplication.instance() or QGuiApplication([])
    sandbox_qml_settings()
    from support.offline import PARK_LOGIN_QML, patch_offline

    patch_offline()
    from waves.providers.base import ProviderDescriptor
    from waves.waves_ui.app import _load_mono
    from waves.waves_ui.backend import WavesBridge

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

    def badge_ok(object_name: str, provider_id: str) -> bool:
        """The badge is visible and renders the descriptor of that provider."""
        prefix = f'{object_name}.descriptor ? {object_name}.descriptor.id : ""'
        mark = f"{object_name}.mark"
        return bool(q(f"{object_name}.visible")) and q(prefix) == provider_id and provider_id in str(q(mark))

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
    apple_ok = badge_ok("bihProviderBadge", "apple")

    # ...TIDAL album page badges TIDAL.
    q("browsePageKey = 'item:album:123'")
    q("browsePage = ({header: %s})" % (header % "123"))
    settle(200)
    tidal_ok = badge_ok("bihProviderBadge", "tidal")

    # Skeleton names its provider from the key: no wrong flash.
    q("browsePage = null")
    q("browsePageKey = 'item:album:apple:9'")
    q("browseTitleHint = 'Hint Album'")
    q("browseHighlightId = ''")
    settle(200)
    skeleton_ok = q("browseItemHeader.visible") and badge_ok("bihProviderBadge", "apple")
    q("browseTitleHint = ''")
    q("browsePageKey = ''")

    # Track drills land on the album header, which badges the album's owner.
    q("browsePageKey = 'item:album:apple:7'")
    q("browsePage = ({header: %s})" % (header % "apple:7"))
    settle(200)
    track_ok = badge_ok("bihProviderBadge", "apple")
    q("browsePage = null")
    q("browsePageKey = ''")
    q("browseOpen = false")
    settle(100)

    # Artist page badges per id, hidden until the id is known.
    q("artistOpen = true")
    q("artistData = ({id: 'apple:artist-1', name: 'Aphex Twin', art: '', bio: ''})")
    settle(200)
    artist_apple_ok = badge_ok("artistProviderBadge", "apple")
    q("artistData = ({id: '42', name: 'Aphex Twin', art: '', bio: ''})")
    settle(200)
    artist_tidal_ok = badge_ok("artistProviderBadge", "tidal")
    q("artistData = ({})")
    settle(200)
    artist_hidden_ok = not q("artistProviderBadge.visible")

    # A third provider registered with a descriptor badges its own rows with
    # no QML edit at all (issue #278's acceptance).
    bridge.providers["qobuz"] = SimpleNamespace(
        descriptor=lambda: ProviderDescriptor(
            id="qobuz",
            name="Qobuz",
            logo="assets/providers/qobuz.png",
            logo_header_width=22,
            logo_header_height=13,
        )
    )
    q("browseOpen = true")
    q("browsePageKey = 'item:album:qobuz:77'")
    q("browsePage = ({header: %s})" % (header % "qobuz:77"))
    settle(200)
    q("artistOpen = false")
    q("artistData = ({})")
    third_ok = badge_ok("bihProviderBadge", "qobuz")
    q("artistOpen = true")
    q("artistData = ({id: 'qobuz:artist-1', name: 'Third Artist', art: '', bio: ''})")
    settle(200)
    third_artist_ok = badge_ok("artistProviderBadge", "qobuz")
    # An unclaimed namespace wears no mark at all (never another provider's).
    q("browsePage = null")
    q("browsePageKey = ''")
    q("artistData = ({id: 'unclaimed:artist-1', name: 'Nobody', art: '', bio: ''})")
    settle(200)
    unclaimed_ok = not q("artistProviderBadge.visible") and not q("bihProviderBadge.visible")

    problems = [
        name
        for name, ok in (
            ("the Apple album header's badge", apple_ok),
            ("the TIDAL album header's badge", tidal_ok),
            ("the skeleton's badge", skeleton_ok),
            ("the track drill's badge", track_ok),
            ("the Apple artist page's badge", artist_apple_ok),
            ("the TIDAL artist page's badge", artist_tidal_ok),
            ("the hidden badge on no artist", artist_hidden_ok),
            ("the third provider's album badge", third_ok),
            ("the third provider's artist badge", third_artist_ok),
            ("the unclaimed namespace's badge", unclaimed_ok),
        )
        if not ok
    ]
    for problem in problems:
        print(f"regressed: {problem}", file=sys.stderr)
    return 0 if not problems else 1


@pytest.mark.qml
def test_provider_badge_on_drill_headers():
    run_scenario(Path(__file__), "--run-scenario", timeout=120, sandbox_prefix="waves-provider-badge-test-")


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_scenario())
