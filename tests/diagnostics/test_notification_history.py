"""The notification center's history store: one redacted entry per event identity,
retained under the configured caps, resolvable across a restart."""

from __future__ import annotations

import json

from waves.desktop.diagnostics import notifications
from waves.desktop.diagnostics.notifications import NotificationHistory
from waves.events import EventDomain, EventReferences, Lifecycle, application_event
from waves.redaction import register_secret


def _payload(
    key: str,
    summary: str,
    *,
    lifecycle: str = "active",
    occurrences: int = 1,
    job_id: int | None = None,
    provider_id: str = "",
) -> dict:
    event = application_event(
        EventDomain.DOWNLOAD,
        summary,
        key=key,
        references=EventReferences(provider_id=provider_id, job_id=job_id),
    )
    if lifecycle != "active":
        event = event.finish(Lifecycle(lifecycle))
    payload = event.payload()
    payload["occurrences"] = occurrences
    return payload


def test_one_entry_per_identity_keeps_peak_occurrences_and_terminal_state(tmp_path):
    history = NotificationHistory(str(tmp_path / "notifications.json"))
    first = _payload("job:7", "Finished Track A")
    history.record(first)
    assert len(history.entries()) == 1

    history.record(_payload("job:7", "Finished Track A", occurrences=3))
    entry = history.entry(first["id"])
    assert entry is not None
    assert entry["occurrences"] == 3
    assert entry["lifecycle"] == "active"

    history.record(_payload("job:7", "Finished Track A", lifecycle="resolved"))
    entry = history.entry(first["id"])
    assert entry["lifecycle"] == "resolved"
    assert entry["actions"] == []
    assert len(history.entries()) == 1


def test_entries_are_newest_updated_first(tmp_path):
    history = NotificationHistory(str(tmp_path / "notifications.json"))
    history.record(_payload("job:1", "One"), now=1000.0)
    history.record(_payload("job:2", "Two"), now=1001.0)
    assert [e["summary"] for e in history.entries()] == ["Two", "One"]

    history.record(_payload("job:1", "One"), now=1002.0)
    assert [e["summary"] for e in history.entries()] == ["One", "Two"]


def test_age_cap_prunes_terminal_entries_but_keeps_active_issues(tmp_path):
    history = NotificationHistory(str(tmp_path / "notifications.json"), max_age_days=7)
    now = 1_000_000.0
    old = now - 8 * 86400
    history.record(_payload("job:done", "Done long ago", lifecycle="resolved"), now=old)
    history.record(_payload("job:open", "Still broken"), now=old)
    history.record(_payload("job:fresh", "Fresh"), now=now)
    assert {e["summary"] for e in history.entries()} == {"Still broken", "Fresh"}


def test_count_cap_prunes_oldest_terminal_first_and_ignores_active_issues(tmp_path):
    history = NotificationHistory(str(tmp_path / "notifications.json"), max_entries=2)
    history.record(_payload("job:1", "One", lifecycle="resolved"), now=1000.0)
    history.record(_payload("job:2", "Two", lifecycle="resolved"), now=1001.0)
    history.record(_payload("job:3", "Three", lifecycle="resolved"), now=1002.0)
    assert [e["summary"] for e in history.entries()] == ["Three", "Two"]

    history.record(_payload("job:4", "Alert"), now=1003.0)
    assert [e["summary"] for e in history.entries()] == ["Alert", "Three", "Two"]


def test_set_limits_clamps_and_prunes_to_the_new_cap(tmp_path):
    history = NotificationHistory(str(tmp_path / "notifications.json"))
    assert history.set_limits(max_entries=5000, max_age_days=0, now=0.0) == (200, 1)
    history.record(_payload("job:1", "One", lifecycle="resolved"), now=1000.0)
    history.record(_payload("job:2", "Two", lifecycle="resolved"), now=1001.0)
    history.set_limits(max_entries=1, max_age_days=7, now=1002.0)
    assert [e["summary"] for e in history.entries()] == ["Two"]


def test_clear_drops_terminal_history_and_keeps_active_issues(tmp_path):
    history = NotificationHistory(str(tmp_path / "notifications.json"))
    history.record(_payload("job:done", "Done", lifecycle="resolved"))
    history.record(_payload("job:open", "Broken"))
    history.clear()
    assert [e["summary"] for e in history.entries()] == ["Broken"]


def test_snapshot_and_load_round_trip_and_resolve_across_restart(tmp_path):
    path = str(tmp_path / "notifications.json")
    history = NotificationHistory(path)
    active = _payload("job:open", "Still broken")
    history.record(active, now=1000.0)
    history.record(_payload("job:done", "Finished", lifecycle="resolved"), now=1001.0)
    (tmp_path / "notifications.json").write_text(history.snapshot(), encoding="utf-8")

    restarted = NotificationHistory(path)
    restarted.load(now=1002.0)
    assert [e["id"] for e in restarted.entries()] == [e["id"] for e in history.entries()]

    restarted.record(_payload("job:open", "Still broken", lifecycle="resolved"), now=1003.0)
    assert restarted.entry(active["id"])["lifecycle"] == "resolved"


def test_unreadable_history_is_set_aside_and_saving_latches_off_when_it_cannot_move(monkeypatch, tmp_path):
    path = tmp_path / "notifications.json"
    path.write_text("{not json", encoding="utf-8")
    history = NotificationHistory(str(path))
    history.load()
    assert history.entries() == [] and history.savable
    assert not path.exists()
    assert list(tmp_path.glob("notifications.json.bak*"))

    blocked = tmp_path / "locked.json"
    blocked.write_text("{{{", encoding="utf-8")
    other = NotificationHistory(str(blocked))
    monkeypatch.setattr(
        notifications.os, "replace", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("read-only"))
    )
    other.load()
    assert other.entries() == [] and not other.savable


def test_load_re_scrubs_stored_text(tmp_path):
    register_secret("history-private-value")
    path = tmp_path / "notifications.json"
    payload = _payload("job:secret", "safe")
    payload["summary"] = "history-private-value"
    payload["details"] = ["copy of history-private-value"]
    path.write_text(json.dumps([payload]), encoding="utf-8")
    history = NotificationHistory(str(path))
    history.load()
    assert "history-private-value" not in json.dumps(history.entries())


def test_finish_matching_resolves_the_stored_scope_and_only_once(tmp_path):
    history = NotificationHistory(str(tmp_path / "notifications.json"))
    first = _payload("job:1", "One", job_id=1)
    second = _payload("job:2", "Two", job_id=2)
    history.record(first, now=1000.0)
    history.record(second, now=1001.0)

    assert history.finish_matching(domain="download", job_id=9, now=1002.0) is False, (
        "an unmatched scope resolves nothing"
    )
    assert history.finish_matching(domain="download", job_id=1, now=1002.0) is True
    entry = history.entry(first["id"])
    assert entry["lifecycle"] == "resolved" and entry["actions"] == []
    assert entry["updated_at"] == 1002.0
    assert history.entry(second["id"])["lifecycle"] == "active"
    assert history.finish_matching(domain="download", job_id=1, now=1003.0) is False, "already terminal"


def test_finish_matching_honours_provider_and_identity(tmp_path):
    history = NotificationHistory(str(tmp_path / "notifications.json"))
    apple = application_event(
        EventDomain.DOWNLOAD, "Apple failed", key="apple", references=EventReferences(provider_id="apple", job_id=3)
    ).payload()
    tidal = application_event(
        EventDomain.DOWNLOAD, "Tidal failed", key="tidal", references=EventReferences(provider_id="tidal", job_id=3)
    ).payload()
    history.record(apple)
    history.record(tidal)

    assert history.finish_matching(domain="download", provider_id="apple", job_id=3) is True
    assert history.entry(tidal["id"])["lifecycle"] == "active", "the other provider's issue stays"
    assert history.finish_matching(domain="download", identity="missing") is False
    assert history.finish_matching(domain="download", identity=tidal["id"]) is True
    assert history.entry(tidal["id"])["lifecycle"] == "resolved"
