"""Apple runtime admission keeps account evidence separate from reachability."""

import json
import os
from dataclasses import replace
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace

import pytest

from waves.providers.apple.runtime_sessions import (
    AccountContext,
    AppleRuntimeSessions,
    RuntimeKind,
    RuntimeProfile,
    SessionEvidence,
)
from waves.providers.apple.supervision import SidecarSupervisor


def test_matching_storefront_requires_confirmation_when_account_identity_is_unknown(tmp_path):
    sessions = AppleRuntimeSessions(tmp_path)
    sessions.configure(
        RuntimeProfile("apple:wrapper-v2", RuntimeKind.USER_MANAGED, "wrapper-v2", "http://127.0.0.1:50100")
    )
    sessions.set_account(AccountContext("", "us", "cookies-revision-1"))
    sessions.observe("apple:wrapper-v2", SessionEvidence(True, True, True, True, "", "us", "session-1"))
    assert sessions.readiness("apple:wrapper-v2") == "confirmation_required"
    assert sessions.confirm_account("apple:wrapper-v2") is True
    assert sessions.readiness("apple:wrapper-v2") == "ready"


def test_deliberate_stop_survives_restoration_and_resume_requires_fresh_evidence(tmp_path):
    profile = RuntimeProfile("apple:wrapper-v2", RuntimeKind.USER_MANAGED, "wrapper-v2", "http://127.0.0.1:50100")
    sessions = AppleRuntimeSessions(tmp_path)
    sessions.configure(profile)
    sessions.stop(profile.id)
    restored = AppleRuntimeSessions(tmp_path)
    restored.configure(profile)
    assert restored.is_stopped(profile.id)
    assert restored.readiness(profile.id) == "stopped"
    restored.resume(profile.id)
    assert not AppleRuntimeSessions(tmp_path).is_stopped(profile.id)
    assert restored.readiness(profile.id) == "unknown"


def test_resuming_one_runtime_after_corrupt_choices_keeps_every_other_runtime_stopped(tmp_path):
    (tmp_path / "runtime-choices.json").write_text("not valid JSON", encoding="utf-8")
    sessions = AppleRuntimeSessions(tmp_path)
    sessions.resume("apple:wrapper-v2")

    assert not sessions.is_stopped("apple:wrapper-v2")
    assert sessions.is_stopped("apple:lite")
    assert sessions.is_stopped("apple:future-runtime")
    restored = AppleRuntimeSessions(tmp_path)
    assert not restored.is_stopped("apple:wrapper-v2")
    assert restored.is_stopped("apple:lite")
    assert restored.is_stopped("apple:future-runtime")


def test_failed_resume_keeps_the_runtime_stopped_in_memory_and_after_restoration(tmp_path, monkeypatch):
    sessions = AppleRuntimeSessions(tmp_path)
    sessions.stop("apple:wrapper-v2")
    revision = sessions.revision("apple:wrapper-v2")

    def fail_save(*args, **kwargs):
        raise OSError("choice persistence refused")

    monkeypatch.setattr(os, "replace", fail_save)
    with pytest.raises(OSError, match="choice persistence refused"):
        sessions.resume("apple:wrapper-v2")

    assert sessions.is_stopped("apple:wrapper-v2")
    assert sessions.revision("apple:wrapper-v2") != revision
    assert AppleRuntimeSessions(tmp_path).is_stopped("apple:wrapper-v2")


def test_queued_old_resume_cannot_undo_a_newer_stop(tmp_path):
    sessions = AppleRuntimeSessions(tmp_path)
    runtime_id = "apple:wrapper-v2"
    sessions.stop(runtime_id)
    older_resume = sessions.request_resume(runtime_id)
    newer_stop = sessions.request_stop(runtime_id)
    assert sessions.stop(runtime_id, expected_choice=newer_stop) is True
    revision = sessions.revision(runtime_id)

    assert sessions.resume(runtime_id, expected_choice=older_resume) is False

    assert sessions.is_stopped(runtime_id)
    assert sessions.revision(runtime_id) == revision
    assert AppleRuntimeSessions(tmp_path).is_stopped(runtime_id)


def test_queued_old_stop_cannot_overwrite_a_newer_resume(tmp_path):
    sessions = AppleRuntimeSessions(tmp_path)
    runtime_id = "apple:wrapper-v2"
    older_stop = sessions.request_stop(runtime_id)
    newer_resume = sessions.request_resume(runtime_id)
    assert sessions.is_stopped(runtime_id)
    assert sessions.resume(runtime_id, expected_choice=newer_resume) is True
    revision = sessions.revision(runtime_id)

    assert sessions.stop(runtime_id, expected_choice=older_stop) is False

    assert not sessions.is_stopped(runtime_id)
    assert sessions.revision(runtime_id) == revision
    assert not AppleRuntimeSessions(tmp_path).is_stopped(runtime_id)


def test_failed_latest_resume_keeps_the_requested_resource_held(tmp_path, monkeypatch):
    sessions = AppleRuntimeSessions(tmp_path)
    runtime_id = "apple:wrapper-v2"
    sessions.stop(runtime_id)
    resume_choice = sessions.request_resume(runtime_id)
    assert sessions.is_stopped(runtime_id)

    def fail_save(*args, **kwargs):
        raise OSError("choice persistence refused")

    monkeypatch.setattr(os, "replace", fail_save)
    with pytest.raises(OSError, match="choice persistence refused"):
        sessions.resume(runtime_id, expected_choice=resume_choice)

    assert sessions.is_stopped(runtime_id)
    assert AppleRuntimeSessions(tmp_path).is_stopped(runtime_id)


def test_pending_restore_keeps_only_the_latest_requested_choice(tmp_path):
    (tmp_path / "runtime-choices.json").write_text("corrupt choices", encoding="utf-8")
    sessions = AppleRuntimeSessions(tmp_path, load_choices=False)
    older_resume = sessions.request_resume("apple:wrapper-v2")
    newer_stop = sessions.request_stop("apple:wrapper-v2")
    assert sessions.resume("apple:wrapper-v2", expected_choice=older_resume) is False
    assert sessions.stop("apple:wrapper-v2", expected_choice=newer_stop) is True
    sessions.request_resume("apple:lite")

    sessions.restore_choices()

    assert sessions.is_stopped("apple:wrapper-v2")
    assert not sessions.is_stopped("apple:lite")
    assert sessions.is_stopped("apple:future-runtime")
    restored = AppleRuntimeSessions(tmp_path)
    assert restored.is_stopped("apple:wrapper-v2")
    assert not restored.is_stopped("apple:lite")
    assert restored.is_stopped("apple:future-runtime")


@pytest.mark.parametrize("operation", ["stop", "resume", "restore"])
def test_disk_flush_does_not_block_memory_calls_and_persists_choices_arriving_during_write(
    tmp_path, monkeypatch, operation
):
    runtime_id = "apple:wrapper-v2"
    if operation == "restore":
        (tmp_path / "runtime-choices.json").write_text("corrupt choices", encoding="utf-8")
    sessions = AppleRuntimeSessions(tmp_path, load_choices=operation != "restore")
    sessions.configure(RuntimeProfile(runtime_id, RuntimeKind.USER_MANAGED, "wrapper-v2"))
    if operation == "resume":
        sessions.stop(runtime_id)
    choice = sessions.request_stop(runtime_id) if operation == "stop" else sessions.request_resume(runtime_id)
    flush_started = Event()
    release_flush = Event()
    memory_done = Event()
    fsync = os.fsync
    failures = []
    outcome = []
    observed = {}
    actions = {
        "restore": sessions.restore_choices,
        "stop": lambda: sessions.stop(runtime_id, expected_choice=choice),
        "resume": lambda: sessions.resume(runtime_id, expected_choice=choice),
    }

    def blocked_fsync(descriptor):
        if not flush_started.is_set():
            flush_started.set()
            assert release_flush.wait(5), "the blocked choice flush was never released"
        fsync(descriptor)

    def save():
        try:
            outcome.append(actions[operation]())
        except Exception as exc:
            failures.append(exc)

    def memory_calls():
        try:
            observed["readiness"] = sessions.readiness(runtime_id)
            observed["revision"] = sessions.revision(runtime_id)
            observed["stop"] = sessions.request_stop(runtime_id)
            observed["resume"] = sessions.request_resume("apple:lite")
            memory_done.set()
        except Exception as exc:
            failures.append(exc)

    monkeypatch.setattr(os, "fsync", blocked_fsync)
    writer = Thread(target=save)
    memory_reader = Thread(target=memory_calls)
    writer.start()
    try:
        assert flush_started.wait(2), "the choice worker never reached its flush"
        memory_reader.start()
        assert memory_done.wait(1), "memory admission and intent calls waited for the disk flush"
        assert not release_flush.is_set()
        assert observed["readiness"] == "stopped"
        assert observed["stop"] > choice
    finally:
        release_flush.set()
        writer.join(5)
        if memory_reader.ident is not None:
            memory_reader.join(5)

    assert not writer.is_alive()
    assert not memory_reader.is_alive()
    assert not failures
    assert outcome == [None if operation == "restore" else False]
    assert sessions.is_stopped(runtime_id)
    assert not sessions.is_stopped("apple:lite")
    restored = AppleRuntimeSessions(tmp_path)
    assert restored.is_stopped(runtime_id)
    assert not restored.is_stopped("apple:lite")
    assert restored.is_stopped("apple:future-runtime") is (operation == "restore")


def test_failed_stop_still_blocks_the_selected_runtime_in_memory(tmp_path, monkeypatch):
    sessions = AppleRuntimeSessions(tmp_path)
    revision = sessions.revision("apple:wrapper-v2")

    def fail_save(*args, **kwargs):
        raise OSError("choice persistence refused")

    monkeypatch.setattr(os, "replace", fail_save)
    with pytest.raises(OSError, match="choice persistence refused"):
        sessions.stop("apple:wrapper-v2")

    assert sessions.is_stopped("apple:wrapper-v2")
    assert not sessions.is_stopped("apple:lite")
    assert sessions.revision("apple:wrapper-v2") != revision


def test_memory_only_invalidation_revokes_evidence_and_confirmation_without_disk_access(tmp_path, monkeypatch):
    sessions = AppleRuntimeSessions(tmp_path)
    for runtime_id in ("apple:wrapper-v2", "apple:lite"):
        sessions.configure(RuntimeProfile(runtime_id, RuntimeKind.USER_MANAGED, "wrapper-v2"))
        sessions.observe(runtime_id, SessionEvidence(True, True, True, True, "", "us", "session-1"))
        assert sessions.confirm_account(runtime_id)
    before_wrapper = sessions.revision("apple:wrapper-v2")
    before_lite = sessions.revision("apple:lite")

    def prohibit_disk(*args, **kwargs):
        raise AssertionError("synchronous invalidation must not access disk")

    monkeypatch.setattr(Path, "read_text", prohibit_disk)
    monkeypatch.setattr(os, "replace", prohibit_disk)
    sessions.invalidate("apple:wrapper-v2")
    assert sessions.readiness("apple:wrapper-v2") == "unknown"
    assert sessions.readiness("apple:lite") == "ready"
    assert sessions.revision("apple:wrapper-v2") != before_wrapper
    assert sessions.revision("apple:lite") == before_lite

    sessions.invalidate_account()
    assert sessions.readiness("apple:wrapper-v2") == "unknown"
    assert sessions.readiness("apple:lite") == "unknown"
    assert sessions.revision("apple:lite") != before_lite


def test_first_account_establishment_preserves_the_current_probe_revision(tmp_path):
    sessions = AppleRuntimeSessions(tmp_path)
    profile = RuntimeProfile("apple:wrapper-v2", RuntimeKind.USER_MANAGED, "wrapper-v2")
    sessions.configure(profile)
    probe_revision = sessions.revision(profile.id)

    sessions.set_account(AccountContext("account-1", "us", "credentials-1"))

    assert sessions.revision(profile.id) == probe_revision
    sessions.observe(profile.id, SessionEvidence(True, True, True, True, "account-1", "us", "session-1"))
    assert sessions.readiness(profile.id) == "ready"


@pytest.mark.parametrize("change", ["stop", "account", "runtime"])
def test_old_probe_cannot_restore_admission_after_context_changes(tmp_path, change):
    sessions = AppleRuntimeSessions(tmp_path)
    profile = RuntimeProfile("apple:wrapper-v2", RuntimeKind.USER_MANAGED, "wrapper-v2")
    sessions.configure(profile)
    revision = sessions.revision(profile.id)
    if change == "stop":
        sessions.request_stop(profile.id)
    elif change == "account":
        sessions.invalidate_account()
    else:
        sessions.configure(replace(profile, endpoint="http://127.0.0.1:50100"))
    current_revision = sessions.revision(profile.id)

    result = sessions.observe_current(
        profile.id,
        revision,
        AccountContext("account-1", "us", "credentials-1"),
        SessionEvidence(True, True, True, True, "account-1", "us", "session-1"),
    )

    assert result is None
    assert sessions.revision(profile.id) == current_revision
    assert not sessions.confirm_account(profile.id)


def test_current_probe_establishes_matching_account_and_returns_its_admission_revision(tmp_path):
    sessions = AppleRuntimeSessions(tmp_path)
    profile = RuntimeProfile("apple:wrapper-v2", RuntimeKind.USER_MANAGED, "wrapper-v2")
    sessions.configure(profile)
    result = sessions.observe_current(
        profile.id,
        sessions.revision(profile.id),
        AccountContext("account-1", "us", "credentials-1"),
        SessionEvidence(True, True, True, True, "account-1", "us", "session-1"),
    )
    assert result == ("ready", sessions.revision(profile.id))
    assert sessions.readiness(profile.id) == "ready"


def test_first_account_establishment_revokes_an_existing_unknown_account_confirmation(tmp_path):
    sessions = AppleRuntimeSessions(tmp_path)
    profile = RuntimeProfile("apple:wrapper-v2", RuntimeKind.USER_MANAGED, "wrapper-v2")
    sessions.configure(profile)
    sessions.observe(profile.id, SessionEvidence(True, True, True, True, "", "us", "session-1"))
    assert sessions.confirm_account(profile.id)
    confirmed_revision = sessions.revision(profile.id)

    sessions.set_account(AccountContext("", "us", "credentials-1"))

    assert sessions.revision(profile.id) != confirmed_revision
    assert sessions.readiness(profile.id) == "confirmation_required"


def test_account_invalidation_revokes_old_work_before_the_new_context_is_established(tmp_path):
    sessions = AppleRuntimeSessions(tmp_path)
    profile = RuntimeProfile("apple:wrapper-v2", RuntimeKind.USER_MANAGED, "wrapper-v2")
    sessions.configure(profile)
    sessions.set_account(AccountContext("account-1", "us", "credentials-1"))
    sessions.observe(profile.id, SessionEvidence(True, True, True, True, "account-1", "us", "session-1"))
    old_revision = sessions.revision(profile.id)

    sessions.invalidate_account()
    invalidated_revision = sessions.revision(profile.id)
    assert invalidated_revision != old_revision
    sessions.set_account(AccountContext("account-1", "us", "credentials-2"))

    assert sessions.revision(profile.id) == invalidated_revision
    assert sessions.revision(profile.id) != old_revision
    assert sessions.readiness(profile.id) == "unknown"


def test_memory_only_stop_disconnects_admission_before_worker_persistence(tmp_path, monkeypatch):
    sessions = AppleRuntimeSessions(tmp_path)
    profile = RuntimeProfile("apple:wrapper-v2", RuntimeKind.USER_MANAGED, "wrapper-v2")
    sessions.configure(profile)
    sessions.observe(profile.id, SessionEvidence(True, True, True, True))
    assert sessions.confirm_account(profile.id)
    revision = sessions.revision(profile.id)

    def prohibit_disk(*args, **kwargs):
        raise AssertionError("request_stop must not access disk")

    monkeypatch.setattr(os, "replace", prohibit_disk)
    sessions.request_stop(profile.id)
    assert sessions.is_stopped(profile.id)
    assert sessions.readiness(profile.id) == "stopped"
    assert sessions.revision(profile.id) != revision


def test_memory_only_construction_defers_choices_and_keeps_early_actions_when_restored(tmp_path, monkeypatch):
    (tmp_path / "runtime-choices.json").write_text('{"stopped": ["apple:lite"]}', encoding="utf-8")

    def prohibit_read(*args, **kwargs):
        raise AssertionError("memory-only construction must not read choices")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_text", prohibit_read)
        patch.setattr(os, "replace", prohibit_read)
        sessions = AppleRuntimeSessions(tmp_path, load_choices=False)
        assert not sessions.choices_restored
        assert sessions.is_stopped("apple:wrapper-v2")
        assert sessions.is_stopped("apple:lite")
        sessions.request_stop("apple:wrapper-v2")
        sessions.resume("apple:lite")
        assert sessions.is_stopped("apple:lite")

    sessions.restore_choices()
    assert sessions.choices_restored
    assert sessions.is_stopped("apple:wrapper-v2")
    assert not sessions.is_stopped("apple:lite")
    restored = AppleRuntimeSessions(tmp_path)
    assert restored.is_stopped("apple:wrapper-v2")
    assert not restored.is_stopped("apple:lite")
    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_text", prohibit_read)
        sessions.restore_choices()


def test_choices_arriving_during_restore_override_the_older_disk_snapshot(tmp_path, monkeypatch):
    choices_path = tmp_path / "runtime-choices.json"
    choices_path.write_text('{"stopped": ["apple:lite"]}', encoding="utf-8")
    sessions = AppleRuntimeSessions(tmp_path, load_choices=False)
    snapshot_read = Event()
    release_read = Event()
    read_text = Path.read_text
    failures = []

    def delayed_read(path, *args, **kwargs):
        text = read_text(path, *args, **kwargs)
        if path == choices_path:
            snapshot_read.set()
            assert release_read.wait(2), "choice snapshot was never released"
        return text

    def restore():
        try:
            sessions.restore_choices()
        except Exception as exc:
            failures.append(exc)

    monkeypatch.setattr(Path, "read_text", delayed_read)
    worker = Thread(target=restore)
    worker.start()
    try:
        assert snapshot_read.wait(2), "restore did not read the disk snapshot"
        sessions.resume("apple:lite")
        sessions.request_stop("apple:wrapper-v2")
        assert sessions.is_stopped("apple:lite")
    finally:
        release_read.set()
        worker.join(2)

    assert not worker.is_alive()
    assert not failures
    assert not sessions.is_stopped("apple:lite")
    assert sessions.is_stopped("apple:wrapper-v2")
    restored = AppleRuntimeSessions(tmp_path)
    assert not restored.is_stopped("apple:lite")
    assert restored.is_stopped("apple:wrapper-v2")


def test_failed_pending_choice_persistence_keeps_every_runtime_held_until_a_successful_retry(tmp_path, monkeypatch):
    (tmp_path / "runtime-choices.json").write_text("corrupt choices", encoding="utf-8")
    sessions = AppleRuntimeSessions(tmp_path, load_choices=False)
    sessions.resume("apple:wrapper-v2")

    def fail_save(*args, **kwargs):
        raise OSError("choice persistence refused")

    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", fail_save)
        with pytest.raises(OSError, match="choice persistence refused"):
            sessions.restore_choices()

    assert not sessions.choices_restored
    assert sessions.is_stopped("apple:wrapper-v2")
    assert sessions.is_stopped("apple:lite")

    sessions.restore_choices()
    assert sessions.choices_restored
    assert not sessions.is_stopped("apple:wrapper-v2")
    assert sessions.is_stopped("apple:lite")
    restored = AppleRuntimeSessions(tmp_path)
    assert not restored.is_stopped("apple:wrapper-v2")
    assert restored.is_stopped("apple:lite")


@pytest.mark.parametrize("change", ["account", "storefront", "credentials", "session", "endpoint", "artifact"])
def test_context_change_invalidates_prior_account_confirmation(tmp_path, change):
    profile = RuntimeProfile("apple:wrapper-v2", RuntimeKind.MANAGED, "wrapper-v2", "http://127.0.0.1:50100")
    account = AccountContext("", "us", "cookies-1")
    evidence = SessionEvidence(True, True, True, True, "", "us", "session-1")
    sessions = AppleRuntimeSessions(tmp_path)
    sessions.configure(profile)
    sessions.set_account(account)
    sessions.observe(profile.id, evidence)
    assert sessions.confirm_account(profile.id)
    if change == "account":
        sessions.set_account(replace(account, account_id="different-account"))
    elif change == "storefront":
        sessions.set_account(replace(account, storefront="gb"))
    elif change == "credentials":
        sessions.set_account(replace(account, credential_revision="cookies-2"))
    elif change == "session":
        sessions.observe(profile.id, replace(evidence, session_revision="session-2"))
    elif change == "endpoint":
        sessions.configure(replace(profile, endpoint="http://127.0.0.1:50101"))
    else:
        sessions.configure(replace(profile, artifact_digest="different-artifact"))
    assert sessions.readiness(profile.id) != "ready"


def test_confirmation_cannot_override_known_account_mismatch_or_unverified_artifact(tmp_path):
    sessions = AppleRuntimeSessions(tmp_path)
    profile = RuntimeProfile("apple:lite", RuntimeKind.USER_MANAGED, "lite")
    sessions.configure(profile)
    sessions.set_account(AccountContext("account-1", "us", "revision-1"))
    sessions.observe(profile.id, SessionEvidence(True, True, True, True, "account-2", "us", "session-1"))
    assert sessions.readiness(profile.id) == "account_mismatch"
    assert not sessions.confirm_account(profile.id)
    sessions.observe(profile.id, SessionEvidence(True, True, True, None, "account-1", "us", "session-1"))
    assert sessions.readiness(profile.id) == "unknown"
    assert not sessions.confirm_account(profile.id)


def test_user_managed_stop_disconnects_and_never_changes_external_service(tmp_path):
    calls = []
    sessions = AppleRuntimeSessions(tmp_path)
    profile = RuntimeProfile("apple:wrapper-v2", RuntimeKind.USER_MANAGED, "wrapper-v2", "http://127.0.0.1:50100")
    supervisor = SidecarSupervisor(runner=lambda *args, **kwargs: calls.append(args))
    supervisor.configure_runtime(profile, sessions)
    assert supervisor.stop(deliberate=True)
    assert sessions.is_stopped(profile.id)
    assert not supervisor.ensure_started(http_port=50100)
    assert calls == []


def test_deliberately_stopped_managed_runtime_never_starts_or_probes(tmp_path):
    calls = []
    sessions = AppleRuntimeSessions(tmp_path)
    profile = RuntimeProfile("apple:wrapper-v2", RuntimeKind.MANAGED, "wrapper-v2")
    sessions.configure(profile)
    sessions.stop(profile.id)
    supervisor = SidecarSupervisor(
        runner=lambda *args, **kwargs: calls.append(args), http_get=lambda *args, **kwargs: calls.append(args)
    )
    supervisor.configure_runtime(profile, sessions)
    assert not supervisor.ensure_started(http_port=50100)
    assert calls == []


def test_external_artifact_and_private_bindings_must_match_before_admission(tmp_path):
    profile = RuntimeProfile(
        "apple:wrapper-v2",
        RuntimeKind.USER_MANAGED,
        "wrapper-v2",
        "http://127.0.0.1:50100",
        "sha256:" + "a" * 64,
        container="my-wrapper",
    )
    sessions = AppleRuntimeSessions(tmp_path)
    calls = []

    def inspect(args, **kwargs):
        calls.append(args)
        observed = {
            "id": "c" * 64,
            "image": "sha256:" + "b" * 64,
            "started_at": "2026-10-12T00:00:00Z",
            "running": True,
            "ports": {
                "80/tcp": [{"HostIp": "127.0.0.1", "HostPort": "50100"}],
                "10020/tcp": [{"HostIp": "127.0.0.1", "HostPort": "10020"}],
            },
            "mounts": [],
        }
        return SimpleNamespace(returncode=0, stdout=json.dumps(observed))

    supervisor = SidecarSupervisor(runner=inspect)
    supervisor.configure_runtime(profile, sessions)
    assert supervisor.verify_identity(50100, 10020) is False
    assert all(command[1] == "inspect" and command[-1] == "my-wrapper" for command in calls)


def test_managed_stop_refuses_a_same_named_container_with_someone_elses_session_storage(tmp_path):
    import json

    from waves.providers.apple.runtime import AppleRuntimeManager

    commands = []

    def inspect(args, **kwargs):
        commands.append(args)
        if args[1] == "ps":
            return SimpleNamespace(returncode=0, stdout="waves-wrapper-v2 running")
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                [{"Source": "/external/session", "Destination": "/app/rootfs/data/data/com.apple.android.music/files"}]
            ),
        )

    sessions = AppleRuntimeSessions(tmp_path)
    supervisor = SidecarSupervisor(manager=AppleRuntimeManager(tmp_path), runner=inspect)
    supervisor.configure_runtime(RuntimeProfile("apple:wrapper-v2", RuntimeKind.MANAGED, "wrapper-v2"), sessions)
    assert not supervisor.stop(deliberate=True)
    assert sessions.is_stopped("apple:wrapper-v2")
    assert not any(command[1] in ("stop", "rm", "start", "run") for command in commands)
