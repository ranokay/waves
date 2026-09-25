"""The README's platform claims match what ships after Windows re-entry.

Both Windows legs went green on the exclusion recipe (run 35836125855;
ADR 0009 is superseded), so the README must present the Windows assets as
downloadable and nothing may claim the park still holds. The guard is
mechanical: a returning park note, a badge without Windows, or a record
that still reads as an active park fails here. A re-park updates this file
alongside the README.
"""

from __future__ import annotations

import pytest
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
    _assert_windows_assets_present(_readme())


def _install_section(text: str) -> str:
    """The `## Install` section, up to the next `## ` heading."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("## ") and "install" in line.lower())
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return "\n".join(lines[start:end])


def _assert_windows_assets_present(text: str) -> None:
    """The Windows row carries both zips and the Windows run clause names the exe.

    A substring check ("Waves.exe" anywhere in the README) stays green when the
    run instruction drifts into another platform's paragraph while the Windows
    row keeps only the downloads, so the guard reads the section structurally.
    """
    assert "parked" not in text, "a park note outlived the re-entry"
    section = _install_section(text)
    rows = [line for line in section.splitlines() if "windows" in line.lower()]
    assert any("waves_windows-x64.zip" in line and "waves_windows-arm64.zip" in line for line in rows), (
        "no Windows table row names both Windows assets"
    )
    run_lines = [line for line in section.splitlines() if "unzip and run" in line.lower()]
    assert run_lines, "the install section lost its run instructions"
    clauses = run_lines[0].split(";")
    windows_clauses = [clause for clause in clauses if "windows" in clause.lower()]
    assert windows_clauses, "the run instructions name no Windows step"
    assert any("Waves.exe" in clause for clause in windows_clauses), (
        "the Windows run step no longer names Waves.exe: a parked platform presented as runnable"
    )


def test_a_windows_run_step_without_the_exe_fails_the_guard():
    """Negative: moving Waves.exe into another platform's clause must fail.

    The mutation keeps every old substring ("Waves.exe", both zips, no "parked")
    so the previous anywhere-in-the-file check stays green on it.
    """
    text = _readme()
    mutated = text.replace("on Windows run `Waves.exe` from the unzipped folder", "on Windows ask your administrator")
    mutated = mutated.replace(
        "on macOS drag `waves.app` to Applications", "on macOS drag `waves.app` to Applications or run `Waves.exe`"
    )
    assert "Waves.exe" in mutated and "waves_windows-x64.zip" in mutated and "parked" not in mutated
    with pytest.raises(AssertionError):
        _assert_windows_assets_present(mutated)


def test_the_windows_record_is_superseded_with_the_revalidation_run():
    hits = sorted(ADR_DIR.glob("*-windows-*.md"))
    assert len(hits) == 1, f"expected one Windows record, found {hits}"
    text = hits[0].read_text(encoding="utf-8")
    assert "superseded" in text.lower(), "the record still reads as an active park"
    assert "35836125855" in text, "the record names no revalidation run"
