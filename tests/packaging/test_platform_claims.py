"""The README's platform claims match what ships after Windows re-entry.

Both Windows legs went green on the exclusion recipe (run 35836125855;
ADR 0009 is superseded), so the README must present the Windows assets as
downloadable and nothing may claim the park still holds. The guard is
mechanical: a returning park note, a badge without Windows, or a record
that still reads as an active park fails here. A re-park updates this file
alongside the README.
"""

from __future__ import annotations

from support.paths import REPO_ROOT

README = REPO_ROOT / "README.md"
ADR_DIR = REPO_ROOT / "docs" / "adr"


def _readme() -> str:
    return README.read_text(encoding="utf-8")


def test_the_platform_badge_covers_windows():
    badge_lines = [line for line in _readme().splitlines() if "platforms-" in line]
    assert len(badge_lines) == 1, "expected one platforms badge line"
    assert "Windows" in badge_lines[0], "the badge lost the revalidated Windows platform"


def test_the_install_section_presents_the_windows_assets_as_downloadable():
    text = _readme()
    assert "parked" not in text, "a park note outlived the re-entry"
    # The asset names stay documented (they are what a release carries).
    assert "waves_windows-x64.zip" in text
    assert "waves_windows-arm64.zip" in text
    # The run instructions must present the Windows build as runnable.
    assert "Waves.exe" in text


def test_the_windows_record_is_superseded_with_the_revalidation_run():
    hits = sorted(ADR_DIR.glob("*-windows-*.md"))
    assert len(hits) == 1, f"expected one Windows record, found {hits}"
    text = hits[0].read_text(encoding="utf-8")
    assert "superseded" in text.lower(), "the record still reads as an active park"
    assert "35836125855" in text, "the record names no revalidation run"
