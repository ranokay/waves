"""A browse card's cursor agrees with its click, and the console headline hovers.

WHAT THIS FENCES OFF
--------------------
`openable` drove only the cursor and the title underline while the click
paths called `host.openBrowseCard` unconditionally, and the two read
different gates: a track with an album but no artist opened its album page
behind an `ArrowCursor` with no underline, while a video card (and any
unknown kind) showed the pointing hand over a click that went nowhere.

The verdict is one function now, `browseCardOpenable` beside
`openBrowseCard` in Main.qml, and the click path consults it first: the
affordance and the navigation share the table, so they cannot drift apart
again. Both card styles bind it.

The console shelf headline had the same class of drift one level down: its
MouseArea set `cursorShape` but not `hoverEnabled`, so Qt never applied the
pointing hand outside a pressed button, while the art-style headline beside
it hovered. It carries `hoverEnabled: enabled` now.

Runs in a SUBPROCESS for the same reason as the other Main.qml scenarios:
building the bridge installs process-global handlers that must not leak
into the rest of the suite.
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

_QML_DIR = QML_MAIN.parent
_MAIN = QML_MAIN.read_text()
_BROWSE_CARD = (_QML_DIR / "BrowseCard.qml").read_text()
_ART_CARD = (_QML_DIR / "ArtCard.qml").read_text()
_BROWSE_SECTION = (_QML_DIR / "BrowseSection.qml").read_text()


def _body(start: str) -> str:
    """The body of the Main.qml block whose opening line carries `start`:
    from just after that line to the next equally-indented closing brace."""
    sig = start.strip()
    lines = _MAIN.splitlines()
    for i, line in enumerate(lines):
        if not line.strip().startswith(sig):
            continue
        indent = len(line) - len(line.lstrip())
        for j in range(i + 1, len(lines)):
            candidate = lines[j]
            if candidate.strip().startswith("}") and len(candidate) - len(candidate.lstrip()) == indent:
                return "\n".join(lines[i + 1 : j])
        raise AssertionError(f"no closing brace after {start!r}")
    raise AssertionError(start)


# ----- the verdict lives in one place ----------------------------------------


def test_the_click_path_and_the_cards_read_the_same_verdict():
    assert "function browseCardOpenable(card) {" in _MAIN
    table = _body("function browseCardOpenable(card) {")
    assert 'kind === "artist" || kind === "playlist" || kind === "mix" || kind === "album"' in table
    assert "return !!(card.album_id || card.artist_id)" in table
    assert "return false" in table, "an unknown kind must stay inert, not offer a page"
    click = _body("function openBrowseCard(card) {")
    assert "if (!browseCardOpenable(card))" in click, "the click must consult the verdict it shows"
    assert click.index("if (!browseCardOpenable(card))") < click.index("var kind"), (
        "the guard stands first: nothing below it may navigate for a card the verdict calls shut"
    )


def test_both_card_styles_delegate_their_affordance_to_the_verdict():
    assert "readonly property bool openable: host.browseCardOpenable(bc.card)" in _BROWSE_CARD
    assert "readonly property bool openable: host.browseCardOpenable(ac.card)" in _ART_CARD
    assert "|| !!bc.card.artist_id" not in _BROWSE_CARD, "the artist-only gate must not survive beside the verdict"
    assert "|| !!ac.card.artist_id" not in _ART_CARD, "the artist-only gate must not survive beside the verdict"
    # Both cursor sites and the underline still read it on each card.
    assert _BROWSE_CARD.count("cursorShape: bc.openable ? Qt.PointingHandCursor : Qt.ArrowCursor") == 2
    assert "font.underline: bcTitleMa.containsMouse && bc.openable" in _BROWSE_CARD
    assert _ART_CARD.count("cursorShape: ac.openable ? Qt.PointingHandCursor : Qt.ArrowCursor") == 2
    assert "font.underline: acTitleMa.containsMouse && ac.openable" in _ART_CARD


def test_both_headline_styles_hover_their_link():
    before, _, after = _BROWSE_SECTION.partition("id: bsecTitle")
    assert "hoverEnabled: enabled" in before, "the console headline must hover, like the art one"
    assert "hoverEnabled: enabled" in after, "the art-style headline must keep hovering"


# ----- the live agreement ----------------------------------------------------

_ITEMS_A = [
    {"id": "al1", "kind": "album", "title": "Alb One", "artist": "A", "artist_id": "ar1", "art": ""},
    {
        "id": "t-full",
        "kind": "track",
        "title": "Trk Full",
        "artist": "A",
        "artist_id": "ar1",
        "album": "Alb One",
        "album_id": "al1",
        "art": "",
    },
    {
        "id": "t-alb",
        "kind": "track",
        "title": "Trk Album Only",
        "artist": "",
        "album": "Alb One",
        "album_id": "al1",
        "art": "",
    },
    {
        "id": "t-art",
        "kind": "track",
        "title": "Trk Artist Only",
        "artist": "A",
        "artist_id": "ar1",
        "album": "",
        "art": "",
    },
    {"id": "t-none", "kind": "track", "title": "Trk Nowhere", "artist": "", "album": "", "art": ""},
]
_ITEMS_B = [
    {"id": "v1", "kind": "video", "title": "Vid One", "artist": "A", "art": ""},
    {"id": "p1", "kind": "playlist", "title": "Play One", "artist": "", "art": ""},
    {"id": "m1", "kind": "mix", "title": "Mix One", "artist": "", "art": ""},
    {"id": "ar1", "kind": "artist", "title": "Art One", "art": ""},
]

# Title to the verdict the shared table gives it.
_EXPECTED = {
    "Alb One": True,
    "Trk Full": True,
    "Trk Album Only": True,
    "Trk Artist Only": True,
    "Trk Nowhere": False,
    "Vid One": False,
    "Play One": True,
    "Mix One": True,
    "Art One": True,
}


@pytest.mark.qml
def test_browse_cards_offer_exactly_the_pages_their_click_opens():
    run_scenario(
        Path(__file__),
        "--run-scenario",
        timeout=180,
        sandbox_prefix="waves-browse-card-openable-test-",
        failure_message="a browse card's cursor disagreed with its click.",
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
        from waves.desktop.app import _load_mono
        from waves.desktop.backend import WavesBridge
    except Exception as exc:
        print(f"Qt platform/backend unavailable: {exc}", file=sys.stderr)
        return EXIT_NO_QT

    engine = QQmlApplicationEngine()
    bridge = WavesBridge(tidal=None)
    # The boot browse sequence emits from a worker (cached payload, then the
    # revalidated one), each landing seconds apart and each overwriting the
    # landing: count the emits so the scenario can wait the sequence out
    # instead of racing it.
    import time as _time

    _browse_emits: list = []
    bridge.browseLoaded.connect(lambda _p: _browse_emits.append(_time.monotonic()))
    _start = _time.monotonic()
    engine.rootContext().setContextProperty("waves", bridge)
    engine.rootContext().setContextProperty("monoFont", _load_mono())
    engine.rootContext().setContextProperty("uiFontFamily", app.font().family())
    engine.load(QUrl.fromLocalFile(str(QML_MAIN)))
    roots = engine.rootObjects()
    if not roots:
        print("Main.qml failed to load", file=sys.stderr)
        return EXIT_PRECONDITION
    root = roots[0]
    root.setProperty("width", 1400)
    root.setProperty("height", 900)

    def q(expr: str):
        e = QQmlExpression(QQmlEngine.contextForObject(root), root, expr)
        r = e.evaluate()
        if e.hasError():
            raise RuntimeError(e.error().toString())
        return r[0] if isinstance(r, tuple) else r

    def settle(ms: int = 150) -> None:
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def fail(msg: str) -> int:
        print(msg, file=sys.stderr)
        return EXIT_REGRESSED

    settle()
    # Freeze the boot machinery so the landing is driven purely by this
    # scenario: a cached-landing revalidate parks during the handover
    # animations and applies when they end, which would overwrite the
    # sections below at an unpredictable moment.
    for anim in ("bootSeq", "bootHandover", "bootBlk", "bootZoom", "bootIntro", "handoverCap"):
        q(f"{anim}.stop()")
    q("bootOverlay.done = true")
    q("bootContentShown = 1")
    q("browseBuilding = false")
    q("_browseAsyncBuild = false")
    q("_browseParked = null")
    # Wait the boot browse sequence out: no landing emit for a full window
    # means the worker is done and nothing will overwrite the sections the
    # scenario sets next. Bounded, so a cache-less boot still proceeds.
    _quiet_from = _time.monotonic()
    while _time.monotonic() - _quiet_from < 3.0 and _time.monotonic() - _start < 40.0:
        settle(250)
        if _browse_emits:
            _quiet_from = _browse_emits[-1]

    def show_sections():
        # A fresh object every time: re-setting an identical value may skip
        # the property notify, leaving the previous style's cards standing.
        root.setProperty(
            "browseSections",
            [
                {"title": "CARDS A", "rowKind": "cards", "data": "", "items": [dict(i) for i in _ITEMS_A]},
                {"title": "CARDS B", "rowKind": "cards", "data": "", "items": [dict(i) for i in _ITEMS_B]},
            ],
        )
        # The shelves virtualize past the viewport (the saved window geometry
        # restores narrower than the shores of cards), so build every delegate
        # before probing: a card that never instantiates would read as absent.
        # The property set lays out on the next turn, so settle once for the
        # shelves themselves, force the buffer, then settle for the cards.
        settle(400)
        built = q("""
        (function() {
            var n = 0
            function walk(o) {
                if (!o) return
                var kids = o.children || []
                for (var i = 0; i < kids.length; i++) {
                    var k = kids[i]
                    if (k && k.cacheBuffer !== undefined && k.count !== undefined) {
                        k.cacheBuffer = 10000
                        n++
                    }
                    walk(k)
                }
            }
            walk(browseLanding)
            return n
        })()
        """)
        if built < 2:
            print(f"expected the two card shelves, found {built}", file=sys.stderr)
            return False
        settle(900)
        return True

    cards_probe = """
    JSON.stringify((function() {
        var out = []
        function walk(item) {
            if (!item) return
            var kids = item.children || []
            for (var i = 0; i < kids.length; i++) {
                var k = kids[i]
                if (k && k.openable !== undefined && k.card !== undefined) {
                    out.push({ title: "" + (k.card.title || ""), kind: "" + (k.card.kind || ""),
                               openable: !!k.openable })
                } else {
                    walk(k)
                }
            }
        }
        walk(browseLanding)
        return out
    })())
    """
    headers_probe = """
    JSON.stringify((function() {
        var out = []
        function walk(item) {
            if (!item) return
            var kids = item.children || []
            for (var i = 0; i < kids.length; i++) {
                var k = kids[i]
                if (k && k.openable !== undefined && k.label !== undefined && k.count !== undefined) {
                    var mas = []
                    var ck = k.children || []
                    for (var j = 0; j < ck.length; j++) {
                        var c = ck[j]
                        if (c && c.hoverEnabled !== undefined && c.cursorShape !== undefined)
                            mas.push({ enabled: !!c.enabled, hover: !!c.hoverEnabled })
                    }
                    out.push({ label: "" + k.label, areas: mas })
                } else {
                    walk(k)
                }
            }
        }
        walk(browseLanding)
        return out
    })())
    """

    for style in ("console", "art"):
        q(f'browseStyle = "{style}"')
        if not show_sections():
            return EXIT_PRECONDITION

        try:
            cards = json.loads(q(cards_probe))
        except Exception as exc:
            print(f"card probe failed ({style}): {exc}", file=sys.stderr)
            return EXIT_PRECONDITION
        if len(cards) != len(_EXPECTED):
            print(f"expected {len(_EXPECTED)} cards, probed {len(cards)} ({style}): {cards}", file=sys.stderr)
            return EXIT_PRECONDITION
        bad = [
            f"{c['title']} ({c['kind']}): openable={c['openable']}, wanted {_EXPECTED[c['title']]}"
            for c in cards
            if c["title"] not in _EXPECTED or c["openable"] != _EXPECTED[c["title"]]
        ]
        if bad:
            print(f"{style} style: " + "; ".join(bad), file=sys.stderr)
            return EXIT_REGRESSED

        # The console headline's own MouseArea must hover its link exactly
        # when it is enabled: Qt only applies a MouseArea's cursor on hover
        # with hoverEnabled, so a missing flag is a missing hand.
        if style == "console":
            try:
                headers = json.loads(q(headers_probe))
            except Exception as exc:
                print(f"headline probe failed: {exc}", file=sys.stderr)
                return EXIT_PRECONDITION
            if len(headers) < 2:
                print(f"expected the two section headlines, probed {headers}", file=sys.stderr)
                return EXIT_PRECONDITION
            for h in headers:
                if not h["areas"]:
                    return fail(f"headline {h['label']!r} has no hoverable area at all")
                for a in h["areas"]:
                    if a["hover"] != a["enabled"]:
                        return fail(f"headline {h['label']!r}: hoverEnabled={a['hover']} with enabled={a['enabled']}")

    # The click half of the agreement, through the real path: the call and
    # the key read share one expression, so no worker turn can land between
    # them (offline the bridge answers nothing either way).
    legs = [
        (
            "track with an album but no artist opens its album",
            "openBrowseCard(({kind: 'track', id: 't-alb', title: 'Trk Album Only', album: 'Alb One', "
            "album_id: 'al1', art: ''})); browsePageKey",
            "item:album:al1",
        ),
        (
            "an album card opens its page",
            "openBrowseCard(({kind: 'album', id: 'al1', title: 'Alb One', art: ''})); browsePageKey",
            "item:album:al1",
        ),
        (
            "a track naming neither goes nowhere",
            "openBrowseCard(({kind: 'track', id: 't-none', title: 'Trk Nowhere', art: ''})); browsePageKey",
            "",
        ),
        (
            "a video card goes nowhere",
            "openBrowseCard(({kind: 'video', id: 'v1', title: 'Vid One', art: ''})); browsePageKey",
            "",
        ),
        ("an unknown kind goes nowhere", "openBrowseCard(({kind: '', id: 'x', title: 'X'})); browsePageKey", ""),
    ]
    for name, expr, want in legs:
        q("browseBack()")
        if q("browsePageKey") != "":
            return fail(f"could not reset to the landing before leg: {name}")
        if q(expr) != want:
            return fail(f"{name}: landed on {q('browsePageKey')!r}, wanted {want!r}")

    print(f"ok: {len(_EXPECTED)} cards agree in both styles, {len(legs)} click legs agree", flush=True)
    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_run_scenario())
