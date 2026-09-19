"""HoverSwell must fade IN fast and OUT slow, not the other way round.

The swell is what hands the light between the PREVIEW and DOWNLOAD halves of a
two-up pill: the arriving half snaps bright (90ms, flat) while the leaving half
eases away (260ms, OutQuad), so the pointer never crosses a dark gap.

Written as a Behavior, both the animated property (``opacity: on ? 1 : 0``) and
the animation config (``duration: hs.on ? 90 : 260``) read the same flag, and
the Behavior captured the flag's OLD value when the flip triggered it. The two
durations came out exactly reversed: ~262ms to light up, ~98ms to go dark, so
crossing the divider read as a quarter-second dead spot. States and transitions
pick by direction instead, which cannot race the flag.

This samples a real HoverSwell out of Main.qml, so it measures whatever the app
actually ships rather than a copy of it. Runs in a SUBPROCESS for the same
reason as the other Main.qml scenarios: building the bridge installs
process-global handlers that must not leak into the rest of the suite.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
from support.paths import QML_MAIN
from support.qml import (
    EXIT_NO_QT,
    EXIT_OK,
    EXIT_PRECONDITION,
    EXIT_REGRESSED,
    run_scenario,
    sandbox_qml_settings,
)

# The designed durations, and the slack the measurement is allowed. Sampling is
# coarse (a 5ms event-loop tick) and an offscreen frame clock is not exact, so
# the assertions only pin each fade to its own half of the range.
_IN_MS = 90
_OUT_MS = 260
_IN_CEILING = 170
_OUT_FLOOR = 200
_OUT_CEILING = 420
_SAMPLE_MS = 5
_GIVE_UP_MS = 1500


@pytest.mark.qml
def test_hover_swell_fades_in_fast_and_out_slow():
    run_scenario(
        Path(__file__),
        "--run-scenario",
        timeout=120,
        sandbox_prefix="waves-swell-test-",
        failure_message=f"the hover swell's fade durations are inverted (in should be ~{_IN_MS}ms, out ~{_OUT_MS}ms)",
    )


def _run_scenario() -> int:
    try:
        from PySide6.QtCore import QEventLoop, QTimer, QUrl
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtQml import QQmlApplicationEngine, QQmlEngine, QQmlExpression
    except Exception as exc:
        print(f"Qt unavailable: {exc}", file=sys.stderr)
        return EXIT_NO_QT

    app = QGuiApplication.instance() or QGuiApplication([])
    sandbox_qml_settings()
    try:
        from waves.waves_ui.app import _load_mono
        from waves.waves_ui.backend import WavesBridge
    except Exception as exc:
        print(f"Qt platform/backend unavailable: {exc}", file=sys.stderr)
        return EXIT_NO_QT

    engine = QQmlApplicationEngine()
    bridge = WavesBridge(tidal=None)
    engine.rootContext().setContextProperty("waves", bridge)
    engine.rootContext().setContextProperty("monoFont", _load_mono())
    engine.rootContext().setContextProperty("uiFontFamily", app.font().family())
    engine.load(QUrl.fromLocalFile(str(QML_MAIN)))
    roots = engine.rootObjects()
    if not roots:
        print("Main.qml failed to load", file=sys.stderr)
        return EXIT_PRECONDITION
    root = roots[0]

    def q(expr: str):
        ctx = QQmlEngine.contextForObject(root)
        e = QQmlExpression(ctx, root, expr)
        r = e.evaluate()
        if e.hasError():
            raise RuntimeError(e.error().toString())
        return r[0] if isinstance(r, tuple) else r

    def settle(ms: int) -> None:
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    settle(120)
    # A real HoverSwell: its own component file since #315, resolved through
    # the qml directory import (which has to be relative: absolute paths are
    # rejected). This measures whatever the app actually ships, not a copy.
    try:
        swell = q(
            'Qt.createQmlObject(\'import QtQuick; import "."; '
            'HoverSwell { width: 40; height: 20 }\', this, "swellProbe")'
        )
    except RuntimeError as exc:
        print(f"could not instantiate HoverSwell: {exc}", file=sys.stderr)
        return EXIT_PRECONDITION
    if swell is None:
        print("HoverSwell probe came back null", file=sys.stderr)
        return EXIT_PRECONDITION

    def fade_ms(to_on: bool) -> float:
        """Wall-clock time for the opacity to finish travelling."""
        target = 1.0 if to_on else 0.0
        swell.setProperty("on", to_on)
        started = time.monotonic()
        while (time.monotonic() - started) * 1000 < _GIVE_UP_MS:
            settle(_SAMPLE_MS)
            if abs(float(swell.property("opacity")) - target) < 0.01:
                return (time.monotonic() - started) * 1000
        return float("inf")

    settle(60)
    in_ms = fade_ms(True)
    settle(300)  # fully lit and idle before timing the way back
    out_ms = fade_ms(False)

    ok_in = in_ms <= _IN_CEILING
    ok_out = _OUT_FLOOR <= out_ms <= _OUT_CEILING
    print(
        f"swell in={in_ms:.0f}ms (designed {_IN_MS}, must be <= {_IN_CEILING})"
        f" out={out_ms:.0f}ms (designed {_OUT_MS}, must be {_OUT_FLOOR}..{_OUT_CEILING})",
        flush=True,
    )
    return EXIT_OK if ok_in and ok_out else EXIT_REGRESSED


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_run_scenario())
