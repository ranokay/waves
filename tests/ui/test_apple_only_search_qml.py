"""The search row is live with Apple enabled and no TIDAL session (J2).

The picker promises "Search works with no account", but the row gated on
``root.signedIn`` alone, so an Apple-only user could not type a query. The
row now gates on "TIDAL signed in or Apple enabled", and the placeholder
names both link types instead of TIDAL's alone.
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


@pytest.mark.qml
def test_search_row_is_live_for_an_apple_only_signed_out_user():
    run_scenario(
        Path(__file__),
        "--run-scenario",
        timeout=120,
        sandbox_prefix="waves-apple-only-search-test-",
        failure_message="the Apple-only search row scenario regressed",
        drop=("waves.qt",),
    )


_FIND_VISIBLE = """
(function () {
    function walk(o) {
        if (!o) return null;
        if (o.objectName === "%s" && o.visible === true && o.width > 0) return o;
        var kids = o.children || [];
        for (var i = 0; i < kids.length; i++) {
            var hit = walk(kids[i]);
            if (hit) return hit;
        }
        if (o.contentItem) { var c = walk(o.contentItem); if (c) return c; }
        if (o.item) { var it = walk(o.item); if (it) return it; }
        return null;
    }
    return walk(root);
})()
"""


def _find_visible(q, object_name: str):
    """The visible object with that objectName, or a falsy value."""
    return q(_FIND_VISIBLE % object_name)


def _check_states(bridge, q, settle) -> tuple[bool, bool, bool]:
    """(loading hint, in-group error + retry, empty state) for an Apple-only
    signed-out user (issues #241 / UI-05, UI-06)."""
    # The loading hint follows the providers that can issue a search: an
    # Apple-only signed-out search builds visibly too.
    bridge.settings.data.apple_enabled = True
    bridge.appleStatusChanged.emit()
    settle(300)
    q("root.searchBuilding = true")
    settle(150)
    loading_on = bool(q("searchBuildHint.active"))
    q("root.searchBuilding = false")
    settle(150)
    loading_ok = loading_on and not bool(q("searchBuildHint.active"))

    # A failed Apple fetch shows the honest words in its own group with a
    # RETRY, and the group's count gives way. The sequence stamp is what the
    # QML accepts a payload by: a real search sets it, this emits directly.
    error = "Apple changed its web app. A Waves update is needed."
    q("root._searchSeq = root._navSeq")
    bridge.searchResults.emit(_payload(error=error))
    settle(400)
    error_ok = (
        q("root.appleSearchError") == error
        and bool(_find_visible(q, "appleSearchError"))
        and bool(_find_visible(q, "appleSearchRetry"))
    )

    # An Apple-only signed-out search that finds nothing shows its empty state:
    # the page is not blank.
    q("root._searchSeq = root._navSeq")
    bridge.searchResults.emit(_payload(error=""))
    settle(400)
    empty_ok = bool(q("emptyHint.visible"))
    return loading_ok, error_ok, empty_ok


def _payload(*, error: str) -> dict:
    apple = {
        "artists": [],
        "albums": [],
        "tracks": [],
        "videos": [],
        "playlists": [],
        "mixes": [],
        "top": None,
        "error": error,
    }
    return {
        "artists": [],
        "albums": [],
        "tracks": [],
        "videos": [],
        "playlists": [],
        "mixes": [],
        "top": None,
        "apple": apple,
    }


def _check_row_gate(bridge, q, settle) -> tuple[bool, bool, bool]:
    """(inert with Apple off, live with Apple on, inert again) for a
    TIDAL-signed-out session."""
    # TIDAL signed out and Apple off: the row and both controls are inert.
    off_ok = (
        not q("signedIn")
        and not q("searchField.enabled")
        and not q("sortBox.enabled")
        and q("searchBox.parent.opacity") == 0.5
    )

    # Apple on: the same signed-out session gets a live field and sort control.
    bridge.settings.data.apple_enabled = True
    bridge.appleStatusChanged.emit()
    settle(500)
    on_ok = (
        q("appleEnabled")
        and q("searchField.enabled")
        and q("sortBox.enabled")
        and q("searchBox.parent.opacity") == 1
        and q("searchField.placeholderText") == "Search, or paste a TIDAL or Apple Music link…"
    )

    # Apple off again: the gate follows the setting, not a one-way latch.
    bridge.settings.data.apple_enabled = False
    bridge.appleStatusChanged.emit()
    settle(500)
    back_off_ok = not q("searchField.enabled") and not q("sortBox.enabled")

    # Leave Apple on for the state checks that follow.
    bridge.settings.data.apple_enabled = True
    bridge.appleStatusChanged.emit()
    settle(300)
    return off_ok, on_ok, back_off_ok


def _run_scenario() -> int:  # noqa: C901 (one straight scenario)
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
        from support.offline import PARK_LOGIN_QML, patch_offline

        patch_offline()
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
    if not engine.rootObjects():
        print("Main.qml failed to load", file=sys.stderr)
        return EXIT_PRECONDITION
    root = engine.rootObjects()[0]
    root.setProperty("width", 1100)
    root.setProperty("height", 900)

    def q(expression: str):
        context = QQmlEngine.contextForObject(root)
        value = QQmlExpression(context, root, expression)
        result = value.evaluate()
        if value.hasError():
            raise RuntimeError(value.error().toString())
        return result[0] if isinstance(result, tuple) else result

    def settle(timeout_ms: int = 300) -> None:
        loop = QEventLoop()
        QTimer.singleShot(timeout_ms, loop.quit)
        loop.exec()

    # Let the launch sequence hand over: mainColumn gates every control until
    # uiShown, so the row's own enable gate is only readable afterwards.
    settle(3000)
    q(PARK_LOGIN_QML)
    q("openSearch()")
    settle()

    off_ok, on_ok, back_off_ok = _check_row_gate(bridge, q, settle)
    loading_ok, error_ok, empty_ok = _check_states(bridge, q, settle)

    if not off_ok:
        print("with TIDAL signed out and Apple off the search row is not inert", file=sys.stderr)
    if not on_ok:
        print("an Apple-only signed-out session did not get a live search row", file=sys.stderr)
    if not back_off_ok:
        print("switching Apple off left the search row live", file=sys.stderr)
    if not loading_ok:
        print("the build hint ignored an Apple-only signed-out search", file=sys.stderr)
    if not error_ok:
        print("a failed Apple fetch did not show its own group error and retry", file=sys.stderr)
    if not empty_ok:
        print("an Apple-only signed-out empty search showed no empty state", file=sys.stderr)
    return EXIT_OK if off_ok and on_ok and back_off_ok and loading_ok and error_ok and empty_ok else EXIT_REGRESSED


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_run_scenario())
