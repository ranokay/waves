"""The self-quit seam needs both markers, never the delay alone.

``WAVES_QUIT_AFTER_BOOT_MS`` inherited from a wrapper script or a stale
export must not quit a normal launch; only the cold-boot test sets
``WAVES_TEST_SEAM=1`` alongside it.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from waves.desktop import app as waves_app


def _quit(monkeypatch, seam: str | None, delay: str | None) -> int:
    if seam is None:
        monkeypatch.delenv("WAVES_TEST_SEAM", raising=False)
    else:
        monkeypatch.setenv("WAVES_TEST_SEAM", seam)
    if delay is None:
        monkeypatch.delenv("WAVES_QUIT_AFTER_BOOT_MS", raising=False)
    else:
        monkeypatch.setenv("WAVES_QUIT_AFTER_BOOT_MS", delay)
    with patch.object(waves_app.QTimer, "singleShot") as quit_after:
        waves_app._install_test_quit(MagicMock())
        return quit_after.call_count


def test_delay_alone_never_quits(monkeypatch):
    assert _quit(monkeypatch, None, "3000") == 0


def test_both_markers_arm_the_quit(monkeypatch):
    assert _quit(monkeypatch, "1", "3000") == 1
