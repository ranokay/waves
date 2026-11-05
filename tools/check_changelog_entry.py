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

import shutil
import subprocess
import sys

BASE_REF = "origin/develop"
CHANGELOG = "CHANGELOG.md"
SHIPPED_PREFIX = "waves/"
OPT_OUT = "[no-changelog]"
UNRELEASED = "## Unreleased"
GIT = shutil.which("git") or ""


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    """Run git with fixed arguments and capture its output."""
    return subprocess.run([GIT, *args], capture_output=True, text=True, check=False)


def _error(message: str) -> int:
    """Print a failure message and return the check's failure code."""
    print(message, file=sys.stderr)
    return 1


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
    """Whether a commit changed a path under waves/."""
    changed = _git("diff-tree", "--no-commit-id", "--name-only", "--no-renames", "-r", "-m", "-z", commit)
    if changed.returncode != 0:
        return False
    return any(path.startswith(SHIPPED_PREFIX) for path in _nul_paths(changed.stdout))


def _has_opt_out(message: str) -> bool:
    """Whether the commit message has [no-changelog] on a line of its own."""
    return any(line.strip() == OPT_OUT for line in message.splitlines())


def _every_shipped_commit_opted_out(base: str) -> bool:
    """Whether each non-merge commit that touches waves/ carries its own opt-out."""
    commits = _git("rev-list", "--no-merges", f"{base}..HEAD").stdout.split()
    shipped = [commit for commit in commits if _commit_touches_shipped(commit)]
    if not shipped:
        return False
    for commit in shipped:
        message = _git("show", "-s", "--format=%B", commit)
        if message.returncode != 0 or not _has_opt_out(message.stdout):
            return False
    return True


def main() -> int:
    """Run the changelog entry guard from the repository root."""
    if not GIT:
        return _error("git is not on PATH; install git and try again.")

    ref = _git("rev-parse", "--verify", "--quiet", BASE_REF)
    if ref.returncode != 0:
        return _error(
            f"{BASE_REF} is not available in this checkout. Run `git fetch origin develop`"
            " (and fetch full history if the clone is shallow), then try again."
        )

    merge_base = _git("merge-base", BASE_REF, "HEAD")
    if merge_base.returncode != 0 or not merge_base.stdout.strip():
        shallow = _git("rev-parse", "--is-shallow-repository").stdout.strip() == "true"
        if shallow:
            cause = "The clone is shallow"
            fix = "run `git fetch --unshallow origin develop`"
        else:
            cause = "The histories are unrelated"
            fix = "fetch the correct base or rebase the branch onto origin/develop"
        return _error(f"No merge-base between HEAD and {BASE_REF}. {cause}; {fix}, then try again.")

    base = merge_base.stdout.strip()
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
