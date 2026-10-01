"""The paste glyph searches what it pastes; a bare Ctrl+V still only fills.

WHAT THIS FENCES OFF
--------------------
The search bar's paste button also runs the search.
The wiring is a one-shot arm on the decode pipeline: the glyph's click sets
``searchDecoder.submitPending`` right before ``paste()``, the decode that
paste starts latches it (``submitArmed``), and ``onDecoded`` submits. The behaviors that must hold:

1. A glyph-armed paste auto-searches once the decrypt animation settles.
2. A plain paste (Ctrl+V, no glyph) fills the field but does NOT search,
   unless it is a TIDAL link (that auto-search predates the glyph arm).
3. The arm is one-shot and disarmed by any non-decode text change, so a
   stale arm (empty clipboard at click time) cannot fire on a later paste.
4. A glyph paste of three characters or fewer searches too. The decoder
   reads a paste off a >=4-char jump, which a short one cannot make,
   so the handler runs the decode itself rather than waiting for a guess.
5. A bare paste replacing a running decode restarts it without the arm:
   the armed term never submits, and the replacement fills without
   searching.
6. Enter while the decode is still animating searches the PASTED text, not
   the scramble on screen, and the settling decode does not search again
   (issue #41).

The scenario never touches the OS clipboard: a paste, to the decoder, is a
multi-char text jump typing can't produce, so the test assigns the field's
text directly, exactly the signal ``noteTextChanged`` keys on. The observable
is ``root._searchSeq``: every submit path stamps it with ``root._navSeq``
before calling ``waves.search``, so "a search fired" is a pure QML fact and
the bridge stays offline.

Runs in a SUBPROCESS like the other Main.qml scenarios: building the bridge
installs process-global handlers that must not leak into the suite.
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

# The heaviest QML boot: excluded from the quick QML pass.
pytestmark = pytest.mark.slow


@pytest.mark.qml
def test_paste_glyph_auto_searches_and_plain_paste_does_not():
    run_scenario(
        Path(__file__),
        "--run-scenario",
        timeout=120,
        sandbox_prefix="waves-paste-search-test-",
        failure_message="paste auto-search behavior regressed.",
    )


def _run_scenario() -> int:  # noqa: C901 (one straight scenario, six legs)
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
    # The submit guard blocks auto-search on the Browse/Library/Settings
    # surfaces (a pasted link must not yank those pages); sit on the Search
    # tab, where the box lives, like a real paste would.
    q("browseOpen = false")
    # The decode runs ~0.6s (24 ticks * 26ms); give it slack.
    decode_ms = 1200

    def paste(text: str) -> None:
        # A paste, to the decoder, is a >=4-char jump; assign directly so the
        # OS clipboard is never involved.
        q(f"searchField.text = {text!r}")

    # 1. Glyph-armed paste: the glyph click's sequence minus the real paste().
    q("_searchSeq = -99")
    q("searchField.forceActiveFocus(); searchField.clear(); searchDecoder.submitPending = true")
    paste("monolink amniotic")
    settle(decode_ms)
    armed_searched = bool(q("_searchSeq === _navSeq")) and q("searchField.text") == "monolink amniotic"

    # 2. Plain paste (no glyph): fills, does not search.
    q("_searchSeq = -99")
    q("searchField.clear()")
    paste("another band name")
    settle(decode_ms)
    plain_inert = bool(q("_searchSeq === -99")) and q("searchField.text") == "another band name"

    # 2b. A pasted TIDAL link still auto-searches without the glyph.
    q("_searchSeq = -99")
    q("searchField.clear()")
    paste("https://tidal.com/browse/album/12345")
    settle(decode_ms)
    url_searched = bool(q("_searchSeq === _navSeq"))

    # 3. One-shot: a stale arm is cleared by a non-decode text change (typing),
    #    so the next plain paste stays inert.
    q("_searchSeq = -99")
    q("searchField.clear(); searchDecoder.submitPending = true")
    q("searchField.text = searchField.text + 'a'")  # 1-char jump: no decode, disarms
    disarmed = not bool(q("searchDecoder.submitPending"))
    q("searchField.clear()")
    paste("yet another term")
    settle(decode_ms)
    stale_inert = bool(q("_searchSeq === -99"))

    # 4. The REAL glyph handler with an empty clipboard: paste() inserts
    #    nothing, so no decode ever latches the arm, and the handler itself
    #    must drop it, or the NEXT bare Ctrl+V (a paste the user meant to
    #    edit) inherits the glyph's search. The offscreen platform's clipboard
    #    is in-process, cleared here; the OS clipboard is never involved.
    from PySide6.QtGui import QGuiApplication

    QGuiApplication.clipboard().clear()
    q("_searchSeq = -99")
    q("searchField.clear()")
    q("pasteGlyph.clicked()")
    glyph_disarmed = not bool(q("searchDecoder.submitPending"))
    paste("paste meant for editing")
    settle(decode_ms)
    empty_glyph_inert = bool(q("_searchSeq === -99"))

    # 5. The REAL glyph handler with a SHORT term on the clipboard.
    #    Three characters or fewer is not a jump typing could not produce, so
    #    the decoder's own heuristic starts nothing and the field's disarm drops
    #    the arm: the button pasted the term and then sat there. The handler has
    #    to run the decode itself. Checked at 1, 2 and 3 characters, since the
    #    threshold is a >=4 jump.
    short_searched = True
    for term in ("U2", "a", "MIA"):
        QGuiApplication.clipboard().setText(term)
        q("_searchSeq = -99")
        q("searchField.clear()")
        q("pasteGlyph.clicked()")
        settle(decode_ms)
        landed = q("searchField.text") == term and bool(q("_searchSeq === _navSeq"))
        short_searched = short_searched and landed
        if not landed:
            print(f"short paste {term!r} did not search: text={q('searchField.text')!r}", file=sys.stderr)

    # 5b. That new path must not have re-armed the stale case: a bare Ctrl+V
    #     after a short glyph paste is still only a fill.
    q("_searchSeq = -99")
    q("searchField.clear()")
    paste("still just filling the box")
    settle(decode_ms)
    short_left_no_arm = bool(q("_searchSeq === -99"))

    ok = armed_searched and plain_inert and url_searched and disarmed and stale_inert
    ok = ok and glyph_disarmed and empty_glyph_inert
    ok = ok and short_searched and short_left_no_arm

    # 6. A bare Ctrl+V mid-decode restarts on the new text and drops the
    #    glyph's arm: the armed decode never submits its term, and the
    #    replacement (not a link, unarmed) fills without searching.
    armed_term = "first armed term"
    replacement = "replacement edit"
    q("_searchSeq = -99")
    q("searchField.clear(); searchDecoder.submitPending = true")
    paste(armed_term)
    settle(200)
    if not bool(q("searchDecoder.decoding")):
        print("the armed decode did not start: no decode window to paste inside", file=sys.stderr)
        return EXIT_REGRESSED
    paste(replacement)
    settle(decode_ms)
    restarted_inert = bool(q("_searchSeq === -99")) and q("searchField.text") == replacement
    if not restarted_inert:
        print(
            f"a mid-decode paste did not restart clean: seq={q('_searchSeq')} text={q('searchField.text')!r}",
            file=sys.stderr,
        )
    ok = ok and restarted_inert

    # 7. Enter while the decode is still running (issue #41): the search must
    #    be for the PASTED text, not the scramble on screen, the field must
    #    settle to that text at once, and the decode's own settle must not
    #    fire a second search afterwards.
    q("_searchSeq = -99")
    q("searchField.clear()")
    paste("monolink amniotic")
    mid_decode = bool(q("searchDecoder.decoding")) and q("searchField.text") != "monolink amniotic"
    q("searchField.accepted()")
    enter_searched = bool(q("_searchSeq === _navSeq")) and q("searchField.text") == "monolink amniotic"
    enter_settled = not bool(q("searchDecoder.decoding"))
    q("_searchSeq = -99")
    settle(decode_ms)
    enter_once = bool(q("_searchSeq === -99")) and q("searchField.text") == "monolink amniotic"
    enter_mid_decode = mid_decode and enter_searched and enter_settled and enter_once
    # 7b. The same with the glyph's arm set: Enter drops the arm, so the
    #     decode that Enter settled cannot search a second time.
    q("_searchSeq = -99")
    q("searchField.clear(); searchDecoder.submitPending = true")
    paste("monolink amniotic")
    q("searchField.accepted()")
    armed_enter_searched = bool(q("_searchSeq === _navSeq"))
    q("_searchSeq = -99")
    settle(decode_ms)
    armed_enter_once = bool(q("_searchSeq === -99")) and not bool(q("searchDecoder.submitArmed"))
    enter_mid_decode = enter_mid_decode and armed_enter_searched and armed_enter_once
    if not enter_mid_decode:
        print(
            f"enter mid-decode: mid_decode={mid_decode} searched={enter_searched} "
            f"settled={enter_settled} once={enter_once} text={q('searchField.text')!r}",
            file=sys.stderr,
        )
    ok = ok and enter_mid_decode
    print(
        f"armed_searched={armed_searched} plain_inert={plain_inert} url_searched={url_searched} "
        f"disarmed={disarmed} stale_inert={stale_inert} "
        f"glyph_disarmed={glyph_disarmed} empty_glyph_inert={empty_glyph_inert} "
        f"short_searched={short_searched} short_left_no_arm={short_left_no_arm} "
        f"restarted_inert={restarted_inert} enter_mid_decode={enter_mid_decode}",
        flush=True,
    )
    return EXIT_OK if ok else EXIT_REGRESSED


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_run_scenario())
