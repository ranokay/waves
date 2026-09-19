"""Track-row hover stability: hover must never reflow the row.

Hovering a track's download options used to shift the layout: the standalone
LYRICS/COVER pair only existed while hovered, so its RowLayout slot opened and
closed under the pointer. Hover may tint and overlay, but the row's inner
geometry must not move.

Proved on the real Main.qml offscreen: a search track row is seeded, its
geometry recorded, the pointer moved onto the row, and the row's own MouseArea
must report hover while the row's height, the download button and the
standalone pair's slot are identical and the pair still shows LYRICS / COVER.
Source parsing could pass with the pair hidden or the row reflowing; the
rendered tree cannot.
"""

from __future__ import annotations

import json
import sys

import pytest
from support.qml import (
    EXIT_OK,
    EXIT_PRECONDITION,
    EXIT_REGRESSED,
    boot_main_qml,
    run_scenario,
)
from support.qml_probe import scene_js

_TRACK_JS = """
    var row = findFirst(root.contentItem, function (o) {
        return o.tId !== undefined && ("" + o.tId) === "t1" && o.durationSec !== undefined;
    });
"""

_GEOMETRY_BODY = (
    _TRACK_JS
    + """
    if (!row) return "";
    var pair = findFirst(row, function (o) {
        if (o.compact !== true) return false;
        var kids = o.children || [];
        for (var i = 0; i < kids.length; i++) if (kids[i].text === "LYRICS") return true;
        return false;
    });
    var dl = findFirst(row, function (o) { return o.chooserKind !== undefined; });
    var hoverArea = findFirst(row, function (o) {
        return o.containsMouse !== undefined && o.width >= row.width - 2;
    });
    return JSON.stringify({
        rowH: row.height,
        rowW: row.width,
        pairVisible: pair ? !!pair.visible : false,
        pairX: pair ? pair.x : -1,
        pairY: pair ? pair.y : -1,
        pairW: pair ? pair.width : -1,
        lyrics: pair ? !!findFirst(pair, function (o) { return o.text === "LYRICS"; }) : false,
        cover: pair ? !!findFirst(pair, function (o) { return o.text === "COVER"; }) : false,
        dlX: dl ? dl.x : -1,
        dlY: dl ? dl.y : -1,
        dlW: dl ? dl.width : -1,
        hovered: hoverArea ? !!hoverArea.containsMouse : false
    });
"""
)

_ROW_CENTER_BODY = _TRACK_JS + "    return row ? row.mapToItem(null, row.width / 2, row.height / 2) : null;"


@pytest.mark.qml
def test_hover_never_reflows_the_track_row():
    run_scenario(
        __file__,
        "--run-scenario",
        timeout=180,
        sandbox_prefix="waves-track-row-hover-test-",
        failure_message="the track row reflowed under the pointer",
    )


def _run_scenario() -> int:
    booted = boot_main_qml()
    if isinstance(booted, int):
        return booted
    _root, q, settle, bridge = booted

    q("openSearch()")
    settle(200)
    track = {
        "id": "t1",
        "kind": "track",
        "title": "Track",
        "artist": "Artist",
        "artist_id": "a1",
        "album": "Album",
        "album_id": "al1",
        "num": 1,
        "vol": 1,
        "art": "",
        "year": "2026",
        "date": "2026-09-01",
        "duration": "3:00",
        "duration_sec": 180,
        "quality": "LOSSLESS",
        "popularity": 1,
        "explicit": False,
        "added": "",
    }
    payload = {
        "groups": [
            {
                "provider": "tidal",
                "artists_layout": "strip",
                "head_when_alone": False,
                "artists": [],
                "albums": [],
                "tracks": [track],
                "videos": [],
                "playlists": [],
                "mixes": [],
                "top": None,
                "error": "",
            }
        ]
    }
    q("root._searchSeq = root._navSeq")
    bridge.searchResults.emit(payload)
    settle(500)

    before = str(q(scene_js(_GEOMETRY_BODY)))
    if not before:
        print("the search track row never rendered", file=sys.stderr)
        return EXIT_PRECONDITION
    before = json.loads(before)

    center = q(scene_js(_ROW_CENTER_BODY))
    if center is None:
        print("the track row has no scene position", file=sys.stderr)
        return EXIT_PRECONDITION

    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QGuiApplication, QMouseEvent

    point = QPointF(float(center.x()), float(center.y()))
    QGuiApplication.instance().sendEvent(
        _root,
        QMouseEvent(
            QMouseEvent.Type.MouseMove,
            point,
            point,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    settle(300)

    after = json.loads(str(q(scene_js(_GEOMETRY_BODY))))
    failures = []
    if not after["hovered"]:
        failures.append("the pointer never engaged the row's own hover area")
    failures.extend(
        f"{field} moved under hover: {before[field]} -> {after[field]}"
        for field in ("rowH", "rowW", "pairX", "pairY", "pairW", "dlX", "dlY", "dlW")
        if after[field] != before[field]
    )
    if not after["pairVisible"]:
        failures.append("the standalone pair is hidden")
    if not (after["lyrics"] and after["cover"]):
        failures.append(f"the standalone pair lost its LYRICS / COVER labels: {after}")
    if failures:
        for line in failures:
            print(line, file=sys.stderr)
        return EXIT_REGRESSED
    print("ok")
    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    sys.exit(_run_scenario())
