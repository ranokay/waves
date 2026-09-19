"""The mixed search view's video grid shows whole rows, never a hole.

Every list section shows five rows until SHOW ALL. The video grid is three
cells wide at the usual window width, so five cells left the sixth blank
and SHOW ALL then filled a hole the page had already made room for. The
grid rounds the five up to whole rows: six at three columns, six at two,
eight at four; SHOW ALL appears only past that count.
"""

from __future__ import annotations

import re

from support.paths import QML_MAIN

MAIN = QML_MAIN.read_text(encoding="utf-8")


def _block(start: str, end: str) -> str:
    return MAIN.split(start, 1)[1].split(end, 1)[0]


def test_the_video_grid_caps_at_whole_rows():
    grid = _block("id: videoGrid", 'section: "videos"')
    assert "readonly property int cap: cols * Math.ceil(5 / cols)" in grid
    assert (
        'root.searchRowVisible("videos", videosModel.count, index, group.isExpanded("videos"), videoGrid.cap)' in grid
    )


def test_show_all_for_videos_waits_for_the_rounded_count():
    m = re.search(r'SearchSectionMore \{\s*\n\s*section: "videos"\n(.*?)\n        \}', MAIN, re.DOTALL)
    assert m, "the videos SHOW ALL instance moved"
    assert "cap: videoGrid.cap" in m.group(1), "the videos SHOW ALL must use the grid-computed cap"
    more = _block("component SearchSectionMore: ShowAllLabel {", "\n    }")
    assert "property int cap: 5" in more and 'root.filterType === "all" && count > cap' in more


def test_the_other_sections_keep_their_five():
    fn = _block("function searchRowVisible(name, count, index, expanded, cap) {", "\n    }")
    assert "index < (cap || 5)" in fn
    for name in ("albums", "tracks", "playlists", "mixes"):
        assert f'root.searchRowVisible("{name}", {name}Model.count, index, ' in MAIN


def test_the_cap_is_whole_rows_at_every_column_count():
    import math

    assert [c * math.ceil(5 / c) for c in (2, 3, 4, 5)] == [6, 6, 8, 5]
