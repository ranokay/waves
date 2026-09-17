"""The QML scenario runner: success, positive dependency skips, loud failures.

A scenario parent skips only when PySide6 is positively absent, and fails
with the child's output on every other non-zero exit, so an application
import error or a QML load failure can never pass as an environment skip.
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

    # The skip half asks for the non-strict state explicitly: the suite may
    # itself be running under --require-qml, where the runner refuses to
    # skip at all (and that refusal is the second half's whole point).
    monkeypatch.setattr(qml, "_REQUIRE_QML", False)
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
        run_scenario(qml.TESTS_ROOT / "ui" / "test_startup_provider_picker_qml.py", "--run-scenario")

    assert "injected app import failure" in str(excinfo.value)


def test_ffmpeg_marker_skips_when_no_binary_is_on_path():
    """The ffmpeg marker is the suite's skip gate for missing binaries."""
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
            "tests/providers/apple/test_apple_download_seam.py",
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


@pytest.mark.integration
def test_qml_marker_skips_without_pyside_and_require_qml_fails(tmp_path):
    """Against an interpreter with no PySide6: the qml marker skips the
    scenario, and the GUI-required run refuses to start instead."""
    import os
    import subprocess
    import sys

    (tmp_path / "sitecustomize.py").write_text(
        "import sys, importlib.abc\n"
        "class _NoQt(importlib.abc.MetaPathFinder):\n"
        "    def find_spec(self, fullname, path=None, target=None):\n"
        "        if fullname == 'PySide6':\n"
        "            raise ModuleNotFoundError('blocked for the test')\n"
        "        return None\n"
        "sys.meta_path.insert(0, _NoQt())\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(tmp_path)
    target = (
        "tests/ui/test_startup_provider_picker_qml.py"
        "::test_first_run_offers_the_provider_choice_and_never_auto_opens_login"
    )

    skipped = subprocess.run(  # noqa: S603 (fixed argv: this interpreter, one collected test)
        [sys.executable, "-m", "pytest", "-m", "qml", "-q", "-p", "no:cacheprovider", target],
        cwd=qml.REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert "1 skipped" in skipped.stdout, skipped.stdout + skipped.stderr

    required = subprocess.run(  # noqa: S603 (fixed argv: this interpreter, one collected test)
        [sys.executable, "-m", "pytest", "-m", "qml", "--require-qml", "-q", "-p", "no:cacheprovider", target],
        cwd=qml.REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert required.returncode != 0
    assert "--require-qml was given but PySide6 is not importable" in (required.stdout + required.stderr)


def test_tail_drops_noisy_lines_and_keeps_the_last_ones():
    output = qml._tail("one\ntwo\nwaves.qt: noise\nthree\n", None, limit=2, drop=("waves.qt",))

    assert output == "two\nthree"


def test_missing_qt_only_reports_a_real_absence(monkeypatch):
    def _raise(exc):
        def _find(_name):
            raise exc

        return _find

    monkeypatch.setattr(qml.importlib.util, "find_spec", _raise(ImportError()))
    assert qml.missing_qt() is True
    # A partially initialised module is not evidence of absence.
    monkeypatch.setattr(qml.importlib.util, "find_spec", _raise(ValueError()))
    assert qml.missing_qt() is False
    monkeypatch.setattr(qml.importlib.util, "find_spec", lambda _name: None)
    assert qml.missing_qt() is True
