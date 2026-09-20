"""Factory reset wiping exported diagnostic bundles.

The reset takes the timestamped diagnostic exports with it, and its name
pattern can never match a file the user put beside them.
"""

from __future__ import annotations

import pathlib
from types import SimpleNamespace
from unittest.mock import MagicMock

from waves.desktop.backend import WavesBridge

# ---- factory reset erases exported diagnostic bundles ----------------------


def test_factory_reset_wipes_diagnostic_bundles(tmp_path: pathlib.Path, monkeypatch) -> None:
    bundle = tmp_path / "waves-diagnostics-20260802-121314-123.txt"
    bundle.write_text("scrubbed diagnostics", encoding="utf-8")
    foreign = tmp_path / "waves-diagnostics-notes.txt"
    foreign.write_text("the user's own notes", encoding="utf-8")

    stub = SimpleNamespace(_ownership=SimpleNamespace(close=lambda: None))
    monkeypatch.setattr("waves.desktop.backend.path_config_base", lambda: str(tmp_path))
    monkeypatch.setattr("waves.desktop.backend.OwnershipStore", lambda _p: SimpleNamespace())
    monkeypatch.setattr("waves.desktop.backend.diagnostics.detach_disk_log", lambda: None)
    monkeypatch.setattr("waves.desktop.backend.QtCore.QSettings", lambda: MagicMock())
    WavesBridge.factoryReset(stub)

    assert not bundle.exists(), "the export contains breadcrumbs and must go with the reset"
    assert foreign.exists(), "only the exact timestamped shape may match"


def test_factory_reset_pattern_cannot_match_a_user_file() -> None:
    from waves.desktop.backend import _FACTORY_WIPE_LOG_PATTERNS

    def one_pattern_matches(name: str) -> bool:
        return any(pat.match(name) for pat in _FACTORY_WIPE_LOG_PATTERNS)

    assert one_pattern_matches("waves-diagnostics-20260802-121314-123.txt")
    # The per-root library caches (see cache_file_for_root) and their sidecars.
    assert one_pattern_matches("library-0123456789ab.sqlite3")
    assert one_pattern_matches("library-0123456789ab.sqlite3-wal")
    assert one_pattern_matches("library-0123456789ab.sqlite3-shm")
    for name in (
        "waves-diagnostics-20260802-121314-123.txt.bak",
        "my-waves-diagnostics-20260802-121314-123.txt",
        "waves-diagnostics-2026-08-02.txt",
        "waves-diagnostics-.txt",
        # A name a user could plausibly have put beside ours must never match:
        # no digest, wrong digest length, uppercase (ours are hexdigest lower),
        # a prefix or suffix, or a non-sqlite extension.
        "library.sqlite3.bak",
        "library-mymusic.sqlite3",
        "library-0123456789ab.sqlite3.bak",
        "library-0123456789AB.sqlite3",
        "library-0123456789abcd.sqlite3",
        "my-library-0123456789ab.sqlite3",
        "library-0123456789ab.txt",
    ):
        assert not one_pattern_matches(name), name
