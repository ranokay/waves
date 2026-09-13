"""Offscreen QML scenario runner for the subprocess-based UI tests.

Building a real WavesBridge installs process-global handlers and a Qt
application that must not leak into the suite, so each QML scenario runs in
its own interpreter. The parent decides whether a scenario may skip: only a
positively absent PySide6 does, and every other non-zero exit fails the
test with the child's last output lines. That keeps an application import
error or a QML load failure from masquerading as a missing dependency, and
``--require-qml`` turns even the missing-dependency skip into a failure for
the GUI-required run.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from support.paths import REPO_ROOT, TESTS_ROOT

EXIT_OK = 0
EXIT_REGRESSED = 1
EXIT_NO_QT = 77
EXIT_PRECONDITION = 78

_REQUIRE_QML = False


def set_require_qml(required: bool) -> None:
    """Record the run's ``--require-qml`` choice (called by conftest)."""
    global _REQUIRE_QML
    _REQUIRE_QML = bool(required)


def require_qml() -> bool:
    """Whether this run was started with ``--require-qml`` (set by conftest)."""
    return _REQUIRE_QML


def missing_qt() -> bool:
    """Whether PySide6 is positively absent, without importing it.

    Only a real absence may skip; a spec that cannot be inspected (a partially
    initialised module) is not evidence of absence and reads as present.
    """
    try:
        return importlib.util.find_spec("PySide6") is None
    except ImportError:
        return True
    except ValueError:
        return False


def scenario_env(sandbox: str) -> dict[str, str]:
    """The environment one scenario child runs with: offscreen Qt, a private
    config directory, and the repo plus tests root importable from any depth."""
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["XDG_CONFIG_HOME"] = sandbox
    parts = [str(TESTS_ROOT), str(REPO_ROOT), env.get("PYTHONPATH", "")]
    env["PYTHONPATH"] = os.pathsep.join(part for part in parts if part)
    return env


def _tail(stdout: str | None, stderr: str | None, limit: int = 12, drop: tuple[str, ...] = ()) -> str:
    text = ((stdout or "") + (stderr or "")).strip()
    lines = [line for line in text.splitlines() if not any(token in line for token in drop)]
    return "\n".join(lines[-limit:])


def _skip_or_fail_missing_qt() -> None:
    message = "PySide6 / offscreen Qt unavailable"
    if require_qml():
        pytest.fail(f"{message} and --require-qml was given")
    pytest.skip(message)


def run_scenario(
    script: str | Path,
    *flags: str,
    timeout: int = 180,
    sandbox_prefix: str = "waves-qml-",
    failure_message: str = "",
    drop: tuple[str, ...] = (),
) -> str:
    """Run one QML scenario child and return its output tail.

    Skips only when PySide6 is positively absent from this interpreter;
    every other non-zero exit fails with the child's last output lines, so
    application import errors, QML load failures and regressions all read
    as failures. ``failure_message`` prefixes the failure when the caller
    has a sharper verdict than "the scenario failed", and ``drop`` removes
    known-noisy lines (Qt warnings) from the reported tail.
    """
    path = Path(script).resolve()
    if missing_qt():
        _skip_or_fail_missing_qt()
    sandbox = tempfile.mkdtemp(prefix=sandbox_prefix)
    try:
        try:
            proc = subprocess.run(  # noqa: S603 (fixed argv: this interpreter, a repo script)
                [sys.executable, str(path), *flags],
                env=scenario_env(sandbox),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            message = failure_message or "the QML scenario did not finish"
            pytest.fail(f"{message} (timed out after {timeout}s)\n{_tail(exc.stdout, exc.stderr, drop=drop)}")
        output = _tail(proc.stdout, proc.stderr, drop=drop)
        if proc.returncode != EXIT_OK:
            message = failure_message or "the QML scenario failed"
            pytest.fail(f"{message}\n{output}")
        return output
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)
