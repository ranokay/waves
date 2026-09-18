"""The update hygiene stays wired: Dependabot targets develop and the release
build carries Nuitka's build tree between runs.

Dependabot reads Poetry through the "pip" ecosystem; the ignored names are
the pins that move by hand (docs/dependency-updates.md). The cache is the
difference between a release that relinks and one that recompiles every
module from a cold runner.
"""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
from pathlib import Path

import yaml
from support.paths import REPO_ROOT

DEPENDABOT = REPO_ROOT / ".github" / "dependabot.yml"
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release-or-test-build.yml"


def _inspector_module():
    """The bundle inspector as a module: its required-native list is what the
    build's include list is checked against, so the two cannot drift apart."""
    spec = importlib.util.spec_from_file_location("inspect_bundle", REPO_ROOT / "tools" / "inspect_bundle.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
    # bindings), invalidated by the lockfile and by the build inputs that
    # change the objects. The fallback prefix spans dependency bumps but not
    # recipe changes.
    key = str(with_block["key"])
    restore_keys = str(with_block["restore-keys"])
    for part in ("matrix.OS_ARCH", "Makefile", "pyproject.toml", "release-or-test-build.yml"):
        assert part in key, part
        assert part in restore_keys, part
    assert "poetry.lock" in key
    assert key == restore_keys.strip() + "${{ hashFiles('poetry.lock') }}"

    # The cached ccache must stay inside the repository cache budget.
    assert wf["jobs"]["build"]["env"]["CCACHE_MAXSIZE"] == "2G"


def _dry_run_nuitka_command(extra_env: dict[str, str]) -> str:
    make = shutil.which("make")
    assert make, "make is not on PATH; every release build needs it"
    result = subprocess.run(  # noqa: S603 (fixed argv: the resolved make, one dry-run target)
        [make, "-n", "gui-waves"],
        cwd=REPO_ROOT,
        env={**os.environ, **extra_env},
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def test_windows_builds_ask_nuitka_for_low_memory():
    """MSVC dies compiling yt-dlp's generated C at full parallelism, so both
    Windows legs must build with one C compiler job (the numbers live in
    docs/platform-enablement-review.md and its evidence file)."""
    wf = yaml.safe_load(RELEASE_WORKFLOW.read_text())
    windows_legs = [
        leg
        for leg in wf["jobs"]["build"]["strategy"]["matrix"]["include"]
        if str(leg.get("os", "")).startswith("windows")
    ]
    assert len(windows_legs) == 2, "expected both Windows legs in the matrix"
    for leg in windows_legs:
        assert "WAVES_NUITKA_FLAGS=--low-memory" in str(leg["CMD_BUILD"]), leg["os"]

    # The Makefile default is what local Windows builds get; it must resolve
    # from OS=Windows_NT alone and stay out of the other platforms' commands.
    assert "--low-memory" in _dry_run_nuitka_command({"OS": "Windows_NT"})
    assert "--low-memory" not in _dry_run_nuitka_command({"OS": ""})


def test_the_build_excludes_yt_dlps_lazy_extractor_table():
    """Every host must exclude yt-dlp's lazy extractor table (issue #245): its
    generated C dominated the cold build (the measured numbers live in
    docs/platform-enablement-review.md) and it is the one module the Windows
    runners cannot compile at all. Waves only ever hands yt-dlp direct stream
    URLs (gamdl's HlsFD/HttpFD path) and yt-dlp's own import contract falls back
    to the real extractor modules when the table is absent, so the artifact
    keeps every extractor. The CI Windows legs export
    WAVES_NUITKA_FLAGS=--low-memory themselves, so the exclusion has to survive
    an environment-provided value, not just resolve from the Makefile's own
    default."""
    for env in ({"OS": "Windows_NT"}, {"OS": ""}, {"OS": "Windows_NT", "WAVES_NUITKA_FLAGS": "--low-memory"}):
        command = _dry_run_nuitka_command(env)
        assert "--nofollow-import-to=yt_dlp.extractor.lazy_extractors" in command, env


def test_the_build_includes_the_pycryptodome_native_modules():
    """PyCryptodome loads its native modules by name through ctypes
    (load_pycryptodome_raw_lib), which Nuitka's import following cannot see:
    --include-package pulls only the Python submodules, so every needed native
    module must be included explicitly or the bundle ships an empty
    Crypto/Cipher and Apple downloads die at the first native load
    ("Crypto.Cipher._raw_aes", then "Crypto.Hash._SHA1", issue #304). Like the
    extractor exclusion, the includes must survive an environment-provided
    WAVES_NUITKA_FLAGS value. The list is resolved against the host's pinned
    PyCryptodome: every flag must name a module this platform installs (so a
    bump that renames one fails here), and the signing/download path's modules
    must all be on it (x86_64 hosts install extra AES-NI/CLMUL modules Nuitka
    picks up on its own)."""
    for env in ({"OS": "Windows_NT"}, {"OS": ""}, {"OS": "Windows_NT", "WAVES_NUITKA_FLAGS": "--low-memory"}):
        command = _dry_run_nuitka_command(env)
        assert "--include-module=Crypto.Cipher._raw_aes" in command, env
        assert "--include-module=Crypto.Hash._SHA1" in command, env

    command = _dry_run_nuitka_command({})
    listed = set(re.findall(r"--include-module=(Crypto\.[^\s]+)", command))
    assert listed, "the build lost its PyCryptodome native-module includes"

    import Crypto

    base = Path(Crypto.__file__).parent
    installed = {
        f"{base.name}.{'.'.join([*path.relative_to(base).parts[:-1], path.name.split('.')[0]])}"
        for path in base.rglob("*")
        if path.suffix in (".so", ".pyd")
    }
    assert listed <= installed, f"the include list names modules this platform lacks: {sorted(listed - installed)}"
    needed = {name for name, _kind in _inspector_module()._REQUIRED_NATIVE}
    missing = [
        name for name in sorted(needed) if not re.search(rf"--include-module=\S+\.{re.escape(name)}(\s|$)", command)
    ]
    assert missing == [], f"the include list dropped: {missing}"


def test_the_bundle_trim_leaves_the_pycryptodome_native_modules_alone(tmp_path):
    """The trim's first Crypto allowlist, built for the signing surface alone,
    deleted the native modules Apple downloads load by name and broke them
    twice in a row ('_raw_aes', then '_SHA1', issue #304). Crypto natives are
    no longer trimmed: run the real script on a fake bundle and assert they
    survive."""
    bundle = tmp_path / "waves.app"
    libdir = bundle / "Contents" / "MacOS"
    (libdir / "PySide6").mkdir(parents=True)
    natives = [
        libdir / "Crypto" / "Cipher" / "_raw_aes.so",
        libdir / "Crypto" / "Cipher" / "_raw_cbc.so",
        libdir / "Crypto" / "Hash" / "_SHA1.so",
    ]
    for native in natives:
        native.parent.mkdir(parents=True, exist_ok=True)
        native.write_bytes(b"\x00")

    bash = shutil.which("bash")
    assert bash, "bash is required to run the bundle trim"
    subprocess.run(  # noqa: S603 (fixed argv: the resolved bash, the repo's own trim script, a fake bundle)
        [bash, str(REPO_ROOT / "tools" / "trim_qt_bundle.sh"), str(bundle)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert all(native.exists() for native in natives)
