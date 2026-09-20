"""Startup resilience of the config write-backs and the ownership store.

The first-run write-backs survive an unwritable config, a broken ownership file
still lets the launch through, and a real alter failure still raises.
"""

from __future__ import annotations

import inspect
import os
import sqlite3

import pytest

from waves.desktop.backend import WavesBridge
from waves.library.ownership import OwnershipStore


# --------------------------------------------------------------------------- #
# three shapes in __init__ that must not kill the launch
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "method",
    ["_apply_first_run_defaults", "_migrate_video_template"],
)
def test_the_first_run_write_backs_survive_an_unwritable_config(method):
    """config.py wraps its own two write-backs in try/except OSError because an
    unwritable config folder inside the constructor is a launch with no window.
    These two run from the same constructor and must do the same."""
    source = inspect.getsource(
        WavesBridge.__init__ if method == "_migrate_video_template" else getattr(WavesBridge, method)
    )
    # The save the method performs must be inside a try that names OSError.
    assert "self.settings.save()" in source
    assert "except OSError" in source, f"{method}'s save can still take the launch down"


def test_a_broken_ownership_file_does_not_take_the_launch_with_it(tmp_path, monkeypatch):
    """The store is constructed unguarded in __init__. A config folder that has
    gone read-only, a corrupt file, or a migration losing a race it cannot
    resolve would be a traceback and no window; an in-memory store forgets what
    has been downloaded until the next launch, and that is all."""
    source = inspect.getsource(WavesBridge.__init__)
    marker = "self._ownership = OwnershipStore(_own_file)"
    assert marker in source, "the guarded construction is gone"
    head = source.split(marker)[0]
    assert head.rstrip().endswith("try:"), "the store is constructed outside a try again"
    assert 'OwnershipStore(":memory:")' in source.split(marker)[1], "no stand-in when it raises"


# --------------------------------------------------------------------------- #
# the duplicate-column race must not be judged by its message text
# --------------------------------------------------------------------------- #
class _RacingConn:
    """The losing copy's view of the first launch after an upgrade.

    Its FIRST column-list read happens before the other copy's ALTER lands, so
    every added column reads as missing; by the time it runs its own ALTER the
    winner holds the write lock, and sqlite answers "database is locked"
    instead of "duplicate column name". A later read then sees the columns.

    sqlite3.Connection.execute is read-only, so the connection itself is what
    gets swapped, never one of its methods.
    """

    def __init__(self, conn, *, winner_lands: bool):
        self._conn = conn
        self._winner_lands = winner_lands
        self.info_reads = 0
        self.alters = 0

    def execute(self, sql, *a, **k):
        head = sql.strip().upper()
        if head.startswith("PRAGMA TABLE_INFO"):
            self.info_reads += 1
            if self.info_reads == 1 or not self._winner_lands:
                return []  # the stale read that starts the race
            return self._conn.execute(sql, *a, **k)
        if head.startswith("ALTER TABLE"):
            self.alters += 1
            raise sqlite3.OperationalError("database is locked")
        return self._conn.execute(sql, *a, **k)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def test_a_locked_database_does_not_re_raise_when_the_column_arrived(tmp_path):
    """Two copies of Waves opening the store on the first launch after an
    upgrade both read the column list before either alters. sqlite answers the
    loser with "duplicate column name" USUALLY, and with "database is locked"
    once its busy timeout is exceeded, which carries no column name at all.
    Matching the text would re-raise precisely the loser this handles, under
    load, at startup. The file is the only witness that settles it."""
    store = OwnershipStore(str(tmp_path / "own.sqlite3"))
    real = store._conn
    guard = _RacingConn(real, winner_lands=True)
    store._conn = guard

    store._ensure_columns()  # the loser must live: the columns are all there

    assert guard.alters, "the race never reached the ALTER, so nothing was tested"
    store._conn = real
    store.close()


def test_a_real_alter_failure_still_raises(tmp_path):
    """The other direction: when the column is genuinely NOT there, an
    OperationalError is a real failure and must not be swallowed."""
    store = OwnershipStore(str(tmp_path / "own.sqlite3"))
    real = store._conn
    store._conn = _RacingConn(real, winner_lands=False)

    with pytest.raises(sqlite3.OperationalError):
        store._ensure_columns()

    store._conn = real
    store.close()


def test_the_store_still_opens_a_real_file(tmp_path):
    """The guards above must not have made a working store optional."""
    path = tmp_path / "own.sqlite3"
    store = OwnershipStore(str(path))
    store.record("t1", str(tmp_path / "a.flac"), "LOSSLESS")
    store.close()

    assert os.path.isfile(path)
