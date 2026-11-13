"""The real source entrypoint shares one isolated GUI owner with CLI clients."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import pytest
from support.paths import REPO_ROOT

pytestmark = [
    pytest.mark.qml,
    pytest.mark.integration,
    pytest.mark.skipif(sys.platform != "darwin", reason="macOS local session control"),
]


def _env(tmp_path):
    env = os.environ.copy()
    env.update(
        XDG_CONFIG_HOME=str(tmp_path / "config"),
        XDG_DATA_HOME=str(tmp_path / "data"),
        XDG_CACHE_HOME=str(tmp_path / "cache"),
        QT_QPA_PLATFORM="offscreen",
        WAVES_TEST_SEAM="1",
        WAVES_QUIT_AFTER_BOOT_MS="15000",
    )
    env.pop("WAVES_ACCOUNT_TESTS", None)
    return env


def _command(env, *args):
    return subprocess.run(  # noqa: S603 - fixed source entrypoint and test arguments
        [sys.executable, str(REPO_ROOT / "waves.py"), *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=35,
        check=False,
    )


def test_no_app_status_and_invalid_command_are_json_only(tmp_path):
    env = _env(tmp_path)
    result = _command(env, "session", "status", "tidal")
    assert result.returncode == 3
    assert json.loads(result.stdout) == {"version": 1, "error": "unavailable"}
    assert not (tmp_path / "config" / "Waves").exists()
    invalid = _command(env, "session", "ensure", "not-a-provider")
    assert invalid.returncode == 2
    assert json.loads(invalid.stdout) == {"version": 1, "error": "invalid_request"}


def test_cli_to_real_gui_and_duplicate_launch(tmp_path):
    env = _env(tmp_path)
    proc = subprocess.Popen(  # noqa: S603 - fixed source entrypoint
        [sys.executable, str(REPO_ROOT / "waves.py")],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            assert proc.poll() is None
            status = _command(env, "session", "status", "apple")
            payload = json.loads(status.stdout)
            if payload.get("error") != "unavailable":
                break
        else:
            pytest.fail("GUI did not publish a session endpoint")
        assert status.returncode == 4
        assert payload["action"] == "enable_provider"
        assert payload["facts"]["catalog"] == "not_ready"
        lock = tmp_path / "config" / "Waves" / "provider-control" / "owner.lock"
        original_inode = lock.stat().st_ino
        duplicate = _command(env)
        assert duplicate.returncode == 0
        assert proc.poll() is None and lock.stat().st_ino == original_inode
        ensure = _command(env, "session", "ensure", "apple")
        assert ensure.returncode == 4
        assert json.loads(ensure.stdout)["action"] == "enable_provider"
    finally:
        if proc.poll() is None:
            proc.terminate()
        proc.wait(timeout=15)


def test_ensure_without_owner_launches_a_gui(tmp_path):
    env = _env(tmp_path)
    env["WAVES_QUIT_AFTER_BOOT_MS"] = "5000"
    result = _command(env, "session", "ensure", "apple")
    assert result.returncode == 4
    assert json.loads(result.stdout)["action"] == "enable_provider"
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if _command(env, "session", "status", "apple").returncode == 3:
            break
    else:
        pytest.fail("task-owned GUI did not shut down")
