"""Official provider logos live in qml/assets/providers/ and are the marks in use.

Issue #58. The user-supplied official logos moved from the repo root into
``waves/waves_ui/qml/assets/providers/`` and replaced the invented vector
glyphs: Settings section headers show the logo image, and so do the search
group headers and the Chooser provider segments. Each provider ships a light
(white-on-transparent, for the app's dark surfaces, the one in use) and a
dark (black-on-transparent, reserved for light backdrops such as the album
provider badge in issue #69) variant. This file pins the asset placement
and every reference, so a future edit cannot silently fall back to
text-only headers or reintroduce the tide-lines / beamed-note glyphs.
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
QML = REPO / "waves" / "waves_ui" / "qml"
PROVIDERS = QML / "assets" / "providers"
TIDAL = PROVIDERS / "tidal.png"
APPLE = PROVIDERS / "apple-music.png"
TIDAL_DARK = PROVIDERS / "tidal-dark.png"
APPLE_DARK = PROVIDERS / "apple-music-dark.png"
_PNG_SIG = b"\x89PNG\r\n\x1a\n"


def test_logos_live_in_the_providers_asset_dir_and_not_at_the_root():
    for logo in (TIDAL, APPLE, TIDAL_DARK, APPLE_DARK):
        assert logo.is_file() and logo.stat().st_size > 0
        assert logo.read_bytes()[:8] == _PNG_SIG
    for stray in (
        "tidal-logo.png",
        "apple-music-logo.png",
        "tidal-logo-dark.png",
        "apple-music-logo-dark.png",
    ):
        assert not (REPO / stray).exists()


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
