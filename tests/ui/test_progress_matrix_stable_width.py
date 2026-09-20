"""A running download's dot matrix must not shed columns when the % readout grows.

WHAT THIS FENCES OFF
--------------------
The download button draws ``[dot matrix][NN%]``: the matrix is anchored to the
left edge of the percentage Text, so the Text's width IS the matrix's right
edge. An unbounded Text narrows the matrix beside it with every digit the
readout gains (…→ 5%, 9% → 10%, 99% → 100%).

DotMatrix answers a width change by holding its old column count for 300ms (its
``_settledWidth``, which exists so dragging the queue drawer's edge doesn't
rebuild every dot per mouse move). For those 300ms the matrix lays its last
columns out past its own new width, so a download visibly LOSES its last two
columns of dots exactly as it reaches 100%, then pops them back when the
settle timer fires. Measured on a 25fps screen capture: the lit dot area falls
from 4189px to 3901px for ten frames at the finish.

Reserving the readout's widest value ("100%") keeps the matrix from resizing
mid-run at all.

HOW THIS STAYS FIXED
--------------------
This drives the real Main.qml: put an album's DownloadButton into a running
download and step its percentage through both digit boundaries, reading the
matrix geometry between steps WITHOUT waiting out the settle interval. Two
things are asserted at every step:

* the matrix width never moves (the reservation itself), and
* the matrix's laid-out extent (``cols * (dot + gap) - gap``) still fits inside
  its width, which is the defect the user could see.

The second is the backstop: it fails for ANY route back to a matrix laid out
wider than the item drawing it, not just an unbounded readout.

THE START-UP TWIN (the Browse card scenario)
--------------------------------------------
On a Browse card the same button widens from its queued face to the full
strip the moment the run starts, and its matrix is built by a Loader in that
same cascade, while the button is still the narrow width. A DotMatrix that
latches its settled width in Component.onCompleted, i.e. mid-cascade, opens
the bar two columns too wide for the settle interval and then sheds them
("an extra set of blocks that quickly disappear"). The settle binding rides
through the creating turn instead. The card scenario reads
the matrix 60ms into the run, inside the settle, and requires its columns
to fit from the first frame.

Runs in a SUBPROCESS like the other Main.qml scenarios: building the bridge
installs process-global handlers that must not leak into the suite.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from support.qml import (
    EXIT_OK,
    EXIT_PRECONDITION,
    EXIT_REGRESSED,
    ROLLING_ALBUM_ROW,
    boot_main_qml,
    run_scenario,
    seed_tidal_search,
)

# The steps that resize the bar: the first real percent (the "…"
# placeholder is one character), the 9 -> 10 boundary, and the 99 -> 100 one.
_STEPS = (5, 9, 10, 42, 99, 100)

# Read between steps, well inside DotMatrix's 300ms settle: waiting it out
# hides the defect from anyone reading a still.
_STEP_SETTLE_MS = 60


@pytest.mark.qml
def test_progress_matrix_keeps_its_columns_as_the_readout_grows():
    run_scenario(
        Path(__file__),
        "--run-scenario",
        sandbox_prefix="waves-dot-matrix-width-test-",
        failure_message="the progress matrix resizes mid-download again",
    )


@pytest.mark.qml
def test_browse_card_matrix_fits_from_its_first_frame():
    run_scenario(
        Path(__file__),
        "--run-card-scenario",
        sandbox_prefix="waves-dot-matrix-width-test-",
        failure_message="the Browse card's progress bar opens with stale columns again",
    )


# The button for our album, then the DotMatrix inside it. Both are found by
# property signature rather than by child index, so neither walk breaks when a
# sibling is added beside them.
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
  if (it.litCount !== undefined && it.cols !== undefined) return it;
  for (var i = 0; i < it.children.length; i++) {
   var hit = walkMx(it.children[i].item || it.children[i]);
   if (hit) return hit;
  }
  return null;
 }
"""


# The Browse card's button and its matrix: the button is the one DownloadButton
# in the tree whose mediaId is the seeded playlist's.
_CARD_WALKERS = """
 function walkBtn(it){
  if (!it) return null;
  if (it.mediaId === 'pl-roll' && it.queuedLabel !== undefined) return it;
  for (var i = 0; i < it.children.length; i++) {
   var hit = walkBtn(it.children[i].item || it.children[i]);
   if (hit) return hit;
  }
  return null;
 }
 function walkMx(it){
  if (!it) return null;
  if (it.litCount !== undefined && it.cols !== undefined) return it;
  for (var i = 0; i < it.children.length; i++) {
   var hit = walkMx(it.children[i].item || it.children[i]);
   if (hit) return hit;
  }
  return null;
 }
"""


def _run_card_scenario() -> int:
    booted = boot_main_qml()
    if isinstance(booted, int):
        return booted
    _root, q, settle, bridge = booted

    bridge._logged_in = True
    bridge.loggedInChanged.emit()
    q('root.browseStyle = "art"')
    q('root.browsePageKey = "lab"')
    q(
        'root.browsePage = { key: "lab", title: "Lab shelf", sections: ['
        '{ rowKind: "cards", title: "PLAYLISTS", items: ['
        '{ kind: "playlist", id: "pl-roll", title: "Rolling Playlist", artist: "", year: "",'
        ' tracks: 40, art: "", artists: [], quality: "LOSSLESS" }'
        '], more: "", data: "", total: 0, offset: 0, modType: "" }] }'
    )
    settle(900)
    # The strip only rises under the cursor; pin the card's riser open the way
    # the browse-card scenarios do (its `on` gate is the only thing changed).
    lit = int(
        q(
            "(function(){var n=0;function w(o){if(!o)return;"
            "if(o.acPvSt!==undefined){o.on=true;n++}"
            "var c=o.children;if(c)for(var i=0;i<c.length;++i)w(c[i])}"
            "w(browseDrill);return n})()"
        )
    )
    if lit < 1:
        print("no ArtCard riser found on the seeded shelf", file=sys.stderr)
        return EXIT_PRECONDITION
    settle(500)

    def measure() -> str:
        return str(
            q(
                "(function(){" + _CARD_WALKERS + " var b = walkBtn(browseDrill); if (!b) return 'shape:button';"
                " var m = walkMx(b); if (!m) return 'shape:matrix';"
                " function r2(v){ return Math.round(v * 100) / 100 }"
                " return 'mx:' + [r2(m.width), m.cols, m.dot, m.gap, r2(m._settledWidth)].join(',');"
                "})()"
            )
            or ""
        )

    # The real sequence: the click acknowledges as queued (the narrow face),
    # then the worker flips it to running with 0% (see _download).
    q("(function(){ var h = root.dlHolder('pl-roll'); h.st = 'queued'; h.pct = -1; return 1 })()")
    settle(500)
    q("(function(){ var h = root.dlHolder('pl-roll'); h.pct = 0; h.st = 'running'; return 1 })()")
    # Read INSIDE DotMatrix's 300ms settle: a matrix that latched a
    # pre-layout width is only visibly wrong until the settle timer fires.
    settle(_STEP_SETTLE_MS)
    first = measure()
    settle(600)
    later = measure()

    for rep in (first, later):
        if not rep.startswith("mx:"):
            print(f"could not locate the card's running dot matrix ({rep})", file=sys.stderr)
            return EXIT_PRECONDITION
    parsed = {}
    for tag, rep in (("first", first), ("settled", later)):
        width, cols, dot, gap, settled = (float(v) for v in rep[len("mx:") :].split(","))
        parsed[tag] = (width, int(cols), dot, gap, settled)

    failures: list[str] = []
    width, cols, dot, gap, settled = parsed["first"]
    extent = cols * (dot + gap) - gap
    if extent > width + 0.5:
        failures.append(
            f"  {_STEP_SETTLE_MS}ms into the run: {cols} columns need {round(extent, 2)}px but the "
            f"matrix is {width}px wide (settled width {settled}px), so the bar opens with "
            f"{max(1, int((extent - width) / (dot + gap)) + 1)} stale column(s)"
        )
    if abs(settled - width) > 0.5:
        failures.append(f"  {_STEP_SETTLE_MS}ms into the run: settled width {settled}px lags the real {width}px")
    if parsed["settled"][1] != cols:
        failures.append(f"  the column count moved after the settle: {cols} -> {parsed['settled'][1]}")
    if failures:
        print("the Browse card's progress bar opens with stale columns:", file=sys.stderr)
        print("\n".join(failures), file=sys.stderr)
        print(f"first {first}\nsettled {later}", file=sys.stderr)
        return EXIT_REGRESSED
    print(f"card matrix fit from the first frame: {first}", flush=True)
    return EXIT_OK


def _run_scenario() -> int:
    booted = boot_main_qml()
    if isinstance(booted, int):
        return booted
    _root, q, settle, _bridge = booted
    q("root.openSearch()")
    seed_tidal_search(q, _bridge, albums=[ROLLING_ALBUM_ROW], expanded=("albums",))
    q("root.searchReveal = 1")
    q("root.searchBuilding = false")
    settle(700)

    def measure() -> str:
        return str(
            q(
                "(function(){" + _WALKERS + " var b = walkBtn(contentCol); if (!b) return 'shape:button';"
                " var m = walkMx(b); if (!m) return 'shape:matrix';"
                " var readout = 0;"
                " var sibs = m.parent ? m.parent.children : [];"
                " for (var i = 0; i < sibs.length; i++)"
                "  if (sibs[i] !== m && sibs[i].width !== undefined) readout = sibs[i].width;"
                " function r2(v){ return Math.round(v * 100) / 100 }"
                " return 'mx:' + [r2(m.width), m.cols, m.dot, m.gap, m.fillTotal, m.litCount, r2(readout)].join(',');"
                "})()"
            )
            or ""
        )

    # Start the download and let the very first frame settle completely, so the
    # baseline is the matrix at rest, not one mid-roll.
    q("(function(){ var h = root.dlHolder('al-roll'); h.st = 'running'; h.pct = -1; return 1 })()")
    settle(700)

    readings: list[tuple[int, str]] = []
    for pct in _STEPS:
        q(f"(function(){{ root.dlHolder('al-roll').pct = {pct}; return 1 }})()")
        # The width is read INSIDE the step (that is the defect this guards);
        # the lit count at 100% is read only once the holder's jump ramp (a
        # forward leap is filled over up to 1.5s, not snapped) has landed.
        settle(_STEP_SETTLE_MS if pct < 100 else 1700)
        readings.append((pct, measure()))

    bad = [(pct, rep) for pct, rep in readings if not rep.startswith("mx:")]
    if bad:
        print(f"could not locate the running download's dot matrix ({bad[0][1]})", file=sys.stderr)
        return EXIT_PRECONDITION

    parsed = []
    for pct, rep in readings:
        width, cols, dot, gap, total, lit, readout = (float(v) for v in rep[len("mx:") :].split(","))
        parsed.append((pct, width, int(cols), dot, gap, int(total), int(lit), readout))

    failures: list[str] = []
    base_width = parsed[0][1]
    for pct, width, cols, dot, gap, total, lit, readout in parsed:
        # The reservation itself: the readout's digit count must not move the
        # matrix's right edge.
        if abs(width - base_width) > 0.5:
            failures.append(
                f"  at {pct}%: matrix width {width}px, was {base_width}px at 5% "
                f"(the readout is {readout}px wide, so it is still reflowing)"
            )
        # The visible defect: the columns laid out must fit the item drawing them.
        extent = cols * (dot + gap) - gap
        if extent > width + 0.5:
            failures.append(
                f"  at {pct}%: {cols} columns need {round(extent, 2)}px but the matrix "
                f"is {width}px wide, so its last "
                f"{max(1, int((extent - width) / (dot + gap)) + 1)} column(s) draw past the edge"
            )
        # And a finished bar reads full.
        if pct == 100 and lit != total:
            failures.append(f"  at 100%: {lit} of {total} fill dots lit (pads excluded)")

    if failures:
        print("the dot matrix moves while the percentage readout grows:", file=sys.stderr)
        print("\n".join(failures), file=sys.stderr)
        print("readings (pct, width, cols, dot, gap, total, lit, readout):", file=sys.stderr)
        for row in parsed:
            print(f"  {row}", file=sys.stderr)
        return EXIT_REGRESSED

    print(f"matrix held {base_width}px across {[p for p, *_ in parsed]}", flush=True)
    return EXIT_OK


if __name__ == "__main__":
    if "--run-scenario" in sys.argv:
        raise SystemExit(_run_scenario())
    if "--run-card-scenario" in sys.argv:
        raise SystemExit(_run_card_scenario())
    raise SystemExit("run this file through pytest")
