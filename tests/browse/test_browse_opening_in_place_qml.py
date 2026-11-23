"""Browse builds in place: section slots, slot rows, and the drilled veil.

A landing refresh rebinds its shelves and rows instead of reassigning arrays
(a Repeater reset tears every card down); growth appends slots at the end; a
fresh drilled page builds behind its own veil and fades in complete, while a
revalidate and any non-wire assignment land in place with no veil.

Runs in a subprocess like the other Main.qml scenarios: building the bridge
installs process-global handlers that must not leak into the suite.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from support.qml import EXIT_OK, boot_main_qml, run_scenario, wait_until_true


@pytest.mark.qml
def test_browse_opens_and_grows_in_place():
    run_scenario(
        Path(__file__),
        "--run-scenario",
        sandbox_prefix="waves-browse-in-place-test-",
        drop=("waves.qt",),
    )


def _landing(*sections) -> dict:
    return {"sections": list(sections), "sources": [], "genres": [], "moods": [], "decades": []}


def _card(ident: str, title: str) -> dict:
    return {
        "id": ident,
        "kind": "album",
        "title": title,
        "artist": "Some Artist",
        "art": "",
        "year": "2026",
        "date": "2026-01-01",
        "rowKind": "cards",
    }


def _shelf(ident: str, title: str, items: list) -> dict:
    return {
        "title": title,
        "rowKind": "cards",
        "items": items,
        "more": "",
        "provider_id": "tidal",
        "data": f"pages/{ident}",
        "offset": len(items),
        "total": len(items),
    }


_FIRST_SHELF_CARD = """
(function () {
    function walk(o) {
        if (!o) return null;
        if (o.objectName === "browseConsoleShelf" && o.visible === true && o.count > 0) return o.itemAt(0);
        var kids = o.children || [];
        for (var i = 0; i < kids.length; i++) { var hit = walk(kids[i]); if (hit) return hit; }
        if (o.item) { var it = walk(o.item); if (it) return it; }
        return null;
    }
    return walk(root);
})()
"""


def _scenario() -> int:
    booted = boot_main_qml()
    if not isinstance(booted, tuple):
        return booted
    _root, q, settle, bridge = booted

    failures: list[str] = []

    def check(cond, what: str) -> None:
        if not cond:
            failures.append(what)

    def wait(expr: str, what: str, timeout_ms: int = 15000) -> None:
        check(wait_until_true(q, expr, what, timeout_ms=timeout_ms), what)

    q("root.browseOpen = true")
    q("bootOverlay.done = true")
    # A landing with two card shelves; the first grows in the refresh below.
    first = _shelf("one", "First Shelf", [_card("al1", "One"), _card("al2", "Two"), _card("al3", "Three")])
    second = _shelf("two", "Second Shelf", [_card("al4", "Four")])
    bridge.browseLoaded.emit(_landing(first, second))
    wait("root.browseBuilding === false && browseSecRep.count === 2", "the landing never built")
    settle(200)
    check(q("browseSecRep.count") == 2, f"the landing lost sections: {q('browseSecRep.count')}")
    shelf_before = q("String(browseSecRep.itemAt(0))")
    card_before = q(f"String({_FIRST_SHELF_CARD.strip()})")

    # A refresh: the shelves are NOT rebuilt (a fresh build would raise no
    # hand-rebuild here, but a reset would change the delegate identities),
    # the changed shelf rebinds its rows in place and the appended row joins
    # through a new slot.
    first_again = _shelf(
        "one", "First Shelf", [_card("al1", "One"), _card("al2", "Two"), _card("al3", "Three"), _card("al9", "Nine")]
    )
    bridge.browseLoaded.emit(
        {"sections": [first_again, second], "sources": [], "genres": [], "moods": [], "decades": []}
    )
    settle(200)
    check(
        q("String(browseSecRep.itemAt(0))") == shelf_before,
        "the refresh rebuilt the shelf delegates instead of rebinding them",
    )
    check(
        q(f"String({_FIRST_SHELF_CARD.strip()})") == card_before,
        "the refresh rebuilt the shelf's cards instead of rebinding slots",
    )
    check(q("browseVisibleSections[0].items.length") == 4, "the appended row never reached the section")

    # Growth appends at the end through the same slots: the grown section
    # keeps its identity and its first card.
    bridge.browseSectionMore.emit(
        {
            "data": "pages/one",
            "reqOffset": 4,
            "offset": 5,
            "more": True,
            "provider_id": "tidal",
            "items": [_card("al10", "Ten")],
        }
    )
    settle(200)
    check(q("String(browseSecRep.itemAt(0))") == shelf_before, "growth rebuilt the shelf delegate")
    check(q(f"String({_FIRST_SHELF_CARD.strip()})") == card_before, "growth rebuilt the existing cards")
    check(q("browseVisibleSections[0].items.length") == 5, "growth never appended its item")

    # A shorter payload drops only its trailing slots: the rows that remain
    # keep their cards, and a released slot does not throw while its dying
    # delegate still reads the previous row.
    shorter = _shelf("one", "First Shelf", [_card("al1", "One"), _card("al2", "Two")])
    bridge.browseLoaded.emit(_landing(shorter))
    settle(200)
    check(q("browseVisibleSections.length") == 1, "the shorter landing kept its trailing section")
    check(q("browseVisibleSections[0].items.length") == 2, "the shorter shelf kept its trailing rows")
    check(q(f"String({_FIRST_SHELF_CARD.strip()})") == card_before, "the shorter shelf rebuilt the rows that remain")

    # A fresh drilled page builds behind its own veil and fades in complete.
    q('openBrowseItem("playlist", "p1")')
    page = {
        "key": "item:playlist:p1",
        "title": "Long Playlist",
        "header": {"title": "Long Playlist", "kind": "playlist"},
        "sections": [
            {"title": "Cards", "rowKind": "cards", "items": [_card(f"c{i}", f"Card {i}") for i in range(6)]},
            {
                "title": "Tracks",
                "rowKind": "tracks",
                "items": [
                    {
                        "id": f"t{n}",
                        "kind": "track",
                        "title": f"Track {n}",
                        "artist": "A",
                        "duration": "3:20",
                        "num": n + 1,
                    }
                    for n in range(30)
                ],
            },
        ],
    }
    bridge.browsePageLoaded.emit(page)
    check(q("root.browsePageBuilding") is True, "a fresh drilled page raised no veil")
    check(q("root.browsePageReveal") == 0, "the drilled pane was not covered while building")
    wait("root.browsePageBuilding === false", "the drilled veil never lifted")
    # Complete, not spent on the stall guard: every counted section/card/row
    # reported in.
    check(
        q("root._browsePageBuildTotal") > 0 and q("root._browsePageBuildReady") == q("root._browsePageBuildTotal"),
        f"the veil lifted before the page was ready ({q('root._browsePageBuildReady')}/{q('root._browsePageBuildTotal')})",
    )
    settle(250)  # the reveal animation's 180ms
    check(q("root.browsePageReveal") == 1, "the drilled pane never faded in")
    check(q("browsePageSecRep.count") == 2, f"the drilled page lost sections: {q('browsePageSecRep.count')}")

    # A revalidate of the page already showing lands in place with no veil.
    bridge.browsePageLoaded.emit(page)
    check(q("root.browsePageBuilding") is False, "a revalidate raised the drilled veil again")

    # A non-wire assignment (a Back, a history restore, a local listing)
    # lands ready and drops any veil left over.
    q("root.browsePage = Object.assign({}, root.browsePage)")
    check(q("root.browsePageBuilding") is False, "a non-wire page assignment inherited a veil")

    if failures:
        for f in failures:
            print("REGRESSED:", f, file=sys.stderr)
        return 1
    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_scenario())
