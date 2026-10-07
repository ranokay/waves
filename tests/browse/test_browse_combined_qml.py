"""The combined Browse landing's controls (issue #600).

A landing composed from several providers' sections gets a source filter and
per-section arrangement: move up/down, collapse and hide, each persisted in
waves.json so the choice survives launches and provider outages. A hidden
section leaves a restore chip behind. Every drill-down keeps its row's owner,
so a section served by a second provider keys its page to that provider.

Runs in a SUBPROCESS for the same reason as the other Main.qml scenarios:
building the bridge installs process-global handlers that must not leak into
the rest of the suite.
"""

from __future__ import annotations

import json
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

# Every arranged (landing) BrowseSection, as {title, provider, collapsed}.
_SECTIONS = """
JSON.stringify((function() {
    var out = []
    function walk(o) {
        if (!o) return
        if (o.visible === true && o.sec !== undefined && o.arrangeable !== undefined && o.landing === true && o.sec)
            out.push({ title: "" + o.sec.title, provider: "" + (o.sec.provider_id || ""), collapsed: !!o.collapsed })
        var kids = o.children || []
        for (var i = 0; i < kids.length; i++) walk(kids[i])
    }
    walk(contentItem)
    return out
})())
"""

_SECTION = """
(function() {
    var section = null
    function findSection(o) {
        if (!o || section) return
        if (o.sec !== undefined && o.arrangeable !== undefined && o.landing === true && o.sec && ("" + o.sec.title) === "%(title)s") { section = o; return }
        var kids = o.children || []
        for (var i = 0; i < kids.length; i++) findSection(kids[i])
    }
    findSection(contentItem)
    if (!section) return "no-section"
    var hit = null
    function find(o) {
        if (!o || hit) return
        if (o.visible === true && o.objectName === "%(objectName)s") { hit = o; return }
        var kids = o.children || []
        for (var i = 0; i < kids.length; i++) find(kids[i])
    }
    find(section)
    if (!hit) return "no-control"
    %(call)s
    return "ok"
})()
"""

_CHIP = """
(function() {
    var hit = null
    function walk(o) {
        if (!o || hit) return
        if (o.visible === true && o.objectName === "browseSourceChip" && ("" + (o.modelData ? o.modelData.provider : "")) === "%(provider)s") { hit = o; return }
        var kids = o.children || []
        for (var i = 0; i < kids.length; i++) walk(kids[i])
    }
    walk(contentItem)
    if (!hit) return "no-chip"
    var tap = null
    function findTap(o) {
        if (!o || tap) return
        if (o.visible === true && o.objectName === "browseSourceChipAction") { tap = o; return }
        var kids = o.children || []
        for (var i = 0; i < kids.length; i++) findTap(kids[i])
    }
    findTap(hit)
    if (!tap) return "no-tap"
    tap.triggered()
    return "ok"
})()
"""

_RESTORE_FIRST = """
(function() {
    var hit = null
    function walk(o) {
        if (!o || hit) return
        if (o.visible === true && o.objectName === "browseRestoreSection") { hit = o; return }
        var kids = o.children || []
        for (var i = 0; i < kids.length; i++) walk(kids[i])
    }
    walk(contentItem)
    if (!hit) return "no-restore"
    hit.triggered()
    return "ok"
})()
"""

# The arranged section's height, so a collapse is proven to hide its body.
_SECTION_HEIGHT = """
(function() {
    var section = null
    function find(o) {
        if (!o || section) return
        if (o.visible === true && o.sec !== undefined && o.landing === true && o.sec && ("" + o.sec.title) === "%(title)s") { section = o; return }
        var kids = o.children || []
        for (var i = 0; i < kids.length; i++) find(kids[i])
    }
    find(contentItem)
    return section ? section.height : -1
})()
"""

# Opens a section's listing through its own route (the headline's action).
_OPEN_SECTION = """
(function() {
    var section = null
    function find(o) {
        if (!o || section) return
        if (o.visible === true && o.sec !== undefined && o.landing === true && o.sec && ("" + o.sec.title) === "%(title)s") { section = o; return }
        var kids = o.children || []
        for (var i = 0; i < kids.length; i++) find(kids[i])
    }
    find(contentItem)
    if (!section) return "no-section"
    section.openListing()
    return "ok"
})()
"""

_PAYLOAD = {
    "sections": [
        {
            "rowKind": "tracks",
            "title": "Tidal Fresh",
            "items": [],
            "more": "",
            "provider_id": "tidal",
        },
        {
            "rowKind": "tracks",
            "title": "Tidal New",
            "items": [],
            "more": "",
            "provider_id": "tidal",
        },
        {
            "rowKind": "tracks",
            "title": "Stub Shelf",
            "items": [
                {
                    "id": "stub:t1",
                    "kind": "track",
                    "title": "Stub Track",
                    "artist": "Some Artist",
                    "album": "Some Album",
                    "album_id": "stub:al1",
                    "num": 1,
                    "duration": "3:20",
                    "duration_sec": 200,
                    "quality": "LOSSLESS",
                    "popularity": 50,
                    "explicit": False,
                    "art": "",
                }
            ],
            "more": "pages/stub-more",
            "provider_id": "stub",
        },
    ],
    "sources": [{"provider_id": "tidal", "name": "TIDAL"}, {"provider_id": "stub", "name": "Stub"}],
    "genres": [],
    "moods": [],
    "decades": [],
    "error": False,
}


@pytest.mark.qml
def test_the_landing_filters_arranges_and_routes_by_provider():
    run_scenario(
        Path(__file__),
        "--run-scenario",
        timeout=180,
        sandbox_prefix="waves-browse-combined-qml-",
        failure_message="the combined landing controls regressed.",
    )


def _run_scenario() -> int:
    try:
        from PySide6.QtCore import QEventLoop, QTimer, QUrl
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtQml import QQmlApplicationEngine, QQmlEngine, QQmlExpression
    except Exception as exc:  # pragma: no cover - environment guard
        print(f"Qt unavailable: {exc}", file=sys.stderr)
        return EXIT_NO_QT

    app = QGuiApplication.instance() or QGuiApplication([])
    sandbox_qml_settings()
    try:
        from waves.desktop.app import _load_mono
        from waves.desktop.backend import WavesBridge
    except Exception as exc:  # pragma: no cover - environment guard
        print(f"Qt platform/backend unavailable: {exc}", file=sys.stderr)
        return EXIT_NO_QT

    # The scenario owns the landing payload; the real fetch would race it
    # (and reach for TIDAL with no session).
    WavesBridge.loadBrowse = lambda self: None
    WavesBridge.refreshBrowse = lambda self: None
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

    def settle(ms: int = 200) -> None:
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def wait(expr, timeout_ms: int = 6000):
        deadline = timeout_ms
        while deadline > 0:
            value = expr() if callable(expr) else q(expr)
            if value:
                return value
            settle(50)
            deadline -= 50
        return None

    def sections() -> list[dict]:
        return json.loads(q(_SECTIONS))

    def titles() -> list[str]:
        return [s["title"] for s in sections()]

    def fail(msg: str) -> int:
        print(msg, file=sys.stderr)
        return EXIT_REGRESSED

    def act(title: str, object_name: str, call: str) -> str:
        return q(_SECTION % {"title": title, "objectName": object_name, "call": call})

    settle()
    q("browseStyle = 'console'")
    bridge._logged_in = True
    bridge.loggedInChanged.emit()
    q("openBrowse()")
    q("bootOverlay.done = true")  # otherwise the landing build takes the veiled path
    settle()
    bridge.browseLoaded.emit(dict(_PAYLOAD))
    if not wait(lambda: q("browseSections.length === 3 && root.browseBuilding === false") and len(sections()) == 3):
        print(f"the combined landing never built: {sections()}", file=sys.stderr)
        return EXIT_PRECONDITION
    settle(200)

    got = sections()
    if [s["title"] for s in got] != ["Tidal Fresh", "Tidal New", "Stub Shelf"]:
        return fail(f"the landing did not keep registry/provider order: {got}")
    if [s["provider"] for s in got] != ["tidal", "tidal", "stub"]:
        return fail(f"the sections lost their owners: {got}")

    # Source filter: the stub chip narrows the landing; All restores it.
    if q(_CHIP % {"provider": "stub"}) != "ok":
        return fail("the stub source chip did not trigger")
    if not wait(lambda: titles() == ["Stub Shelf"]):
        return fail(f"the source filter did not narrow the landing: {titles()}")
    if q("waves.wavesPref('browse_source_filter')") != "stub":
        return fail("the source filter did not persist")
    if q(_CHIP % {"provider": "all"}) != "ok":
        return fail("the All source chip did not trigger")
    # The filter rebuilds the section delegates; wait for the objects, not
    # just the model.
    if not wait(lambda: titles() == ["Tidal Fresh", "Tidal New", "Stub Shelf"]):
        return fail(f"clearing the source filter did not restore the landing: {titles()}")

    # Move DOWN on the first TIDAL section: order persists per provider and
    # never crosses into the stub's group.
    moved = act("Tidal Fresh", "browseArrangeDown", "hit.tapped()")
    if moved != "ok":
        return fail(f"the DOWN control did not trigger: {moved}")
    if not wait(
        'root.browseVisibleSections[0].title === "Tidal New" && root.browseVisibleSections[1].title === "Tidal Fresh"'
    ):
        return fail(f"moving did not reorder: {[s['title'] for s in sections()]}")
    order = json.loads(q("waves.wavesPref('browse_section_order')"))
    if order != {"tidal": ["Tidal New", "Tidal Fresh"]}:
        return fail(f"the order did not persist per provider: {order!r}")
    # At the group's end the control stands down (and the stub section's
    # delegates settle before the next action).
    if q("root.browseCanMove(root.browseVisibleSections[1], 1)"):
        return fail("DOWN still reports movable at the group's end")
    if not q("root.browseCanMove(root.browseVisibleSections[1], -1)"):
        return fail("UP does not report movable mid-group")
    if not wait(lambda: titles() == ["Tidal New", "Tidal Fresh", "Stub Shelf"]):
        return fail(f"the moved delegates never settled: {titles()}")

    # Collapse: header toggles, state persists, body hides.
    def shelf_height():
        return q(_SECTION_HEIGHT % {"title": "Stub Shelf"})

    expanded_h = shelf_height()
    if expanded_h < 60:
        return fail(f"the stub shelf has no body to hide ({expanded_h})")
    toggled = act("Stub Shelf", "browseSectionHeader", "hit.toggled()")
    if toggled != "ok":
        return fail(f"the section header did not toggle: {toggled}")
    if not wait('root.browseCollapsed["stub|Stub Shelf"] === true'):
        return fail("the collapse did not persist")
    if not any(s["title"] == "Stub Shelf" and s["collapsed"] for s in sections()):
        return fail(f"the section did not report collapsed: {sections()}")
    if not wait(lambda: shelf_height() < expanded_h - 40):
        return fail(f"collapsing did not hide the body ({shelf_height()} vs {expanded_h})")
    if act("Stub Shelf", "browseSectionHeader", "hit.toggled()") != "ok":
        return fail("the section header did not toggle back")
    if not wait('root.browseCollapsed["stub|Stub Shelf"] === undefined'):
        return fail("expanding did not clear the collapse")
    if not wait(lambda: shelf_height() > expanded_h - 3):
        return fail("expanding did not bring the body back")

    # Hide: the section leaves the landing and a restore chip brings it back.
    hid = act("Tidal New", "browseArrangeHide", "hit.tapped()")
    if hid != "ok":
        return fail(f"the HIDE control did not trigger: {hid}")
    if not wait(lambda: titles() == ["Tidal Fresh", "Stub Shelf"] and q("root.browseHiddenSections.length") == 1):
        return fail(f"hiding did not remove the section (or grew no restore chip): {titles()}")
    hidden = json.loads(q("waves.wavesPref('browse_sections_hidden')"))
    if hidden != {"tidal|Tidal New": True}:
        return fail(f"the hidden set did not persist: {hidden!r}")
    if q(_RESTORE_FIRST) != "ok":
        return fail("the restore chip did not trigger")
    if not wait(lambda: len(titles()) == 3 and q("root.browseHiddenSections.length") == 0):
        return fail(f"restoring did not bring the section back: {titles()}")
    if json.loads(q("waves.wavesPref('browse_sections_hidden')")) != {}:
        return fail("the restored section stayed in the hidden set")

    # A category resolve answers the action that asked for it, with its own
    # owner on the signal: arm the pending DOWNLOAD ALL, emit the resolve for
    # the stub, and the download must read the stub's cache entry.
    seen_keys: list = []
    bridge._cached_category = lambda key: (seen_keys.append(key), [])[1]
    q("root.catPendingDl = 'pages/stub-cat'")
    bridge.playlistCategoryResolved.emit("pages/stub-cat", "Stub cat", 1, "stub:pl1", "stub")
    settle(200)
    if q("root.catPendingDl") != "":
        return fail("the resolve did not clear the pending download")
    prompt_provider = q("root.catDlPrompt ? root.catDlPrompt.provider : ''")
    if prompt_provider != "stub" and seen_keys != ["cat:stub:pages/stub-cat"]:
        return fail(f"the resolve did not join the stub's owner (prompt={prompt_provider!r}, keys={seen_keys})")

    # A section's headline route carries its owner: opening the stub shelf
    # keys the page to stub, not to the first provider.
    if q(_OPEN_SECTION % {"title": "Stub Shelf"}) != "ok":
        return fail("the section headline did not open")
    if q("browsePageKey") != "pages/stub-more":
        return fail(f"the headline keyed the wrong page: {q('browsePageKey')!r}")
    if q("browsePageProvider") != "stub":
        return fail(f"the headline lost its provider: {q('browsePageProvider')!r}")

    print("combined browse landing controls OK", flush=True)
    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_run_scenario())
