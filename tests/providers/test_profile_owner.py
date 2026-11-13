"""Profile ownership uses an OS lock and refuses unsafe control paths."""

import os
import subprocess
import sys

import pytest

from waves.desktop.providers.profile_owner import OwnerBusy, OwnerUnavailable, ProfileOwner

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX profile ownership")


@pytest.fixture
def owner_process(tmp_path):
    processes = []

    def start():
        code = (
            "import sys\n"
            "from pathlib import Path\n"
            "from waves.desktop.providers.profile_owner import ProfileOwner\n"
            "with ProfileOwner.acquire(Path(sys.argv[1])):\n"
            " print('ready', flush=True)\n"
            " sys.stdin.read()\n"
        )
        proc = subprocess.Popen(  # noqa: S603 - fixed interpreter and fixture script
            [sys.executable, "-c", code, str(tmp_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        processes.append(proc)
        assert proc.stdout.readline().strip() == "ready"
        return proc

    yield start
    for proc in processes:
        if proc.poll() is None:
            proc.kill()
        proc.communicate(timeout=5)


def test_owner_excludes_another_process_and_release_allows_next(tmp_path, owner_process):
    proc = owner_process()
    with pytest.raises(OwnerBusy):
        ProfileOwner.acquire(tmp_path)
    proc.stdin.close()
    proc.stdin = None
    assert proc.wait(timeout=5) == 0
    with ProfileOwner.acquire(tmp_path) as owner:
        assert owner.control_dir.stat().st_mode & 0o777 == 0o700
        assert (owner.control_dir / "owner.lock").stat().st_mode & 0o777 == 0o600
        assert len(owner.endpoint_id) == 64
    with ProfileOwner.acquire(tmp_path) as next_owner:
        assert next_owner.endpoint_id == owner.endpoint_id


def test_abrupt_exit_releases_lock_without_unlinking(tmp_path, owner_process):
    proc = owner_process()
    lock = tmp_path / "provider-control" / "owner.lock"
    inode = lock.stat().st_ino
    proc.kill()
    proc.wait(timeout=5)
    with ProfileOwner.acquire(tmp_path):
        assert lock.stat().st_ino == inode


@pytest.mark.parametrize("unsafe", ["control_symlink", "control_mode", "lock_symlink", "lock_mode", "lock_hardlink"])
def test_unsafe_existing_paths_fail_closed(tmp_path, unsafe):
    control = tmp_path / "provider-control"
    if unsafe == "control_symlink":
        target = tmp_path / "target"
        target.mkdir(mode=0o700)
        control.symlink_to(target, target_is_directory=True)
    else:
        control.mkdir(mode=0o700)
        if unsafe == "control_mode":
            control.chmod(0o755)
        elif unsafe == "lock_symlink":
            target = tmp_path / "target"
            target.touch(mode=0o600)
            (control / "owner.lock").symlink_to(target)
        elif unsafe == "lock_mode":
            lock = control / "owner.lock"
            lock.touch(mode=0o600)
            lock.chmod(0o644)
        else:
            target = tmp_path / "target"
            target.touch(mode=0o600)
            os.link(target, control / "owner.lock")
    with pytest.raises(OwnerUnavailable):
        ProfileOwner.acquire(tmp_path)


def test_distinct_resolved_profiles_have_distinct_endpoint_ids(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    with ProfileOwner.acquire(first) as a, ProfileOwner.acquire(second) as b:
        assert a.endpoint_id != b.endpoint_id


def test_wrong_control_owner_is_rejected(tmp_path, monkeypatch):
    control = tmp_path / "provider-control"
    control.mkdir(mode=0o700)
    monkeypatch.setattr(os, "getuid", lambda: control.stat().st_uid + 1)
    with pytest.raises(OwnerUnavailable):
        ProfileOwner.acquire(tmp_path)


def test_missing_profile_is_unavailable(tmp_path):
    with pytest.raises(OwnerUnavailable):
        ProfileOwner.acquire(tmp_path / "missing")


def test_lock_failure_without_owner_is_unavailable(tmp_path, monkeypatch):
    from waves.desktop.providers import profile_owner

    monkeypatch.setattr(profile_owner, "try_lock", lambda *_args, **_kwargs: None)
    with pytest.raises(OwnerUnavailable):
        ProfileOwner.acquire(tmp_path)
