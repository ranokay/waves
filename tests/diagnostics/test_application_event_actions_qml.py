"""Allowlisted event actions reach the composed QML settings and logs surfaces."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from support.qml import EXIT_OK, EXIT_REGRESSED, boot_main_qml, run_scenario, wait_until


@pytest.mark.qml
def test_event_actions_open_existing_surfaces_and_copy_safe_diagnostics():
    run_scenario(Path(__file__), "--run-scenario", sandbox_prefix="waves-event-actions-")


def _run_scenario() -> int:
    boot = boot_main_qml()
    if isinstance(boot, int):
        return boot
    _root, q, _settle, bridge = boot
    from PySide6.QtGui import QGuiApplication

    from waves.events import EventAction, EventDomain, application_event

    seen = []
    bridge.applicationEvent.connect(seen.append)
    event = application_event(
        EventDomain.CONFIGURATION,
        "Settings could not be saved",
        exception=PermissionError('password=private123 path="/Volumes/Private Music/config.json"'),
        actions=(EventAction.OPEN_SETTINGS, EventAction.OPEN_LOGS, EventAction.COPY_DIAGNOSTICS),
    )
    bridge._events.publish(event)
    wait_until(lambda: bool(seen), message="event reached QML")
    assert not bridge.eventAction(event.id, "run_shell")
    assert bridge.eventAction(event.id, "open_settings")
    wait_until(lambda: bool(q("settingsOpen")), message="settings action")
    assert bridge.eventAction(event.id, "open_logs")
    wait_until(lambda: bool(q("logsDrawer.visible")), message="logs action")
    assert bridge.eventAction(event.id, "copy_diagnostics")
    copied = QGuiApplication.clipboard().text()
    for payload in (copied, json.dumps(seen)):
        assert "private123" not in payload
        assert "Private Music" not in payload
        assert "config.json" not in payload
    bridge.dismissEvent(event.id)
    q("logsDrawer.close()")
    wait_until(lambda: not bool(q("logsDrawer.visible")), message="logs closed")
    rejected = not bridge.eventAction(event.id, "open_logs")
    bridge.shutdown()
    return EXIT_OK if rejected else EXIT_REGRESSED


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    raise SystemExit(_run_scenario())
