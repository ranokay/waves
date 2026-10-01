"""The provider contract names its current distribution decisions and defaults.

Bundling and wrapper distribution point at the maintained ADRs. The lyrics
and art defaults stay documented; settings tests cover the shipped values.
"""

from __future__ import annotations

from support.paths import REPO_ROOT

SPEC = REPO_ROOT / "docs" / "apple-music-provider-spec.md"


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    rest = text[start:]
    for marker in ("\n## ", "\n---\n"):
        cut = rest.find(marker, len(heading))
        if cut != -1:
            return rest[:cut]
    return rest


def test_engine_bundling_names_adr_0004():
    section = _section(SPEC.read_text(encoding="utf-8"), "## 10. Packaging")
    assert "0004-apple-engine-bundling" in section


def test_wrapper_image_names_adr_0005():
    section = _section(SPEC.read_text(encoding="utf-8"), "## 10. Packaging")
    assert "0005-wrapper-image-distribution" in section


def test_lyrics_art_defaults_state_the_ratified_set():
    section = _section(SPEC.read_text(encoding="utf-8"), "## 9. Lyrics")
    for stated in (
        "lyrics_embed` off",
        "lyrics_file` **on**",
        "word-timed **on**",
        ".ttml` sidecar **on**",
        "raw (default",
    ):
        assert stated in section, f"the ratified default {stated!r} left §9.1"
