"""The download button's progress bar fills the whole button, and its
percentage is carved into the bar on hover.

WHAT THIS FENCES OFF
--------------------
The running face of DownloadButton (the SAME face on every download button:
track rows, album and playlist pages, artist pages, the Browse cards' pill) is
a dense grid filling the button: SEVEN rows of 3px cells with 1px gaps, 1px
inside the outline at every edge, centred to the DEVICE pixel, with no readout
beside it, and its outer cells fading toward every edge on the shelf edge
fades' curve (26px at the ends, 8px top and bottom: DotMatrix.edgeFadeW /
edgeFadeH) so the field sits in a soft frame inside the outline. The percentage
is spelled in the matrix's own cells (a 3x5 dot font on the middle five rows),
always lit, on a PLATE knocked back to near black, and only while the button
(or, on a Browse card, the card) is hovered: each cell dissolves from its bar
state to its carve state on its own random delay, driven by one eased value,
so a leave mid-way reverses from wherever it is.

Two rules keep the number readable at every value:

  * the stroke is always 1.0 and the plate around it always 0.04, whatever
    the bar is doing. The carve must not invert the bar under it (a hole over
    a lit cell, a lit dot over an unlit one), which reads at either end of a
    run but not while the fill edge crosses the digits. A 3x5 glyph is mostly
    stroke, so dark digits on a lit plate read as a blob to be decoded from
    their counters;
  * the zone is the word's own width, centred, for one, two or three digits
    alike. A FIXED four-glyph zone with the word right-aligned in it moves
    nothing from 9 -> 10 and 99 -> 100, hanging every ordinary reading two to
    four columns right of centre.

HOW THIS STAYS FIXED
--------------------
The real Main.qml runs offscreen (a subprocess, like the sibling scenarios:
building the bridge installs process-global handlers). A search-result album
button is put into "running" at 37% and the scenario reads the matrix that
the Loader built:

  * seven rows, no readout sibling, its width the whole face, its y centred,
    the fade lengths set, an outermost column all but gone, the centre at
    full strength, and the fade the same at both ends and both edges;
  * at rest (wordHover false) every cell shows its bar state (times its own
    static edge fade);
  * hovered, the word cells spell exactly "37%" in the font, centred (the
    field left of the number and right of it match within a cell), each
    stroke is fully lit (1.0) and each plate cell around them is 0.04, both
    regardless of the bar under them;
  * part-way through the reveal the shared value is strictly between 0 and
    1 (it animates, it does not snap), and unhovered every cell is a bar
    cell again.

The Browse card's wiring (the card's hover, not just the pill's) is pinned
statically: the ArtCard's live download button must bind wordHover to the
card-wide HoverHandler.
"""

from __future__ import annotations

import math
import re
import sys
from pathlib import Path

import pytest
from support.paths import QML_DIR, QML_MAIN
from support.qml import EXIT_OK, EXIT_PRECONDITION, EXIT_REGRESSED, run_scenario

# 3x5 dot font, the same table the matrix draws from; the scenario compares
# the CELLS it finds against this rather than trusting the matrix's own idea
# of the glyphs.
_FONT = {
    "3": ["111", "001", "111", "001", "111"],
    "7": ["111", "001", "001", "001", "001"],
    "%": ["101", "001", "010", "100", "101"],
}


def _expected_rows(word: str) -> list[str]:
    """The word's own zone (glyph, gap, glyph, ...; 4 cells a glyph less the
    trailing gap), one string per row."""
    rows = []
    for r in range(5):
        row = ""
        for i, ch in enumerate(word):
            row += _FONT[ch][r]
            if i < len(word) - 1:
                row += "0"
        rows.append(row)
    return rows


@pytest.mark.qml
def test_running_face_is_a_full_width_bar_with_the_percent_carved_in_on_hover():
    run_scenario(
        Path(__file__),
        "--run-carved-scenario",
        sandbox_prefix="waves-carved-percent-test-",
        failure_message="the download button's progress face regressed",
    )


def test_browse_card_button_reveals_the_percent_for_the_whole_card():
    art_card = (QML_DIR / "ArtCard.qml").read_text()
    m = re.search(r"DownloadButton \{\s*id: acDl(.*?)\n\s*\}\n", art_card, re.DOTALL)
    assert m, "the ArtCard's live download button (id: acDl) moved"
    assert "wordHover: acWrapHover.hovered" in m.group(1), (
        "the card's download button must carve its percentage in for the CARD's hover "
        "(wordHover: acWrapHover.hovered), not only the pill's own"
    )


def test_ledger_and_scrub_matrices_do_not_carve():
    """Only the download face names a word; the other DotMatrix sites (the
    queue ledger's two-row bar, the preview scrubber, the compact running
    row) stay plain bars, and a word on fewer than five rows is ignored by
    the component itself; only the download face fades its edges."""
    db = (QML_DIR / "DownloadButton.qml").read_text()
    dm = (QML_DIR / "DotMatrix.qml").read_text()
    assert 'rows >= 5 && word !== ""' in dm, "DotMatrix must gate the word on five rows or more"
    # The download face lives in DownloadButton.qml; the one-site
    # rule spans the tree, so count both files.
    both = db + QML_MAIN.read_text()
    assert both.count("word: db.pct >= 0") == 1, "exactly one site (the download face) sets the word"
    assert both.count("edgeFadeW: 26") == 1, "exactly one site (the download face) fades its edges"


# ---------------------------------------------------------------------------
# The scenario itself
# ---------------------------------------------------------------------------

_WALKERS = """
 function walkBtn(it){
  if (!it) return null;
  if (it.mediaId === 'al-roll' && it.st !== undefined) return it;
  for (var i = 0; i < it.children.length; i++) {
   var hit = walkBtn(it.children[i].item || it.children[i]);
   if (hit) return hit;
  }
  return null;
 }
 function walkMx(it){
  if (!it) return null;
  if (it.objectName === 'dbMatrix') return it;
  for (var i = 0; i < it.children.length; i++) {
   var hit = walkMx(it.children[i].item || it.children[i]);
   if (hit) return hit;
  }
  return null;
 }
 function cells(m){
  var out = [];
  for (var i = 0; i < m.children.length; i++) {
   var c = m.children[i];
   if (c.barOpacity === undefined) continue;
   out.push([c.col, c.rowTop, c.lit ? 1 : 0, c.wordCell ? 1 : 0, Math.round(c.opacity * 100) / 100,
             Math.round(c.barOpacity * c.edgeMul * 100) / 100, Math.round(c.edgeMul * 1000) / 1000,
             c.plateCell ? 1 : 0]);
  }
  return out;
 }
"""


def _run_carved_scenario() -> int:
    import json

    from support.qml import ROLLING_ALBUM_ROW, boot_main_qml, seed_tidal_search, wait_until

    booted = boot_main_qml()
    if isinstance(booted, int):
        return booted
    _root, q, _settle, _bridge = booted  # all waits poll via wait_until; no fixed sleep remains

    def shape():
        return q(
            "(function(){" + _WALKERS + " var b = walkBtn(contentCol); if (!b) return 'shape:button';"
            " var m = walkMx(b); if (!m) return 'shape:matrix';"
            " var sibsWithText = 0; var sibs = m.parent.children;"
            " for (var i = 0; i < sibs.length; i++) if (sibs[i] !== m && sibs[i].text !== undefined) sibsWithText++;"
            " return JSON.stringify({rows: m.rows, dot: m.dot, gap: m.gap, width: m.width, faceWidth: m.parent.width,"
            "  y: m.y, faceH: m.parent.height, ih: m.implicitHeight, word: m.word, reveal: m.wordReveal,"
            "  sibsWithText: sibsWithText, cols: m.cols, hover: b.wordHover, dpr: Screen.devicePixelRatio,"
            "  fadeW: m.edgeFadeW, fadeH: m.edgeFadeH, wordRowTop: m.wordRowTop, faceInset: m.parent.parent.anchors.leftMargin});"
            "})()"
        )

    def read_cells():
        return q(
            "(function(){"
            + _WALKERS
            + " var b = walkBtn(contentCol); var m = walkMx(b); return JSON.stringify(cells(m)); })()"
        )

    def shape_word() -> str:
        rep = shape()
        if not str(rep).startswith("{"):
            return ""
        try:
            return str(json.loads(rep)["word"])
        except (KeyError, ValueError):
            return ""

    q("root.openSearch()")
    seed_tidal_search(q, _bridge, albums=[ROLLING_ALBUM_ROW], expanded=("albums",))
    q("root.searchReveal = 1")
    q("root.searchBuilding = false")
    # Poll for the search build (state), not a fixed sleep; the holder exists when built.
    try:
        wait_until(
            lambda: bool(q("root.dlHolder('al-roll') !== null && root.dlHolder('al-roll') !== undefined")),
            message="carved: search built",
        )
    except AssertionError as exc:
        print(f"CHECKPOINT carved-search FAILED: {exc}", file=sys.stderr)
        return EXIT_REGRESSED

    q("(function(){ var h = root.dlHolder('al-roll'); h.st = 'running'; h.pct = 37; return 1 })()")
    # Poll for the running face (state: word lands at 37%), not a fixed sleep.
    try:
        wait_until(lambda: shape_word() == "37%", message="carved: running face ready")
    except AssertionError as exc:
        print(f"CHECKPOINT carved-running FAILED: {exc}", file=sys.stderr)
        return EXIT_REGRESSED

    rep = shape()
    if not str(rep).startswith("{"):
        print(f"could not locate the running face ({rep})", file=sys.stderr)
        return EXIT_PRECONDITION
    s = json.loads(rep)
    failures: list[str] = []

    # --- geometry: seven rows, to the outline, no readout, centred to the device pixel
    if s["rows"] != 7 or s["dot"] != 3 or s["gap"] != 1:
        failures.append(
            f"  the running face is not the dense seven-row grid: rows {s['rows']} dot {s['dot']} gap {s['gap']}"
        )
    if s["faceInset"] != 1:
        failures.append(f"  the face sits {s['faceInset']}px in from the outline, not 1 (the grid should run to it)")
    if (s["fadeW"], s["fadeH"]) != (26, 8):
        failures.append(f"  the edge fades are {s['fadeW']}/{s['fadeH']}, wanted 26 (ends) / 8 (top and bottom)")
    if abs(s["width"] - s["faceWidth"]) > 0.5:
        failures.append(f"  the matrix is {s['width']}px in a {s['faceWidth']}px face: something sits beside it again")
    if s["sibsWithText"]:
        failures.append(f"  {s['sibsWithText']} text item(s) beside the matrix: the readout is back")
    true_y = (s["faceH"] - s["ih"]) / 2
    dpr = s["dpr"] or 1
    if abs(s["y"] - true_y) > 0.5 / dpr + 1e-6:
        failures.append(f"  matrix y {s['y']} is off the centre {true_y} by more than a device pixel (dpr {dpr})")
    if s["word"] != "37%":
        failures.append(f"  the word is {s['word']!r}, expected '37%'")

    # --- at rest every cell is a bar cell
    if s["hover"] or s["reveal"] != 0:
        failures.append(f"  the word is revealed at rest (hover {s['hover']}, reveal {s['reveal']})")
    rest_cells = json.loads(read_cells())
    for col, row, _lit, wc, op, bar, _mul, pl in rest_cells:
        if wc or pl or abs(op - bar) > 0.011:
            failures.append(
                f"  at rest cell ({col},{row}) is not its bar state: opacity {op} vs bar {bar}, "
                f"wordCell {wc}, plateCell {pl}"
            )
            break
    # --- the conveyor fade: outermost column all but gone, centre untouched,
    # symmetric end to end and top to bottom, the outer rows dimmed too
    mul = {(c, r): m for c, r, _l, _w, _o, _b, m, _p in rest_cells}
    cols_n, rows_n = s["cols"], s["rows"]
    mid_c, mid_r = cols_n // 2, rows_n // 2
    if mul[(0, mid_r)] > 0.1 or mul[(cols_n - 1, mid_r)] > 0.1:
        failures.append(f"  the outermost columns are not faded out: {mul[(0, mid_r)]} / {mul[(cols_n - 1, mid_r)]}")
    if mul[(mid_c, mid_r)] != 1:
        failures.append(f"  the centre cell is faded ({mul[(mid_c, mid_r)]}); the fade must stay at the edges")
    if not (mul[(mid_c, 0)] < 1 and abs(mul[(mid_c, 0)] - mul[(mid_c, rows_n - 1)]) < 0.001):
        failures.append(
            f"  top/bottom rows: {mul[(mid_c, 0)]} vs {mul[(mid_c, rows_n - 1)]} (dimmed and equal expected)"
        )
    for k in range(6):
        if abs(mul[(k, mid_r)] - mul[(cols_n - 1 - k, mid_r)]) > 0.001:
            failures.append(f"  the fade is not the same at both ends at column {k}")
            break
    if not all(mul[(k, mid_r)] < mul[(k + 1, mid_r)] for k in range(5)):
        failures.append("  the end fade does not rise monotonically toward the centre")

    # --- hovered: the reveal animates (not a snap) and lands at 1
    print("CHECKPOINT carved-hover", flush=True)
    q("(function(){" + _WALKERS + " walkBtn(contentCol).wordHover = true; return 1 })()")
    # Poll for a mid-flight value (proves an animation, not a snap) instead of
    # asserting at a fixed wall-clock delta; then poll for the landing.
    try:
        wait_until(
            lambda: 0 < json.loads(shape())["reveal"] < 1,
            timeout_ms=800,
            message="carved-hover: reveal mid-flight",
        )
        mid = json.loads(shape())["reveal"]
    except AssertionError as exc:
        failures.append(f"CHECKPOINT carved-hover FAILED: never mid-flight ({exc})")
        mid = -1.0
    if mid != -1.0 and not (0 < mid < 1):
        failures.append(f"CHECKPOINT carved-hover: the reveal is {mid}: it should animate mid-way, not snap")
    try:
        wait_until(lambda: json.loads(shape())["reveal"] == 1, message="carved-hover: reveal landed")
    except AssertionError as exc:
        failures.append(f"CHECKPOINT carved-hover FAILED: never landed ({exc})")
    s2 = json.loads(shape())
    if s2["reveal"] != 1:
        failures.append(f"CHECKPOINT carved-hover: hovered and settled, the reveal is {s2['reveal']}, not 1")

    # --- hovered: the word cells spell 37% and read the inverse of the bar
    cells = json.loads(read_cells())
    cols = s2["cols"]
    # The zone is the word's own width now, centred (JS Math.round, hence the
    # + 0.5 floor rather than Python's banker's rounding).
    zone_w = len("37%") * 4 - 1
    zone_start = math.floor((cols - zone_w) / 2 + 0.5)
    if abs(zone_start - (cols - zone_start - zone_w)) > 1:
        failures.append(
            f"  the number is not centred: {zone_start} column(s) of field to its left, "
            f"{cols - zone_start - zone_w} to its right"
        )
    got_rows = ["" for _ in range(5)]
    by_pos = {(c, r): (lit, wc, op, bar) for c, r, lit, wc, op, bar, _m, _p in cells}
    top = s2["wordRowTop"]
    if top != 1:
        failures.append(f"  the word sits on rows from {top}; in a seven-row grid it should be the middle five (1..5)")
    for r in range(5):
        for z in range(zone_w):
            wc = by_pos[(zone_start + z, top + r)][1]
            got_rows[r] += "1" if wc else "0"
    exp_rows = _expected_rows("37%")
    if got_rows != exp_rows:
        failures.append(
            "  the carved cells do not spell 37%:\n    got      "
            + "\n    got      ".join(got_rows)
            + "\n    expected "
            + "\n    expected ".join(exp_rows)
        )
    # A stroke is lit and its plate is knocked back, both to a FIXED value:
    # what the bar under them is doing must not enter into it.
    stroke_bad = [(c, r, lit, op) for c, r, lit, wc, op, _bar, m, _p in cells if wc and abs(op - m * 1.0) > 0.011]
    if stroke_bad:
        failures.append(
            f"  {len(stroke_bad)} stroke cell(s) are not fully lit, e.g. {stroke_bad[:3]} (col,row,lit,opacity)"
        )
    plate_bad = [(c, r, lit, op) for c, r, lit, _wc, op, _bar, m, pl in cells if pl and abs(op - m * 0.04) > 0.011]
    if plate_bad:
        failures.append(
            f"  {len(plate_bad)} plate cell(s) are not the fixed 0.04, e.g. {plate_bad[:3]} (col,row,lit,opacity)"
        )
    # the plate is exactly the glyph box plus a cell of margin: on a
    # seven-row face that is the full height, so every column of the zone
    # (and one either side) carries it top to bottom
    want_plate = {
        (c, r)
        for c in range(zone_start - 1, zone_start + zone_w + 1)
        for r in range(top - 1, top + 6)
        if 0 <= c < cols and 0 <= r < s2["rows"]
    }
    got_plate = {(c, r) for c, r, _l, wc, _o, _b, _m, pl in cells if pl or wc}
    if got_plate != want_plate:
        failures.append(
            f"  the plate is not the glyph box plus a cell of margin: "
            f"{len(want_plate - got_plate)} missing, {len(got_plate - want_plate)} extra"
        )
    outside_bad = [
        (c, r, op, bar) for c, r, _lit, wc, op, bar, _m, pl in cells if not wc and not pl and abs(op - bar) > 0.011
    ]
    if outside_bad:
        failures.append(f"  {len(outside_bad)} cell(s) outside the number moved on hover, e.g. {outside_bad[:3]}")

    # --- unhovered: back to a plain bar
    print("CHECKPOINT carved-unhover", flush=True)
    q("(function(){" + _WALKERS + " walkBtn(contentCol).wordHover = false; return 1 })()")
    try:
        wait_until(lambda: json.loads(shape())["reveal"] == 0, message="carved-unhover: reveal released")
    except AssertionError as exc:
        failures.append(f"CHECKPOINT carved-unhover FAILED: never released ({exc})")
    s3 = json.loads(shape())
    if s3["reveal"] != 0:
        failures.append(f"CHECKPOINT carved-unhover: unhovered and settled, the reveal is {s3['reveal']}, not 0")
    for col, row, _lit, wc, op, bar, _m, pl in json.loads(read_cells()):
        if wc or pl or abs(op - bar) > 0.011:
            failures.append(f"  after the hover cell ({col},{row}) is not its bar state: opacity {op} vs bar {bar}")
            break

    if failures:
        print("the download button's carved-percent face regressed:", file=sys.stderr)
        print("\n".join(failures), file=sys.stderr)
        return EXIT_REGRESSED
    print(f"carved percent ok: {s2}", flush=True)
    return EXIT_OK


if __name__ == "__main__":
    if "--run-carved-scenario" in sys.argv:
        raise SystemExit(_run_carved_scenario())
    raise SystemExit(EXIT_PRECONDITION)
