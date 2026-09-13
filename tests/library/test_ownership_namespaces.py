"""Ownership rows are namespaced (§4.2 of the provider spec): every row is
stored as ``tidal:123`` / ``apple:456``, never bare, so a second provider's
catalog can share the numeric id space without the two owners' answers
bleeding into each other -- owning on TIDAL never satisfies another
provider's gate.

The store owns the convention end to end:

- a bare id in, whether recorded or asked, reads as tidal -- the spelling
  every pre-namespace caller uses, so a TIDAL-only library's every existing
  query keeps its answer;
- an existing database's bare rows are backfilled to ``tidal:`` on open,
  one row each, none lost, none duplicated;
- a namespaced id is taken literally, and only a row of the SAME provider
  can answer it.
"""

from __future__ import annotations

import sqlite3

from waves.ownership import OwnershipStore


def _store(tmp_path):
    return OwnershipStore(str(tmp_path / "ownership.sqlite3"))


def _track_file(tmp_path, name):
    p = tmp_path / name
    p.write_text("audio")
    return str(p)


def _rows(tmp_path):
    con = sqlite3.connect(str(tmp_path / "ownership.sqlite3"))
    rows = con.execute("SELECT track_id, path FROM downloads ORDER BY track_id").fetchall()
    con.close()
    return rows


# --------------------------------------------------------------------------- #
# The store's own spelling: bare in, namespaced on the row
# --------------------------------------------------------------------------- #
def test_a_bare_record_is_stored_namespaced(tmp_path):
    store = _store(tmp_path)
    path = _track_file(tmp_path, "song.flac")
    store.record("123", path, "LOSSLESS")
    assert _rows(tmp_path) == [("tidal:123", path)]


def test_a_bare_query_reads_as_tidal(tmp_path):
    """Every pre-namespace caller (the engine gates, the queue rollup, QML row
    ids) asks bare. The bare spelling is tidal's, so the answer must not move."""
    store = _store(tmp_path)
    path = _track_file(tmp_path, "song.flac")
    store.record("123", path, "LOSSLESS")
    assert store.ownership_of("123") is not None


def test_a_namespaced_query_names_the_same_row(tmp_path):
    store = _store(tmp_path)
    path = _track_file(tmp_path, "song.flac")
    store.record("123", path, "LOSSLESS")
    assert store.ownership_of("tidal:123")["path"] == path


def test_recording_both_spellings_of_one_id_upserts_one_row(tmp_path):
    """The same copy recorded bare by an old caller and namespaced by a new one
    is one copy: the (track_id, path) key must coalesce, not duplicate."""
    store = _store(tmp_path)
    path = _track_file(tmp_path, "song.flac")
    store.record("123", path, "HIGH")
    store.record("tidal:123", path, "LOSSLESS")
    assert _rows(tmp_path) == [("tidal:123", path)]
    assert store.ownership_of("123")["quality_tier"] == "LOSSLESS"


def test_a_degraded_count_survives_the_namespaced_key(tmp_path):
    """record()'s read-back (the caller's retry counter) must ask for the row
    under the spelling it was actually stored under."""
    store = _store(tmp_path)
    path = _track_file(tmp_path, "song.flac")
    assert store.record("123", path, "HIGH", ceiling_rank=2, requested_rank=0, degraded=True) == 1
    assert store.record("123", path, "HIGH", ceiling_rank=2, requested_rank=0, degraded=True) == 2


# --------------------------------------------------------------------------- #
# Provider scoping: the reason the namespace exists
# --------------------------------------------------------------------------- #
def test_owning_on_tidal_never_answers_another_provider(tmp_path):
    store = _store(tmp_path)
    path = _track_file(tmp_path, "song.flac")
    store.record("123", path, "LOSSLESS")
    assert store.ownership_of("tidal:123") is not None
    assert store.ownership_of("apple:123") is None


def test_a_foreign_row_answers_only_its_own_provider(tmp_path):
    store = _store(tmp_path)
    apple = _track_file(tmp_path, "apple.m4a")
    store.record("apple:456", apple, "LOSSLESS")
    assert store.ownership_of("apple:456")["path"] == apple
    # Bare reads as tidal, never as "whatever provider the row happens to be".
    assert store.ownership_of("456") is None


# --------------------------------------------------------------------------- #
# The backfill: an existing database's bare rows become tidal:
# --------------------------------------------------------------------------- #
def _legacy_database(tmp_path, rows):
    """A database shaped like an older build left it: the store's schema, bare
    ids. The store itself creates the schema, so the DDL never drifts from it."""
    seed = _store(tmp_path)
    seed.close()
    con = sqlite3.connect(str(tmp_path / "ownership.sqlite3"))
    con.executemany("INSERT INTO downloads (track_id, path) VALUES (?, ?)", rows)
    con.commit()
    con.close()


def test_backfill_maps_bare_ids_to_tidal(tmp_path):
    path_a = _track_file(tmp_path, "a.flac")
    path_b = _track_file(tmp_path, "b.flac")
    _legacy_database(tmp_path, [("123", path_a), ("456", path_b)])

    store = _store(tmp_path)

    assert _rows(tmp_path) == [("tidal:123", path_a), ("tidal:456", path_b)]
    assert store.ownership_of("123")["path"] == path_a
    assert store.ownership_of("456")["path"] == path_b


def test_backfill_loses_no_rows(tmp_path):
    """A whole legacy library at once: every bare row survives, 1:1."""
    rows = [(str(i), _track_file(tmp_path, f"s{i}.flac")) for i in range(25)]
    _legacy_database(tmp_path, rows)

    _store(tmp_path)

    assert len(_rows(tmp_path)) == len(rows)


def test_backfill_is_a_no_op_on_an_already_namespaced_database(tmp_path):
    path = _track_file(tmp_path, "song.flac")
    store = _store(tmp_path)
    store.record("123", path, "LOSSLESS")
    store.close()

    reopened = _store(tmp_path)

    assert _rows(tmp_path) == [("tidal:123", path)]
    assert reopened.ownership_of("tidal:123") is not None


def test_backfill_does_not_crash_on_a_bare_row_with_a_namespaced_twin(tmp_path):
    """A library that went back to an older Waves and returned has both
    spellings of one copy on one path. The PRIMARY KEY cannot hold both under
    one spelling: the bare row is the store's own re-record of that copy (the
    same upsert rule record() lives by), so it replaces the twin and the copy
    stays owned -- no constraint error at startup, no row written twice."""
    path = _track_file(tmp_path, "song.flac")
    _legacy_database(tmp_path, [("123", path), ("tidal:123", path)])

    store = _store(tmp_path)

    assert _rows(tmp_path) == [("tidal:123", path)]
    assert store.ownership_of("123") is not None


def test_backfill_leaves_an_empty_id_alone(tmp_path):
    """A row with no id at all (an event without one, from an old build) is
    junk, not a tidal row: prefixing it would launder it into a malformed
    "tidal:" id. It stays as written, matching nothing but itself."""
    path = _track_file(tmp_path, "song.flac")
    _legacy_database(tmp_path, [("", path)])

    store = _store(tmp_path)

    assert _rows(tmp_path) == [("", path)]
    assert store.ownership_of("123") is None
    assert store.ownership_of("tidal:") is None
