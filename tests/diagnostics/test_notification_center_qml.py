"""The notification center: the header entry point, retained history, clearing,
row expansion and the accessibility metadata of its controls -- plus an active
issue that resolves after a restart, from the persisted store."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from support.qml import (
    EXIT_NO_QT,
    EXIT_OK,
    EXIT_REGRESSED,
    boot_main_qml,
    checkpoint,
    click_point,
    require_qt,
    run_scenario,
    scenario_env,
    wait_until,
)
from support.qml_probe import scene_js


@pytest.mark.qml
def test_the_center_lists_retained_history_and_clears():
    run_scenario(
        Path(__file__),
        "--run-scenario",
        sandbox_prefix="waves-notification-center-",
        drop=("WARN", "waves.qt"),
    )


@pytest.mark.qml
def test_an_active_issue_resolves_across_a_restart():
    """One child leaves an unresolved issue in the store; a second boots from
    the same store, resolves it, and sees the retained entry go terminal."""
    sandbox = tempfile.mkdtemp(prefix="waves-notification-restart-")
    try:
        for flag in ("--publish-open", "--resolve-it"):
            proc = subprocess.run(  # noqa: S603 (fixed argv: this interpreter, this file)
                [sys.executable, str(Path(__file__).resolve()), flag],
                env=scenario_env(sandbox),
                capture_output=True,
                text=True,
                timeout=180,
            )
            if proc.returncode == EXIT_NO_QT:
                require_qt()
            if proc.returncode != EXIT_OK:
                pytest.fail(f"{flag} failed\n" + (proc.stdout + proc.stderr).strip()[-1200:])
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


def test_a_configured_retention_window_survives_a_restart():
    """A user-set 30-day window must be in force before the stored history is
    read; loading first would prune at the shipped 7 days and lose the rest."""
    sandbox = tempfile.mkdtemp(prefix="waves-notification-retention-")
    try:
        for flag in ("--seed-old-entry", "--expect-old-entry"):
            proc = subprocess.run(  # noqa: S603 (fixed argv: this interpreter, this file)
                [sys.executable, str(Path(__file__).resolve()), flag],
                env=scenario_env(sandbox),
                capture_output=True,
                text=True,
                timeout=180,
            )
            if proc.returncode == EXIT_NO_QT:
                require_qt()
            if proc.returncode != EXIT_OK:
                pytest.fail(f"{flag} failed\n" + (proc.stdout + proc.stderr).strip()[-1200:])
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


def _run_scenario() -> int:
    boot = boot_main_qml()
    if isinstance(boot, int):
        return boot
    root, q, settle, bridge = boot
    from PySide6.QtCore import QPointF

    from waves.events import EventAction, EventDomain, Severity, application_event

    def publish(event) -> None:
        bridge._events.publish(event)

    def history() -> list:
        return list(bridge.notificationHistory())

    checkpoint("the header entry point opens the center with retained history")
    active = application_event(
        EventDomain.LIBRARY,
        "The library folder could not be read.",
        key="center-active",
        title="Library",
        details=("Checked the folder again",),
        actions=(EventAction.OPEN_SETTINGS,),
    )
    done = application_event(
        EventDomain.DOWNLOAD, "Saved Track B", key="center-done", severity=Severity.SUCCESS
    ).finish()
    publish(active)
    publish(done)
    wait_until(
        lambda: {entry["id"] for entry in history()} >= {active.id, done.id},
        timeout_ms=15000,
        message="both entries retained",
    )

    button = q(scene_js("return findObject(root, 'noticeBtn');"))
    assert button is not None, "the header carries the notification entry point"
    name = str(q(scene_js("return findObject(root, 'noticeBtn').Accessible.name;")))
    assert "Notifications" in name
    point = q(
        scene_js(
            "var o = findObject(root, 'noticeBtn');"
            " var p = o.mapToItem(null, o.width / 2, o.height / 2);"
            " return JSON.stringify([p.x, p.y]);"
        )
    )
    coords = json.loads(point)
    click_point(root, QPointF(coords[0], coords[1]), settle)
    wait_until(lambda: bool(q("notificationCenter.opened")), timeout_ms=10000, message="center opens")

    checkpoint("history is newest first and rows expand")
    entries = int(q("notificationCenter.items.length"))
    assert entries >= 3, "the boot sign-in error, the active issue and the completion are all kept"
    ids = [str(q(f"notificationCenter.items[{index}].id")) for index in range(entries)]
    assert ids.index(done.id) < ids.index(active.id), "the newest update leads the issue it followed"
    expand = q(
        scene_js(
            "return findFirst(notificationCenter.contentItem,"
            " function (o) { return o.objectName === 'notificationExpand'; });"
        )
    )
    assert expand is not None, "rows expand"
    q(
        scene_js(
            "findFirst(notificationCenter.contentItem,"
            " function (o) { return o.objectName === 'notificationExpand'; }).triggered();"
            " return 1;"
        )
    )
    settle(100)
    expanded = q(
        scene_js(
            "var c = findFirst(notificationCenter.contentItem,"
            " function (o) { return o.objectName === 'notificationCard'; });"
            " return c && c.expanded === true;"
        )
    )
    assert bool(expanded), "the detail expander opens the row"

    checkpoint("every tab stop in the center is named")
    stops = json.loads(
        q(
            scene_js(
                "var out = [];"
                " var visited = [];"
                " function walk(o) {"
                "   if (!o || visited.indexOf(o) !== -1) return;"
                "   visited.push(o);"
                "   if (o.activeFocusOnTab === true && o.visible !== false && o.width > 0)"
                "     out.push({ name: '' + (o.Accessible && o.Accessible.name ? o.Accessible.name : ''),"
                "                object: '' + (o.objectName || '') });"
                "   var kids = o.children || [];"
                "   for (var i = 0; i < kids.length; i++) walk(kids[i]);"
                " }"
                " walk(notificationCenter.contentItem);"
                " return JSON.stringify(out);"
            )
        )
    )
    assert stops, "the center has keyboard-reachable controls"
    for stop in stops:
        assert stop["name"], f"tab stop without a name: {stop['object']}"

    checkpoint("clear keeps active issues and drops the resolved history")
    clear = q(
        scene_js(
            "return findFirst(notificationCenter.contentItem,"
            " function (o) { return o.objectName === 'notificationClear'; });"
        )
    )
    assert clear is not None
    q(
        scene_js(
            "findFirst(notificationCenter.contentItem,"
            " function (o) { return o.objectName === 'notificationClear'; }).clicked();"
            " return 1;"
        )
    )
    wait_until(
        lambda: all(str(entry["lifecycle"]) == "active" for entry in history()) and len(history()) >= 1,
        timeout_ms=15000,
        message="terminal history cleared",
    )
    assert done.id not in {entry["id"] for entry in history()}, "the resolved completion is gone"
    assert active.id in {entry["id"] for entry in history()}, "the active issue stays discoverable"

    q("notificationCenter.close()")
    settle(100)
    bridge.shutdown()
    return EXIT_OK


def _publish_open() -> int:
    boot = boot_main_qml()
    if isinstance(boot, int):
        return boot
    _root, _q, settle, bridge = boot
    import time

    from waves.events import EventAction, EventDomain, application_event

    event = application_event(
        EventDomain.LIBRARY,
        "The library folder could not be read.",
        key="restart-open",
        title="Library",
        actions=(EventAction.OPEN_SETTINGS,),
    )
    bridge._events.publish(event)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        settle(100)
        if any(str(entry["id"]) == event.id for entry in bridge.notificationHistory()):
            bridge.shutdown()
            return EXIT_OK
    return EXIT_REGRESSED


def _resolve_it() -> int:
    boot = boot_main_qml(keep_settings=True)
    if isinstance(boot, int):
        return boot
    _root, _q, settle, bridge = boot
    import time

    from waves.events import EventDomain, application_event

    identity = application_event(EventDomain.LIBRARY, "", key="restart-open").id
    entry = bridge._history.entry(identity)
    if entry is None:
        return EXIT_REGRESSED
    assert str(entry["lifecycle"]) == "active", "the active issue survived the restart"
    # The owning scope resolves with no live index entry (fresh process): the
    # retained history must follow it.
    bridge._events.resolve(EventDomain.LIBRARY)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        settle(100)
        current = bridge._history.entry(identity)
        if current is not None and str(current["lifecycle"]) == "resolved":
            bridge.shutdown()
            return EXIT_OK
    return EXIT_REGRESSED


def _seed_old_entry() -> int:
    boot = boot_main_qml()
    if isinstance(boot, int):
        return boot
    _root, _q, _settle, bridge = boot
    import time

    from waves.events import EventDomain, application_event

    # The configured window must be in force before the old entry is recorded,
    # so the store itself keeps it; flush so the file is on disk for child two.
    bridge.setWavesPref("notify_history_days", 30)
    payload = application_event(EventDomain.LIBRARY, "Ten days old", key="retention-window").finish().payload()
    bridge._history.record(payload, now=time.time() - 10 * 86400)
    bridge._save_notification_history()
    bridge._config_writer.flush()
    bridge.shutdown()
    return EXIT_OK


def _expect_old_entry() -> int:
    boot = boot_main_qml(keep_settings=True)
    if isinstance(boot, int):
        return boot
    _root, _q, _settle, bridge = boot
    from waves.events import EventDomain, application_event

    identity = application_event(EventDomain.LIBRARY, "", key="retention-window").id
    entry = bridge._history.entry(identity)
    bridge.shutdown()
    if entry is not None and str(entry["lifecycle"]) == "resolved":
        return EXIT_OK
    return EXIT_REGRESSED


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_run_scenario())
if __name__ == "__main__" and "--publish-open" in sys.argv:
    raise SystemExit(_publish_open())
if __name__ == "__main__" and "--resolve-it" in sys.argv:
    raise SystemExit(_resolve_it())
if __name__ == "__main__" and "--seed-old-entry" in sys.argv:
    raise SystemExit(_seed_old_entry())
if __name__ == "__main__" and "--expect-old-entry" in sys.argv:
    raise SystemExit(_expect_old_entry())
