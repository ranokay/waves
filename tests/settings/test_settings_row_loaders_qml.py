"""Settings rows instantiate only the control variant their field needs.

WHAT THIS FENCES OFF
--------------------
Every field row used to declare all of its variants -- the inline row, the
full-width string column, cover sizes, the library card, a status row, the
Apple setup wizard and an action row -- and hide the ones the field's type
did not select. Only ~1,550 of the page's ~15,300 items were ever visible;
the first Settings open still paid scene-graph sync for every hidden control
(350-500 ms and a ~500 MB transient spike, issue #549).

The variants are now Loaders activated by the field's type AND the section
being open (the pattern the library card established), so a collapsed
section builds nothing and an open one builds one variant per row. This
scenario pins the instantiation contract -- the counts are the fence, not
timing -- and proves the active variant renders on open and leaves again on
close.

Counts are Qt item-subtree sizes of ``settingsPage``; they are stable across
platforms because they are the same QML object tree.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from support.qml import EXIT_OK, EXIT_REGRESSED, boot_main_qml, run_scenario

pytestmark = pytest.mark.qml

# Open/close every section through the page's own persisted-state API.
_SET_ALL = """(function () {
    var gs = settingsPage.groups
    for (var i = 0; i < gs.length; i++) settingsPage.setSectionOpen(gs[i].id, %s)
    return gs.length
})()"""

_COUNT = """(function () {
    var t = {total: 0, visible: 0}
    function walk(o) {
        t.total++
        if (o.visible === true) t.visible++
        var k = o.children || []
        for (var i = 0; i < k.length; i++) walk(k[i])
    }
    walk(settingsPage)
    return JSON.stringify(t)
})()"""

_FIND_AUDIO_QUALITY = """(function () {
    var hit = null
    function walk(o) {
        if (hit) return
        if (String(o).indexOf("QQuickText") === 0 && String(o.text) === "Audio quality" && o.visible === true)
            hit = o
        var k = o.children || []
        for (var i = 0; i < k.length; i++) walk(k[i])
    }
    walk(settingsPage)
    return hit ? true : false
})()"""


def test_settings_rows_build_only_their_own_variant():
    run_scenario(
        Path(__file__),
        "--run-scenario",
        timeout=180,
        sandbox_prefix="waves-settings-loaders-",
        failure_message="settings rows instantiate variants their fields do not use.",
    )


def _run_scenario() -> int:  # noqa: C901 (one straight scenario, five checks)
    booted = boot_main_qml()
    if isinstance(booted, int):
        return booted
    _root, q, settle, _bridge = booted

    problems: list[str] = []

    q("settingsOpen = true")
    settle(400)
    closed = json.loads(q(_COUNT))
    # A collapsed page must stay a shell: every row starts as a placeholder
    # plus at most one loader. Before the variant loaders it was ~15,300.
    if closed["total"] > 3000:
        problems.append(f"the collapsed page instantiates {closed['total']} items (cap 3000)")

    # The save gate's fields come from the schema, so a laundered value in a
    # card that is still collapsed keeps SAVE CHANGES blocked; delegate-run
    # registration would have missed it until the card was opened.
    registered = bool(q('settingsPage.sanitizeKeys["filename_illegal_replacement"] !== undefined'))
    if not registered:
        problems.append("the sanitized field is missing from the save gate's schema walk")
    q('settingsPage.editMap = {filename_illegal_replacement: "a/b"}')
    if q("settingsPage.hasInvalidEdits()") is not True:
        problems.append("a laundered value in a collapsed card no longer blocks save")
    q("settingsPage.editMap = ({})")

    opened = int(q(_SET_ALL % "true"))
    settle(600)
    opened_count = json.loads(q(_COUNT))
    # All eleven sections open is the page's heaviest state; one variant per
    # row must stay well under the old all-variants count.
    if opened_count["total"] > 6500:
        problems.append(f"the fully open page instantiates {opened_count['total']} items (cap 6500)")
    if opened_count["total"] <= closed["total"]:
        problems.append("opening every section instantiated nothing: the loaders never activate")
    if opened == 0:
        problems.append("the schema exposed no sections")

    if not bool(q(_FIND_AUDIO_QUALITY)):
        problems.append("the open Downloads card has no visible 'Audio quality' row")

    q(_SET_ALL % "false")
    settle(600)
    recloses = json.loads(q(_COUNT))
    # Closing must shed the rows again, or a long session accumulates the
    # whole page no matter which sections are open.
    if recloses["total"] > closed["total"]:
        problems.append(
            f"closing every section left {recloses['total']} items behind (collapsed page is {closed['total']})"
        )

    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        return EXIT_REGRESSED
    print(f"ok closed={closed['total']} open={opened_count['total']} recloses={recloses['total']}")
    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    sys.exit(_run_scenario())
