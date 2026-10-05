"""Privacy, lifecycle and GUI-thread delivery at the application-event boundary."""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication

from waves.desktop.backend import WavesBridge
from waves.desktop.diagnostics.events import ApplicationEvents, operation_state, provider_failure_event
from waves.desktop.settings.persistence import SingleFlightWriter
from waves.events import (
    ApplicationEvent,
    EventAction,
    EventCode,
    EventDomain,
    EventReferences,
    FailureScope,
    application_event,
)
from waves.redaction import register_secret


@pytest.fixture
def event_loop():
    app = QCoreApplication.instance() or QCoreApplication([])
    yield app
    app.processEvents()


def test_every_event_representation_is_redacted_before_export(tmp_path):
    credential = "event-test-private-credential"
    register_secret(credential)
    private = f"{tmp_path}/Private Album/secret-song.flac"
    text = f'password="two private words" token={credential} path="{private}"'
    event = application_event(
        EventDomain.DOWNLOAD,
        text,
        key=private,
        title=text,
        references=EventReferences(provider_id="apple", media_id=text, engine_id=text, runtime_id=text),
        details=(text,),
        exception=RuntimeError(text),
        actions=(EventAction.COPY_DIAGNOSTICS,),
    )
    for representation in (repr(event), json.dumps(event.payload()), event.copy_text()):
        for value in (credential, "two private words", "Private Album", "secret-song.flac", str(tmp_path)):
            assert value not in representation
    assert event.id == application_event(EventDomain.DOWNLOAD, "different cause", key=private).id
    assert "RuntimeError" not in event.summary
    assert "RuntimeError" in event.diagnostics


def test_export_scrubs_newly_learned_credentials():
    event = application_event(EventDomain.ACCOUNT, "account-private-value")
    register_secret("account-private-value")
    assert "account-private-value" not in json.dumps(event.payload())
    assert "account-private-value" not in event.copy_text()


def test_actions_and_identifiers_cannot_carry_arbitrary_commands():
    with pytest.raises(ValueError):
        application_event(EventDomain.RUNTIME, "safe", actions=("run_shell",))
    with pytest.raises(ValueError):
        ApplicationEvent("/private/home", EventDomain.RUNTIME, EventCode.FAILED, "safe", "safe")
    with pytest.raises(ValueError):
        EventReferences(job_id=True)


def test_unknown_exception_words_do_not_classify_an_account_or_runtime_failure():
    provider = SimpleNamespace(id="future-provider")
    event = provider_failure_event(provider, EventDomain.DOWNLOAD, RuntimeError("401 wrapper credentials"))
    assert event.scope == FailureScope.UNKNOWN
    assert not event.retryable
    assert "401" not in event.summary
    assert EventAction.RECONNECT not in event.actions


def test_worker_publication_is_queued_and_guarded_on_the_gui_thread(event_loop):
    relay = ApplicationEvents()
    seen = []
    guard_threads = []
    gui_thread = threading.get_ident()
    valid = True
    relay.changed.connect(lambda payload: seen.append((threading.get_ident(), payload)))
    event = application_event(EventDomain.SEARCH, "Search failed", actions=(EventAction.OPEN_LOGS,))

    def guard():
        guard_threads.append(threading.get_ident())
        return valid

    worker = threading.Thread(target=lambda: relay.publish(event, guard))
    worker.start()
    worker.join()
    assert seen == []
    event_loop.processEvents()
    assert seen[0][0] == gui_thread
    assert guard_threads == [gui_thread]
    valid = False
    assert relay.action(event.id, EventAction.OPEN_LOGS) is None
    assert seen[-1][1]["lifecycle"] == "resolved"
    assert seen[-1][1]["actions"] == []


def test_repeated_issue_updates_one_identity_and_recovery_revokes_actions(event_loop):
    relay = ApplicationEvents()
    seen = []
    relay.changed.connect(seen.append)
    event = application_event(
        EventDomain.RUNTIME,
        "Runtime unavailable",
        key="apple:wrapper",
        references=EventReferences(provider_id="apple"),
        actions=(EventAction.OPEN_SETTINGS,),
    )
    relay.publish(event)
    relay.publish(event)
    event_loop.processEvents()
    assert [value["id"] for value in seen] == [event.id, event.id]
    assert seen[-1]["occurrences"] == 2
    relay.resolve(EventDomain.RUNTIME, "apple")
    event_loop.processEvents()
    assert seen[-1]["lifecycle"] == "resolved"
    assert relay.action(event.id, EventAction.OPEN_SETTINGS) is None


def test_revoked_generation_and_shutdown_drop_late_publication(event_loop):
    relay = ApplicationEvents()
    seen = []
    relay.changed.connect(seen.append)
    current = True
    event = application_event(EventDomain.LIBRARY, "Could not scan")
    relay.publish(event, lambda: current)
    current = False
    event_loop.processEvents()
    assert seen == []
    relay.publish(event)
    relay.close()
    event_loop.processEvents()
    assert seen == []


def test_bridge_only_dispatches_advertised_current_actions(event_loop, monkeypatch):
    relay = ApplicationEvents()
    copied = []
    monkeypatch.setattr(
        "waves.desktop.backend.QtGui.QGuiApplication.clipboard", lambda: SimpleNamespace(setText=copied.append)
    )
    event = application_event(
        EventDomain.DOWNLOAD,
        "Download failed",
        exception=ValueError("token=private123"),
        references=EventReferences(job_id=7),
        actions=(EventAction.COPY_DIAGNOSTICS, EventAction.RETRY_JOB),
    )
    relay.publish(event)
    event_loop.processEvents()
    row = {"status": "failed"}
    retries = []
    bridge = SimpleNamespace(_events=relay, _queue_item=lambda qid: row, retryQueueItem=retries.append)
    assert not WavesBridge.eventAction(bridge, event.id, "arbitrary_url")
    assert WavesBridge.eventAction(bridge, event.id, "copy_diagnostics")
    assert "private123" not in copied[0]
    assert WavesBridge.eventAction(bridge, event.id, "retry_job")
    assert retries == [7]
    row["status"] = "running"
    assert not WavesBridge.eventAction(bridge, event.id, "retry_job")
    WavesBridge.dismissEvent(bridge, event.id)
    assert not WavesBridge.eventAction(bridge, event.id, "copy_diagnostics")


def test_install_failure_legacy_payload_and_event_are_both_redacted(event_loop):
    relay = ApplicationEvents()
    events = []
    states = []
    relay.changed.connect(events.append)
    bridge = SimpleNamespace(_events=relay, ffmpegStateChanged=SimpleNamespace(emit=lambda *args: states.append(args)))
    operation_state(
        bridge,
        EventDomain.DEPENDENCY,
        "ffmpegStateChanged",
        "failed",
        "Cannot install: password=private123 at /Volumes/Private Music/install.bin",
        exception=PermissionError("/Volumes/Private Music/install.bin"),
    )
    event_loop.processEvents()
    for value in (str(states), json.dumps(events)):
        assert "private123" not in value
        assert "Private Music" not in value
        assert "install.bin" not in value
    assert events[0]["scope"] == "configuration"
    operation_state(bridge, EventDomain.DEPENDENCY, "ffmpegStateChanged", "done", "Ready")
    event_loop.processEvents()
    assert events[-1]["lifecycle"] == "resolved"


def test_background_configuration_failure_reports_actual_disk_result(event_loop):
    relay = ApplicationEvents()
    seen = []
    relay.changed.connect(seen.append)
    bridge = SimpleNamespace(_events=relay)
    writer = SingleFlightWriter(lambda key, error: WavesBridge._config_write_finished(bridge, key, error))

    def fail():
        raise OSError("Cannot write /Volumes/Private Music/settings.json password=private123")

    writer.submit("settings", fail)
    writer.flush()
    event_loop.processEvents()
    assert seen[-1]["domain"] == "configuration"
    assert seen[-1]["lifecycle"] == "active"
    assert "private123" not in json.dumps(seen)
    writer.submit("settings", lambda: None)
    writer.flush()
    event_loop.processEvents()
    assert seen[-1]["lifecycle"] == "resolved"


def test_one_update_recovery_preserves_the_other_operation_actions(event_loop):
    relay = ApplicationEvents()
    bridge = SimpleNamespace(
        _events=relay,
        ffmpegStateChanged=SimpleNamespace(emit=lambda *args: None),
        ffmpegProbeChanged=SimpleNamespace(emit=lambda *args: None),
    )
    seen = []
    relay.changed.connect(seen.append)
    operation_state(bridge, EventDomain.DEPENDENCY, "ffmpegStateChanged", "failed", "Install failed")
    operation_state(bridge, EventDomain.DEPENDENCY, "ffmpegProbeChanged", "failed", "Probe failed")
    event_loop.processEvents()
    install, probe = seen
    operation_state(bridge, EventDomain.DEPENDENCY, "ffmpegProbeChanged", "done", "Ready")
    event_loop.processEvents()
    assert relay.action(install["id"], "open_settings") is not None
    assert relay.action(probe["id"], "open_settings") is None


def test_apple_job_events_follow_the_queue_settle_and_provider_epoch(event_loop):
    from waves.desktop.providers.lifecycle import ProviderContexts

    relay = ApplicationEvents()
    seen = []
    relay.changed.connect(seen.append)
    contexts = ProviderContexts()
    row = {"status": "failed"}
    bridge = SimpleNamespace(_events=relay, _provider_contexts=contexts, _queue_item=lambda qid: row)
    hooks = WavesBridge._apple_job_hooks(bridge)
    event = application_event(
        EventDomain.DOWNLOAD,
        "Runtime unavailable",
        references=EventReferences(provider_id="apple", job_id=7),
        actions=(EventAction.OPEN_SETTINGS,),
    )
    hooks.event(event)
    row["status"] = "cancelled"
    event_loop.processEvents()
    assert seen == []
    row["status"] = "failed"
    hooks.event(event)
    contexts.revoke("apple")
    event_loop.processEvents()
    assert seen == []


def test_library_scan_reports_missing_folder_and_resolves_after_recovery(event_loop, tmp_path):
    from library.fakes import make_library_bridge

    root = tmp_path / "Private Music"
    bridge = make_library_bridge(tmp_path, library_folder=str(root))
    bridge._events = ApplicationEvents()
    seen = []
    bridge._events.changed.connect(seen.append)
    try:
        bridge._rebuild_library_index()
        event_loop.processEvents()
        failure = seen[-1]
        assert failure["code"] == "path_unreachable"
        assert failure["scope"] == "configuration"
        assert "Private Music" not in json.dumps(seen)
        root.mkdir()
        bridge._rebuild_library_index()
        event_loop.processEvents()
        assert seen[-1]["id"] == failure["id"]
        assert seen[-1]["lifecycle"] == "resolved"
        assert bridge._events.action(failure["id"], "open_settings") is None
    finally:
        bridge._library.close()


def test_library_scan_exception_is_diagnostic_and_revoked_roots_cannot_publish(event_loop, tmp_path):
    from library.fakes import make_library_bridge

    root = tmp_path / "Private Music"
    root.mkdir()
    bridge = make_library_bridge(tmp_path, library_folder=str(root))
    bridge._events = ApplicationEvents()
    seen = []
    bridge._events.changed.connect(seen.append)

    def fail(*args):
        raise PermissionError(f'Authorization: Basic dXNlcjpwYXNz path="{root}/secret.flac"')

    bridge._library_scan_once = fail
    try:
        bridge._rebuild_library_index()
        event_loop.processEvents()
        assert seen[-1]["scope"] == "configuration"
        assert "PermissionError" not in seen[-1]["summary"]
        assert "PermissionError" in seen[-1]["diagnostics"]
        assert "dXNlcjpwYXNz" not in json.dumps(seen)
        assert "secret.flac" not in json.dumps(seen)
        seen.clear()
        bridge._rebuild_library_index()
        bridge.setWavesPref("library_folder", str(tmp_path / "new-root"))
        event_loop.processEvents()
        assert seen == []
    finally:
        bridge._library.close()


def test_library_permission_denial_recovers_after_listing_is_allowed(event_loop, tmp_path, monkeypatch):
    import os

    from library.fakes import make_library_bridge

    import waves.library.index as library_index

    root = tmp_path / "Private Music"
    root.mkdir()
    bridge = make_library_bridge(tmp_path, library_folder=str(root))
    bridge._events = ApplicationEvents()
    seen = []
    bridge._events.changed.connect(seen.append)
    real_scandir = os.scandir
    denied = True

    def scandir(path=".", *args, **kwargs):
        if denied and os.path.abspath(path) == str(root):
            raise PermissionError(1, "Operation not permitted")
        return real_scandir(path, *args, **kwargs)

    monkeypatch.setattr(library_index.os, "scandir", scandir)
    try:
        bridge._rebuild_library_index()
        event_loop.processEvents()
        assert WavesBridge.libraryScanStatus(bridge) == "unreadable"
        failure = seen[-1]
        assert failure["scope"] == "configuration"
        assert "Private Music" not in json.dumps(seen)
        denied = False
        bridge._rebuild_library_index()
        event_loop.processEvents()
        assert seen[-1]["id"] == failure["id"]
        assert seen[-1]["lifecycle"] == "resolved"
    finally:
        bridge._library.close()


def test_folder_recovery_requires_proof_for_the_current_folder(event_loop, tmp_path):
    from threading import Lock

    root = str(tmp_path / "Private Music")
    seen = []
    relay = ApplicationEvents()
    relay.changed.connect(seen.append)
    bridge = SimpleNamespace(
        _events=relay,
        _base_ok=("", 0.0),
        _BASE_OK_TTL_SEC=WavesBridge._BASE_OK_TTL_SEC,
        settings=SimpleNamespace(data=SimpleNamespace(download_base_path=root)),
        _pending_lock=Lock(),
        _pending_downloads=[],
        _probe_download_base=lambda: ("dead", root),
        _set_status=lambda message: None,
        _remember_share_origin=lambda base: None,
        downloadFolderUnreachable=SimpleNamespace(emit=lambda path: None),
        _recoveryWatchWanted=SimpleNamespace(emit=lambda: None),
    )
    bridge._stash_pending_download = WavesBridge._stash_pending_download.__get__(bridge)
    bridge._note_download_base_ok = WavesBridge._note_download_base_ok.__get__(bridge)
    assert not WavesBridge._gate_reachability(bridge, lambda: None, "media-id")
    event_loop.processEvents()
    failure = seen[-1]
    assert failure["code"] == "path_unreachable"
    assert "Private Music" not in json.dumps(seen)
    bridge.settings.data.download_base_path = str(tmp_path / "new-folder")
    bridge._note_download_base_ok(root)
    event_loop.processEvents()
    assert seen[-1]["lifecycle"] == "active"
    bridge._probe_download_base = lambda: ("ok", bridge.settings.data.download_base_path)
    assert WavesBridge._gate_reachability(bridge, lambda: None)
    event_loop.processEvents()
    assert seen[-1]["id"] == failure["id"]
    assert seen[-1]["lifecycle"] == "resolved"
    assert relay.action(failure["id"], "open_settings") is None
