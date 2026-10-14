"""Managed Apple tool activation and recovery through the runtime manager."""

from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import subprocess
import tarfile
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from waves.providers.apple import runtime
from waves.providers.apple.runtime import (
    WRAPPER_V2_IMAGE,
    WRAPPER_V2_IMAGE_DIGEST,
    AppleRuntimeCancelled,
    AppleRuntimeManager,
    Nm3u8dlreRelease,
    wrapper_auth_state,
)


@pytest.fixture(autouse=True)
def native_tool_version(monkeypatch):
    def run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout=Path(command[0]).read_text(), stderr="")

    monkeypatch.setattr(subprocess, "run", run)


class DownloadResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.headers = {"Content-Length": str(len(payload))}

    def raise_for_status(self) -> None:
        pass

    def iter_content(self, chunk_size: int):
        yield self.payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class DownloadSession:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def get(self, url: str, **kwargs):
        return DownloadResponse(self.payload)


def tool_release(manager: AppleRuntimeManager, version: str):
    binary = version.encode()
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w:gz") as output:
        member = tarfile.TarInfo(manager.binary_path.name)
        member.size = len(binary)
        output.addfile(member, io.BytesIO(binary))
    payload = archive.getvalue()
    return (
        Nm3u8dlreRelease(
            version, f"https://example.invalid/{version}.tar.gz", sha256=hashlib.sha256(payload).hexdigest()
        ),
        DownloadSession(payload),
    )


def install_tool(manager: AppleRuntimeManager, version: str, **kwargs):
    release, session = tool_release(manager, version)
    return manager.install(release=release, session=session, **kwargs)


def test_updated_tool_can_restore_the_previous_binary_and_provenance(tmp_path):
    manager = AppleRuntimeManager(tmp_path)
    first = install_tool(manager, "1.0")
    previous_bytes = manager.binary_path.read_bytes()

    updated = install_tool(manager, "2.0")
    assert updated["version"] == "2.0"
    assert updated["rollback_available"] is True

    restored = AppleRuntimeManager(tmp_path).rollback()
    assert restored["version"] == "1.0"
    assert restored["source_url"] == first["source_url"]
    assert restored["sha256"] == first["sha256"]
    assert restored["verified"] is True
    assert manager.binary_path.read_bytes() == previous_bytes


def test_failed_receipt_activation_restores_the_working_tool_and_receipt(tmp_path, monkeypatch):
    manager = AppleRuntimeManager(tmp_path)
    before = install_tool(manager, "1.0")
    original_bytes = manager.binary_path.read_bytes()
    replace = os.replace
    failed = False

    def fail_receipt_once(source, destination):
        nonlocal failed
        if Path(destination) == manager.manifest_path and not failed:
            failed = True
            raise OSError("receipt activation refused")
        return replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_receipt_once)
    with pytest.raises(OSError, match="receipt activation refused"):
        install_tool(manager, "2.0")

    restored = AppleRuntimeManager(tmp_path).verify()
    assert restored["version"] == before["version"]
    assert restored["source_url"] == before["source_url"]
    assert restored["verified"] is True
    assert restored["available"] is True
    assert manager.binary_path.read_bytes() == original_bytes


def test_failed_rollback_receipt_activation_keeps_the_current_working_generation(tmp_path, monkeypatch):
    manager = AppleRuntimeManager(tmp_path)
    install_tool(manager, "1.0")
    install_tool(manager, "2.0")
    current_bytes = manager.binary_path.read_bytes()
    replace = os.replace
    failed = False

    def fail_receipt_once(source, destination):
        nonlocal failed
        if Path(destination) == manager.manifest_path and not failed:
            failed = True
            raise OSError("rollback receipt activation refused")
        return replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_receipt_once)
    with pytest.raises(OSError, match="rollback receipt activation refused"):
        manager.rollback()

    current = manager.verify()
    assert current["version"] == "2.0"
    assert current["verified"] is True
    assert current["available"] is True
    assert manager.binary_path.read_bytes() == current_bytes


def test_cancel_after_native_tool_validation_keeps_the_working_version(tmp_path, monkeypatch):
    manager = AppleRuntimeManager(tmp_path)
    install_tool(manager, "1.0")
    abort = Event()

    def validate_and_cancel(command, **kwargs):
        abort.set()
        return subprocess.CompletedProcess(command, 0, stdout="2.0", stderr="")

    monkeypatch.setattr(subprocess, "run", validate_and_cancel)
    with pytest.raises(AppleRuntimeCancelled):
        install_tool(manager, "2.0", abort=abort)

    current = manager.status()
    assert current["version"] == "1.0"
    assert current["verified"] is True
    assert current["rollback_available"] is False


def test_an_interrupted_activation_can_restore_the_last_working_version(tmp_path, monkeypatch):
    manager = AppleRuntimeManager(tmp_path)
    install_tool(manager, "1.0")
    replace = os.replace

    def interrupt_receipt(source, destination):
        if Path(destination) == manager.manifest_path:
            raise SystemExit("process stopped during activation")
        return replace(source, destination)

    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", interrupt_receipt)
        with pytest.raises(SystemExit, match="process stopped during activation"):
            install_tool(manager, "2.0")

    recovered = AppleRuntimeManager(tmp_path)
    interrupted = recovered.status()
    assert interrupted["available"] is False
    assert interrupted["verified"] is False
    assert interrupted["rollback_available"] is True

    restored = recovered.rollback()
    assert restored["version"] == "1.0"
    assert restored["available"] is True
    assert restored["verified"] is True


def test_modified_managed_bytes_are_unavailable_under_the_old_receipt(tmp_path):
    manager = AppleRuntimeManager(tmp_path)
    install_tool(manager, "1.0")
    manager.binary_path.write_bytes(b"different tool")

    status = AppleRuntimeManager(tmp_path).verify()
    assert status["binary_integrity"] == "mismatch"
    assert status["available"] is False
    assert status["verified"] is False


def test_active_tool_use_prevents_install_remove_and_rollback(tmp_path):
    from waves.providers.apple.runtime import AppleRuntimeBusy

    manager = AppleRuntimeManager(tmp_path)
    install_tool(manager, "1.0")
    install_tool(manager, "2.0")

    with manager.usage():
        with pytest.raises(AppleRuntimeBusy):
            install_tool(manager, "3.0")
        with pytest.raises(AppleRuntimeBusy):
            manager.remove()
        with pytest.raises(AppleRuntimeBusy):
            manager.rollback()

    assert manager.status()["version"] == "2.0"
    assert manager.rollback()["version"] == "1.0"


def test_custom_tool_usage_does_not_validate_an_unused_managed_binary(tmp_path):
    from waves.providers.apple.runtime import AppleRuntimeBusy

    manager = AppleRuntimeManager(tmp_path)
    install_tool(manager, "1.0")
    manager.binary_path.write_bytes(b"unused modified managed tool")

    with manager.usage(verify_binary=False), pytest.raises(AppleRuntimeBusy):
        manager.remove()

    with pytest.raises(RuntimeError, match="cannot be verified"), manager.usage():
        pass


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits do not describe Windows ACLs")
def test_runtime_private_directories_repair_inherited_permissions(tmp_path):
    manager = AppleRuntimeManager(tmp_path)
    manager.runtime_dir.mkdir(mode=0o755)
    engine_config = manager.engine_config_dir()

    assert stat.S_IMODE(manager.runtime_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(engine_config.stat().st_mode) == 0o700
    assert stat.S_IMODE(manager.session_data_dir().stat().st_mode) == 0o700


@pytest.mark.parametrize(
    ("receipt", "provenance", "verified"),
    [
        ({}, "unknown", False),
        ({"digest": "", "digest_ok": None}, "unknown", False),
        ({"digest": WRAPPER_V2_IMAGE_DIGEST, "digest_ok": True}, "verified", True),
        ({"digest": "sha256:" + "0" * 64, "digest_ok": False}, "mismatch", False),
    ],
)
def test_image_provenance_keeps_legacy_unknown_and_verified_receipts_distinct(tmp_path, receipt, provenance, verified):
    manager = AppleRuntimeManager(tmp_path)
    manager.runtime_dir.mkdir()
    manager.image_manifest_path.write_text(json.dumps({"image": WRAPPER_V2_IMAGE, "pulled_at": 1, **receipt}))

    state = manager.image_status()
    assert state["provenance"] == provenance
    assert state["verified"] is verified


def image_runner(digest: str = "", cancel: Event | None = None):
    def run(command, **kwargs):
        if "pull" in command:
            if cancel is not None:
                cancel.set()
            return SimpleNamespace(returncode=0, stdout="Pulled", stderr="")
        repo = WRAPPER_V2_IMAGE.rsplit(":", 1)[0]
        return SimpleNamespace(returncode=0, stdout=json.dumps([f"{repo}@{digest}"] if digest else []), stderr="")

    return run


def test_verified_image_admission_refuses_unknown_digest_and_preserves_the_verified_receipt(tmp_path):
    manager = AppleRuntimeManager(tmp_path)
    manager.ensure_image(runner=image_runner(WRAPPER_V2_IMAGE_DIGEST))

    with pytest.raises(RuntimeError, match="verify"):
        manager.ensure_image(runner=image_runner(), require_verified=True)

    assert manager.image_status()["verified"] is True


def test_status_reads_cached_integrity_without_streaming_executables(tmp_path, monkeypatch):
    manager = AppleRuntimeManager(tmp_path)
    install_tool(manager, "1.0")
    install_tool(manager, "2.0")
    open_file = Path.open

    def reject_binary_read(path, *args, **kwargs):
        if path.name == manager.binary_path.name:
            raise AssertionError("GUI status must not stream current or previous tool bytes")
        return open_file(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", reject_binary_read)
    state = manager.status()
    assert state["verified"] is True
    assert state["rollback_available"] is True


def test_restored_manager_keeps_integrity_unknown_until_worker_verification(tmp_path):
    manager = AppleRuntimeManager(tmp_path)
    install_tool(manager, "1.0")

    restored = AppleRuntimeManager(tmp_path)
    assert restored.status()["verified"] is False
    assert restored.verify()["verified"] is True


def test_cancelled_injected_image_pull_never_replaces_the_verified_receipt(tmp_path):
    manager = AppleRuntimeManager(tmp_path)
    manager.ensure_image(runner=image_runner(WRAPPER_V2_IMAGE_DIGEST))
    abort = Event()

    with pytest.raises(AppleRuntimeCancelled):
        manager.ensure_image(runner=image_runner(cancel=abort), abort=abort)

    assert manager.image_status()["verified"] is True


def test_cancelled_native_image_pull_terminates_its_process_without_activating_a_receipt(tmp_path, monkeypatch):
    manager = AppleRuntimeManager(tmp_path)
    abort = Event()

    class PullProcess:
        returncode = None
        terminated = False

        def communicate(self, timeout):
            if not self.terminated:
                abort.set()
                raise subprocess.TimeoutExpired("docker pull", timeout)
            return "", ""

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = -15

        def kill(self):
            raise AssertionError("the cooperative pull already stopped")

    process = PullProcess()
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)

    with pytest.raises(AppleRuntimeCancelled):
        manager.ensure_image(abort=abort)

    assert process.terminated is True
    assert manager.image_pulled() is False


def test_update_status_offers_shipped_pins_without_provisioning_unused_assets(tmp_path):
    manager = AppleRuntimeManager(tmp_path)
    fresh = manager.update_status()
    assert fresh["available"] is False
    assert fresh["binary"]["available"] is False
    assert fresh["image"]["available"] is False

    install_tool(manager, "old-working-version")
    offered = manager.update_status()
    assert offered["available"] is True
    assert offered["binary"]["version"] == "v0.6.0-beta"
    assert offered["binary"]["installed_version"] == "old-working-version"
    assert offered["image"]["available"] is False
    assert offered["manual_install_default"] is True
    assert offered["client_updates"] == "waves"

    with manager.usage():
        assert manager.update_status()["busy"] is True


def test_approved_image_update_can_restore_a_compatible_verified_immutable_image(tmp_path, monkeypatch):
    manager = AppleRuntimeManager(tmp_path)
    manager.ensure_image(runner=image_runner(WRAPPER_V2_IMAGE_DIGEST), require_verified=True)
    session_file = manager.session_data_dir() / "synthetic-session"
    session_file.write_text("test session remains isolated")
    repo = WRAPPER_V2_IMAGE.rsplit(":", 1)[0]
    newer_digest = "sha256:" + "1" * 64
    monkeypatch.setattr(runtime, "WRAPPER_V2_IMAGE", repo + ":0.2.5")
    monkeypatch.setattr(runtime, "WRAPPER_V2_IMAGE_DIGEST", newer_digest)
    manager.ensure_image(runner=image_runner(newer_digest), require_verified=True)

    assert manager.active_image() == repo + "@" + newer_digest

    seen = []

    def installed_image(command, **kwargs):
        seen.append(command)
        return SimpleNamespace(returncode=0, stdout="sha256:local-image-id", stderr="")

    restored = manager.rollback_image(runner=installed_image)
    assert restored["verified"] is True
    assert restored["current"] is False
    assert manager.active_image() == repo + "@" + WRAPPER_V2_IMAGE_DIGEST
    assert seen == [["docker", "image", "inspect", "--format", "{{.Id}}", repo + "@" + WRAPPER_V2_IMAGE_DIGEST]]
    assert session_file.read_text() == "test session remains isolated"


@pytest.mark.parametrize("failure", ["missing_local", "incompatible_protocol", "unknown_provenance"])
def test_image_rollback_refuses_unusable_previous_artifacts_without_changing_the_active_image(
    tmp_path, monkeypatch, failure
):
    manager = AppleRuntimeManager(tmp_path)
    manager.ensure_image(runner=image_runner(WRAPPER_V2_IMAGE_DIGEST), require_verified=True)
    repo = WRAPPER_V2_IMAGE.rsplit(":", 1)[0]
    newer_digest = "sha256:" + "1" * 64
    monkeypatch.setattr(runtime, "WRAPPER_V2_IMAGE", repo + ":0.2.5")
    monkeypatch.setattr(runtime, "WRAPPER_V2_IMAGE_DIGEST", newer_digest)
    manager.ensure_image(runner=image_runner(newer_digest), require_verified=True)

    if failure != "missing_local":
        receipt = json.loads(manager.image_previous_path.read_text())
        if failure == "incompatible_protocol":
            receipt["protocol"] = "different-protocol"
        else:
            receipt["digest"] = ""
            receipt["digest_ok"] = None
        manager.image_previous_path.write_text(json.dumps(receipt))

    def inspect(command, **kwargs):
        return SimpleNamespace(returncode=1 if failure == "missing_local" else 0, stdout="", stderr="missing")

    with pytest.raises(RuntimeError, match="no image was changed"):
        manager.rollback_image(runner=inspect)

    assert manager.active_image() == repo + "@" + newer_digest


@pytest.mark.parametrize(
    ("payload", "expected_id", "expected_storefront"),
    [
        (
            {"auth": {"state": "authenticated", "account_id": "synthetic-account-27", "storefront": "gb"}},
            "synthetic-account-27",
            "gb",
        ),
        ({"auth": {"state": "authenticated"}, "account": {"id": 27, "storefront": "us"}}, "27", "us"),
        (
            {
                "auth": {
                    "state": "authenticated",
                    "apple_id": "test@example.invalid",
                    "username": "test@example.invalid",
                }
            },
            None,
            None,
        ),
        ({"auth": {"state": "authenticated", "account_id": "first"}, "account": {"id": "second"}}, None, None),
    ],
)
def test_wrapper_context_reads_only_present_machine_identifiers_and_storefronts(
    payload, expected_id, expected_storefront
):
    response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload)
    session = SimpleNamespace(get=lambda *args, **kwargs: response)

    state = wrapper_auth_state("http://127.0.0.1:51234", session=session)
    assert state.get("account_id") == expected_id
    assert state.get("storefront") == expected_storefront
    if expected_id is None:
        assert "account_id" not in state
    if expected_storefront is None:
        assert "storefront" not in state
