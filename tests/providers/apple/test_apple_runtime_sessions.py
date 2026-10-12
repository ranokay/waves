"""Apple runtime admission keeps account evidence separate from reachability."""

from dataclasses import replace
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
        outputs = {
            "{{.Image}}": "sha256:" + "b" * 64,
            "{{.State.Running}}": "true",
            "{{json .HostConfig.PortBindings}}": '{"80/tcp":[{"HostIp":"127.0.0.1","HostPort":"50100"}],"10020/tcp":[{"HostIp":"127.0.0.1","HostPort":"10020"}]}',
        }
        return SimpleNamespace(returncode=0, stdout=outputs.get(args[3], ""))

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
