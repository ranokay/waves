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
    """Load the tool module for an in-process run."""
    spec = importlib.util.spec_from_file_location("check_changelog_entry", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _isolated_git(monkeypatch):
    """Scrub inherited Git environment and use an empty global config."""
    for key in [key for key in os.environ if key.startswith("GIT_")]:
        monkeypatch.delenv(key)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)


def _git(repo: Path, *args: str) -> str:
    """Run git in the fixture repo and return stripped stdout."""
    result = subprocess.run(  # noqa: S603 (fixed argv: the resolved git binary)
        [GIT, *args], cwd=repo, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def _configure(repo: Path) -> None:
    """Set the fixture repo's identity and disable signing."""
    _git(repo, "config", "user.name", "Changelog fixture")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    _git(repo, "config", "commit.gpgsign", "false")


def _init_repo(root: Path) -> Path:
    """Create and configure a fixture repository."""
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _configure(root)
    return root


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A fresh repository with a configured identity."""
    return _init_repo(tmp_path / "repo")


def _commit(repo: Path, message: str, files: dict[str, str]) -> str:
    """Write files, commit them, and return the new commit."""
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _base(repo: Path) -> None:
    """Commit the base files and create origin/develop."""
    _commit(repo, "base", {"waves/shipped.py": "value = 1\n", "CHANGELOG.md": "# Changelog\n"})
    _git(repo, "update-ref", "refs/remotes/origin/develop", "HEAD")


def _run(repo: Path, monkeypatch, capsys) -> tuple[int, str]:
    """Run the tool from the fixture repo and capture its stderr."""
    monkeypatch.chdir(repo)
    code = _tool_module().main()
    return code, capsys.readouterr().err


def test_an_old_git_fails_with_upgrade_guidance(monkeypatch, capsys):
    """merge-tree --write-tree needs Git 2.38 or newer."""
    module = _tool_module()

    def old_git(*args):
        return subprocess.CompletedProcess(["git", *args], 0, "git version 2.34.1\n", "")

    monkeypatch.setattr(module, "_git", old_git)
    assert module.main() == 1
    assert "2.38" in capsys.readouterr().err


def test_a_waves_change_with_an_unreleased_bullet_passes(repo, monkeypatch, capsys):
    """A new bullet under Unreleased satisfies the guard."""
    _base(repo)
    _commit(
        repo,
        "fix shipped behavior",
        {
            "waves/shipped.py": "value = 2\n",
            "CHANGELOG.md": "# Changelog\n\n## Unreleased\n\n- fixed a shipped behavior\n",
        },
    )
    code, err = _run(repo, monkeypatch, capsys)
    assert code == 0
    assert err == ""


def test_an_unreleased_heading_without_a_bullet_fails(repo, monkeypatch, capsys):
    """Adding the heading alone does not add a release note."""
    _base(repo)
    _commit(
        repo,
        "change shipped behavior",
        {"waves/shipped.py": "value = 2\n", "CHANGELOG.md": "# Changelog\n\n## Unreleased\n"},
    )
    code, err = _run(repo, monkeypatch, capsys)
    assert code == 1
    assert "## Unreleased" in err


def test_an_older_release_bullet_does_not_count(repo, monkeypatch, capsys):
    """An edit to a past release section is not an Unreleased entry."""
    _commit(
        repo,
        "base",
        {
            "waves/shipped.py": "value = 1\n",
            "CHANGELOG.md": "# Changelog\n\n## v1.0.0\n\n- old note\n",
        },
    )
    _git(repo, "update-ref", "refs/remotes/origin/develop", "HEAD")
    _commit(
        repo,
        "change shipped behavior",
        {
            "waves/shipped.py": "value = 2\n",
            "CHANGELOG.md": "# Changelog\n\n## v1.0.0\n\n- old note\n- new old-section note\n",
        },
    )
    code, err = _run(repo, monkeypatch, capsys)
    assert code == 1
    assert "CHANGELOG.md" in err


def test_a_waves_change_without_an_entry_fails_and_names_the_opt_out(repo, monkeypatch, capsys):
    """A shipped change with no changelog change names both remedies."""
    _base(repo)
    _commit(repo, "change shipped behavior", {"waves/shipped.py": "value = 2\n"})
    code, err = _run(repo, monkeypatch, capsys)
    assert code == 1
    assert "## Unreleased" in err
    assert "CHANGELOG.md" in err
    assert "[no-changelog]" in err


def test_a_no_changelog_line_in_a_commit_message_opts_out(repo, monkeypatch, capsys):
    """A whole-line marker on the shipped commit opts that change out."""
    _base(repo)
    _commit(repo, "internal refactor\n\n[no-changelog]\n", {"waves/shipped.py": "value = 2\n"})
    code, err = _run(repo, monkeypatch, capsys)
    assert code == 0
    assert err == ""


def test_each_shipped_commit_can_opt_out(repo, monkeypatch, capsys):
    """Every commit touching waves/ may carry its own whole-line marker."""
    _base(repo)
    _commit(repo, "internal one\n\n[no-changelog]\n", {"waves/shipped.py": "value = 2\n"})
    _commit(repo, "internal two\n\n[no-changelog]\n", {"waves/shipped.py": "value = 3\n"})
    code, err = _run(repo, monkeypatch, capsys)
    assert code == 0
    assert err == ""


def test_one_commits_opt_out_does_not_cover_another_shipped_change(repo, monkeypatch, capsys):
    """A marker on an earlier commit does not exempt a later shipped change."""
    _base(repo)
    _commit(repo, "internal one\n\n[no-changelog]\n", {"waves/shipped.py": "value = 2\n"})
    _commit(repo, "user-facing change", {"waves/shipped.py": "value = 3\n"})
    code, err = _run(repo, monkeypatch, capsys)
    assert code == 1
    assert "## Unreleased" in err


def test_a_clean_merge_of_opted_out_commits_passes(repo, monkeypatch, capsys):
    """A clean merge adds no resolution change, as on a PR's merge commit."""
    _base(repo)
    _git(repo, "checkout", "-q", "-b", "side")
    _commit(repo, "side change\n\n[no-changelog]\n", {"waves/side.py": "side\n"})
    _git(repo, "checkout", "-q", "main")
    _commit(repo, "main change\n\n[no-changelog]\n", {"waves/main.py": "main\n"})
    _git(repo, "merge", "--no-ff", "-m", "clean merge", "side")
    code, err = _run(repo, monkeypatch, capsys)
    assert code == 0
    assert err == ""


def test_a_clean_merge_of_a_shared_waves_file_passes(repo, monkeypatch, capsys):
    """A clean merge of one shared file adds no resolution hunk."""
    _commit(repo, "base", {"waves/shared.py": "alpha\nbeta\ngamma\n"})
    _git(repo, "update-ref", "refs/remotes/origin/develop", "HEAD")
    _git(repo, "checkout", "-q", "-b", "side")
    _commit(repo, "side change\n\n[no-changelog]\n", {"waves/shared.py": "alpha-side\nbeta\ngamma\n"})
    _git(repo, "checkout", "-q", "main")
    _commit(repo, "main change\n\n[no-changelog]\n", {"waves/shared.py": "alpha\nbeta\ngamma-main\n"})
    _git(repo, "merge", "--no-ff", "-m", "clean merge", "side")
    code, err = _run(repo, monkeypatch, capsys)
    assert code == 0
    assert err == ""


def test_an_auto_merged_waves_path_is_not_a_conflict(repo, monkeypatch, capsys):
    """An informational auto-merge record is not a waves resolution."""
    _commit(
        repo,
        "base",
        {"waves/shared.py": "alpha\nbeta\ngamma\n", "docs/note.txt": "base\n"},
    )
    _git(repo, "update-ref", "refs/remotes/origin/develop", "HEAD")
    _git(repo, "checkout", "-q", "-b", "side")
    _commit(
        repo,
        "side change\n\n[no-changelog]\n",
        {"waves/shared.py": "alpha-side\nbeta\ngamma\n", "docs/note.txt": "side\n"},
    )
    _git(repo, "checkout", "-q", "main")
    _commit(
        repo,
        "main change\n\n[no-changelog]\n",
        {"waves/shared.py": "alpha\nbeta\ngamma-main\n", "docs/note.txt": "main\n"},
    )
    with pytest.raises(subprocess.CalledProcessError):
        _git(repo, "merge", "side")
    (repo / "docs/note.txt").write_text("resolved\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "merge resolution")
    code, err = _run(repo, monkeypatch, capsys)
    assert code == 0
    assert err == ""


def test_a_clean_merge_edit_matching_one_parent_needs_an_opt_out(repo, monkeypatch, capsys):
    """A clean merge edited to a parent's waves version is still a resolution."""
    _base(repo)
    _git(repo, "checkout", "-q", "-b", "side")
    _commit(
        repo,
        "side change\n\n[no-changelog]\n",
        {"waves/shipped.py": "side\n", "waves/other.py": "side-other\n"},
    )
    _git(repo, "checkout", "-q", "main")
    _commit(repo, "main change\n\n[no-changelog]\n", {"docs/note.txt": "main\n"})
    _git(repo, "merge", "--no-ff", "--no-commit", "side")
    (repo / "waves/shipped.py").write_text("value = 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "clean merge")
    code, err = _run(repo, monkeypatch, capsys)
    assert code == 1
    assert "## Unreleased" in err


def test_a_non_conflicted_waves_edit_in_a_conflicted_merge_needs_an_opt_out(repo, monkeypatch, capsys):
    """A manual waves edit during a merge conflict elsewhere is a resolution."""
    _commit(
        repo,
        "base",
        {"waves/shared.py": "base\n", "docs/note.txt": "base\n"},
    )
    _git(repo, "update-ref", "refs/remotes/origin/develop", "HEAD")
    _git(repo, "checkout", "-q", "-b", "side")
    _commit(repo, "side change\n\n[no-changelog]\n", {"docs/note.txt": "side\n"})
    _git(repo, "checkout", "-q", "main")
    _commit(repo, "main change\n\n[no-changelog]\n", {"docs/note.txt": "main\n"})
    with pytest.raises(subprocess.CalledProcessError):
        _git(repo, "merge", "side")
    (repo / "docs/note.txt").write_text("resolved\n", encoding="utf-8")
    (repo / "waves/shared.py").write_text("manual\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "merge resolution")
    code, err = _run(repo, monkeypatch, capsys)
    assert code == 1
    assert "## Unreleased" in err


def test_an_ascii_quoted_conflict_path_under_waves_is_detected(repo, monkeypatch, capsys):
    """A non-ASCII conflicted path is found without Git's quoting."""
    _commit(repo, "base", {"waves/café.py": "base\n"})
    _git(repo, "update-ref", "refs/remotes/origin/develop", "HEAD")
    _git(repo, "checkout", "-q", "-b", "side")
    _commit(repo, "side change\n\n[no-changelog]\n", {"waves/café.py": "side\n"})
    _git(repo, "checkout", "-q", "main")
    _commit(repo, "main change\n\n[no-changelog]\n", {"waves/café.py": "main\n"})
    with pytest.raises(subprocess.CalledProcessError):
        _git(repo, "merge", "side")
    (repo / "waves/café.py").write_text("resolved\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "merge resolution")
    code, err = _run(repo, monkeypatch, capsys)
    assert code == 1
    assert "## Unreleased" in err


def test_a_conflict_resolved_to_one_parent_still_needs_an_opt_out(repo, monkeypatch, capsys):
    """Choosing one parent's version at a conflict is still a resolution."""
    _base(repo)
    _git(repo, "checkout", "-q", "-b", "side")
    _commit(repo, "side change\n\n[no-changelog]\n", {"waves/shipped.py": "side\n"})
    _git(repo, "checkout", "-q", "main")
    _commit(repo, "main change\n\n[no-changelog]\n", {"waves/shipped.py": "main\n"})
    with pytest.raises(subprocess.CalledProcessError):
        _git(repo, "merge", "side")
    (repo / "waves/shipped.py").write_text("main\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "merge resolution")
    code, err = _run(repo, monkeypatch, capsys)
    assert code == 1
    assert "## Unreleased" in err


def test_a_merge_resolution_needs_its_own_opt_out(repo, monkeypatch, capsys):
    """A conflict resolution touching waves/ is a shipped change of its own."""
    _base(repo)
    _git(repo, "checkout", "-q", "-b", "side")
    _commit(repo, "side change\n\n[no-changelog]\n", {"waves/shipped.py": "side\n"})
    _git(repo, "checkout", "-q", "main")
    _commit(repo, "main change\n\n[no-changelog]\n", {"waves/shipped.py": "main\n"})
    with pytest.raises(subprocess.CalledProcessError):
        _git(repo, "merge", "side")
    (repo / "waves/shipped.py").write_text("resolved\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "merge resolution")
    code, err = _run(repo, monkeypatch, capsys)
    assert code == 1
    assert "## Unreleased" in err


def test_an_inherited_git_dir_does_not_redirect_the_guard(repo, tmp_path, monkeypatch, capsys):
    """GIT_DIR from the caller cannot make the guard inspect another repository."""
    _base(repo)
    _commit(repo, "change shipped behavior", {"waves/shipped.py": "value = 2\n"})
    decoy = _init_repo(tmp_path / "decoy")
    _commit(decoy, "decoy", {"waves/decoy.py": "value = 1\n"})
    monkeypatch.setenv("GIT_DIR", str(decoy / ".git"))
    code, err = _run(repo, monkeypatch, capsys)
    assert code == 1
    assert "## Unreleased" in err


def test_a_sentence_mentioning_the_marker_does_not_opt_out(repo, monkeypatch, capsys):
    """The marker must be a line of its own, not prose."""
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
    """A docs-only change needs no Unreleased bullet."""
    _base(repo)
    _commit(repo, "document something", {"docs/guide.md": "# Guide\n"})
    code, err = _run(repo, monkeypatch, capsys)
    assert code == 0
    assert err == ""


def test_a_sibling_directory_is_not_shipped(repo, monkeypatch, capsys):
    """waves_foo/ is not the shipped waves/ directory."""
    _base(repo)
    _commit(repo, "change a sibling", {"waves_foo/shipped.py": "value = 2\n"})
    code, err = _run(repo, monkeypatch, capsys)
    assert code == 0
    assert err == ""


def test_a_non_ascii_path_under_waves_still_counts(repo, monkeypatch, capsys):
    """Git's path quoting must not hide a non-ASCII shipped file."""
    _base(repo)
    _commit(repo, "change a non-ascii path", {"waves/café.py": "value = 2\n"})
    code, err = _run(repo, monkeypatch, capsys)
    assert code == 1
    assert "CHANGELOG.md" in err


def test_a_file_moved_out_of_waves_still_counts(repo, monkeypatch, capsys):
    """A rename out of waves/ shows the deletion with --no-renames."""
    _base(repo)
    (repo / "elsewhere").mkdir()
    _git(repo, "mv", "waves/shipped.py", "elsewhere/shipped.py")
    _git(repo, "commit", "-q", "-m", "move shipped code out of waves")
    code, err = _run(repo, monkeypatch, capsys)
    assert code == 1
    assert "waves/**" in err


def test_a_missing_origin_develop_fails_with_its_cause_and_fix(repo, monkeypatch, capsys):
    """A checkout without origin/develop names the fetch that fixes it."""
    _commit(repo, "base", {"waves/shipped.py": "value = 1\n"})
    code, err = _run(repo, monkeypatch, capsys)
    assert code == 1
    assert "origin/develop" in err
    assert "git fetch origin 'develop:refs/remotes/origin/develop'" in err


def _point_origin_develop_at_an_unrelated_commit(repo: Path) -> None:
    """Point origin/develop at a root commit with no common ancestor."""
    tree = _git(repo, "write-tree")
    unrelated = _git(repo, "commit-tree", tree, "-m", "unrelated history")
    _git(repo, "update-ref", "refs/remotes/origin/develop", unrelated)


def test_unrelated_histories_name_the_cause_and_the_remedy(repo, monkeypatch, capsys):
    """Unrelated histories ask for the correct base or a rebase."""
    _commit(repo, "base", {"waves/shipped.py": "value = 1\n"})
    _point_origin_develop_at_an_unrelated_commit(repo)
    code, err = _run(repo, monkeypatch, capsys)
    assert code == 1
    assert "merge-base" in err
    assert "unrelated" in err
    assert "rebase the branch onto origin/develop" in err
    assert "unshallow" not in err


def test_a_shallow_clone_without_a_merge_base_names_the_unshallow_fix(tmp_path, monkeypatch, capsys):
    """An unrelated base in a shallow clone asks for the unshallow fetch."""
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


def test_a_shallow_boundary_inside_the_range_is_detected(repo, monkeypatch):
    """A boundary inside origin/develop..HEAD makes the opt-out walk incomplete."""
    _base(repo)
    commit = _commit(repo, "change shipped behavior", {"waves/shipped.py": "value = 2\n"})
    base = _git(repo, "rev-parse", "refs/remotes/origin/develop")
    shown = Path(_git(repo, "rev-parse", "--git-path", "shallow"))
    shallow = shown if shown.is_absolute() else repo / shown
    shallow.write_text(commit + "\n", encoding="utf-8")
    monkeypatch.chdir(repo)
    assert _tool_module()._shallow_boundary_in_range(base)
