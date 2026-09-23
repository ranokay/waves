"""The provider spec names the decisions that superseded it.

Sections of `docs/apple-music-provider-spec.md` that later decisions changed
must point at their successor (ADR or issue), so a reader never follows a
stale ruling. The guard is mechanical: dropping any successor note below
fails here instead of silently reopening HD-15/LM-12. The §9.1 assertions
pin the ratified #59 fresh-install defaults staying stated (LM-12, fixed
by #280); the shipped values themselves are pinned by the settings tests.
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


def test_platform_section_and_deferrals_name_the_windows_record():
    text = SPEC.read_text(encoding="utf-8")
    assert "0009-windows-builds-parked" in _section(text, "## 10. Packaging")
    assert "ADR 0009" in _section(text, "## 12. Post-v1")


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
