"""A cold app launch boots, persists and rehydrates (issue #247, audit TT-03).

WHAT THIS FENCES OFF
--------------------
Every other boot test builds the bridge in-process and, at best, reloads the
QML over the same objects, so the state that only the real entry point touches
-- the settings/migration load, the first-run defaults, the window-frame save
and its restore, the quit flush -- had no regression guard: a change that broke
a true restart stayed green.

The child runs the packaged entry point (``waves.py``) offscreen against an
isolated XDG config, asks it to quit after its boot (``WAVES_QUIT_AFTER_BOOT_MS``,
the test seam in app.py) and must exit 0. A second, identical launch then
proves the first run's files are a valid launch state, that a seeded pref is
not re-defaulted by a later boot, and that the saved window frame is restored
through the real startup path.

The frame restore logs at INFO (``waves_dev.log``) only while ``WAVES_DEBUG``
is on, which is also what makes a failing run diagnosable.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from support.paths import REPO_ROOT

# Same marker split as the rest of the Qt-driving suite: `qml` because the
# child needs a working offscreen Qt, `integration` because the assertion
# only means something across a real process boundary.
pytestmark = [pytest.mark.qml, pytest.mark.integration]

_CONFIG_DIR = "Waves"
_SEEDED_FRAME = (640, 480)
_SEEDED_PREF = "name"


def _launch(env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603 (fixed argv: this interpreter, the entry file)
        [sys.executable, str(REPO_ROOT / "waves.py")],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _isolated_env(tmp_path: Path) -> dict[str, str]:
    """The child's environment: offscreen Qt, isolated dirs, self-quit."""
    env = dict(os.environ)
    env.update(
        {
            "QT_QPA_PLATFORM": "offscreen",
            "WAVES_QUIT_AFTER_BOOT_MS": "3000",
            "WAVES_DEBUG": "1",
            "XDG_CONFIG_HOME": str(tmp_path / "config"),
            "XDG_DATA_HOME": str(tmp_path / "data"),
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
        }
    )
    env.pop("WAVES_ACCOUNT_TESTS", None)
    return env


def _wrong(proc: subprocess.CompletedProcess, tmp_path: Path) -> str:
    log = tmp_path / "config" / _CONFIG_DIR / "waves_dev.log"
    tail = log.read_text(encoding="utf-8")[-2500:] if log.exists() else "(no dev log)"
    return f"rc={proc.returncode}\nstdout:\n{proc.stdout[-1500:]}\nstderr:\n{proc.stderr[-1500:]}\nlog tail:\n{tail}"


def test_a_cold_launch_boots_persists_and_rehydrates(tmp_path):
    config = tmp_path / "config" / _CONFIG_DIR
    config.mkdir(parents=True)
    # The seeded launch state: a window frame to restore and a pref whose
    # non-default value a later boot must not re-default.
    (config / "waves.json").write_text(
        json.dumps(
            {
                "win_w": _SEEDED_FRAME[0],
                "win_h": _SEEDED_FRAME[1],
                "win_x": 0,
                "win_y": 0,
                "search_sort": _SEEDED_PREF,
            }
        ),
        encoding="utf-8",
    )
    env = _isolated_env(tmp_path)

    first = _launch(env)
    assert first.returncode == 0, f"the first cold launch did not exit clean:\n{_wrong(first, tmp_path)}"
    log_path = config / "waves_dev.log"
    assert log_path.exists(), "the launch wrote no dev log at all"
    first_log = log_path.read_text(encoding="utf-8")
    assert f"restore window {_SEEDED_FRAME[0]}x{_SEEDED_FRAME[1]}" in first_log, _wrong(first, tmp_path)

    # A second launch over the files the first one wrote: the entry point must
    # come up again, keep the seeded pref, and restore the same frame.
    second = _launch(env)
    assert second.returncode == 0, f"the second launch did not exit clean:\n{_wrong(second, tmp_path)}"
    second_log = log_path.read_text(encoding="utf-8")
    assert second_log.count("restore window") == 2, _wrong(second, tmp_path)
    prefs = json.loads((config / "waves.json").read_text(encoding="utf-8"))
    assert prefs["search_sort"] == _SEEDED_PREF, "a later boot re-defaulted a saved pref"
    assert (prefs["win_w"], prefs["win_h"]) == _SEEDED_FRAME, "a later boot dropped the saved frame"
