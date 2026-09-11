"""Track-row hover stability (issue #70): hover must never reflow the row.

Hovering a track's download options used to shift the layout: the
standalone LYRICS/COVER pair only existed while hovered, so its RowLayout
slot opened and closed under the pointer. Hover may tint and overlay, but
no `visible:` binding inside TrackRow may read hover state. The pair is
always visible (compact) instead, labelled LYRICS / COVER.
"""

from __future__ import annotations

import re
from pathlib import Path

MAIN_QML = Path(__file__).resolve().parent.parent / "waves" / "waves_ui" / "qml" / "Main.qml"


def _strip_strings_and_comments(line: str) -> str:
    """A line with string literals and // comments blanked, for brace counting."""
    line = re.sub(r'"(?:[^"\\]|\\.)*"', '""', line)
    return line.split("//", 1)[0]


def _track_row_block() -> str:
    """The `component TrackRow` block, brace-matched from its opening line."""
    lines = MAIN_QML.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip().startswith("component TrackRow:"))
    depth = 0
    for i in range(start, len(lines)):
        cleaned = _strip_strings_and_comments(lines[i])
        depth += cleaned.count("{") - cleaned.count("}")
        if depth == 0 and i > start:
            return "\n".join(lines[start : i + 1])
    raise AssertionError("TrackRow block never closes")


def test_hover_never_toggles_visibility_inside_track_row():
    block = _track_row_block()
    # The extractor really scoped the row, not a fragment of it.
    assert "StandalonePair" in block and "id: trowMa" in block
    # Only the visible binding's own expression counts: a sibling prop on
    # the same line (PlayBadge's hover-lit overlay) paints, never reflows.
    offenders = []
    for line in block.splitlines():
        if "visible:" not in line:
            continue
        binding = line.split("visible:", 1)[1].split(";", 1)[0]
        if "containsMouse" in binding or ".hovered" in binding:
            offenders.append(line.strip())
    assert offenders == [], f"hover-gated layout would reflow the row: {offenders}"


def test_standalone_pair_is_always_visible_and_renamed():
    text = MAIN_QML.read_text(encoding="utf-8")
    assert '"LYRICS ONLY"' not in text and '"ART ONLY"' not in text
    pair = re.search(r"component StandalonePair: Row \{(.*?)\n    \}", text, re.DOTALL)
    assert pair is not None
    assert 'text: "LYRICS"' in pair.group(1) and 'text: "COVER"' in pair.group(1)
    block = _track_row_block()
    instance = re.search(r"StandalonePair \{(.*?)\}", block, re.DOTALL)
    assert instance is not None
    assert "containsMouse" not in instance.group(1)
    assert "compact: true" in instance.group(1)
