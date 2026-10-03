"""The provider contract names the owner of each distribution decision.

Bundling and wrapper distribution point at the maintained ADRs; the shipped
lyrics/art defaults are covered behaviorally by the settings tests.
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
