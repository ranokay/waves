"""The README's platform claims match what ships while Windows is parked.

Windows bundle builds cannot be produced on hosted runners (MSVC fails on
yt-dlp's generated `lazy_extractors`; ADR 0009 records the park), so the
README must not present Windows assets as downloadable. The guard is
mechanical: removing the park note, re-adding Windows to the platform
badge, or deleting the ADR fails here instead of silently re-advertising
the platform. Re-entry updates this file alongside the README (ADR 0009
names the three steps).
"""

from __future__ import annotations

from support.paths import REPO_ROOT

README = REPO_ROOT / "README.md"
ADR_DIR = REPO_ROOT / "docs" / "adr"


def _readme() -> str:
    return README.read_text(encoding="utf-8")


def test_the_platform_badge_covers_only_shippable_platforms():
    badge_lines = [line for line in _readme().splitlines() if "platforms-" in line]
    assert len(badge_lines) == 1, "expected one platforms badge line"
    assert "Windows" not in badge_lines[0], "the badge re-advertises parked Windows builds"


def test_the_install_section_names_the_park_and_points_at_the_adr():
    text = _readme()
    assert "parked" in text, "the Windows park note is gone from the README"
    assert "docs/adr/0009-windows-builds-parked.md" in text, "the park note lost its ADR pointer"
    # The asset names stay documented (they are what a revalidated release
    # will carry), but not as downloadable builds.
    assert "waves_windows-x64.zip" in text


def test_the_windows_park_is_recorded_with_reentry_conditions():
    hits = sorted(ADR_DIR.glob("*-windows-*.md"))
    assert len(hits) == 1, f"expected one Windows park record, found {hits}"
    text = hits[0].read_text(encoding="utf-8")
    assert "Re-entry" in text or "re-entry" in text, "the park names no re-entry conditions"
