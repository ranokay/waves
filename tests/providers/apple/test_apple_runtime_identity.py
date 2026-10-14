"""Admission requires one live container instance and a known matching image."""

import json
import subprocess
from dataclasses import replace
from types import SimpleNamespace

import pytest

from waves.providers.apple.runtime import WRAPPER_V2_IMAGE, WRAPPER_V2_IMAGE_DIGEST
from waves.providers.apple.runtime_sessions import AppleRuntimeSessions, RuntimeKind, RuntimeProfile
from waves.providers.apple.supervision import SidecarSupervisor

IMAGE_ID = "sha256:" + "a" * 64
OTHER_IMAGE_ID = "sha256:" + "b" * 64


def container_snapshot(tmp_path):
    return {
        "id": "c" * 64,
        "image": IMAGE_ID,
        "started_at": "2026-10-12T20:00:00Z",
        "running": True,
        "ports": {
            "80/tcp": [{"HostIp": "127.0.0.1", "HostPort": "50100"}],
            "10020/tcp": [{"HostIp": "127.0.0.1", "HostPort": "10020"}],
        },
        "mounts": [
            {
                "Source": str(tmp_path / "apple-runtime" / "wrapper-data"),
                "Destination": "/app/rootfs/data/data/com.apple.android.music/files",
            }
        ],
    }


class RuntimeRunner:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.commands = []
        self.local_image = IMAGE_ID
        self.list_result = SimpleNamespace(returncode=0, stdout="waves-wrapper-v2 running")
        self.on_inspect = lambda: None
        self.inspection_error = None

    def __call__(self, command, **kwargs):
        self.commands.append(command)
        if command[1] == "ps":
            if isinstance(self.list_result, Exception):
                raise self.list_result
            return self.list_result
        if command[1:3] == ["image", "inspect"]:
            return SimpleNamespace(returncode=0 if self.local_image else 1, stdout=self.local_image)
        if command[1] == "inspect":
            if self.inspection_error is not None:
                raise self.inspection_error
            self.on_inspect()
            value = self.snapshot["mounts"] if command[3] == "{{json .Mounts}}" else self.snapshot
            return SimpleNamespace(returncode=0, stdout=json.dumps(value))
        if command[1] == "stop":
            return SimpleNamespace(returncode=0, stdout="")
        raise AssertionError(f"Unexpected runtime operation: {command}")


def configured_supervisor(tmp_path, kind=RuntimeKind.MANAGED):
    sessions = AppleRuntimeSessions(tmp_path / "apple-runtime")
    profile = RuntimeProfile(
        "apple:wrapper-v2",
        kind,
        "wrapper-v2",
        "http://127.0.0.1:50100",
        IMAGE_ID,
        container="my-wrapper" if kind == RuntimeKind.USER_MANAGED else "",
    )
    manager = SimpleNamespace(
        app_dir=tmp_path,
        image_status=lambda: {
            "verified": True,
            "compatible": True,
            "image": WRAPPER_V2_IMAGE,
            "digest": WRAPPER_V2_IMAGE_DIGEST,
        },
    )
    run = RuntimeRunner(container_snapshot(tmp_path))
    supervisor = SidecarSupervisor(manager=manager, runner=run)
    supervisor.configure_runtime(profile, sessions)
    return supervisor, run, sessions, profile


@pytest.mark.parametrize("kind", [RuntimeKind.MANAGED, RuntimeKind.USER_MANAGED])
def test_live_matching_instance_is_verified_with_a_stable_revision(tmp_path, kind):
    supervisor, run, _, profile = configured_supervisor(tmp_path, kind)
    first = supervisor.observe_identity(50100, 10020)
    assert first.verified is True
    assert len(first.revision) == 64
    assert supervisor.observe_identity(50100, 10020) == first
    assert supervisor.verify_identity(50100, 10020) is True
    inspections = [command for command in run.commands if command[1] == "inspect"]
    assert len(inspections) == 3
    assert all(command[-1] == (profile.container or "waves-wrapper-v2") for command in inspections)


@pytest.mark.parametrize("kind", [RuntimeKind.MANAGED, RuntimeKind.USER_MANAGED])
@pytest.mark.parametrize("field,value", [("id", ""), ("image", ""), ("started_at", "")])
def test_missing_instance_identity_never_verifies(tmp_path, kind, field, value):
    supervisor, run, _, _ = configured_supervisor(tmp_path, kind)
    run.snapshot[field] = value
    identity = supervisor.observe_identity(50100, 10020)
    assert identity.verified is None
    assert identity.revision == ""


def test_unknown_approved_local_image_never_verifies_managed_instance(tmp_path):
    supervisor, run, _, _ = configured_supervisor(tmp_path)
    run.local_image = ""
    assert supervisor.observe_identity(50100, 10020).verified is None


@pytest.mark.parametrize("kind", [RuntimeKind.MANAGED, RuntimeKind.USER_MANAGED])
def test_known_image_mismatch_is_rejected(tmp_path, kind):
    supervisor, run, _, _ = configured_supervisor(tmp_path, kind)
    previous = supervisor.observe_identity(50100, 10020)
    run.snapshot["image"] = OTHER_IMAGE_ID
    observed = supervisor.observe_identity(50100, 10020)
    assert observed.verified is False
    assert observed.revision != previous.revision


@pytest.mark.parametrize("error", [OSError("runtime unavailable"), subprocess.TimeoutExpired("inspect", 15)])
def test_failed_or_timed_out_instance_inspection_stays_unknown(tmp_path, error):
    supervisor, run, _, _ = configured_supervisor(tmp_path)
    run.inspection_error = error
    observed = supervisor.observe_identity(50100, 10020)
    assert observed.verified is None
    assert observed.revision == ""


@pytest.mark.parametrize("kind", [RuntimeKind.MANAGED, RuntimeKind.USER_MANAGED])
@pytest.mark.parametrize("change", ["stopped", "unpublished", "wildcard", "missing_decrypt", "extra_port"])
def test_stopped_or_unconfined_live_transport_is_rejected(tmp_path, kind, change):
    supervisor, run, _, _ = configured_supervisor(tmp_path, kind)
    if change == "stopped":
        run.snapshot["running"] = False
    elif change == "unpublished":
        run.snapshot["ports"] = {}
    elif change == "wildcard":
        run.snapshot["ports"]["80/tcp"][0]["HostIp"] = "0.0.0.0"  # noqa: S104 - rejected synthetic mapping, never bound
    elif change == "missing_decrypt":
        del run.snapshot["ports"]["10020/tcp"]
    else:
        run.snapshot["ports"]["9000/tcp"] = [{"HostIp": "127.0.0.1", "HostPort": "9000"}]
    assert supervisor.observe_identity(50100, 10020).verified is False


def test_managed_instance_requires_owned_session_mount(tmp_path):
    supervisor, run, _, _ = configured_supervisor(tmp_path)
    run.snapshot["mounts"][0]["Source"] = str(tmp_path / "someone-else")
    assert supervisor.observe_identity(50100, 10020).verified is False


@pytest.mark.parametrize("field,value", [("id", "d" * 64), ("started_at", "2026-10-12T21:00:00Z")])
def test_replacement_or_restart_changes_instance_revision(tmp_path, field, value):
    supervisor, run, _, _ = configured_supervisor(tmp_path)
    first = supervisor.observe_identity(50100, 10020)
    run.snapshot[field] = value
    second = supervisor.observe_identity(50100, 10020)
    assert second.verified is True
    assert second.revision != first.revision


@pytest.mark.parametrize("change", ["profile", "binary"])
def test_configuration_change_during_inspection_discards_identity(tmp_path, change):
    supervisor, run, sessions, profile = configured_supervisor(tmp_path)

    def reconfigure():
        run.on_inspect = lambda: None
        replacement = replace(profile, endpoint="http://127.0.0.1:50101") if change == "profile" else profile
        supervisor.configure_runtime(replacement, sessions, binary="podman" if change == "binary" else None)

    run.on_inspect = reconfigure
    observed = supervisor.observe_identity(50100, 10020)
    assert observed.verified is None
    assert observed.revision == ""


def test_configured_container_binary_drives_all_identity_reads(tmp_path):
    supervisor, run, sessions, profile = configured_supervisor(tmp_path)
    supervisor.configure_runtime(profile, sessions, binary="podman")
    assert supervisor.observe_identity(50100, 10020).verified is True
    assert all(command[0] == "podman" for command in run.commands)


@pytest.mark.parametrize(
    "listing",
    [
        SimpleNamespace(returncode=1, stdout=""),
        SimpleNamespace(returncode=0, stdout=None),
        SimpleNamespace(returncode=0, stdout="waves-wrapper-v2"),
        OSError("daemon unavailable"),
    ],
)
def test_failed_container_observation_never_reports_a_successful_stop(tmp_path, listing):
    supervisor, run, sessions, profile = configured_supervisor(tmp_path)
    run.list_result = listing
    assert supervisor.stop(deliberate=True) is False
    assert sessions.is_stopped(profile.id)
    assert not any(command[1] == "stop" for command in run.commands)


@pytest.mark.parametrize("listing", ["", "waves-wrapper-v2 exited"])
def test_confirmed_absent_or_exited_container_is_already_stopped(tmp_path, listing):
    supervisor, run, sessions, profile = configured_supervisor(tmp_path)
    run.list_result = SimpleNamespace(returncode=0, stdout=listing)
    assert supervisor.stop(deliberate=True) is True
    assert sessions.is_stopped(profile.id)
    assert not any(command[1] == "stop" for command in run.commands)


def test_running_owned_container_stops_through_selected_runtime(tmp_path):
    supervisor, run, sessions, profile = configured_supervisor(tmp_path)
    supervisor.configure_runtime(profile, sessions, binary="podman")
    assert supervisor.stop(deliberate=True) is True
    assert sessions.is_stopped(profile.id)
    assert all(command[0] == "podman" for command in run.commands)
    assert any(command[1] == "stop" for command in run.commands)
