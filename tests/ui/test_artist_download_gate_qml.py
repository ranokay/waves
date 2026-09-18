"""The artist surfaces offer a discography control only where one can run (#288).

An Apple artist page and an Apple artist *card* used to render the same
DOWNLOAD DISCOGRAPHY / DOWNLOAD ARTIST controls as a TIDAL one, and the click
could only refuse ("Not available for Apple Music yet", #242). The controls
now render from the provider's own capability answer
(``Capability.ARTIST_DOWNLOAD``), so this scenario drives all four surfaces:
the TIDAL page and card keep their controls, the Apple page and card show none
(the pages and cards themselves still render).

Runs through the shared boot helper in a subprocess like the other scenarios.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from support.qml import (
    EXIT_OK,
    EXIT_PRECONDITION,
    EXIT_REGRESSED,
    boot_main_qml,
    run_scenario,
)
from support.qml_probe import scene_js

# A control is present, visible and laid out; a hidden one is neither.
_FIND_ARTIST_CONTROL = scene_js("""
    var hit = findObject(root, "artistDownload");
    return hit !== null && hit.visible === true && hit.width > 0;
""")
_FIND_CARD_CONTROL = scene_js("""
    var hit = findObject(root, "artistCardDownload");
    return hit !== null && hit.visible === true && hit.width > 0;
""")


@pytest.mark.qml
def test_the_artist_surfaces_gate_the_discography_control():
    run_scenario(
        Path(__file__),
        "--run-scenario",
        timeout=120,
        sandbox_prefix="waves-artistgate-test-",
        failure_message="the artist surfaces' discography gate regressed",
    )


def _artist(ident: str, name: str) -> dict:
    """An artistLoaded payload, the shape the bridge emits."""

    def album(i: int) -> dict:
        return {
            "id": f"{ident}:album-{i}",
            "title": f"{name} Album {i}",
            "artist": name,
            "artist_id": ident,
            "art": "",
            "year": "2020",
            "date": "2020-01-01",
            "tracks": 10,
            "quality": "LOSSLESS",
            "popularity": 50,
        }

    def track(i: int) -> dict:
        return {
            "id": f"{ident}:track-{i}",
            "title": f"{name} Track {i}",
            "artist": name,
            "artist_id": ident,
            "album": f"{name} Album 0",
            "album_id": f"{ident}:album-0",
            "art": "",
            "year": "2020",
            "date": "2020-01-01",
            "duration": "3:20",
            "quality": "LOSSLESS",
            "popularity": 50,
        }

    return {
        "id": ident,
        "name": name,
        "art": "",
        "bio": f"About {name}.",
        "albums": [album(i) for i in range(2)],
        "eps": [],
        "tracks": [track(i) for i in range(2)],
        "videos": [],
    }


def _card(ident: str, name: str) -> dict:
    return {"id": ident, "name": name, "art": "", "roles": "Artist", "popularity": -1}


def _search_payload(*, apple: bool) -> dict:
    """A search payload whose artist section holds one card, in the Apple
    group or the TIDAL one (issue #292's group shape)."""
    if apple:
        return {
            "groups": [
                {
                    "provider": "apple",
                    "artists_layout": "flow",
                    "head_when_alone": True,
                    "artists": [_card("apple:artist-1", "Apple Artist")],
                    "albums": [],
                    "tracks": [],
                    "playlists": [],
                    "top": None,
                    "error": "",
                }
            ]
        }
    return {
        "groups": [
            {
                "provider": "tidal",
                "artists_layout": "strip",
                "head_when_alone": False,
                "artists": [_card("artist-1", "Tidal Artist")],
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


def _run_scenario() -> int:  # noqa: C901 (one straight scenario)
    booted = boot_main_qml()
    if isinstance(booted, int):
        return booted
    _root, q, settle, bridge = booted
    q("openSearch()")
    settle(400)
    if q("navOrigin") != "search":
        print(f"the search surface never opened (navOrigin={q('navOrigin')})", file=sys.stderr)
        return EXIT_PRECONDITION

    problems: list[str] = []

    # The verdicts the controls' bindings read: TIDAL answers an artist sweep,
    # Apple does not.
    if not bool(q('waves.artistDownloadSupported("artist-1")')):
        problems.append("a TIDAL artist was not offered the discography verb")
    if bool(q('waves.artistDownloadSupported("apple:artist-1")')):
        problems.append("an Apple artist was offered the discography verb")

    # Search-result artist cards: the TIDAL card keeps the control, the Apple
    # card renders without one (the card itself still renders).
    q("root._searchSeq = root._navSeq")
    bridge.searchResults.emit(_search_payload(apple=False))
    settle(500)
    if q("root.searchGroupFor('tidal').modelFor('artists').count") != 1:
        problems.append("the TIDAL artist card never rendered")
    elif not bool(q(_FIND_CARD_CONTROL)):
        problems.append("the TIDAL artist card lost its download control")

    q("root._searchSeq = root._navSeq")
    bridge.searchResults.emit(_search_payload(apple=True))
    settle(500)
    if q("root.searchGroupFor('apple').modelFor('artists').count") != 1:
        problems.append("the Apple artist card never rendered")
    elif bool(q(_FIND_CARD_CONTROL)):
        problems.append("the Apple artist card still offers a download control")

    # Artist pages: work through the shared boot helper's own search input.
    bridge.artistLoaded.emit(_artist("artist-1", "Tidal Artist"))
    settle(500)
    if not q("artistOpen") or q("artistData.name") != "Tidal Artist":
        problems.append("the TIDAL artist page never rendered")
    elif not bool(q(_FIND_ARTIST_CONTROL)):
        problems.append("the TIDAL artist page lost its discography control")

    bridge.artistLoaded.emit(_artist("apple:artist-1", "Apple Artist"))
    settle(500)
    if not q("artistOpen") or q("artistData.name") != "Apple Artist":
        problems.append("the Apple artist page never rendered")
    elif bool(q(_FIND_ARTIST_CONTROL)):
        problems.append("the Apple artist page still offers a discography control")

    for problem in problems:
        print(problem, file=sys.stderr)
    return EXIT_REGRESSED if problems else EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_run_scenario())
