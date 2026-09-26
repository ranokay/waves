"""Parked pages refresh on a ceiling while they are the view.

WHAT THIS FENCES OFF
--------------------
Entry slots revalidate only on entry and Back restores from memory, so a
page the user parks on froze at its open. Four five-minute timers re-poke
the silent refresh slots while their page is the view (landing, drilled
item, artist, library pane); the backend repaints only on a change. The
timers stop while the window is hidden or minimized, and a re-show after a
night away fires each running one once instead of serving the old page for
another interval.

Checked on the source: the behavior needs a parked page and a hidden
window, which a scenario cannot hold still cheaply. The Python halves
(`refreshArtist`, `refreshBrowseItem`, `windowShown`) carry their own unit
coverage through the slots they already had.
"""

from __future__ import annotations

import re

from support.paths import QML_MAIN


def _main() -> str:
    return QML_MAIN.read_text(encoding="utf-8")


def test_the_four_ceiling_timers_exist_and_call_the_silent_slots():
    main = _main()
    for timer, slot in (
        ("browseLandingFreshTimer", "waves.refreshBrowse()"),
        ("browseItemFreshTimer", "waves.refreshBrowseItem("),
        ("artistFreshTimer", "waves.refreshArtist("),
        ("libraryFreshTimer", "root.loadLib("),
    ):
        assert f"id: {timer}" in main, f"{timer} is gone: its parked page freezes at its open"
        assert slot in main, f"{timer} no longer calls {slot}"
    assert main.count("interval: 5 * 60 * 1000") >= 4


def test_the_timers_run_only_while_their_page_is_the_view():
    main = _main()
    guards = {
        "browseLandingFreshTimer": 'root.browsePageKey === ""',
        "browseItemFreshTimer": 'root.browsePageKey !== ""',
        "artistFreshTimer": "root.artistOpen",
        "libraryFreshTimer": "root.libraryOpen",
    }
    for timer, guard in guards.items():
        block = main[main.index(f"id: {timer}") : main.index(f"id: {timer}") + 900]
        assert guard in block, f"{timer} lost its view guard ({guard})"
        assert "root.windowUp" in block, f"{timer} refreshes a hidden window"
        assert "root.signedIn" in block


def test_a_long_hide_fires_the_running_timers_once_on_reshow():
    main = _main()
    assert "readonly property bool windowUp" in main
    assert "waves.windowShown" in main, "the bridge never learns the window hid"
    assert "freshDownAt" in main
    for timer in ("browseLandingFreshTimer", "browseItemFreshTimer", "artistFreshTimer", "libraryFreshTimer"):
        assert timer in main[main.index("var timers =") :], f"re-show forgets {timer}"


def test_the_window_signal_reaches_the_bridge():
    assert re.search(r"onWindowUpChanged:\s*if\s*\(waves\s*&&\s*waves\.windowShown\)", _main()), (
        "a partial bridge (the QML labs) must not break on the wiring"
    )
