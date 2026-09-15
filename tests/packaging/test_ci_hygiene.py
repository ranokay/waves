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
    # Exact set: adding a pin to the ignore list means updating the playbook's
    # story too, and this fails until it does.
    ignored = {entry["dependency-name"] for entry in poetry["ignore"]}
    assert ignored == {"gamdl", "yt-dlp", "nuitka", "pyside6"}

    actions = _entry(cfg, "github-actions")
    assert actions["target-branch"] == "develop"


def test_the_build_job_restores_the_nuitka_cache_before_it_builds():
    wf = yaml.safe_load(RELEASE_WORKFLOW.read_text())
    steps = wf["jobs"]["build"]["steps"]

    cache_index = next(
        (index for index, step in enumerate(steps) if str(step.get("uses", "")).startswith("actions/cache")),
        None,
    )
    assert cache_index is not None, "the build job lost its Nuitka cache step"
    build_index = next(
        (index for index, step in enumerate(steps) if str(step.get("name", "")).startswith("Build Waves for")),
        None,
    )
    assert build_index is not None, "the build job lost its build step"
    assert cache_index < build_index, "the cache must restore before the build"

    with_block = steps[cache_index]["with"]
    path = str(with_block["path"])
    assert "dist/waves.build" in path
    # Each platform's Nuitka cache root carries ccache, the module cache and
    # downloads; the Windows path follows appdirs' appname/appname/Cache layout.
    assert "~/.cache/Nuitka" in path
    assert "~/Library/Caches/Nuitka" in path
    assert "~/AppData/Local/Nuitka/Nuitka/Cache" in path

    # One cache per matrix leg (the legacy macOS flavors build different Qt
    # bindings), invalidated by the lockfile and by the build recipe itself,
    # with a fallback salted the same way.
    key = str(with_block["key"])
    assert "matrix.OS_ARCH" in key and "poetry.lock" in key
    assert "Makefile" in key and "release-or-test-build.yml" in key
    restore_keys = str(with_block["restore-keys"])
    assert "matrix.OS_ARCH" in restore_keys
    assert "Makefile" in restore_keys and "release-or-test-build.yml" in restore_keys

    # The cached ccache must stay inside the repository cache budget.
    assert wf["jobs"]["build"]["env"]["CCACHE_MAXSIZE"] == "2G"


def test_windows_builds_ask_nuitka_for_low_memory():
    """MSVC dies compiling yt-dlp's generated C at full parallelism, so both
    Windows legs must build with one C compiler job (docs/dependency-updates.md
    has the numbers; docs/platform-enablement-review.md has the failure)."""
    makefile = (REPO_ROOT / "Makefile").read_text()
    assert "$(WAVES_NUITKA_LOW_MEMORY)" in makefile, "the Makefile must pass the flag to Nuitka"

    wf = yaml.safe_load(RELEASE_WORKFLOW.read_text())
    windows_legs = [
        leg
        for leg in wf["jobs"]["build"]["strategy"]["matrix"]["include"]
        if str(leg.get("os", "")).startswith("windows")
    ]
    assert len(windows_legs) == 2, "expected both Windows legs in the matrix"
    for leg in windows_legs:
        assert "WAVES_NUITKA_LOW_MEMORY=--low-memory" in str(leg["CMD_BUILD"]), leg["os"]
