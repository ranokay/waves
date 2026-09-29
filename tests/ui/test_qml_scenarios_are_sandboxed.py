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
  ``patch_offline()`` -- the harness's last moment before any app import --
  calls it, because ``waves.config`` resolves ``BaseConfig.path_base`` at
  import time. ``sandbox_qml_settings()`` wraps it too.

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
    for path in sorted(TESTS_ROOT.rglob("test_*.py")):
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


_CONFIG_PROBE = """
import os

from support.offline import patch_offline

patch_offline()
from waves.config import BaseConfig

print("XDG", os.environ.get("XDG_CONFIG_HOME", ""))
print("BASE", BaseConfig.path_base)
"""


@pytest.mark.integration
def test_patch_offline_sandboxes_before_the_first_app_import(tmp_path):
    """``waves.config`` resolves ``BaseConfig.path_base()`` at import, and
    ``patch_offline`` is the harness call that precedes every bridge: its own
    import chain must already have a sandbox, or a direct run pins -- and even
    a sandboxed bridge then ``makedirs()`` into -- the real config dir."""
    env = scenario_env(None)
    env["HOME"] = str(tmp_path)
    proc = subprocess.run(  # noqa: S603 (fixed argv: this interpreter, a literal probe)
        [sys.executable, "-c", _CONFIG_PROBE],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr[-800:]
    values = dict(line.split(" ", 1) for line in proc.stdout.splitlines() if line.startswith(("XDG ", "BASE ")))
    xdg = values.get("XDG", "")
    assert xdg, "patch_offline left no XDG_CONFIG_HOME; the first app import would resolve the real config dir"
    assert values.get("BASE") == str(Path(xdg) / "Waves"), (
        f"BaseConfig.path_base resolved to {values.get('BASE')!r}, outside the sandbox {xdg!r}"
    )


@pytest.mark.qml
def test_a_direct_scenario_run_never_writes_the_native_config(tmp_path, monkeypatch):
    """The file's own ``__main__`` path hands the child no XDG_CONFIG_HOME.

    That is how a single scenario is iterated on, and before this pin the
    bridge resolved the developer's real config directory: settings, token and
    ``waves_dev.log`` were written there, so the run's Qt warnings reached the
    user's diagnostics. The scenario must sandbox itself. The named scenario
    calls ``patch_offline`` before its settings sandbox, so this also pins
    that order.
    """
    from waves import paths

    # What the child's own platform-native config path would be with no XDG
    # set: the directory a scenario without a sandbox writes into.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    native = Path(paths.path_config_base())

    env = scenario_env(None)
    env["HOME"] = str(tmp_path)
    proc = subprocess.run(  # noqa: S603 (fixed argv: this interpreter, a repo scenario file)
        [sys.executable, str(TESTS_ROOT / "ui" / "test_search_query_collapse_qml.py"), "--run-scenario"],
        env=env,
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
