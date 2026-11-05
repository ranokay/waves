"""The Unreleased guard fails a branch that changes shipped code silently.

Every case runs the tool against a real temporary git repository: the base ref
is a commit, the branch is committed, and the tool reads committed HEAD rather
than the working tree. Inherited GIT_* variables are scrubbed so a parent
session's GIT_DIR or GIT_WORK_TREE cannot point the fixture at another repo.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from support.paths import REPO_ROOT

TOOL = REPO_ROOT / "tools" / "check_changelog_entry.py"
GIT = shutil.which("git")
assert GIT, "git is required to run the changelog guard fixtures"


def _tool_module():
    spec = importlib.util.spec_from_file_location("check_changelog_entry", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _isolated_git(monkeypatch):
    for key in [key for key in os.environ if key.startswith("GIT_")]:
        monkeypatch.delenv(key)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(  # noqa: S603 (fixed argv: the resolved git binary)
        [GIT, *args], cwd=repo, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def _configure(repo: Path) -> None:
    _git(repo, "config", "user.name", "Changelog fixture")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    _git(repo, "config", "commit.gpgsign", "false")


def _init_repo(root: Path) -> Path:
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _configure(root)
    return root


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return _init_repo(tmp_path / "repo")


def _commit(repo: Path, message: str, files: dict[str, str]) -> str:
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _base(repo: Path) -> None:
    _commit(repo, "base", {"waves/shipped.py": "value = 1\n", "CHANGELOG.md": "# Changelog\n"})
    _git(repo, "update-ref", "refs/remotes/origin/develop", "HEAD")


def _run(repo: Path, monkeypatch, capsys) -> tuple[int, str]:
    monkeypatch.chdir(repo)
    code = _tool_module().main()
    return code, capsys.readouterr().err


def test_a_waves_change_with_an_unreleased_entry_passes(repo, monkeypatch, capsys):
    _base(repo)
    _commit(
        repo,
        "fix shipped behavior",
        {"waves/shipped.py": "value = 2\n", "CHANGELOG.md": "# Changelog\n\n## Unreleased\n"},
    )
    code, err = _run(repo, monkeypatch, capsys)
    assert code == 0
    assert err == ""


def test_a_waves_change_without_an_entry_fails_and_names_the_opt_out(repo, monkeypatch, capsys):
    _base(repo)
    _commit(repo, "change shipped behavior", {"waves/shipped.py": "value = 2\n"})
    code, err = _run(repo, monkeypatch, capsys)
    assert code == 1
    assert "## Unreleased" in err
    assert "CHANGELOG.md" in err
    assert "[no-changelog]" in err


def test_a_no_changelog_line_in_a_commit_message_opts_out(repo, monkeypatch, capsys):
    _base(repo)
    _commit(repo, "internal refactor\n\n[no-changelog]\n", {"waves/shipped.py": "value = 2\n"})
    code, err = _run(repo, monkeypatch, capsys)
    assert code == 0
    assert err == ""


def test_a_sentence_mentioning_the_marker_does_not_opt_out(repo, monkeypatch, capsys):
    _base(repo)
    _commit(
        repo,
        "This mentions [no-changelog] in prose but is not an opt-out",
        {"waves/shipped.py": "value = 2\n"},
    )
    code, err = _run(repo, monkeypatch, capsys)
    assert code == 1
    assert "## Unreleased" in err


def test_a_change_outside_waves_needs_no_entry(repo, monkeypatch, capsys):
    _base(repo)
    _commit(repo, "document something", {"docs/guide.md": "# Guide\n"})
    code, err = _run(repo, monkeypatch, capsys)
    assert code == 0
    assert err == ""


def test_a_sibling_directory_is_not_shipped(repo, monkeypatch, capsys):
    _base(repo)
    _commit(repo, "change a sibling", {"waves_foo/shipped.py": "value = 2\n"})
    code, err = _run(repo, monkeypatch, capsys)
    assert code == 0
    assert err == ""


def test_a_non_ascii_path_under_waves_still_counts(repo, monkeypatch, capsys):
    _base(repo)
    _commit(repo, "change a non-ascii path", {"waves/café.py": "value = 2\n"})
    code, err = _run(repo, monkeypatch, capsys)
    assert code == 1
    assert "CHANGELOG.md" in err


def test_a_file_moved_out_of_waves_still_counts(repo, monkeypatch, capsys):
    _base(repo)
    (repo / "elsewhere").mkdir()
    _git(repo, "mv", "waves/shipped.py", "elsewhere/shipped.py")
    _git(repo, "commit", "-q", "-m", "move shipped code out of waves")
    code, err = _run(repo, monkeypatch, capsys)
    assert code == 1
    assert "waves/**" in err


def test_a_missing_origin_develop_fails_with_its_cause_and_fix(repo, monkeypatch, capsys):
    _commit(repo, "base", {"waves/shipped.py": "value = 1\n"})
    code, err = _run(repo, monkeypatch, capsys)
    assert code == 1
    assert "origin/develop" in err
    assert "git fetch origin develop" in err


def _point_origin_develop_at_an_unrelated_commit(repo: Path) -> None:
    tree = _git(repo, "write-tree")
    unrelated = _git(repo, "commit-tree", tree, "-m", "unrelated history")
    _git(repo, "update-ref", "refs/remotes/origin/develop", unrelated)


def test_unrelated_histories_name_the_cause_and_the_remedy(repo, monkeypatch, capsys):
    _commit(repo, "base", {"waves/shipped.py": "value = 1\n"})
    _point_origin_develop_at_an_unrelated_commit(repo)
    code, err = _run(repo, monkeypatch, capsys)
    assert code == 1
    assert "merge-base" in err
    assert "unrelated" in err
    assert "rebase the branch onto origin/develop" in err
    assert "unshallow" not in err


def test_a_shallow_clone_names_the_cause_and_the_remedy(tmp_path, monkeypatch, capsys):
    source = _init_repo(tmp_path / "source")
    _commit(source, "one", {"waves/shipped.py": "value = 1\n"})
    _commit(source, "two", {"waves/shipped.py": "value = 2\n"})

    clone = tmp_path / "clone"
    _git(tmp_path, "clone", "-q", "--depth", "1", source.as_uri(), str(clone))
    _configure(clone)
    _point_origin_develop_at_an_unrelated_commit(clone)

    code, err = _run(clone, monkeypatch, capsys)
    assert code == 1
    assert "shallow" in err
    assert "git fetch --unshallow origin develop" in err
