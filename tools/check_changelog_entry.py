"""Fail when a branch changes shipped code without adding an Unreleased bullet.

The Unreleased section in CHANGELOG.md is the source of the next release
notes, so a user-facing change adds its new bullet in the same PR. An
internal-only change opts out with [no-changelog] on a line of its own in every
commit that touches waves/.

The check compares committed HEAD with its merge-base on origin/develop; the
working tree is not part of the decision, and --no-renames makes a file moved
out of waves/ still count. Run it from the repository root, as `mise run
check` does.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

BASE_REF = "origin/develop"
CHANGELOG = "CHANGELOG.md"
SHIPPED_PREFIX = "waves/"
OPT_OUT = "[no-changelog]"
UNRELEASED = "## Unreleased"
MIN_GIT = (2, 38)
GIT = shutil.which("git") or ""


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    """Run git with fixed arguments and capture its output."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    return subprocess.run([GIT, *args], capture_output=True, text=True, check=False, env=env)


def _error(message: str) -> int:
    """Print a failure message and return the check's failure code."""
    print(message, file=sys.stderr)
    return 1


def _git_version_supported() -> bool:
    """Whether the installed Git provides merge-tree --write-tree."""
    version = _git("--version")
    match = re.search(r"git version (\d+)\.(\d+)", version.stdout)
    return version.returncode == 0 and bool(match) and (int(match[1]), int(match[2])) >= MIN_GIT


def _git_prerequisite_error() -> str | None:
    """The missing-Git error, or None when the toolchain is usable."""
    if not GIT:
        return "git is not on PATH; install git and try again."
    if not _git_version_supported():
        return "git 2.38 or newer is required for merge-tree --write-tree; upgrade git and try again."
    return None


def _nul_paths(output: str) -> list[str]:
    """Split a NUL-delimited git path list without quoting non-ASCII names."""
    return [path for path in output.split("\0") if path]


def _unreleased_bullets(revision: str) -> set[str]:
    """Return the bullet lines under ## Unreleased in a committed revision."""
    shown = _git("show", f"{revision}:{CHANGELOG}")
    if shown.returncode != 0:
        return set()
    bullets = set()
    in_unreleased = False
    for line in shown.stdout.splitlines():
        if line.startswith("## "):
            in_unreleased = line.strip() == UNRELEASED
        elif in_unreleased and line.startswith("- "):
            bullets.add(line)
    return bullets


def _commit_touches_shipped(commit: str) -> bool:
    """Whether a non-merge commit changed a path under waves/."""
    changed = _git("diff-tree", "--no-commit-id", "--name-only", "--no-renames", "-r", "-z", commit)
    if changed.returncode != 0:
        return False
    return any(path.startswith(SHIPPED_PREFIX) for path in _nul_paths(changed.stdout))


def _merge_resolution_touches_shipped(commit: str) -> bool:
    """Whether a merge commit adds a resolution change under waves/."""
    parents = _git("rev-list", "--parents", "-n", "1", commit).stdout.split()[1:]
    if len(parents) == 2:
        merged = _git("merge-tree", "--write-tree", "--name-only", "--no-messages", "-z", parents[0], parents[1])
        merged_tree = merged.stdout.split("\0")[0].strip() if merged.stdout else ""
        valid_tree = len(merged_tree) in (40, 64) and all(char in "0123456789abcdef" for char in merged_tree)
        actual = _git("rev-parse", f"{commit}^{{tree}}")
        if merged.returncode in (0, 1) and valid_tree and actual.returncode == 0:
            resolved = _git("diff", "--name-only", "--no-renames", "-z", merged_tree, actual.stdout.strip())
            if resolved.returncode == 0:
                if any(path.startswith(SHIPPED_PREFIX) for path in _nul_paths(resolved.stdout)):
                    return True
                if merged.returncode == 0:
                    return False
        if merged.returncode == 1 and valid_tree:
            conflicts = {
                token.strip() for token in merged.stdout.split("\0") if token.strip().startswith(SHIPPED_PREFIX)
            }
            return bool(conflicts)

    changed = _git("diff-tree", "--cc", "--no-commit-id", "--name-only", "--no-renames", "-r", "-z", commit)
    if changed.returncode != 0:
        return False
    return any(path.startswith(SHIPPED_PREFIX) for path in _nul_paths(changed.stdout))


def _is_ancestor(commit: str, revision: str) -> bool:
    """Whether commit is an ancestor of revision."""
    return _git("merge-base", "--is-ancestor", commit, revision).returncode == 0


def _shallow_boundary_in_range(base: str) -> bool:
    """Whether the shallow boundary is inside base..HEAD, where history is incomplete."""
    shown = _git("rev-parse", "--git-path", "shallow")
    if shown.returncode != 0:
        return False
    path = Path(shown.stdout.strip())
    if not path.is_file():
        return False
    return any(
        _is_ancestor(commit, "HEAD") and not _is_ancestor(commit, base)
        for commit in path.read_text(encoding="utf-8").split()
    )


def _has_opt_out(message: str) -> bool:
    """Whether the commit message has [no-changelog] on a line of its own."""
    return any(line.strip() == OPT_OUT for line in message.splitlines())


def _every_shipped_commit_opted_out(base: str) -> bool:
    """Whether each shipped change, including a merge resolution, has its own opt-out."""
    shipped = [
        commit
        for commit in _git("rev-list", "--no-merges", f"{base}..HEAD").stdout.split()
        if _commit_touches_shipped(commit)
    ]
    shipped += [
        commit
        for commit in _git("rev-list", "--merges", f"{base}..HEAD").stdout.split()
        if _merge_resolution_touches_shipped(commit)
    ]
    if not shipped:
        return False
    for commit in shipped:
        message = _git("show", "-s", "--format=%B", commit)
        if message.returncode != 0 or not _has_opt_out(message.stdout):
            return False
    return True


def main() -> int:
    """Run the changelog entry guard from the repository root."""
    prerequisite = _git_prerequisite_error()
    if prerequisite:
        return _error(prerequisite)

    ref = _git("rev-parse", "--verify", "--quiet", BASE_REF)
    if ref.returncode != 0:
        return _error(
            f"{BASE_REF} is not available in this checkout. Run"
            " `git fetch origin 'develop:refs/remotes/origin/develop'` (and fetch full history"
            " if the clone is shallow), then try again."
        )

    merge_base = _git("merge-base", BASE_REF, "HEAD")
    if merge_base.returncode != 0 or not merge_base.stdout.strip():
        shallow = _git("rev-parse", "--is-shallow-repository").stdout.strip() == "true"
        if shallow:
            return _error("The clone is shallow; run `git fetch --unshallow origin develop`, then try again.")
        return _error(
            f"No merge-base between HEAD and {BASE_REF}. The histories are unrelated;"
            " fetch the correct base or rebase the branch onto origin/develop, then try again."
        )

    base = merge_base.stdout.strip()
    if _shallow_boundary_in_range(base):
        return _error(
            "The shallow boundary falls inside origin/develop..HEAD; run"
            " `git fetch --unshallow origin develop`, then try again."
        )
    changed = _git("diff", "--name-only", "--no-renames", "-z", base, "HEAD")
    if changed.returncode != 0:
        return _error(f"git diff failed: {changed.stderr.strip()}")
    paths = _nul_paths(changed.stdout)
    if not any(path.startswith(SHIPPED_PREFIX) for path in paths):
        return 0

    if _unreleased_bullets("HEAD") - _unreleased_bullets(base):
        return 0
    if _every_shipped_commit_opted_out(base):
        return 0

    return _error(
        f'{SHIPPED_PREFIX}** changed without a new bullet under "{UNRELEASED}" in {CHANGELOG}.'
        f' Add a user-facing bullet, or put "{OPT_OUT}" on a line of its own in every commit that'
        f" touches {SHIPPED_PREFIX} for an internal-only change."
    )


if __name__ == "__main__":
    sys.exit(main())
