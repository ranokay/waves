"""The QML scenario runner: success, positive dependency skips, loud failures.

The old per-file parents treated exit 77 (no Qt) and exit 78 (QML did not
load) as skips alike, and their children returned 77 for application import
errors, so a broken app could pass the suite as an environment skip. The
runner decides in the parent: only a positively absent PySide6 skips, and
every other non-zero exit fails with the child's output.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from support import qml
from support.qml import run_scenario


def _script(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "scenario.py"
    path.write_text(body)
    return path


def test_scenario_success_returns_the_output(tmp_path):
    script = _script(tmp_path, "print('scenario-ok')\n")

    output = run_scenario(script)

    assert "scenario-ok" in output


def test_application_error_fails_with_the_child_output(tmp_path):
    script = _script(tmp_path, "raise RuntimeError('app import exploded')\n")

    with pytest.raises(pytest.fail.Exception) as excinfo:
        run_scenario(script)

    assert "app import exploded" in str(excinfo.value)


def test_a_qml_precondition_exit_fails_rather_than_skips(tmp_path):
    script = _script(tmp_path, "raise SystemExit(78)\n")

    with pytest.raises(pytest.fail.Exception):
        run_scenario(script)


def test_no_qt_exit_never_skips_when_qt_is_present(tmp_path, monkeypatch):
    """A child's 77 is only meaningful when the parent positively lacks Qt."""
    monkeypatch.setattr(qml, "missing_qt", lambda: False)
    script = _script(tmp_path, "raise SystemExit(77)\n")

    with pytest.raises(pytest.fail.Exception):
        run_scenario(script)


def test_missing_qt_skips_normally_and_fails_under_require_qml(tmp_path, monkeypatch):
    monkeypatch.setattr(qml, "missing_qt", lambda: True)
    script = _script(tmp_path, "raise AssertionError('the child must not run')\n")

    with pytest.raises(pytest.skip.Exception):
        run_scenario(script)

    monkeypatch.setattr(qml, "_REQUIRE_QML", True)
    with pytest.raises(pytest.fail.Exception) as excinfo:
        run_scenario(script)
    assert "--require-qml" in str(excinfo.value)


def test_scenario_env_puts_the_repo_and_tests_root_on_pythonpath(tmp_path):
    env = qml.scenario_env(str(tmp_path))

    parts = env["PYTHONPATH"].split(":")
    assert str(qml.TESTS_ROOT) in parts
    assert str(qml.REPO_ROOT) in parts
    assert env["QT_QPA_PLATFORM"] == "offscreen"
    assert env["XDG_CONFIG_HOME"] == str(tmp_path)


@pytest.mark.qml
def test_a_broken_app_import_fails_the_startup_scenario(tmp_path, monkeypatch):
    """The audit's probe, as a regression test: injecting a RuntimeError while
    importing waves.waves_ui.app must fail the scenario, never skip it."""
    (tmp_path / "sitecustomize.py").write_text(
        "import sys, importlib.abc\n"
        "class _Blocker(importlib.abc.MetaPathFinder):\n"
        "    def find_spec(self, fullname, path=None, target=None):\n"
        "        if fullname == 'waves.waves_ui.app':\n"
        "            raise RuntimeError('injected app import failure')\n"
        "        return None\n"
        "sys.meta_path.insert(0, _Blocker())\n"
    )
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))

    with pytest.raises(pytest.fail.Exception) as excinfo:
        run_scenario(qml.TESTS_ROOT / "test_startup_provider_picker_qml.py", "--run-scenario")

    assert "injected app import failure" in str(excinfo.value)


def test_ffmpeg_marker_skips_when_no_binary_is_on_path():
    """The ffmpeg marker replaces the old per-file skipif helper."""
    import os
    import subprocess
    import sys

    env = dict(os.environ)
    env["PATH"] = str(Path(sys.executable).parent)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_apple_download_seam.py",
            "-q",
            "-k",
            "decode_check_accepts_clean_audio",
            "-p",
            "no:cacheprovider",
        ],
        cwd=qml.REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )

    assert "1 skipped" in proc.stdout, proc.stdout + proc.stderr
