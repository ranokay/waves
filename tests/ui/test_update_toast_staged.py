"""The update toast never names a version the restart will not land.

WHAT THIS FENCES OFF
--------------------
install() refuses to stage a second update over an already-armed helper, on
purpose: the two would race the same backup folder (tests/ui/test_updater.py
pins that refusal). Handing back the STAGED result in that case, before it has
looked at the release it was asked for, breaks the toast:

With a swap staged and never restarted into, the toast offers a newer release,
the user presses INSTALL, the toast says that newer version was installed, and
the restart lands the staged one. The Settings card is honest throughout (it
pins the staged version into its own copy); the toast is not, because it
renders its own idea of the version and was never told the install went
nowhere near it.

HOW THIS STAYS FIXED
--------------------
An offer is refused outright while a restart is pending (the pill goes on
saying what the restart will give, and the newer release is offered again by
the check that follows the restart), and the installed label reads the staged
version whenever the app knows one.

Runs in a SUBPROCESS for the same reason as the other QML scenarios: building
the bridge installs process-global handlers that must not leak into the suite.
"""

from __future__ import annotations

import sys
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

# Staged yesterday, never restarted into. Spelled as the release TAG, which is
# what the updater stores: everything the UI prints puts its own "v" in front,
# so an unstripped tag renders "Waves vv0.1.26".
_STAGED_TAG = "v0.1.26"
_STAGED = "0.1.26"
_NEWER = "0.1.27"  # published since, and what the check finds today


@pytest.mark.qml
def test_the_toast_does_not_offer_over_a_staged_restart():
    run_scenario(
        Path(__file__),
        "--run-scenario",
        timeout=120,
        sandbox_prefix="waves-toaststaged-test-",
        failure_message="the staged-install toast regressed:",
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
        from support.offline import patch_offline

        from waves.desktop.app import _load_mono
        from waves.desktop.backend import WavesBridge
    except Exception as exc:
        print(f"Qt platform/backend unavailable: {exc}", file=sys.stderr)
        return EXIT_NO_QT

    patch_offline()
    engine = QQmlApplicationEngine()
    bridge = WavesBridge(tidal=None)
    # A swap staged in an earlier session and re-armed at this launch. This is
    # exactly the shape resume_pending_apply leaves behind (and the shape the
    # updater's own tests use), so status() reports the restart as pending.
    bridge._updater._armed_result = {
        "ok": True,
        "version": _STAGED_TAG,
        "applied_to": "staged",
        "relaunch": True,
    }
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

    def settle(ms: int = 150) -> None:
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    settle()
    if not q("waves.appUpdateStatus().pending_restart"):
        print("the staged swap did not read as a pending restart", file=sys.stderr)
        return EXIT_PRECONDITION

    # The check finds the newer release and asks the toast to offer it.
    q(f'updateToast.offer("{_NEWER}")')
    settle()
    phase = q("updateToast.phase")
    print(f"phase_after_offer={phase!r}", flush=True)
    if phase:
        # The offer overwrote the restart pill.
        print(
            "the toast offered an install over an update already staged: pressing it hands back the "
            "staged result, so the restart lands the other version.",
            file=sys.stderr,
        )
        return EXIT_REGRESSED

    # And whatever the toast is showing when an install reports done, the
    # version it names is the one the restart will actually land.
    q(f'updateToast.version = "{_NEWER}"')
    landed = q("updateToast.landedVersion()")
    print(f"landed={landed!r} staged={_STAGED!r} tag={_STAGED_TAG!r}", flush=True)
    # The staged version, and spelled the way the label can print it: the label
    # supplies the "v" itself, so handing back the raw tag reads "vv0.1.26".
    if landed != _STAGED:
        # The label promised a version nobody staged.
        print("the toast said a version was installed that the restart will not land.", file=sys.stderr)
        return EXIT_REGRESSED

    # The label is what the user reads, so it has to be the one asking. Pinned
    # on the label's own expression, not merely on the function existing.
    label = '"Waves v" + updateToast.landedVersion() + " installed"'
    if label not in QML_MAIN.read_text(encoding="utf-8"):
        print("the installed label no longer asks what the restart will land", file=sys.stderr)
        return EXIT_REGRESSED

    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_run_scenario())
