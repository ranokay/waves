"""The ARTISTS SHOW ALL / SHOW LESS label needs artists to label.

WHAT THIS FENCES OFF
--------------------
Every capped section on the search page hides its SHOW ALL toggle when the
section is empty, because the grid, the header and the toggle all gate on
``sectionVisible(name, count)``. An ARTISTS toggle that asks only whether the
view is the mixed All one and whether the row is expanded or overflowing
stands alone.

The expanded flag is pref-backed (``search_section_artists_expanded`` on the
unified results view), so it comes back true for anyone who has ever expanded
the ARTISTS row. With a page that answered with no artists, the grid is
correctly gone, and the toggle must be too: a lone SHOW LESS floating over an
empty Search page. Clicking it writes the pref false, so it vanishes and does
not come back, which is what makes it look like a phantom.

HOW THIS STAYS FIXED
--------------------
The toggle carries the same count gate its section-mates get from
sectionVisible. The positive leg matters as much as the negative one: a guard
that hid the label unconditionally would also pass the empty case, so this
pins that one artist in the model brings the expanded row's SHOW LESS back.

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
    run_scenario,
    sandbox_qml_settings,
    seed_tidal_search,
)

_FLOATED = 1  # the label showed over a page with no artists on it
_NEVER_SHOWS = 2  # the count gate swallowed the label that should show
_PAGE_NOT_SHOWN = 3  # an invisible ancestor, so the read means nothing

_ALBUM = {
    "id": "tidal:al1",
    "title": "Album",
    "artist": "Artist",
    "artist_id": "",
    "artists": [],
    "art": "",
    "year": "2026",
    "date": "2026-01-01",
    "tracks": 3,
    "duration_sec": 300,
    "quality": "LOSSLESS",
    "popularity": -1,
    "explicit": False,
    "added": "",
}


@pytest.mark.qml
def test_the_artists_show_all_label_needs_artists():
    run_scenario(
        Path(__file__),
        "--run-scenario",
        timeout=180,
        sandbox_prefix="waves-artists-showall-",
        failure_message="the ARTISTS toggle regressed:",
    )


def _run_scenario() -> int:
    try:
        from PySide6.QtCore import QEventLoop, QTimer, QUrl
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtQml import QQmlApplicationEngine, QQmlEngine, QQmlExpression
    except Exception as exc:  # pragma: no cover - environment guard
        print(f"Qt unavailable: {exc}", file=sys.stderr)
        return EXIT_NO_QT

    from support.offline import PARK_LOGIN_QML, patch_offline

    patch_offline()
    app = QGuiApplication.instance() or QGuiApplication([])
    sandbox_qml_settings()
    try:
        from waves.desktop.app import _load_mono
        from waves.desktop.backend import WavesBridge
    except Exception as exc:  # pragma: no cover - environment guard
        print(f"Qt platform/backend unavailable: {exc}", file=sys.stderr)
        return EXIT_NO_QT

    bridge = WavesBridge(tidal=None)
    # The state this needs, and the only state it needs: someone expanded
    # the ARTISTS row in an earlier session. Written BEFORE the QML loads: the
    # unified results view reads its prefs once, when it is created.
    bridge.setWavesPref("search_section_artists_expanded", True)

    engine = QQmlApplicationEngine()
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
        e = QQmlExpression(QQmlEngine.contextForObject(root), root, expr)
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
    settle(120)
    # The app opens on Browse, and the search page is hidden wholesale while it
    # is. Reading the label from there would report HIDDEN whatever the binding
    # says, so the read must happen on the search page itself.
    q("root.openSearch()")
    settle(250)

    # A page that answered with no artists at all: the unified view is mounted
    # (the pref-backed fold came with it), its ARTISTS row is empty, and the
    # SHOW ALL label must stay hidden. The album keeps the page from being an
    # empty-catalog state.
    seed_tidal_search(q, bridge, albums=[dict(_ALBUM)])
    settle(300)

    # Walks `data`, not `children`: the label is not a visual child of the item
    # that declares it, so a children-only walk reports MISSING and the whole
    # scenario skips itself green.
    #
    # `visible` on a QQuickItem is EFFECTIVE visibility, so it is only evidence
    # about this binding when every ancestor is visible. The walk reports the
    # first invisible ancestor and the caller refuses to judge without one.
    _SHOWN = """(function () {
            var hit = null;
            function walk(o, d) {
                if (!o || hit || d > 40) return;
                if (o.objectName === 'artistsShowAll') { hit = o; return }
                var kids = o.data !== undefined ? o.data : o.children;
                for (var i = 0; i < (kids ? kids.length : 0); ++i) walk(kids[i], d + 1);
            }
            walk(root, 0);
            if (!hit) return 'MISSING';
            var blocked = '';
            var o = hit.parent, n = 0;
            while (o && n < 25) {
                if (!o.visible) { blocked = o.objectName || ('' + o); break }
                o = o.parent; n++;
            }
            return (hit.visible ? 'SHOWN' : 'HIDDEN') + '|' + (blocked || 'ancestors-visible');
        })()"""

    if int(q("searchResultsView.countFor('artists')")) != 0:
        print("a fresh page already held artists", file=sys.stderr)
        return EXIT_PRECONDITION
    if not bool(q("searchResultsView.isExpanded('artists')")):
        print("the pref did not reach the page; the scenario proves nothing", file=sys.stderr)
        return EXIT_PRECONDITION

    state = str(q(_SHOWN))
    if state == "MISSING":
        # The label is instantiated with the results view; a walk that cannot
        # find it is a finder regression, not a pass.
        print("no item named artistsShowAll in the tree", file=sys.stderr)
        return EXIT_PRECONDITION
    if not state.endswith("|ancestors-visible"):
        print(f"the search page is not on screen ({state}); the read proves nothing", file=sys.stderr)
        return _PAGE_NOT_SHOWN
    if state.startswith("SHOWN"):
        print(f"SHOW LESS floated over a search page with no artists (label read {state})", file=sys.stderr)
        return _FLOATED

    # The positive leg: one artist, the row still expanded, and the toggle is
    # back. Without this an always-false binding would pass the check above.
    seed_tidal_search(q, bridge, artists=[{"id": "1", "name": "A", "art": "", "popularity": 0}])
    settle(250)
    state = str(q(_SHOWN))
    artist_count = int(q("searchResultsView.countFor('artists')"))
    artist_expanded = bool(q("searchResultsView.isExpanded('artists')"))
    if artist_count != 1 or not artist_expanded:
        print(
            f"the artist row did not land expanded (count={artist_count}, expanded={artist_expanded})",
            file=sys.stderr,
        )
        return _NEVER_SHOWS
    if not state.startswith("SHOWN"):
        print(f"the label no longer shows when the row really is expanded (label read {state})", file=sys.stderr)
        return _NEVER_SHOWS
    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_run_scenario())
