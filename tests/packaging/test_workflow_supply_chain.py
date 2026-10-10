"""The GitHub workflows keep their supply-chain hygiene without Scorecard.

Scorecard does not support forks and is disabled on this one, so its
Pinned-Dependencies and Token-Permissions checks live here: every action a
workflow or composite action runs is pinned to a full commit SHA, and a
workflow's token starts read-only, with write scopes granted only to the jobs
listed below.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from pathlib import Path

import yaml
from support.paths import REPO_ROOT

GITHUB_DIR = REPO_ROOT / ".github"
PINNED_REF = re.compile(r"[^@\s]+@[0-9a-f]{40}")


def _parsed(paths: Iterable[Path]) -> dict[Path, dict]:
    return {path: yaml.safe_load(path.read_text()) for path in sorted(paths)}


# GitHub accepts both YAML extensions, and a local action may sit at any depth.
WORKFLOWS = _parsed([*(GITHUB_DIR / "workflows").glob("*.yml"), *(GITHUB_DIR / "workflows").glob("*.yaml")])
COMPOSITE_ACTIONS = _parsed([*GITHUB_DIR.rglob("action.yml"), *GITHUB_DIR.rglob("action.yaml")])


def _write_scopes(permissions: str | dict[str, str] | None) -> set[str]:
    """The scopes a `permissions:` value grants write on; `write-all` is all."""
    if isinstance(permissions, str):
        return {"*"} if permissions == "write-all" else set()
    return {scope for scope, level in (permissions or {}).items() if level == "write"}


def _uses_sites(document: dict) -> Iterator[dict]:
    """Every mapping that may carry a `uses:` reference."""
    if "runs" in document:
        yield from document["runs"].get("steps", [])
        return
    for job in document["jobs"].values():
        # A job that calls a reusable workflow carries its own `uses:`.
        yield job
        yield from job.get("steps", [])


def test_every_action_is_pinned_to_a_commit_sha():
    assert WORKFLOWS, "the glob must find the workflows"
    assert COMPOSITE_ACTIONS, "the glob must find the setup-env action"
    unpinned = [
        f"{path.relative_to(REPO_ROOT)}: {site['uses']}"
        for path, document in {**WORKFLOWS, **COMPOSITE_ACTIONS}.items()
        for site in _uses_sites(document)
        if "uses" in site and not site["uses"].startswith("./") and not PINNED_REF.fullmatch(site["uses"])
    ]
    assert not unpinned, unpinned


def test_every_workflow_token_starts_read_only():
    """An absent top-level block falls back to the repository's default token,
    which may write, so every workflow states its own."""
    granted = {}
    for path, document in WORKFLOWS.items():
        assert "permissions" in document, f"{path.name} must declare its top-level token permissions"
        if scopes := _write_scopes(document["permissions"]):
            granted[path.name] = scopes
    assert not granted, granted


def test_write_scopes_stay_on_the_jobs_that_need_them():
    """Exact set: a new write grant must name its job here, so a build or test
    job never quietly gains the authority to publish."""
    granted = {
        (path.name, job_id): scopes
        for path, document in WORKFLOWS.items()
        for job_id, job in document["jobs"].items()
        if (scopes := _write_scopes(job.get("permissions")))
    }
    assert granted == {
        # The release draft is created, filled per leg, then signed and published.
        ("release-or-test-build.yml", "create-release"): {"contents"},
        ("release-or-test-build.yml", "build"): {"contents"},
        ("release-or-test-build.yml", "sign-manifest"): {"contents"},
        # Each Flatpak leg attaches its bundle to the tagged release.
        ("flatpak-build.yml", "linux"): {"contents"},
        # The wrapper image is pushed to GHCR.
        ("wrapper-image.yml", "build"): {"packages"},
        # The weekly watcher files one deduped issue when upstream moves.
        ("wrapper-upstream-check.yml", "check"): {"issues"},
        # Upstream commits the regenerated chart; the fork keeps the job off.
        ("star-history.yml", "star-history"): {"contents"},
        # Code scanning upload and OIDC result publishing.
        ("scorecard.yml", "analysis"): {"security-events", "id-token"},
    }
