"""Fail when a branch changes shipped code without adding a changelog entry.

The Unreleased section in CHANGELOG.md is the source of the next release
notes, so a user-facing change adds its bullet in the same PR. An internal-only
change opts out with [no-changelog] on a line of its own in a commit message.

The check compares committed HEAD with its merge-base on origin/develop; the
working tree is not part of the decision, and --no-renames makes a file moved
out of waves/ still count. Run it from the repository root, as `mise run
check` does.
"""

from __future__ import annotations

import subprocess
import sys

BASE_REF = "origin/develop"
CHANGELOG = "CHANGELOG.md"
SHIPPED_PREFIX = "waves/"
OPT_OUT = "[no-changelog]"
UNRELEASED = "## Unreleased"


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False)


def _error(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


def main() -> int:
    ref = _git("rev-parse", "--verify", "--quiet", BASE_REF)
    if ref.returncode != 0:
        return _error(
            f"{BASE_REF} is not available in this checkout. Run `git fetch origin develop`"
            " (and fetch full history if the clone is shallow), then try again."
        )

    merge_base = _git("merge-base", BASE_REF, "HEAD")
    if merge_base.returncode != 0 or not merge_base.stdout.strip():
        return _error(
            f"No merge-base between HEAD and {BASE_REF}. The histories are unrelated or the clone is"
            " shallow; fetch full history with `git fetch --unshallow origin develop`, then try again."
        )

    base = merge_base.stdout.strip()
    changed = _git("diff", "--name-only", "--no-renames", base, "HEAD")
    if changed.returncode != 0:
        return _error(f"git diff failed: {changed.stderr.strip()}")
    paths = [line for line in changed.stdout.splitlines() if line]
    if CHANGELOG in paths or not any(path.startswith(SHIPPED_PREFIX) for path in paths):
        return 0

    messages = _git("log", "--format=%B", f"{base}..HEAD")
    if messages.returncode != 0:
        return _error(f"git log failed: {messages.stderr.strip()}")
    if any(line.strip() == OPT_OUT for line in messages.stdout.splitlines()):
        return 0

    return _error(
        f"{SHIPPED_PREFIX}** changed without a {CHANGELOG} entry. Add a user-facing bullet under"
        f' "{UNRELEASED}" in {CHANGELOG}, or put "{OPT_OUT}" on a line of its own in a commit message'
        " for an internal-only change."
    )


if __name__ == "__main__":
    sys.exit(main())
