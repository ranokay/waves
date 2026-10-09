"""Verify checks and actual Git hooks without risking the developer's checkout."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from support.paths import REPO_ROOT

pytestmark = pytest.mark.integration


def run(repo: Path, *args: str, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "UV_PROJECT_ENVIRONMENT": str(repo / ".venv"),
        "UV_NO_SYNC": "1",
        "UV_OFFLINE": "1",
        "RUFF_CACHE_DIR": str(repo / ".git" / "ruff-cache"),
        "GIT_CONFIG_GLOBAL": str(repo.parent / (repo.name + ".global.gitconfig")),
        "GIT_CONFIG_NOSYSTEM": "1",
        "MISE_TRUSTED_CONFIG_PATHS": str(repo),
        **(extra_env or {}),
    }
    return subprocess.run(args, cwd=repo, env=env, capture_output=True, timeout=120)


def succeeds(repo: Path, *args: str) -> subprocess.CompletedProcess:
    result = run(repo, *args)
    assert result.returncode == 0, result.stdout + result.stderr
    return result


@pytest.fixture
def checkout(tmp_path):
    # Copy tracked inputs from the working tree so this also tests an uncommitted change.
    paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=REPO_ROOT).decode().split("\0")
    paths += ["hk.pkl", *[str(p.relative_to(REPO_ROOT)) for p in (REPO_ROOT / "tools").glob("*.py")]]
    for name in paths:
        source = REPO_ROOT / name
        if name and source.is_file():
            target = tmp_path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    succeeds(tmp_path, "git", "init", "-q", "-b", "fixture")
    succeeds(tmp_path, "git", "config", "user.name", "Hook fixture")
    succeeds(tmp_path, "git", "config", "user.email", "fixture@example.invalid")
    succeeds(tmp_path, "git", "config", "commit.gpgsign", "false")
    succeeds(tmp_path, "git", "add", ".")
    succeeds(tmp_path, "git", "commit", "-qm", "Fixture")
    succeeds(tmp_path, "uv", "sync", "--locked", "--all-extras")
    return tmp_path


def snapshot(repo: Path) -> tuple[dict[str, str], bytes]:
    paths = succeeds(repo, "git", "ls-files", "--cached", "--others", "--exclude-standard", "-z").stdout
    files = {
        name.decode(): hashlib.sha256((repo / os.fsdecode(name)).read_bytes()).hexdigest()
        for name in paths.split(b"\0")
        if name and (repo / os.fsdecode(name)).is_file()
    }
    return files, succeeds(repo, "git", "write-tree").stdout


def test_dirty_check_fails_without_changing_files_or_index(checkout):
    (checkout / "sample.py").write_text("value=1  \n")
    succeeds(checkout, "git", "add", "sample.py")
    before = snapshot(checkout)
    result = run(checkout, "mise", "run", "check")
    assert result.returncode != 0, result.stdout + result.stderr
    assert b"sample.py" in result.stdout + result.stderr
    assert snapshot(checkout) == before


@pytest.mark.parametrize("name", ["sample.py", "-sample.py", "odd ' $() `x` ; ü.py", "line\nbreak.py"])
@pytest.mark.parametrize("staged_good", [True, False])
def test_commit_checks_staged_content_and_preserves_unstaged_work(checkout, name, staged_good):
    succeeds(checkout, "mise", "run", "install")
    sample = checkout / name
    good, bad = "value = 1\n", "value=2  \n"
    sample.write_text(good if staged_good else bad)
    succeeds(checkout, "git", "add", "--", name)
    sample.write_text(bad if staged_good else good)
    unrelated = checkout / "unrelated untracked.txt"
    unrelated.write_bytes(b"keep this untracked work exactly  ")
    before = snapshot(checkout)
    head = succeeds(checkout, "git", "rev-parse", "HEAD").stdout
    result = run(checkout, "git", "commit", "-qm", "Staged sample")
    assert (result.returncode == 0) == staged_good, result.stdout + result.stderr
    assert snapshot(checkout) == before
    if staged_good:
        assert succeeds(checkout, "git", "show", f"HEAD:{name}").stdout == good.encode()
    else:
        assert succeeds(checkout, "git", "rev-parse", "HEAD").stdout == head
    assert succeeds(checkout, "git", "stash", "list").stdout == b""


@pytest.mark.parametrize("branch", ["main", "develop"])
def test_protected_branch_guard_runs_only_for_commits(checkout, branch):
    succeeds(checkout, "mise", "run", "install")
    succeeds(checkout, "git", "switch", "-c", branch)
    # Whole-tree validation is allowed on the integration and mirror branches.
    succeeds(checkout, "mise", "run", "check")
    (checkout / "sample.md").write_text("# Sample\n")
    succeeds(checkout, "git", "add", "sample.md")
    before = snapshot(checkout)
    result = run(checkout, "git", "commit", "-qm", "Blocked")
    assert result.returncode != 0
    assert b"no-commit-to-branch" in result.stdout + result.stderr
    assert snapshot(checkout) == before


def test_install_and_doctor_recognise_missing_and_installed_hooks(checkout):
    assert run(checkout, "mise", "run", "doctor").returncode != 0
    succeeds(checkout, "mise", "run", "install")
    succeeds(checkout, "mise", "run", "doctor")
    succeeds(checkout, "mise", "run", "install")
    succeeds(checkout, "mise", "run", "doctor")
    assert not (checkout.parent / (checkout.name + ".global.gitconfig")).exists()


@pytest.mark.parametrize("kind", ["foreign", "symlink", "shared-path"])
def test_install_refuses_to_change_foreign_or_shared_hooks(checkout, kind):
    hook = checkout / ".git" / "hooks" / "pre-commit"
    owner = checkout / "owner-hook"
    owner.write_text("#!/bin/sh\nexit 0\n")
    owner.chmod(0o755)
    if kind == "foreign":
        shutil.copy2(owner, hook)
    elif kind == "symlink":
        hook.symlink_to(owner)
    else:
        succeeds(checkout, "git", "config", "--global", "core.hooksPath", str(owner.parent))
    original = owner.read_bytes()
    config = (checkout / ".git" / "config").read_bytes()
    result = run(checkout, "mise", "run", "install")
    assert result.returncode != 0
    assert b"Refusing" in result.stdout + result.stderr
    assert owner.read_bytes() == original
    assert (checkout / ".git" / "config").read_bytes() == config
    if kind == "symlink":
        assert hook.is_symlink()


def test_install_saves_generated_hooks_and_doctor_rejects_stale_hooks(checkout):
    hook = checkout / ".git" / "hooks" / "pre-commit"
    generated = b"#!/bin/sh\n# File generated by pre-commit: https://pre-commit.com\nexit 0\n"
    hook.write_bytes(generated)
    hook.chmod(0o755)
    succeeds(checkout, "mise", "run", "install")
    assert hook.with_name("pre-commit.before-hk").read_bytes() == generated
    succeeds(checkout, "mise", "run", "doctor")
    # Removing the installed push hook must fail doctor, even if commit is present.
    succeeds(checkout, "hk", "uninstall")
    assert run(checkout, "mise", "run", "doctor").returncode != 0


@pytest.mark.parametrize(
    ("step", "name", "source"),
    [
        ("ruff", "invalid.py", "print(undefined_name)\n"),
        ("ruff-format", "invalid.py", "value=1\n"),
        ("pyupgrade", "invalid.py", 'value = "{x}".format(**locals())\n'),
        ("prettier", "invalid.json", '{"a":1}\n'),
        ("check-yaml", "invalid.yaml", "x: [\n"),
        ("check-toml", "invalid.toml", "x = [\n"),
        ("end-of-file-fixer", "invalid.txt", "missing newline"),
        ("trailing-whitespace", "invalid.txt", "trailing  \n"),
        ("qmlformat", "waves/desktop/qml/Invalid.qml", "import QtQuick\nItem { property int value: 1 }\n"),
        ("qmllint", "waves/desktop/qml/Invalid.qml", "import QtQuick\nItem {\n"),
    ],
)
def test_known_static_failure_is_read_only(checkout, step, name, source):
    (checkout / name).write_text(source)
    before = snapshot(checkout)
    result = run(checkout, "hk", "check", "--step", step, "--", name)
    assert result.returncode != 0, result.stdout + result.stderr
    assert snapshot(checkout) == before


def test_formatter_exclusions_and_output_remain_stable(checkout):
    generated = checkout / "assets/star-history/fixture.json"
    generated.write_bytes(b'{"a":1}  ')
    license_file = checkout / "LICENSE"
    license_file.write_bytes(b"License without final newline")
    dialect = checkout / "waves/desktop/qml/Dialect.js"
    dialect.write_text(".pragma library\nfunction value() { return 1; }\n")
    before = snapshot(checkout)
    succeeds(
        checkout,
        "hk",
        "check",
        "--step",
        "prettier",
        "--step",
        "end-of-file-fixer",
        "--step",
        "trailing-whitespace",
        "--",
        str(generated.relative_to(checkout)),
        "LICENSE",
        str(dialect.relative_to(checkout)),
    )
    assert snapshot(checkout) == before
    sample = checkout / "sample.py"
    sample.write_text("value=1\n")
    succeeds(checkout, "git", "add", "sample.py")
    index = succeeds(checkout, "git", "write-tree").stdout
    succeeds(checkout, "hk", "fix", "--step", "ruff-format", "--no-stage", "sample.py")
    assert sample.read_bytes() == b"value = 1\n"
    assert succeeds(checkout, "git", "write-tree").stdout == index


def test_merge_conflicts_fail_during_a_merge_without_rewriting(checkout):
    head = succeeds(checkout, "git", "rev-parse", "HEAD").stdout
    (checkout / ".git/MERGE_HEAD").write_bytes(head)
    (checkout / ".git/MERGE_MSG").write_text("Fixture merge\n")
    (checkout / "conflict.txt").write_text("<<<<<<< ours\nleft\n=======\nright\n>>>>>>> theirs\n")
    before = snapshot(checkout)
    result = run(checkout, "hk", "check", "--step", "check-merge-conflict", "conflict.txt")
    assert result.returncode != 0
    assert snapshot(checkout) == before


def test_binary_case_conflicts_are_checked_against_other_tracked_paths(checkout):
    (checkout / "photo.PNG").write_bytes(b"\x00binary")
    succeeds(checkout, "git", "add", "photo.PNG")
    # The spelling conflict is represented in the index even on a case-insensitive host.
    blob = succeeds(checkout, "git", "hash-object", "photo.PNG").stdout.decode().strip()
    succeeds(checkout, "git", "update-index", "--add", "--cacheinfo", f"100644,{blob},PHOTO.png")
    before = snapshot(checkout)
    result = run(checkout, "hk", "check", "--step", "check-case-conflict", "photo.PNG")
    assert result.returncode != 0
    assert snapshot(checkout) == before


@pytest.mark.parametrize("step", ["lock", "ty", "deptry"])
def test_comprehensive_gate_retains_lock_type_and_dependency_failures(checkout, step):
    if step == "lock":
        project = checkout / "pyproject.toml"
        project.write_text(project.read_text().replace('"ruff==0.16.10"', '"ruff==0.16.9"'))
    elif step == "ty":
        (checkout / "waves/invalid.py").write_text('def value() -> int:\n    return "wrong"\n')
    else:
        (checkout / "waves/invalid.py").write_text("import missing_dependency_for_fixture\n")
    before = snapshot(checkout)
    result = run(checkout, "hk", "check", "--all", "--step", step)
    assert result.returncode != 0
    assert snapshot(checkout) == before


def test_linked_worktree_install_and_doctor_use_the_repository_hooks(checkout, tmp_path):
    linked = tmp_path / "linked"
    succeeds(checkout, "git", "worktree", "add", "-b", "linked-fixture", str(linked))
    succeeds(linked, "mise", "run", "install")
    succeeds(linked, "mise", "run", "doctor")
    succeeds(checkout, "mise", "run", "doctor")
