"""Realtime logs console (issue #68): tail helper plus the copy/tail slots.

The tail is bounded both ways (line count and bytes) so a runaway log file
cannot stall the GUI thread that polls it; a missing log reads as "".
"""

from __future__ import annotations

from types import SimpleNamespace

from waves.waves_ui import diagnostics
from waves.waves_ui.backend import WavesBridge


def _write_log(tmp_path, lines: list[str]) -> None:
    (tmp_path / diagnostics.LOG_FILENAME).write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_tail_returns_the_last_n_lines(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostics, "_log_dir", tmp_path)
    _write_log(tmp_path, [f"line {i}" for i in range(10)])

    assert diagnostics.log_tail(3).splitlines() == ["line 7", "line 8", "line 9"]
    assert diagnostics.log_tail(500).splitlines() == [f"line {i}" for i in range(10)]


def test_missing_log_reads_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostics, "_log_dir", tmp_path)

    assert diagnostics.log_tail() == ""


def test_no_log_dir_reads_empty(monkeypatch):
    monkeypatch.setattr(diagnostics, "_log_dir", None)

    assert diagnostics.log_tail() == ""


def test_tail_is_byte_capped(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostics, "_log_dir", tmp_path)
    _write_log(tmp_path, ["x" * 1000 for _ in range(3000)])

    out = diagnostics.log_tail(max_lines=2000, max_bytes=262144)
    assert len(out.encode("utf-8")) <= 262144 + 4096
    assert len(out.splitlines()) <= 2000


def test_bad_arguments_fall_back_to_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostics, "_log_dir", tmp_path)
    _write_log(tmp_path, ["only"])

    assert diagnostics.log_tail("abc", "def") == "only"


def _slot_stub(**over):
    stub = SimpleNamespace(_set_status=lambda *a: None)
    for key, value in over.items():
        setattr(stub, key, value)
    return stub


def test_log_tail_slot_passes_the_tail_through(monkeypatch):
    stub = _slot_stub()
    stub.logTail = WavesBridge.logTail.__get__(stub)
    monkeypatch.setattr(diagnostics, "log_tail", lambda max_lines=500: f"tail:{max_lines}")

    assert stub.logTail(500) == "tail:500"


def test_log_tail_slot_never_raises(monkeypatch):
    stub = _slot_stub()
    stub.logTail = WavesBridge.logTail.__get__(stub)

    def _boom(max_lines=500):
        raise OSError("disk gone")

    monkeypatch.setattr(diagnostics, "log_tail", _boom)

    assert stub.logTail(500) == ""


def test_copy_logs_copies_the_tail(monkeypatch):
    seen: dict = {}
    statuses: list = []

    class _Clipboard:
        def setText(self, text):
            seen["text"] = text

    class _App:
        @staticmethod
        def clipboard():
            return _Clipboard()

    import waves.waves_ui.backend as backend_mod

    monkeypatch.setattr(backend_mod.QtGui, "QGuiApplication", _App)
    monkeypatch.setattr(diagnostics, "log_tail", lambda max_lines=500: "line-a\nline-b")
    stub = _slot_stub()
    stub._set_status = statuses.append
    stub.copyLogs = WavesBridge.copyLogs.__get__(stub)

    stub.copyLogs()

    assert seen["text"] == "line-a\nline-b"
    assert statuses == ["Logs copied"]


def test_copy_logs_reports_a_dead_clipboard(monkeypatch):
    statuses: list = []

    class _App:
        @staticmethod
        def clipboard():
            raise RuntimeError("no app")

    import waves.waves_ui.backend as backend_mod

    monkeypatch.setattr(backend_mod.QtGui, "QGuiApplication", _App)
    stub = _slot_stub()
    stub._set_status = statuses.append
    stub.copyLogs = WavesBridge.copyLogs.__get__(stub)

    stub.copyLogs()

    assert statuses == ["Could not copy the logs"]
