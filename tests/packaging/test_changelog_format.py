"""CHANGELOG.md format guard.

Every release section must list its subheadings in the fixed order
Added > Changed > Fixed > Removed (any subset, but never shuffled), so the
notes read the same way in every GitHub Release. The heading text may carry
an emoji accent; only the trailing word is significant.

An issue a bullet closes must be written as a full link ("[issue #11](url)")
rather than a bare "(#11)": these notes are lifted verbatim into the Release
body and read well outside the repo, where a bare number links to nothing
and does not even say what it refers to.

A bullet also lives on a single line, however long. GitHub renders a Release
body with every newline turned into a line break, so a bullet wrapped across
source lines reaches the Releases page as one ragged fragment per source line
instead of a paragraph.
"""

from __future__ import annotations

import re

from support.paths import REPO_ROOT

CHANGELOG = REPO_ROOT / "CHANGELOG.md"

CANONICAL = ["Added", "Changed", "Fixed", "Removed"]


def _sections() -> list[tuple[str, list[str]]]:
    """Return (release heading, [subheading names]) per release section."""
    sections: list[tuple[str, list[str]]] = []
    current: tuple[str, list[str]] | None = None
    for line in CHANGELOG.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            if current:
                sections.append(current)
            current = (line[3:].strip(), [])
        elif line.startswith("### ") and current:
            # Keep only the canonical name: strip any emoji accent.
            match = re.search(r"(Added|Changed|Fixed|Removed)\s*$", line)
            assert match, f"unknown subheading {line!r} under {current[0]!r}"
            current[1].append(match.group(1))
    if current:
        sections.append(current)
    return sections


def test_changelog_has_release_sections():
    assert _sections(), "CHANGELOG.md has no '## ' release sections"


def test_subheadings_are_unique_per_section():
    for heading, subs in _sections():
        assert len(subs) == len(set(subs)), f"duplicate subheading under {heading!r}: {subs}"


def test_subheadings_follow_canonical_order():
    for heading, subs in _sections():
        expected = [name for name in CANONICAL if name in subs]
        assert subs == expected, (
            f"{heading!r} lists subheadings as {subs}; they must follow Added > Changed > Fixed > Removed ({expected})"
        )


def _classify(line: str) -> str:
    """The structural kind of a changelog line: release, fence, blank, heading, bullet, or text."""
    if line.startswith("## "):
        return "release"
    if line.lstrip().startswith("```"):
        return "fence"
    if not line.strip():
        return "blank"
    if line.startswith("### ") or line.startswith("# "):
        return "heading"
    if line.startswith("- "):
        return "bullet"
    return "text"


def _wrapped_bullet_lines(lines: list[str]) -> list[str]:
    """Non-blank text hanging directly off a bullet (or its continuation).

    Bullet-scoped, not line-pair-scoped: headings, the footer markup inside a
    section, and indented blocks after a blank line are not bullets, so starting
    a wrapped continuation with `<` no longer exempts it. Each release section
    carries its own state instead of one flag for the whole file.
    """
    wrapped = []
    in_release = False
    in_fence = False
    in_bullet = False
    for lineno, line in enumerate(lines, 1):
        kind = _classify(line)
        if kind == "fence":
            in_fence = not in_fence
            in_bullet = False
        elif in_fence:
            continue
        elif kind == "release":
            in_release = True
            in_bullet = False
        elif kind in ("blank", "heading") or not in_release:
            in_bullet = False
        elif kind == "bullet":
            in_bullet = True
        elif in_bullet and lines[lineno - 2].strip():
            # A bullet may carry an indented block (a command, a follow-up
            # paragraph) below it, but only after a blank line: what is banned
            # is text hanging directly off the bullet above, which is a wrap.
            wrapped.append(f"line {lineno}: {line.strip()[:60]}")
        else:
            in_bullet = False
    return wrapped


def test_bullets_are_never_wrapped_across_lines():
    """One bullet, one line: a source newline becomes a break in the Release."""
    lines = CHANGELOG.read_text(encoding="utf-8").splitlines()
    wrapped = _wrapped_bullet_lines(lines)
    assert not wrapped, "write each bullet on one line, unwrapped:\n" + "\n".join(wrapped)


def test_no_bullets_live_outside_release_sections():
    """The preamble carries the format contract in prose; bullets live in sections."""
    lines = CHANGELOG.read_text(encoding="utf-8").splitlines()
    first = next((index for index, line in enumerate(lines) if line.startswith("## ")), None)
    assert first is not None, "CHANGELOG.md has no '## ' release sections"
    strays = [
        f"line {lineno}: {line.strip()[:60]}" for lineno, line in enumerate(lines[:first], 1) if line.startswith("- ")
    ]
    assert not strays, "bullets outside any release section:\n" + "\n".join(strays)


def test_a_bullet_wrapped_with_an_angle_bracket_continuation_fails_the_guard():
    """Negative: the old line-pair check exempted any continuation starting with
    `<`, so a wrapped bullet could pass by opening its second line with markup."""
    lines = ["## Unreleased", "", "### Fixed", "", "- a bullet", "<wrapped continuation>"]
    assert _wrapped_bullet_lines(lines) == ["line 6: <wrapped continuation>"]


def test_section_boundaries_reset_bullet_state():
    """Negative: state is per-section — a heading ends the previous bullet, so
    text opening the next section is not a wrap of it, while a real wrap in the
    new section is still caught. The old single-flag check flagged the opener."""
    lines = ["## v1", "", "- bullet", "## v2", "plain text", "", "- other", "wrapped"]
    assert _wrapped_bullet_lines(lines) == ["line 8: wrapped"]


def test_issue_references_are_labelled_links():
    """No bare '#12' anywhere: an issue is named and linked, or not cited."""
    bare = []
    for lineno, raw in enumerate(CHANGELOG.read_text(encoding="utf-8").splitlines(), 1):
        # Inline code spans quote the rule's own counter-example; they cite
        # nothing, so they are not held to it.
        line = re.sub(r"`[^`]*`", "", raw)
        for match in re.finditer(r"#\d+", line):
            start = match.start()
            # A reference is fine when it reads "issue #N" AND that text is a
            # markdown link ("[issue #N](url)"), which is how they are written.
            named = line[:start].rstrip().endswith("issue")
            linked = "](http" in line[match.end() : match.end() + 80]
            if not (named and linked):
                bare.append(f"line {lineno}: {line.strip()}")
    assert not bare, "cite issues as [issue #N](https://github.com/.../issues/N):\n" + "\n".join(bare)
