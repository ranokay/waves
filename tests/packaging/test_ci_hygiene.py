"""The update hygiene stays wired: Dependabot targets develop and the release
build carries Nuitka's build tree between runs.

Dependabot reads Poetry through the "pip" ecosystem; the ignored names are
the pins that move by hand (docs/dependency-updates.md). The cache is the
difference between a release that relinks and one that recompiles every
module from a cold runner.
"""

from __future__ import annotations

import yaml
from support.paths import REPO_ROOT

DEPENDABOT = REPO_ROOT / ".github" / "dependabot.yml"
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release-or-test-build.yml"


def _entry(cfg: dict, ecosystem: str) -> dict:
    matches = [
        update for update in cfg["updates"] if update["package-ecosystem"] == ecosystem and update["directory"] == "/"
    ]
    assert matches, f"no Dependabot entry for {ecosystem}"
    return matches[0]


def test_dependabot_updates_develop_and_leaves_the_deliberate_pins_alone():
    cfg = yaml.safe_load(DEPENDABOT.read_text())
    assert cfg["version"] == 2

    poetry = _entry(cfg, "pip")
    assert poetry["target-branch"] == "develop"
    assert poetry["groups"], "a week of bumps should arrive as one grouped PR"
    ignored = {entry["dependency-name"] for entry in poetry["ignore"]}
    assert {"gamdl", "yt-dlp", "nuitka", "pyside6"} <= ignored

    actions = _entry(cfg, "github-actions")
    assert actions["target-branch"] == "develop"


def test_the_build_job_restores_the_nuitka_cache_before_it_builds():
    wf = yaml.safe_load(RELEASE_WORKFLOW.read_text())
    steps = wf["jobs"]["build"]["steps"]

    cache_index = next(
        index for index, step in enumerate(steps) if str(step.get("uses", "")).startswith("actions/cache")
    )
    build_index = next(
        index for index, step in enumerate(steps) if str(step.get("name", "")).startswith("Build Waves for")
    )
    assert cache_index < build_index

    with_block = steps[cache_index]["with"]
    assert "dist/waves.build" in with_block["path"]
    # One cache per matrix leg (the legacy macOS flavors build different Qt
    # bindings), invalidated by the lockfile, with a fallback that warms the
    # first build after a dependency bump.
    assert "matrix.OS_ARCH" in with_block["key"]
    assert "poetry.lock" in with_block["key"]
    assert with_block["restore-keys"]
