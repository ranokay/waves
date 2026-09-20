"""The search row is live with Apple enabled and no TIDAL session.

The picker promises "Search works with no account": the row gates on
"TIDAL signed in or Apple enabled", and the placeholder names both link
types instead of TIDAL's alone. An Apple-only search that fails or finds
nothing says so in Apple's own group instead of leaving a page that reads
as an empty catalog.
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

# AppleCatalogUnavailable's words: the honest failure a catalog fetch raises
# when Apple's web app moves under the fetch.
APPLE_WORDS = "Apple changed its web app. A Waves update is needed."

# The Apple rows the stub catalog answers with. Enough for the build veil to
# have a total to wait on (a total of 0 raises no veil at all).
_ARTISTS = [{"id": f"apple:artist-{n}", "name": f"Artist {n}", "art": "", "popularity": -1} for n in range(1, 5)]


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


def _settle_until(q, settle, predicate, *, timeout_ms: int = 5000, step_ms: int = 20) -> bool:
    """Spin the event loop until the predicate holds, or its budget runs out.

    The bridge answers a search from a worker thread, so a state a payload
    produces cannot be read the moment the search is issued. ``step_ms`` 0
    samples one event-loop pass at a time: a build veil over a handful of
    cards can rise and fall inside a few milliseconds.
    """
    waited = 0
    while not predicate():
        if waited >= timeout_ms:
            return False
        settle(step_ms)
        waited += max(step_ms, 1)
    return True


def _apple_answer(artists=None) -> dict:
    """An AppleProvider.search reply, shaped like the provider's own."""
    return {
        "artists": list(artists or []),
        "albums": [],
        "tracks": [],
        "videos": [],
        "playlists": [],
        "mixes": [],
        "top": None,
    }


def _check_states(bridge, q, settle) -> tuple[bool, bool, bool, bool]:
    """(loading hint, in-group error + retry, empty state, no ghost head) for
    an Apple-only signed-out user.

    No account can answer in this sandbox, so the Apple catalog is stubbed;
    every step below still goes through the bridge's real search slot and the
    QML's real payload handler, so the states are the states a user gets. The
    stub answers rows, fails once for "flaky" (the fetch error Apple's own
    exception carries), and finds nothing for "nothingmatches". The
    group lives on the page's provider groups and is read through
    root.searchGroupFor('apple').
    """
    from waves.providers.apple import AppleCatalogUnavailable

    apple = "root.searchGroupFor('apple')"
    bridge.settings.data.apple_enabled = True
    bridge.appleStatusChanged.emit()
    _settle_until(q, settle, lambda: q("appleEnabled"), timeout_ms=2000, step_ms=10)

    searches: list[str] = []

    def catalog(needle: str) -> dict:
        searches.append(needle)
        if needle == "flaky" and searches.count("flaky") == 1:
            raise AppleCatalogUnavailable()
        return _apple_answer([] if needle == "nothingmatches" else _ARTISTS)

    bridge.providers["apple"].search = catalog

    # The loading hint follows the providers that can issue a search, and the
    # veil's build total counts the Apple rows: an Apple-only signed-out
    # search has to enter the building state (a total of 0 raises no veil at
    # all, so the hint would never show).
    q("root.submitSearch('hello')")
    hint_seen = False

    def _rows_landed() -> bool:
        nonlocal hint_seen
        hint_seen = hint_seen or bool(q("searchBuildHint.active"))
        return bool(q(apple)) and q(apple + ".rowCount") == len(_ARTISTS)

    rows_landed = _settle_until(q, settle, _rows_landed, step_ms=0)
    # The veil's total is what holds it up until every Apple card has loaded:
    # the rendered hint proves it rose, this proves it counted the rows.
    build_total_ok = q("root._searchBuildTotal") == len(_ARTISTS)
    veil_down = _settle_until(q, settle, lambda: not bool(q("searchBuildHint.active")))
    loading_ok = rows_landed and build_total_ok and hint_seen and veil_down

    # A failed Apple fetch shows the honest words in its own group with a
    # RETRY, and the RETRY issues the search again: the words give way to the
    # rows when the fetch answers.
    q("root.submitSearch('flaky')")
    error_shown = _settle_until(q, settle, lambda: q(apple + ".errorText") == APPLE_WORDS)
    error_ok = (
        error_shown
        and bool(_find_visible(q, "searchGroupError"))
        and bool(_find_visible(q, "searchGroupRetry"))
        # A failed fetch is not an empty catalog: the page never reports the
        # query as having found nothing, and its own line names the failure
        # instead of inviting a first search it already ran.
        and q("root.searchNoResultsFor") == ""
        and q("root.searchGroupError") == APPLE_WORDS
        and q("emptyHint.text") == "Search failed"
    )
    # The head answers to the same type filter as the group's rows: Apple
    # serves no videos or mixes, so that filter never shows its head -- error
    # or not -- while the filters it does answer under keep it.
    q("root.filterType = 'videos'")
    filter_ok = _settle_until(q, settle, lambda: not bool(q(apple + ".headVisible")), timeout_ms=1000, step_ms=5)
    q("root.filterType = 'tracks'")
    filter_ok = filter_ok and _settle_until(
        q, settle, lambda: bool(q(apple + ".headVisible")), timeout_ms=1000, step_ms=5
    )
    q("root.filterType = 'all'")
    q("(" + (_FIND_VISIBLE % "searchGroupRetry") + ").clicked()")
    retried = _settle_until(
        q, settle, lambda: q(apple + ".errorText") == "" and q(apple + ".rowCount") == len(_ARTISTS)
    )
    error_ok = error_ok and filter_ok and retried and searches.count("flaky") == 2

    # An Apple-only signed-out search that finds nothing shows its own empty
    # state: the payload was accepted (the group is mounted, no stale error
    # stands) and the page names the query instead of reading as a blank one.
    q("root.submitSearch('nothingmatches')")
    empty_shown = _settle_until(q, settle, lambda: q("root.searchNoResultsFor") == "nothingmatches")
    empty_ok = (
        empty_shown
        and bool(q("emptyHint.visible"))
        and q(apple + ".errorText") == ""
        and bool(q(apple))
        and q(apple + ".rowCount") == 0
    )

    # Switching Apple off clears the group; a refresh landing afterwards (the
    # in-place revalidation of a page built with Apple on) still carries the
    # group, and must not resurrect a head for a provider that is off.
    bridge.settings.data.apple_enabled = False
    bridge.appleStatusChanged.emit()
    cleared = _settle_until(q, settle, lambda: not bool(q(apple)), timeout_ms=2000, step_ms=10)
    q("root._searchSeq = root._navSeq")
    bridge.searchResults.emit({**_payload(error=APPLE_WORDS), "refresh": True})
    settle(150)
    # The refresh cannot mount the provider's group, so there is no head, no
    # words and no retry anywhere.
    ghost_ok = (
        cleared
        and not bool(q(apple))
        and q("root.searchGroupError") == ""
        and not bool(_find_visible(q, "searchGroupError"))
        and not bool(_find_visible(q, "searchGroupRetry"))
    )
    return loading_ok, error_ok, empty_ok, ghost_ok


def _payload(*, error: str) -> dict:
    """A one-group Apple payload, shaped like the bridge's own."""
    return {
        "groups": [
            {
                "provider": "apple",
                "artists_layout": "flow",
                "artists": [],
                "albums": [],
                "tracks": [],
                "playlists": [],
                "top": None,
                "error": error,
            }
        ]
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
    _settle_until(
        q,
        settle,
        lambda: q("appleEnabled") and q("searchField.enabled") and q("sortBox.enabled"),
        timeout_ms=2000,
        step_ms=10,
    )
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
    _settle_until(
        q, settle, lambda: not q("searchField.enabled") and not q("sortBox.enabled"), timeout_ms=2000, step_ms=10
    )
    back_off_ok = not q("searchField.enabled") and not q("sortBox.enabled")

    # Leave Apple on for the state checks that follow.
    bridge.settings.data.apple_enabled = True
    bridge.appleStatusChanged.emit()
    _settle_until(q, settle, lambda: q("appleEnabled"), timeout_ms=2000, step_ms=10)
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
        from waves.desktop.app import _load_mono
        from waves.desktop.backend import WavesBridge
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
    loading_ok, error_ok, empty_ok, ghost_ok = _check_states(bridge, q, settle)

    if not off_ok:
        print("with TIDAL signed out and Apple off the search row is not inert", file=sys.stderr)
    if not on_ok:
        print("an Apple-only signed-out session did not get a live search row", file=sys.stderr)
    if not back_off_ok:
        print("switching Apple off left the search row live", file=sys.stderr)
    if not loading_ok:
        print("the build hint ignored an Apple-only signed-out search", file=sys.stderr)
    if not error_ok:
        print("a failed Apple fetch did not show its own group error and a retry that re-searches", file=sys.stderr)
    if not empty_ok:
        print("an Apple-only signed-out empty search showed no empty state", file=sys.stderr)
    if not ghost_ok:
        print("a refresh after Apple was switched off put the group head back", file=sys.stderr)
    return (
        EXIT_OK
        if off_ok and on_ok and back_off_ok and loading_ok and error_ok and empty_ok and ghost_ok
        else EXIT_REGRESSED
    )


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_run_scenario())
