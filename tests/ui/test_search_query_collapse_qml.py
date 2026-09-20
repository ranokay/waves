"""The search field sends the words it shows, and says when a search found
nothing.

A pasted title with a line break reads as one line in the single-line field,
and the break must not reach the bridge: pressing Enter rewrites the field to
the collapsed query and sends that, and the paste decoder collapses the same
way. A search that answers with nothing replaces the "begin" hint with
"No results for ..." so the page never looks untouched.

Runs in a SUBPROCESS like the other Main.qml scenarios.
"""

from __future__ import annotations

import sys

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
def test_search_query_collapses_and_an_empty_answer_says_so():
    run_scenario(
        __file__,
        "--run-scenario",
        timeout=120,
        sandbox_prefix="waves-query-collapse-test-",
        failure_message="search query hygiene regressed",
    )


def _run_scenario() -> int:
    try:
        from PySide6.QtCore import QEventLoop, QTimer, QUrl
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtQml import QQmlApplicationEngine, QQmlEngine, QQmlExpression
    except Exception as exc:
        print(f"Qt unavailable: {exc}", file=sys.stderr)
        return EXIT_NO_QT

    from support.offline import PARK_LOGIN_QML, patch_offline

    patch_offline()

    app = QGuiApplication.instance() or QGuiApplication([])
    sandbox_qml_settings()
    try:
        from PySide6.QtCore import Slot

        from waves.desktop.app import _load_mono
        from waves.desktop.backend import WavesBridge
    except Exception as exc:
        print(f"Qt platform/backend unavailable: {exc}", file=sys.stderr)
        return EXIT_NO_QT

    searched: list[str] = []

    class SpyBridge(WavesBridge):
        @Slot(str)
        def search(self, needle: str) -> None:
            searched.append(needle)

    engine = QQmlApplicationEngine()
    bridge = SpyBridge(tidal=None)
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
    q(PARK_LOGIN_QML)
    q("browseOpen = false")
    verdicts = {}

    # Enter on a field holding an invisible line break sends one space.
    # Typed in steps under the decoder's 4-char paste threshold, so the field
    # keeps the raw text (a one-jump assignment reads as a paste and decodes).
    typed = "Record\nSoft  Power"
    q("searchField.forceActiveFocus(); searchField.clear()")
    for i in range(3, len(typed) + 3, 3):
        q(f"searchField.text = {typed[:i]!r}")
    settle(50)
    raw_kept = "\n" in str(q("searchField.text"))
    q("searchField.accepted()")
    settle(50)
    verdicts["raw_text_reached_the_field"] = raw_kept
    verdicts["enter_sends_collapsed"] = searched[-1:] == ["Record Soft Power"]
    verdicts["field_shows_what_was_sent"] = q("searchField.text") == "Record Soft Power"
    verdicts["query_remembered"] = q("root.lastSearchQuery") == "Record Soft Power"

    # The paste glyph's decode path collapses a tab the same way.
    q("searchField.forceActiveFocus(); searchField.clear(); searchDecoder.submitPending = true")
    q("searchField.text = 'tab\\tseparated words'")
    settle(1200)
    verdicts["decoder_sends_collapsed"] = searched[-1:] == ["tab separated words"]

    # An empty answer says so; an answer with rows does not.
    empty = {"groups": []}
    q("root._searchSeq = root._navSeq; root.lastSearchQuery = 'zzz'")
    bridge.searchResults.emit(empty)
    settle(200)
    verdicts["empty_answer_named"] = (
        not bool(q("root.hasResults")) and q("emptyHint.text") == "No results for \u201czzz\u201d"
    )
    q("root._searchSeq = root._navSeq; root.lastSearchQuery = 'band'")
    row = {"id": "a1", "name": "Band", "art": "", "roles": "", "popularity": -1}
    bridge.searchResults.emit(
        {
            "groups": [
                {
                    "provider": "tidal",
                    "artists_layout": "strip",
                    "artists": [row],
                    "albums": [],
                    "tracks": [],
                    "videos": [],
                    "playlists": [],
                    "mixes": [],
                    "top": None,
                    "error": "",
                }
            ]
        }
    )
    settle(300)
    verdicts["rows_clear_the_hint"] = q("root.searchNoResultsFor") == "" and not bool(q("emptyHint.visible"))

    failed = [k for k, v in verdicts.items() if not v]
    for k, v in verdicts.items():
        print(f"{k}: {v}")
    return EXIT_REGRESSED if failed else EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    sys.exit(_run_scenario())
