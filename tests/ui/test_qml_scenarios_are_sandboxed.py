"""An offscreen scenario must never run against the real config directory.

WHAT THIS FENCES OFF
--------------------
A scenario that builds a real ``WavesBridge`` inherits whatever config
directory the environment points at, and on a developer's machine that is
the packaged app's own: ``~/Library/Application Support/Waves`` (or the
platform equivalent). The bridge then adopts the user's settings, writes
its startup lines, tracebacks and Qt warnings into the user's
``waves_dev.log``, and, if a library root is configured, starts a REAL scan
of the user's music library from its constructor.

A scenario missing the sandbox shows it: a verbose log kept by a developer is
interleaved with test sessions, each one starting a library scan that bails
seconds later, a test's own "live TIDAL API disabled in this test" traceback
is written into it as an app ERROR, and exported diagnostics bundles carry
``waves.qt`` warnings the app itself never produced.

HOW THIS STAYS FIXED
--------------------
Two gates, one per launch path:

* Through the suite, every test module that constructs a bridge behind a QML
  engine either runs its child through ``support.qml.run_scenario`` (which
  hands it a private ``XDG_CONFIG_HOME``) or sets that variable on its own
  subprocess env.
* Run directly -- ``python tests/ui/<file>.py --run-scenario``, how a single
  scenario is iterated on -- there is no parent runner to hand one over, so
  the scenario sandboxes itself: ``support.qml.sandbox_app_config()`` routes
  the app's config to a throwaway directory when the process has none, and
  re-points ``BaseConfig.path_base`` when a module-level app import already
  resolved it against the real one. The harness calls it from
  ``patch_offline()`` (the pre-bridge step every runner takes) and from
  ``sandbox_qml_settings()``.

``path_config_base()`` honours the variable first on every platform, so a
scenario given one can only ever touch a temporary directory.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from support.paths import REPO_ROOT, TESTS_ROOT
from support.qml import EXIT_NO_QT, require_qt, scenario_env

# A declared sandbox: an env of the scenario's own, or a harness call that
# establishes one before the bridge (patch_offline underneath them all).
_SANDBOX_TOKENS = (
    "XDG_CONFIG_HOME",
    "patch_offline(",
    "sandbox_app_config(",
    "sandbox_qml_settings(",
    "boot_main_qml(",
)


# Wiring, not behavior coverage: the corpus is every test file, and the absence
# it asserts -- no bridge-building file without a sandbox -- has no behavioral
# seam. Proving it per file would mean running every scenario once; the
# behavioral half is the direct-run regression below.
def test_wiring_every_offscreen_bridge_scenario_declares_its_config_sandbox():
    unsandboxed = []
    own_file = Path(__file__).resolve()
    for path in sorted(TESTS_ROOT.rglob("test_*.py")):
        if path.resolve() == own_file:
            continue  # it builds no bridge, and its own text names the tokens above
        src = path.read_text()
        builds_bridge = "WavesBridge(" in src and "QQmlApplicationEngine" in src
        if not builds_bridge:
            continue
        if not any(token in src for token in _SANDBOX_TOKENS):
            unsandboxed.append(str(path.relative_to(TESTS_ROOT)))

    assert not unsandboxed, (
        "these scenarios build a real WavesBridge behind a QML engine with no "
        "config sandbox of their own, so a run outside the suite adopts the packaged "
        "app's config dir: the user's settings, the user's log, and a real scan of the "
        'user\'s library. Set env["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="waves-<name>-'
        'test-"), call support.qml.sandbox_app_config() before the bridge, or run the '
        "child through support.qml.run_scenario: " + ", ".join(unsandboxed)
    )


_CONFIG_PROBES = {
    "fresh-import": """
import os

from support.offline import patch_offline

patch_offline()

from waves.config import BaseConfig

print("XDG", os.environ.get("XDG_CONFIG_HOME", ""))
print("BASE", BaseConfig.path_base)
""",
    "pre-imported": """
import os

# The shape a test module has when it imports an app module at module scope:
# waves.config resolves BaseConfig.path_base before any runner can sandbox.
from waves.config import BaseConfig

from support.offline import patch_offline

patch_offline()

print("XDG", os.environ.get("XDG_CONFIG_HOME", ""))
print("BASE", BaseConfig.path_base)
""",
}


def _sandboxed_home(monkeypatch, tmp_path) -> Path:
    """Sandbox HOME and APPDATA (Windows anchors the native config base on
    ``%APPDATA%``, not HOME) and drop XDG_CONFIG_HOME; return the native config
    dir that leaves -- the directory a scenario without a sandbox writes
    into."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    monkeypatch.delenv("HOMEDRIVE", raising=False)
    monkeypatch.delenv("HOMEPATH", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    from waves import paths

    # A "failed" migration left by another test would answer with the legacy
    # dir instead, and the assertions below would check the wrong directory.
    monkeypatch.setattr(paths, "CONFIG_MIGRATION", "")
    return Path(paths.path_config_base())


def _run_probe(script: str) -> subprocess.CompletedProcess[str]:
    """Run a literal probe in a child the scenario must sandbox itself."""
    return subprocess.run(  # noqa: S603 (fixed argv: this interpreter, a literal probe)
        [sys.executable, "-c", script],
        cwd=str(REPO_ROOT),
        env=scenario_env(None),
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.mark.integration
@pytest.mark.parametrize("probe", list(_CONFIG_PROBES.values()), ids=list(_CONFIG_PROBES.keys()))
def test_patch_offline_sandboxes_the_config_base(probe, tmp_path, monkeypatch):
    """``waves.config`` resolves ``BaseConfig.path_base()`` at import, and
    ``patch_offline`` is the harness call that precedes every bridge: it must
    leave the base sandboxed whether the app import comes after it (fresh
    import) or already happened at module scope (pre-imported), or a direct
    run would ``makedirs()`` the real config dir on a save."""
    _sandboxed_home(monkeypatch, tmp_path)
    proc = _run_probe(probe)
    assert proc.returncode == 0, proc.stderr[-800:]
    values = dict(line.split(" ", 1) for line in proc.stdout.splitlines() if line.startswith(("XDG ", "BASE ")))
    xdg = values.get("XDG", "")
    assert xdg, "patch_offline left no XDG_CONFIG_HOME; the app would resolve the real config dir"
    assert values.get("BASE") == str(Path(xdg) / "Waves"), (
        f"BaseConfig.path_base resolved to {values.get('BASE')!r}, outside the sandbox {xdg!r}"
    )


_IMPORT_PROBE = """
import waves.desktop.app  # noqa: F401 -- the app entry module a test may import at module scope
import waves.desktop.backend  # noqa: F401 -- the bridge module
from waves.config import Settings, SingletonMeta
from waves.desktop.session import WavesTidal

print("SETTINGS", Settings in SingletonMeta._instances)
print("TIDAL", WavesTidal in SingletonMeta._instances)
"""


@pytest.mark.qml
def test_importing_the_app_constructs_no_config_singleton(tmp_path, monkeypatch):
    """An app import must not build Settings/Tidal: construction reads the
    config file and can persist migrations, so a module-scope import that built
    one would escape every later sandbox -- ``sandbox_app_config`` re-points
    the cached ``BaseConfig.path_base``, not a built instance's ``file_path``
    (and therefore its dev log directory)."""
    require_qt()
    _sandboxed_home(monkeypatch, tmp_path)
    proc = _run_probe(_IMPORT_PROBE)
    assert proc.returncode == 0, proc.stderr[-800:]
    assert proc.stdout.split() == ["SETTINGS", "False", "TIDAL", "False"], proc.stdout
    stray = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*"))
    assert not stray, f"importing the app wrote into the sandboxed home: {stray[:8]}"


@pytest.mark.qml
def test_a_direct_scenario_run_never_writes_the_native_config(tmp_path, monkeypatch):
    """The file's own ``__main__`` path hands the child no XDG_CONFIG_HOME.

    That is how a single scenario is iterated on, and before this pin the
    bridge resolved the developer's real config directory: settings, token and
    ``waves_dev.log`` were written there, so the run's Qt warnings reached the
    user's diagnostics. The named scenario imports an app module at module
    scope and boots through ``boot_main_qml``, so the config base is resolved
    before any runner can sandbox -- the shape the patch_offline repair exists
    for.
    """
    native = _sandboxed_home(monkeypatch, tmp_path)
    proc = subprocess.run(  # noqa: S603 (fixed argv: this interpreter, a repo scenario file)
        [sys.executable, str(TESTS_ROOT / "ui" / "test_search_sort_pref.py"), "--run-scenario"],
        env=scenario_env(None),
        capture_output=True,
        text=True,
        timeout=180,
    )
    if proc.returncode == EXIT_NO_QT:
        require_qt()
    assert proc.returncode == 0, (proc.stdout + proc.stderr)[-1200:]

    assert not native.exists(), (
        f"a direct scenario run created the native config dir {native}: "
        f"{sorted(str(p.relative_to(native)) for p in native.rglob('*'))[:8]}. The scenario "
        "must route the app's config to a throwaway directory before its first app import."
    )
