"""Bridge delivery for the notification center: recorded history, store writes,
copy/report actions and the factory wipe."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication

from waves.desktop import backend as bk
from waves.desktop.backend import WavesBridge
from waves.desktop.diagnostics.notifications import NotificationHistory
from waves.desktop.settings.persistence import SingleFlightWriter
from waves.events import EventDomain, application_event
from waves.redaction import register_secret


@pytest.fixture
def event_loop():
    app = QCoreApplication.instance() or QCoreApplication([])
    yield app
    app.processEvents()


class _Stub:
    pass


def _bind(stub, name):
    return getattr(WavesBridge, name).__get__(stub, type(stub))


def _history_stub(tmp_path):
    stub = _Stub()
    stub._history_path = str(tmp_path / "notifications.json")
    stub._history = NotificationHistory(stub._history_path)
    stub._factory_reset = False
    stub._config_writer = SingleFlightWriter()
    stub._waves_prefs = {"notify_history_max": 200, "notify_history_days": 7}
    changed = []
    stub.notificationsChanged = SimpleNamespace(emit=lambda: changed.append(True))
    for name in (
        "_record_notification",
        "_save_notification_history",
        "_resolve_notification",
        "_waves_pref_int",
        "_apply_notification_limits",
    ):
        setattr(stub, name, _bind(stub, name))
    return stub, changed


def test_recording_persists_through_the_writer_and_notifies(event_loop, tmp_path):
    stub, changed = _history_stub(tmp_path)
    payload = application_event(EventDomain.DOWNLOAD, "Finished Track", key="job:7").payload()
    stub._record_notification(payload)
    stub._config_writer.flush()
    assert changed
    stored = json.loads((tmp_path / "notifications.json").read_text(encoding="utf-8"))
    assert [entry["id"] for entry in stored] == [payload["id"]]


def test_factory_reset_stops_history_writes(event_loop, tmp_path):
    stub, _ = _history_stub(tmp_path)
    stub._factory_reset = True
    stub._record_notification(application_event(EventDomain.DOWNLOAD, "Finished", key="job:7").payload())
    stub._config_writer.flush()
    assert not (tmp_path / "notifications.json").exists()


def test_history_slots_serve_history_status_and_clear(event_loop, tmp_path):
    stub, _changed = _history_stub(tmp_path)
    active = application_event(EventDomain.RUNTIME, "Runtime unavailable", key="apple:wrapper").payload()
    done = application_event(EventDomain.DOWNLOAD, "Finished", key="job:7").finish().payload()
    stub._record_notification(active)
    stub._record_notification(done)

    assert {entry["id"] for entry in WavesBridge.notificationHistory(stub)} == {active["id"], done["id"]}
    assert WavesBridge.notificationStatus(stub) == {"active": 1, "count": 2}

    WavesBridge.clearNotificationHistory(stub)
    assert [entry["id"] for entry in WavesBridge.notificationHistory(stub)] == [active["id"]]
    stub._config_writer.flush()


def test_copy_and_report_actions_re_scrub_a_stored_entry(event_loop, tmp_path, monkeypatch):
    stub, _ = _history_stub(tmp_path)
    register_secret("center-private-value")
    payload = application_event(EventDomain.CONFIGURATION, "Settings could not be saved", key="config").payload()
    payload["summary"] = "center-private-value"
    payload["details"] = ["center-private-value"]
    stub._history.record(payload)

    assert not WavesBridge.copyEventDiagnostics(stub, "0" * 32)
    copied = []
    monkeypatch.setattr(bk.QtGui.QGuiApplication, "clipboard", lambda: SimpleNamespace(setText=copied.append))
    assert WavesBridge.copyEventDiagnostics(stub, payload["id"])
    assert "center-private-value" not in copied[0]

    opened = []
    monkeypatch.setattr(bk.QtGui.QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(str(url))))
    assert not WavesBridge.reportEventIssue(stub, "0" * 32)
    stub._updater = SimpleNamespace(repository_url=lambda: "https://github.com/example/repo")
    assert WavesBridge.reportEventIssue(stub, payload["id"])
    assert "/issues/new" in opened[0] and "center-private-value" not in opened[0]


def test_notification_limits_follow_the_prefs_and_clamp(event_loop, tmp_path):
    stub, changed = _history_stub(tmp_path)
    stub._waves_prefs = {"notify_history_max": 5000, "notify_history_days": 0}
    stub._apply_notification_limits()
    assert (stub._history.max_entries, stub._history.max_age_days) == (200, 1)
    assert changed

    assert WavesBridge._waves_pref_int(stub, "missing", 7) == 7
    stub._waves_prefs["notify_history_max"] = "12"
    assert WavesBridge._waves_pref_int(stub, "notify_history_max") == 12


def test_a_resolution_reaches_the_retained_history_without_a_live_index_entry(event_loop, tmp_path):
    from waves.desktop.diagnostics.events import ApplicationEvents

    stub, changed = _history_stub(tmp_path)
    payload = application_event(EventDomain.LIBRARY, "Folder unreachable", key="scope").payload()
    stub._record_notification(payload)
    relay = ApplicationEvents()
    relay.resolved.connect(stub._resolve_notification)
    relay.publish(application_event(EventDomain.LIBRARY, "Folder unreachable", key="scope"))
    event_loop.processEvents()
    relay.resolve(EventDomain.LIBRARY)
    event_loop.processEvents()
    assert stub._history.entry(payload["id"])["lifecycle"] == "resolved"
    assert changed


def test_factory_wipe_covers_the_notification_history():
    assert "notifications.json" in bk._FACTORY_WIPE_FILES
    assert "notifications.json.bak" in bk._FACTORY_WIPE_FILES
    assert any(pattern.match("notifications.json.abc123.tmp") for pattern in bk._FACTORY_WIPE_LOG_PATTERNS)
    assert any(pattern.match("notifications.json.bak-20260101-120000") for pattern in bk._FACTORY_WIPE_LOG_PATTERNS)
