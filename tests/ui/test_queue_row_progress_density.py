"""A running queue row's progress bar is the dense grid, and its slot fits it.

WHAT THIS FENCES OFF
--------------------
The queue drawer's per-row bar was two rows of 4px cells with 4px gaps in a
12px slot while the download button's running face had moved to a dense grid
(five rows of 3px cells, 1px gaps). The queue progress lab (2026-08-17, six
densities side by side in the real drawer) picked FOUR rows of 3px cells with
1px gaps: the same family as the button, 15px tall, so the running row grows
three pixels for it. Two things can drift apart here: the matrix geometry and
the slot the row keeps for it (the slot clips, so a slot shorter than the
matrix silently cuts off its bottom row).

HOW THIS STAYS FIXED
--------------------
On the real Main.qml offscreen: a running row is seeded through the bridge,
and the row's matrix must be exactly as tall as its slot, span the row (its
width is the row's content width, not a fixed number), fade its ends over 28px
(rounds 2-4 of the lab: the download face's conveyor fade, a shade shorter
than a shelf's) and shade its top and bottom rows' cells from 15% at their
outer edge (a gradient on those cells only; the middle rows stay flat). The
geometry is read off the rendered matrix, never off the QML source.

Runs in a SUBPROCESS like the other Main.qml scenarios (shares
``support.qml.boot_main_qml``).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from support.qml import EXIT_OK, EXIT_REGRESSED, boot_main_qml, run_scenario

_WALK = """
 function walk(it, pred){
  if (!it) return null;
  if (pred(it)) return it;
  for (var i = 0; i < it.children.length; i++) {
   var hit = walk(it.children[i].item || it.children[i], pred);
   if (hit) return hit;
  }
  return null;
 }
 function mx(){ return walk(queueDrawer.contentItem, function(it){ return it.objectName === 'queueRowMatrix' }) }
"""


@pytest.mark.qml
def test_running_queue_row_slot_fits_its_bar():
    run_scenario(
        Path(__file__),
        "--run-queue-row-scenario",
        sandbox_prefix="waves-queue-row-density-test-",
        failure_message="the queue row's bar and its slot disagree again",
    )


@pytest.mark.qml
def test_a_queue_row_that_is_not_running_builds_no_bar():
    """Hiding the bar is not sparing it.

    The slot collapses to height 0 and opacity 0 when a row is not running, but
    an invisible subtree is still BUILT, so every QUEUED row used to pay for the
    full grid: 364 cells at the drawer's 420px floor and past a thousand with
    the drawer dragged wide. A flick through a long queue dropped frames on rows
    that show nothing. The download button's smaller matrix has sat behind a
    Loader for exactly this reason; this one did not."""
    run_scenario(
        Path(__file__),
        "--run-queue-row-idle-scenario",
        sandbox_prefix="waves-queue-row-density-test-",
        failure_message="a queue row is building its bar with nothing to show",
    )


def _scenario() -> int:
    booted = boot_main_qml()
    if not isinstance(booted, tuple):
        return booted
    _root, q, settle, bridge = booted
    qid = bridge._enqueue("Density Row", "track", media_id="lab-density", artist="Lab", tracks=0)
    # Through the real mutators: a poked field is invisible to the delta
    # protocol (nothing marks it), so the row would stay queued on screen.
    bridge._set_queue_status(qid, "running")
    bridge._set_queue_progress(qid, 37)
    settle(120)
    q("queueDrawer.open()")
    settle(900)  # past the slot's 300ms grow and the drawer's slide
    got = q(
        "(function(){" + _WALK + " var m = mx(); if (!m) return 'none';"
        " var top = null, mid = null, bot = null;"
        " for (var i = 0; i < m.children.length; i++) { var c = m.children[i]; if (c.rowTop === undefined) continue;"
        "  if (c.rowTop === 0 && !top) top = c; if (c.rowTop === 1 && !mid) mid = c; if (c.rowTop === m.rows - 1 && !bot) bot = c; }"
        " return [m.rows, m.dot, m.gap, m.implicitHeight, m.parent.height, m.width, m.parent.width, m.litCount, m.total,"
        "  m.edgeFadeW, m.edgeFadeH, m.edgeSoft, top && top.gradient ? 1 : 0, mid && mid.gradient ? 1 : 0, bot && bot.gradient ? 1 : 0].join(',') })()"
    )
    if not got or got == "none":
        print("no running row matrix found in the drawer", file=sys.stderr)
        return 78
    rows, dot, gap, ih, slot, w, pw, lit, total, fw, fh, soft, tg, mg, bg = (float(v) for v in str(got).split(","))
    failures = []
    if (rows, dot, gap) != (4, 3, 1):
        failures.append(f"geometry {rows},{dot},{gap}, wanted 4,3,1")
    if abs(ih - 15) > 0.01:
        failures.append(f"matrix implicitHeight {ih}, wanted 15")
    if abs(slot - ih) > 0.5:
        failures.append(f"the row's slot is {slot}px for a {ih}px matrix (it clips)")
    if w < 200 or abs(w - pw) > 0.5:
        failures.append(f"matrix width {w} does not span the row's {pw}")
    if not (0 < lit < total) or abs(lit / total - 0.37) > 0.02:
        failures.append(f"lit {lit} of {total} is not 37%")
    if (fw, fh) != (28, 0):
        failures.append(f"edge fade {fw}/{fh}, wanted 28 at the ends and none top/bottom")
    if abs(soft - 0.15) > 1e-6:
        failures.append(f"edgeSoft {soft}, wanted 0.15")
    if (tg, mg, bg) != (1, 0, 1):
        failures.append(f"outer-row shading gradients top/mid/bottom = {tg}/{mg}/{bg}, wanted 1/0/1")
    for f in failures:
        print(f, file=sys.stderr)
    return EXIT_REGRESSED if failures else EXIT_OK


_COUNT = """
 function count(it, pred){
  if (!it) return 0;
  var n = pred(it) ? 1 : 0;
  for (var i = 0; i < it.children.length; i++) n += count(it.children[i].item || it.children[i], pred);
  return n;
 }
 function mats(c){ return count(c, function(it){ return it.objectName === 'queueRowMatrix' }) }
 function cells(c){ return count(c, function(it){ return it.rowTop !== undefined }) }
"""


def _idle_scenario() -> int:
    """40 queued rows must build no bar at all; the first running one must."""
    booted = boot_main_qml()
    if not isinstance(booted, tuple):
        return booted
    _root, q, settle, bridge = booted

    for i in range(40):
        bridge._enqueue(f"Queued Album {i}", "album", media_id=f"idle-{i}", artist="Lab", tracks=12)
    bridge._emit_queue()
    settle(200)
    q("queueDrawer.open()")
    settle(900)

    got = q("(function(){" + _COUNT + " var c = queueDrawer.contentItem; return [mats(c), cells(c)].join(',') })()")
    if not got:
        print("could not walk the queue drawer", file=sys.stderr)
        return 78
    idle_mats, idle_cells = (int(v) for v in str(got).split(","))

    run_qid = bridge._enqueue("Running", "track", media_id="idle-run", artist="Lab", tracks=0)
    bridge._set_queue_status(run_qid, "running")
    bridge._set_queue_progress(run_qid, 50)
    settle(900)
    run_mats = int(q("(function(){" + _COUNT + " return mats(queueDrawer.contentItem) })()") or 0)

    failures = []
    if idle_mats or idle_cells:
        failures.append(f"{idle_mats} bars ({idle_cells} cells) built for 40 rows that show none")
    if run_mats < 1:
        failures.append("a running row built no bar, so the gate is stuck shut")
    for f in failures:
        print(f, file=sys.stderr)
    return EXIT_REGRESSED if failures else EXIT_OK


if __name__ == "__main__" and "--run-queue-row-scenario" in sys.argv:
    sys.exit(_scenario())

if __name__ == "__main__" and "--run-queue-row-idle-scenario" in sys.argv:
    sys.exit(_idle_scenario())
