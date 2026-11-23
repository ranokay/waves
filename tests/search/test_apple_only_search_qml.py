"""The search row is live with Apple enabled and no TIDAL session.

The picker promises "Search works with no account": the row gates on
"TIDAL signed in or Apple enabled", and the placeholder names both link
types instead of TIDAL's alone. An Apple-only search paints the unified
page with Apple as its one source; a fetch that fails puts Apple's own
honest words on the page with a RETRY, a search that finds nothing says
so, and switching Apple off retires its source and rows in place.
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

# Apple-owned safe copy for a catalog protocol incompatibility.
APPLE_WORDS = "Apple's catalog format has changed. Check for a Waves update."

# The Apple rows the stub catalog answers with: the unified sections stand on
# them, and their cards exercise the row windows' inline opening screen.
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


_CHIP_BY_LABEL = """
(function () {
    function walk(o) {
        if (!o) return null;
        if (o.objectName === "searchTypeChip" && o.accessibleLabel === "%s") return o;
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


def _click_chip(q, label: str) -> None:
    """Click a search type chip the way the pointer does."""
    q("(" + (_CHIP_BY_LABEL % label) + ").triggered()")


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


def _check_states(bridge, q, settle) -> tuple[bool, bool, bool, bool, bool]:
    """(loading hint + chips, source error + retry, empty state, blank page,
    switch-off ghost) for an Apple-only signed-out user.

    No account can answer in this sandbox, so the Apple catalog is stubbed;
    every step below still goes through the bridge's real search slot and the
    QML's real payload handler, so the states are the states a user gets. The
    stub answers rows, fails once for "flaky" (classified by Apple's owner),
    and finds nothing for "nothingmatches". The page is the unified results
    view, read through root.searchSources and searchResultsView.
    """
    from waves.providers.apple import AppleCatalogUnavailable

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

    def sources() -> str:
        return q("(root.searchSources || []).map(function (s) { return s.provider }).join(',')")

    # The veil is the LIBRARY's wait now, never the rows': rows build by
    # window (the opening screen inline, the rest incubating with reserved
    # heights). This sandbox has no library configured, so
    # libraryIndexReady() is true and a fresh search has nothing to wait
    # for: the page is done without any hint standing.
    q("root.submitSearch('hello')")

    def _rows_landed() -> bool:
        return q("searchResultsView.countFor('artists')") == len(_ARTISTS)

    rows_landed = _settle_until(q, settle, _rows_landed, step_ms=0)
    loading_ok = rows_landed and not bool(q("searchBuildHint.active")) and sources() == "apple"

    # The type chips show for an Apple-only signed-out search with results,
    # and clicking one filters the unified sections.
    chips_visible = bool(_find_visible(q, "searchTypeChips"))
    if chips_visible:
        _click_chip(q, "Videos")
        chip_click_ok = _settle_until(
            q,
            settle,
            lambda: (
                q("root.filterType") == "videos"
                and not bool(q("searchResultsView.sectionVisible('artists')"))
                and bool(q("emptyHint.visible"))
            ),
            timeout_ms=1000,
            step_ms=5,
        )
        chip_click_ok = (
            chip_click_ok
            and q("root.filteredResultCount") == 0
            and q("emptyHint.text") == "No videos among 4 results"
            and not bool(_find_visible(q, "emptySetupCtas"))
        )
        _click_chip(q, "All")
        chip_click_ok = chip_click_ok and _settle_until(
            q,
            settle,
            lambda: (
                q("root.filterType") == "all"
                and bool(q("searchResultsView.sectionVisible('artists')"))
                and not bool(q("emptyHint.visible"))
            ),
            timeout_ms=1000,
            step_ms=5,
        )
    else:
        chip_click_ok = False
    loading_ok = loading_ok and chips_visible and chip_click_ok

    # A second Search press is the blank page: the sections and the sources
    # of the query being cleared go with it, and the rows go with the models.
    q("root.openSearch()")
    settle(120)
    blank_ok = (
        q("root.searchSources.length") == 0
        and q("Object.keys(root.searchSections).length") == 0
        and not bool(q("root.hasResults"))
        and q("searchResultsView.countFor('artists')") == 0
    )

    # A failed Apple fetch names itself on the page with a RETRY, and the
    # RETRY issues the search again: the words give way to the rows when the
    # fetch answers.
    q("root.submitSearch('flaky')")
    error_shown = _settle_until(q, settle, lambda: q("root.searchSourceError") == APPLE_WORDS)
    states = q("JSON.stringify((root.searchSources || []).map(function (s) { return [s.provider, s.state]; }))")
    error_ok = (
        error_shown
        and bool(_find_visible(q, "searchSourceError"))
        and bool(_find_visible(q, "searchSourceRetry"))
        # A failed fetch is not an empty catalog: the page never reports the
        # query as having found nothing, and its own line names the failure
        # instead of inviting a first search it already ran.
        and q("root.searchNoResultsFor") == ""
        and q("emptyHint.text") == "Search failed"
        and states == '[["apple","failed"]]'
    )
    q("(" + (_FIND_VISIBLE % "searchSourceRetry") + ").clicked()")
    retried = _settle_until(
        q,
        settle,
        lambda: q("root.searchSourceError") == "" and q("searchResultsView.countFor('artists')") == len(_ARTISTS),
    )
    error_ok = error_ok and retried and searches.count("flaky") == 2

    # An Apple-only signed-out search that finds nothing shows its own empty
    # state: the payload was accepted (the source is listed as ready, no
    # stale error stands) and the page names the query instead of reading as
    # a blank one.
    q("root.submitSearch('nothingmatches')")
    empty_shown = _settle_until(q, settle, lambda: q("root.searchNoResultsFor") == "nothingmatches")
    empty_ok = (
        empty_shown
        and bool(q("emptyHint.visible"))
        and q("root.searchSourceError") == ""
        and sources() == "apple"
        and q("searchResultsView.countFor('artists')") == 0
    )

    # Switching Apple off retires its source and its rows; a later refresh
    # from the refold the bridge runs for an in-place repaint cannot bring a
    # revoked source back.
    bridge.settings.data.apple_enabled = False
    bridge.appleStatusChanged.emit()
    bridge.providerStateChanged.emit("apple")
    cleared = _settle_until(q, settle, lambda: sources() == "" and q("searchResultsView.countFor('artists')") == 0)
    bridge.dropSearchSource("apple")
    settle(150)
    # The refolded page has no source, no rows, no words and no retry
    # anywhere.
    ghost_ok = (
        cleared
        and sources() == ""
        and q("root.searchSourceError") == ""
        and not bool(q("root.hasResults"))
        and not bool(_find_visible(q, "searchSourceError"))
        and not bool(_find_visible(q, "searchSourceRetry"))
    )
    return loading_ok, error_ok, empty_ok, blank_ok, ghost_ok


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
    loading_ok, error_ok, empty_ok, blank_ok, ghost_ok = _check_states(bridge, q, settle)

    if not off_ok:
        print("with TIDAL signed out and Apple off the search row is not inert", file=sys.stderr)
    if not on_ok:
        print("an Apple-only signed-out session did not get a live search row", file=sys.stderr)
    if not back_off_ok:
        print("switching Apple off left the search row live", file=sys.stderr)
    if not loading_ok:
        print("the build hint ignored an Apple-only signed-out search", file=sys.stderr)
    if not error_ok:
        print("a failed Apple fetch did not show its own words and a retry that re-searches", file=sys.stderr)
    if not empty_ok:
        print("an Apple-only signed-out empty search showed no empty state", file=sys.stderr)
    if not blank_ok:
        print("a second Search press left the previous search's sections or sources behind", file=sys.stderr)
    if not ghost_ok:
        print("a refresh after Apple was switched off put the retired source back", file=sys.stderr)
    return (
        EXIT_OK
        if off_ok and on_ok and back_off_ok and loading_ok and error_ok and empty_ok and blank_ok and ghost_ok
        else EXIT_REGRESSED
    )


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_run_scenario())
