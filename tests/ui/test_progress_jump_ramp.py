"""A download bar that jumps forward fills to the new point at speed, it does
not snap.

WHAT THIS FENCES OFF
--------------------
Start (or resume) an album or playlist that is already partly saved: the
owned tracks are skipped in one burst and the engine's progress leaps, say,
0 to 40 in a beat. The Browse card's pill and the small icon button used to
snap straight to that point (livetest report, 2026-08-17). The user asked for
the bar to fill up to it quickly and then carry on as normal.

The ramp lives in the one place every download control reads from: the media
id's holder (root.dlHolder). ``pct`` is what the engine says; ``shownPct`` is
what the controls draw (root.dlPct returns it) and rides pct with a forward
jump of more than 3 points filled LINEARLY over 200ms + 22ms a point, 1.5s at
most. An ordinary tick (a fraction of a point) still lands at once, so a bar
that is merely downloading is unchanged; a fall (a new run resetting the
holder) and the first reading snap; hover motion off snaps everything.

The first cut at this rode OutCubic over 8ms a point and was livetested as
still "basically all fill at once": OutCubic spends half its travel in the
first fifth of the duration, so the blocks it lights arrive in a burst
whatever the total. The bar's blocks light in fill order, so an even cadence
is the whole point, and linear is what gives it one.

HOW THIS STAYS FIXED
--------------------
The real Main.qml is booted offscreen and a holder is driven straight: a
small step reads through at once; a 0 -> 40 leap reads strictly between the
two 200ms in, is still short of half way at that point (the burst the
livetest caught would be past it), and reads exactly 40 once landed; a
retarget mid-ramp keeps moving to the new target without snapping; a fall
snaps; and with hover motion off the same leap snaps.

Runs in a SUBPROCESS like the other Main.qml scenarios (shares
``support.qml.boot_main_qml``).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from support.paths import QML_MAIN
from support.qml import EXIT_OK, EXIT_PRECONDITION, EXIT_REGRESSED, run_scenario


@pytest.mark.qml
def test_a_forward_jump_fills_at_speed_and_a_tick_lands_at_once():
    run_scenario(
        Path(__file__),
        "--run-ramp-scenario",
        sandbox_prefix="waves-jump-ramp-test-",
        failure_message="the download bar snaps on a jump again",
    )


def test_the_controls_read_the_ramped_value():
    src = QML_MAIN.read_text()
    a = src.index("function dlPct(id)")
    body = src[a : src.index("function dlSt(id)", a)]
    assert "h.shownPct" in body, "dlPct must hand controls the ramped shownPct"
    a = src.index("id: dlHolderComp")
    holder = src[a : src.index("function dlHolder(id)", a)]
    assert "Behavior on shownPct" in holder, "the holder lost its ramp"
    assert "d > 3" in holder, "the ramp threshold (a forward jump of more than 3 points) moved"
    assert "Math.min(1500, 200 + d * 22)" in holder, "the ramp timing (200ms + 22ms a point, 1.5s cap) moved"
    assert "Easing.Linear" in holder, "the ramp must be linear: an eased one lights the blocks in a burst"
    assert "root.hoverMotion" in holder, "the ramp must snap when hover motion is off"


# ---------------------------------------------------------------------------
# The scenario itself
# ---------------------------------------------------------------------------


def _run_ramp_scenario() -> int:
    from support.qml import boot_main_qml

    booted = boot_main_qml()
    if isinstance(booted, int):
        return booted
    _root, q, settle, _bridge = booted

    def put(pct: float) -> None:
        q(f"(function(){{ var h = root.dlHolder('ramp-1'); h.st = 'running'; h.pct = {pct}; return 1 }})()")

    def shown() -> float:
        return float(q("root.dlPct('ramp-1')"))

    failures: list[str] = []

    # first reading snaps
    put(0)
    settle(40)
    if shown() != 0:
        failures.append(f"  the first reading did not snap: {shown()}")

    # an ordinary tick lands at once
    put(2)
    settle(40)
    if shown() != 2:
        failures.append(f"  a 2-point tick did not land at once: {shown()}")

    # a leap fills over time, at an even cadence: 200ms into a ramp of about
    # a second the bar is a fifth of the way, not most of it
    put(40)
    settle(200)
    mid = shown()
    if not (2 < mid < 21):
        failures.append(f"  200ms into a 2 -> 40 leap the bar reads {mid}: expected an early, even climb")
    settle(1100)
    if shown() != 40:
        failures.append(f"  the leap did not land on 40: {shown()}")

    # a retarget mid-ramp keeps moving, no snap, and lands on the new target
    put(60)
    settle(120)
    a = shown()
    put(90)
    settle(120)
    b = shown()
    if not (40 < a < 60 and a < b < 90):
        failures.append(f"  retarget mid-ramp: read {a} then {b}, expected a steady climb short of 60 then short of 90")
    settle(1400)
    if shown() != 90:
        failures.append(f"  the retargeted ramp did not land on 90: {shown()}")

    # a fall snaps (a new run resets the holder)
    put(-1)
    settle(40)
    if shown() != -1:
        failures.append(f"  a fall did not snap: {shown()}")

    # hover motion off: the same leap snaps
    q("root.hoverMotion = false")
    put(0)
    settle(40)
    put(40)
    settle(40)
    if shown() != 40:
        failures.append(f"  with hover motion off the leap did not snap: {shown()}")
    q("root.hoverMotion = true")

    if failures:
        print("the download bar's jump ramp regressed:", file=sys.stderr)
        print("\n".join(failures), file=sys.stderr)
        return EXIT_REGRESSED
    print("jump ramp ok", flush=True)
    return EXIT_OK


if __name__ == "__main__":
    if "--run-ramp-scenario" in sys.argv:
        raise SystemExit(_run_ramp_scenario())
    raise SystemExit(EXIT_PRECONDITION)
