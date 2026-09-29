"""The verbose stall monitor names a native stack while the GUI loop is stuck.

The faulthandler dump proves the loop stopped, not what stopped it: a block
inside Qt/QML leaves the Python stack at ``app.exec()`` and nothing under it,
which is exactly the crash.log record the 7.5 s freeze left behind. The stall
monitor closes that gap: a thread watches the GUI heartbeat and, while the
loop is still stuck, runs macOS's ``sample`` on this process.

Pure unit tests of the decision and the command line: no Qt, no real sampler.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
import types
from pathlib import Path

from waves.desktop import diagnostics


def _armed(tmp_path: Path, monkeypatch) -> diagnostics._StallMonitor:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/sample")
    monitor = diagnostics._StallMonitor()
    monitor.start(tmp_path, 2.5)
    return monitor


def _fake_run(runs: list[list[str]], *, fail: Exception | None = None):
    def run(argv, **_kwargs):
        runs.append(argv)
        if fail is not None:
            raise fail
        Path(argv[argv.index("-file") + 1]).write_text("native stacks")
        return types.SimpleNamespace(returncode=0)

    return run


def test_start_is_a_noop_without_darwin_or_sample(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/sample")
    monitor = diagnostics._StallMonitor()
    monitor.start(tmp_path, 2.5)
    assert monitor._thread is None, "non-macOS must not start the sampler thread"

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(shutil, "which", lambda name: None)
    monitor.start(tmp_path, 2.5)
    assert monitor._thread is None, "a missing `sample` must not start the thread"


def test_due_only_after_the_warn_gap(tmp_path, monkeypatch):
    monitor = _armed(tmp_path, monkeypatch)
    try:
        monitor.heartbeat(100.0)
        assert not monitor._due(102.0, monitor._stop), "below the warn gap is not a stall"
        assert monitor._due(102.6, monitor._stop), "past the warn gap is a stall"
    finally:
        monitor.stop()


def test_capture_runs_sample_and_files_the_stack(tmp_path, monkeypatch, caplog):
    monitor = _armed(tmp_path, monkeypatch)
    try:
        runs: list[list[str]] = []
        monkeypatch.setattr(diagnostics.subprocess, "run", _fake_run(runs))
        with caplog.at_level(logging.WARNING, logger="waves.diag"):
            monitor._capture(monitor._stop)

        assert len(runs) == 1
        argv = runs[0]
        assert argv[:2] == ["/usr/bin/sample", str(os.getpid())]
        written = Path(argv[argv.index("-file") + 1])
        assert written.parent == tmp_path
        assert written.name.startswith("freeze-") and written.name.endswith(".sample.txt")
        assert "[freeze] native stack captured" in caplog.text
    finally:
        monitor.stop()


def test_a_failed_capture_is_a_noop(tmp_path, monkeypatch, caplog):
    monitor = _armed(tmp_path, monkeypatch)
    try:
        runs: list[list[str]] = []
        monkeypatch.setattr(diagnostics.subprocess, "run", _fake_run(runs, fail=FileNotFoundError("no sample")))
        with caplog.at_level(logging.WARNING, logger="waves.diag"):
            monitor._capture(monitor._stop)  # must not raise
        assert "[freeze] native stack capture failed" in caplog.text
    finally:
        monitor.stop()


def test_the_session_budget_caps_captures(tmp_path, monkeypatch):
    monitor = _armed(tmp_path, monkeypatch)
    try:
        runs: list[list[str]] = []
        monkeypatch.setattr(diagnostics.subprocess, "run", _fake_run(runs))
        for _ in range(diagnostics._STALL_SAMPLE_MAX_PER_SESSION):
            monitor._capture(monitor._stop)
        assert len(runs) == diagnostics._STALL_SAMPLE_MAX_PER_SESSION
        monitor.heartbeat(100.0)
        assert not monitor._due(10_000.0, monitor._stop), "the capture budget must end the session's captures"
    finally:
        monitor.stop()


def test_stop_disarms(tmp_path, monkeypatch):
    monitor = _armed(tmp_path, monkeypatch)
    monitor.heartbeat(100.0)
    monitor.stop()
    assert not monitor._due(10_000.0, monitor._stop), "a stopped monitor must never capture"


def test_a_restart_retires_the_previous_run(tmp_path, monkeypatch):
    monitor = _armed(tmp_path, monkeypatch)
    first_stop = monitor._stop
    monitor.stop()
    monitor.start(tmp_path, 2.5)
    try:
        assert first_stop.is_set(), "a restart must not clear the retired run's stop event"
        assert monitor._stop is not first_stop, "each run needs its own stop event"
    finally:
        monitor.stop()


def test_the_export_carries_the_native_sample_scrubbed(tmp_path, monkeypatch):
    """The one artifact that names a native stall must reach the shared export."""
    monkeypatch.setattr(diagnostics, "_log_dir", tmp_path)
    sample = tmp_path / "freeze-20260101-000000-000.sample.txt"
    sample.write_text("Call graph:\n+ 1 start (in dyld)\n  /Users/testuser/Music/Album/01 track.flac\n")

    out = diagnostics.export_bundle()

    body = Path(out).read_text(encoding="utf-8")
    assert "NATIVE STALL SAMPLE (freeze-20260101-000000-000.sample.txt)" in body
    assert "testuser" not in body, "the sample's home paths must be scrubbed like every other section"
    assert "Call graph:" in body
