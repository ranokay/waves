"""OpenCodeReview's project rules keep QML and Markdown in scope.

WHAT THIS FENCES OFF
--------------------
OCR's default filters skip `.qml` and `.md` as unsupported extensions, so a
Waves review would silently cover only the Python/JS part of a diff. The
project rule file's `include` list is the documented bypass, and the per-path
rules carry the house invariants into OCR's prompt. This guard pins both, so
the coverage cannot silently regress when someone edits the file.

The rule file is repo config, not product behaviour: the guard reads it as
JSON and asserts the two things a review needs — the extension bypass and a
house rule for each language the repo writes.
"""

from __future__ import annotations

import json

from support.paths import REPO_ROOT

RULE_FILE = REPO_ROOT / ".opencodereview" / "rule.json"

# The paths a review must resolve a house rule for.
HOUSE_RULES = ("**/*.qml", "waves/**/*.py", "tests/**/*.py", "**/*.md", "waves/desktop/BRIDGE.md")


def _rules() -> dict:
    assert RULE_FILE.is_file(), f"{RULE_FILE} is missing"
    return json.loads(RULE_FILE.read_text(encoding="utf-8"))


def test_qml_and_markdown_bypass_the_default_extension_filter():
    data = _rules()
    include = data.get("include") or []

    assert "**/*.qml" in include, "QML would fall back to the unsupported-extension filter"
    assert "**/*.md" in include, "Markdown would fall back to the unsupported-extension filter"


def test_every_surface_the_review_covers_resolves_a_house_rule():
    rules = _rules().get("rules") or []
    patterns = [entry.get("path", "") for entry in rules]

    for expected in HOUSE_RULES:
        assert expected in patterns, f"no house rule for {expected!r}"

    # merge_system_rule keeps the built-in language rules alongside ours (the
    # field is undocumented upstream but present in the installed v1.12.3 and
    # used by OpenCodeReview's own project file); losing it would silently
    # shrink every review to our text alone.
    for entry in rules:
        assert entry.get("merge_system_rule") is True, f"{entry.get('path')!r} does not merge the system rule"

    # Every entry must SAY something: a missing or blank rule gives the
    # reviewer nothing. Length is not a proxy for that (a padded sentence
    # fixes no wrong code), so it is not asserted.
    for entry in rules:
        assert str(entry.get("rule", "")).strip(), f"rule for {entry.get('path')!r} is blank"
