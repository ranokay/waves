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
  the scenario sandboxes itself: ``support.qml.sandbox_app_config()`` (and
  the settings sandbox that wraps it, ``sandbox_qml_settings``) routes the
  app's config to a throwaway directory when the process has none.

``path_config_base()`` honours the variable first on every platform, so a
scenario given one can only ever touch a temporary directory.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from support.paths import REPO_ROOT, TESTS_ROOT
from support.qml import EXIT_NO_QT, require_qt

# One sanctioned sandbox call each, or an env of the scenario's own.
_SANDBOX_TOKENS = ("XDG_CONFIG_HOME", "sandbox_app_config", "sandbox_qml_settings", "boot_main_qml")


def test_every_offscreen_bridge_scenario_declares_its_config_sandbox():
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


@pytest.mark.qml
def test_a_direct_scenario_run_never_writes_the_native_config(tmp_path, monkeypatch):
    """The file's own ``__main__`` path hands the child no XDG_CONFIG_HOME.

    That is how a single scenario is iterated on, and before this pin it
    resolved the developer's real config directory: the bridge wrote
    ``settings.json``, ``waves.json`` and its ``waves_dev.log`` there, so the
    run's Qt warnings reached the user's diagnostics. The scenario must
    sandbox itself; this is the regression test for the leak.
    """
    from waves import paths

    # What the child's own platform-native config path would be with no XDG
    # set: the directory a scenario without a sandbox writes into.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    native = Path(paths.path_config_base())

    env = {key: value for key, value in os.environ.items() if key != "XDG_CONFIG_HOME"}
    env["HOME"] = str(tmp_path)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = os.pathsep.join(p for p in (str(TESTS_ROOT), str(REPO_ROOT), env.get("PYTHONPATH", "")) if p)
    proc = subprocess.run(  # noqa: S603 (fixed argv: this interpreter, a repo scenario file)
        [sys.executable, str(TESTS_ROOT / "ui" / "test_hover_swell_fade.py"), "--run-scenario"],
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if proc.returncode == EXIT_NO_QT:
        require_qt()
    assert proc.returncode == 0, (proc.stdout + proc.stderr)[-1200:]

    stray = sorted(str(p.relative_to(native)) for p in native.rglob("*") if p.is_file())
    assert not stray, (
        f"a direct scenario run wrote into the native config dir {native}: {stray}. "
        "The scenario must route the app's config to a throwaway directory "
        "(support.qml.sandbox_app_config) before building the bridge."
    )
