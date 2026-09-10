"""Official provider logos live in qml/assets/providers/ and are the marks in use.

Issue #58. The user-supplied official logos (white-on-transparent artwork for
the app's dark surfaces) moved from the repo root into
``waves/waves_ui/qml/assets/providers/`` and replaced the invented vector
glyphs: Settings section headers show the logo image, and so do the search
group headers and the Chooser provider segments. This file pins the asset
placement and every reference, so a future edit cannot silently fall back to
text-only headers or reintroduce the tide-lines / beamed-note glyphs.
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
QML = REPO / "waves" / "waves_ui" / "qml"
PROVIDERS = QML / "assets" / "providers"
TIDAL = PROVIDERS / "tidal.png"
APPLE = PROVIDERS / "apple-music.png"
_PNG_SIG = b"\x89PNG\r\n\x1a\n"


def test_logos_live_in_the_providers_asset_dir_and_not_at_the_root():
    assert TIDAL.is_file() and TIDAL.stat().st_size > 0
    assert APPLE.is_file() and APPLE.stat().st_size > 0
    assert TIDAL.read_bytes()[:8] == _PNG_SIG
    assert APPLE.read_bytes()[:8] == _PNG_SIG
    assert not (REPO / "tidal-logo.png").exists()
    assert not (REPO / "apple-music-logo.png").exists()


def test_settings_headers_use_the_logos_not_vector_glyphs():
    src = (QML / "SettingsPage.qml").read_text()
    assert '"assets/providers/tidal.png"' in src
    assert '"assets/providers/apple-music.png"' in src
    assert "function providerLogo(id)" in src
    assert "logoSrc" in src
    # The invented glyphs are retired: no provider case may remain in iconPath,
    # or a section would have two competing marks.
    assert "providers_tidal" not in src.split("function providerLogo(id)")[0].split("function iconPath(id)")[1]
    assert "providers_apple" not in src.split("function providerLogo(id)")[0].split("function iconPath(id)")[1]


def test_search_headers_and_chooser_segments_use_the_logos():
    src = (QML / "Main.qml").read_text()
    # One reference per search group header plus one per Chooser segment.
    assert src.count('"assets/providers/tidal.png"') >= 2
    assert src.count('"assets/providers/apple-music.png"') >= 2
