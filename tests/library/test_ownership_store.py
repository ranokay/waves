"""Tests for the download-ownership store (waves/library/ownership.py).

Pure standard library, no PySide6, so these run in the lint venv like the other
engine-level tests. The store's whole point is that ownership is decided against
the live filesystem, so every test writes and deletes real files under tmp_path.
"""

from __future__ import annotations

import os
import sqlite3
import threading

import pytest

from waves.library.ownership import OwnershipStore, quality_rank


def _store(tmp_path):
    return OwnershipStore(str(tmp_path / "ownership.sqlite3"))


def _track_file(tmp_path, name):
    p = tmp_path / name
    p.write_text("audio")
    return str(p)


def _on_fresh_thread(fn):
    """Run ``fn`` on a new thread (so it opens its own reader) and return its
    result, or the exception it raised."""
    out = {}

    def run():
        try:
            out["r"] = fn()
        except Exception as e:
            out["r"] = e

    t = threading.Thread(target=run)
    t.start()
    t.join(10)
    assert not t.is_alive(), "the fresh thread never finished"
    return out["r"]


def _replace_store(path):
    """Swap the store file for an empty one, as a sync client or a restore can."""
    os.remove(path)
    open(path, "wb").close()


@pytest.mark.parametrize(
    "tier,rank",
    [("LOW", 0), ("HIGH", 1), ("LOSSLESS", 2), ("HI_RES_LOSSLESS", 3), ("lossless", 2), (None, -1), ("bogus", -1)],
)
def test_quality_rank(tier, rank):
    assert quality_rank(tier) == rank


def test_record_then_owned(tmp_path):
    store = _store(tmp_path)
    path = _track_file(tmp_path, "song.flac")
    store.record("123", path, "LOSSLESS")
    info = store.ownership_of("123")
    assert info is not None
    assert info["owned"] is True
    assert info["path"] == path
    assert info["quality_tier"] == "LOSSLESS"
    assert info["quality_rank"] == 2


def test_unrecorded_is_not_owned(tmp_path):
    store = _store(tmp_path)
    assert store.ownership_of("nope") is None


def test_deleted_file_self_heals(tmp_path):
    store = _store(tmp_path)
    path = _track_file(tmp_path, "song.flac")
    store.record("123", path, "LOSSLESS")
    assert store.ownership_of("123") is not None
    # The user deletes the file: ownership must fall back to "not owned" without
    # any history clearing, so a re-download is offered.
    (tmp_path / "song.flac").unlink()
    assert store.ownership_of("123") is None
    # Re-create it: the same recorded row makes it owned again, no re-record.
    _track_file(tmp_path, "song.flac")
    assert store.ownership_of("123") is not None


def test_batch_answers_match_the_single_answer_for_a_version_filter(tmp_path):
    """A row carrying only the audio_type column (no audio_mode) answers the
    same through the batch query as through the single one, filtered or not;
    the batch must not omit the column and fall back to the legacy mode."""
    store = _store(tmp_path)
    atmos = _track_file(tmp_path, "song.m4a")
    stereo = _track_file(tmp_path, "song.flac")
    store.record("123", atmos, "LOW", audio_type="atmos")
    store.record("456", stereo, "LOSSLESS", audio_type="stereo")

    for tid, want in (("123", "atmos"), ("123", "stereo"), ("456", "stereo"), ("456", "atmos")):
        assert store.ownership_of_many([tid], audio_type=want)[tid] == store.ownership_of(tid, audio_type=want)
    assert store.ownership_of_many(["123", "456"]) == {
        "123": store.ownership_of("123"),
        "456": store.ownership_of("456"),
    }
    assert store.ownership_of_many(["123"], audio_type="atmos")["123"]["audio_type"] == "atmos"
    assert store.ownership_of_many(["456"], audio_type="stereo")["456"]["audio_type"] == "stereo"
    # Each filter refuses the other Version's copy.
    assert store.ownership_of("123", audio_type="stereo") is None
    assert store.ownership_of_many(["123"], audio_type="stereo")["123"] is None
    assert store.ownership_of_many(["456"], audio_type="atmos")["456"] is None


def test_best_surviving_quality_wins(tmp_path):
    store = _store(tmp_path)
    low = _track_file(tmp_path, "song.m4a")
    hi = _track_file(tmp_path, "song.flac")
    store.record("123", low, "HIGH")
    store.record("123", hi, "HI_RES_LOSSLESS")
    info = store.ownership_of("123")
    assert info["path"] == hi
    assert info["quality_tier"] == "HI_RES_LOSSLESS"


def test_falls_back_to_lower_quality_when_better_copy_is_gone(tmp_path):
    store = _store(tmp_path)
    low = _track_file(tmp_path, "song.m4a")
    hi = _track_file(tmp_path, "song.flac")
    store.record("123", low, "HIGH")
    store.record("123", hi, "HI_RES_LOSSLESS")
    (tmp_path / "song.flac").unlink()  # lose the hi-res copy
    info = store.ownership_of("123")
    assert info["path"] == low
    assert info["quality_tier"] == "HIGH"


def test_upsert_same_path_updates_in_place(tmp_path):
    store = _store(tmp_path)
    path = _track_file(tmp_path, "song.flac")
    store.record("123", path, "HIGH")
    store.record("123", path, "HI_RES_LOSSLESS")  # re-download to the same path
    con = sqlite3.connect(str(tmp_path / "ownership.sqlite3"))
    # Rows are stored namespaced (§4.2): the bare id the caller passed reads as tidal.
    (count,) = con.execute("SELECT COUNT(*) FROM downloads WHERE track_id='tidal:123'").fetchone()
    con.close()
    assert count == 1, "same (track_id, path) must update, not append"
    assert store.ownership_of("123")["quality_tier"] == "HI_RES_LOSSLESS"


def test_different_paths_append_rows(tmp_path):
    store = _store(tmp_path)
    a = _track_file(tmp_path, "a.flac")
    b = _track_file(tmp_path, "b.flac")
    store.record("123", a, "LOSSLESS")
    store.record("123", b, "LOSSLESS")
    con = sqlite3.connect(str(tmp_path / "ownership.sqlite3"))
    (count,) = con.execute("SELECT COUNT(*) FROM downloads WHERE track_id='tidal:123'").fetchone()
    con.close()
    assert count == 2


def test_user_id_scoping_is_optional(tmp_path):
    store = _store(tmp_path)
    path = _track_file(tmp_path, "song.flac")
    store.record("123", path, "LOSSLESS", user_id="userA")
    # Default (no filter) sees it; a matching user sees it; a different user does not.
    assert store.ownership_of("123") is not None
    assert store.ownership_of("123", user_id="userA") is not None
    assert store.ownership_of("123", user_id="userB") is None


def test_reopening_existing_db_is_safe(tmp_path):
    path = _track_file(tmp_path, "song.flac")
    store = _store(tmp_path)
    store.record("123", path, "LOSSLESS")
    store.close()
    # Re-running CREATE TABLE / ensure-columns against the populated DB must be a
    # no-op, and the data must survive.
    store2 = _store(tmp_path)
    assert store2.ownership_of("123") is not None
    store2.close()


def test_optional_metadata_columns_round_trip(tmp_path):
    store = _store(tmp_path)
    path = _track_file(tmp_path, "song.flac")
    store.record("123", path, "HI_RES_LOSSLESS", audio_mode="STEREO", bit_depth=24, sample_rate=96000, codecs="FLAC")
    info = store.ownership_of("123")
    assert info["audio_mode"] == "STEREO"
    assert info["bit_depth"] == 24
    assert info["sample_rate"] == 96000
    assert info["codecs"] == "FLAC"


def test_a_re_record_without_the_delivered_columns_keeps_them(tmp_path):
    """A later record of the same (id, path) without the audio columns must not
    null the copy's Version: the Atmos/stereo fact is what the per-Version
    ownership gate answers from."""
    store = _store(tmp_path)
    path = _track_file(tmp_path, "song.flac")
    store.record("123", path, "HI_RES_LOSSLESS", audio_type="atmos", audio_mode="DOLBY_ATMOS")
    store.record("123", path, "HI_RES_LOSSLESS")
    info = store.ownership_of("123")
    assert info["audio_type"] == "atmos"
    assert info["audio_mode"] == "DOLBY_ATMOS"


def test_concurrent_records_all_land(tmp_path):
    store = _store(tmp_path)
    files = [_track_file(tmp_path, f"song{i}.flac") for i in range(40)]

    def worker(i):
        store.record(str(i), files[i], "LOSSLESS")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for i in range(40):
        assert store.ownership_of(str(i)) is not None


# --------------------------------------------------------------------------- #
# Collection membership: which track ids make up an album/playlist/mix,
# learned locally so a later "is this fully owned" question elsewhere in the
# app never needs to re-fetch from TIDAL.
# --------------------------------------------------------------------------- #
def test_unknown_collection_is_none_not_empty(tmp_path):
    store = _store(tmp_path)
    assert store.members_of("album1") is None


def test_replace_then_members_of(tmp_path):
    store = _store(tmp_path)
    store.record_members_replace("album1", ["10", "11", "12"])
    assert sorted(store.members_of("album1")) == ["10", "11", "12"]


def test_replace_overwrites_previous_membership(tmp_path):
    store = _store(tmp_path)
    store.record_members_replace("pl1", ["1", "2", "3"])
    store.record_members_replace("pl1", ["1", "2"])  # a track was removed from the playlist
    assert sorted(store.members_of("pl1")) == ["1", "2"]


def test_add_is_additive_not_a_replace(tmp_path):
    store = _store(tmp_path)
    store.record_members_add("album1", ["1"])
    store.record_members_add("album1", ["2"])
    assert sorted(store.members_of("album1")) == ["1", "2"]


def test_add_ignores_duplicates(tmp_path):
    store = _store(tmp_path)
    store.record_members_add("album1", ["1", "1", "2"])
    store.record_members_add("album1", ["2"])
    assert sorted(store.members_of("album1")) == ["1", "2"]


def test_empty_track_list_replace_reads_back_as_unknown(tmp_path):
    # An edge case (a genuinely empty collection) collapses to "unknown" rather
    # than a real distinct state; documented as an accepted, low-consequence
    # simplification (an empty collection has nothing to badge anyway).
    store = _store(tmp_path)
    store.record_members_replace("empty1", [])
    assert store.members_of("empty1") is None


def test_membership_is_scoped_per_collection(tmp_path):
    store = _store(tmp_path)
    store.record_members_replace("album1", ["1", "2"])
    store.record_members_replace("album2", ["3", "4"])
    assert sorted(store.members_of("album1")) == ["1", "2"]
    assert sorted(store.members_of("album2")) == ["3", "4"]


def test_add_falsy_ids_are_skipped(tmp_path):
    store = _store(tmp_path)
    store.record_members_add("album1", ["1", "", None])
    assert store.members_of("album1") == ["1"]


# --------------------------------------------------------------------------- #
# A read outlives the store file being removed, replaced or corrupted under
# it: a reader opens only an existing file (read-write URI, no create), and a
# reader that cannot use the file falls back to the connection every write
# goes to.
# --------------------------------------------------------------------------- #
def test_cold_reader_works_under_an_awkward_folder_name(tmp_path, caplog):
    """The per-thread reader opens the file by URI, so a space or a '#' in the
    config folder's path must not push it onto the fallback."""
    folder = tmp_path / "Waves site #1"
    folder.mkdir()
    store = OwnershipStore(str(folder / "ownership.sqlite3"))
    store.record_members_replace("album1", ["1", "2"])

    def answer():
        got = store.members_of("album1")
        return got, getattr(store._readers, "reader", None) is not None

    with caplog.at_level("WARNING", logger="waves.ownership"):
        got, had_reader = _on_fresh_thread(answer)
    assert sorted(got) == ["1", "2"]
    assert had_reader is True, "the fresh thread fell back instead of opening its own reader"
    assert "shared connection" not in caplog.text
    assert store._shared_reads is False


@pytest.mark.skipif(os.name == "nt", reason="Windows refuses to remove a file sqlite holds open")
def test_cold_reader_survives_the_file_being_replaced(tmp_path):
    """The file swapped for an empty one while the app runs: a thread whose
    first read comes after that still reads what the store was opened on, the
    file every write still goes to."""
    path = tmp_path / "ownership.sqlite3"
    store = OwnershipStore(str(path))
    store.record_members_replace("album1", ["1", "2"])
    _replace_store(path)
    assert sorted(_on_fresh_thread(lambda: store.members_of("album1"))) == ["1", "2"]
    # And once one reader has failed, every thread reads the same way.
    assert sorted(_on_fresh_thread(lambda: store.members_of("album1"))) == ["1", "2"]
    assert sorted(store.members_of("album1")) == ["1", "2"]


@pytest.mark.skipif(os.name == "nt", reason="Windows refuses to remove a file sqlite holds open")
def test_cold_reader_never_creates_a_missing_file(tmp_path):
    """A reader opens only an existing file: a read cannot recreate the store."""
    path = tmp_path / "ownership.sqlite3"
    store = OwnershipStore(str(path))
    store.record_members_replace("album1", ["1"])
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(str(path) + suffix):
            os.remove(str(path) + suffix)
    assert _on_fresh_thread(lambda: store.members_of("album1")) == ["1"]
    assert not path.exists()


def test_members_of_reads_as_unknown_when_the_store_cannot_answer(tmp_path):
    """Broken under the shared connection too: members_of is called from a
    Slot, so it answers None ("never observed") instead of raising."""
    path = tmp_path / "ownership.sqlite3"
    store = OwnershipStore(str(path))
    store.record_members_replace("album1", ["1"])
    con = sqlite3.connect(str(path))
    con.execute("DROP TABLE collection_members")
    con.commit()
    con.close()
    assert store.members_of("album1") is None
    assert _on_fresh_thread(lambda: store.members_of("album1")) is None


def test_members_of_reads_as_unknown_when_the_file_is_corrupted_in_place(tmp_path):
    """Not every unanswerable store raises an OperationalError: a main file
    overwritten in place (a sync client, a restore) makes the shared connection
    raise DatabaseError "file is not a database". members_of still reads it as
    unknown, and the failed reader closes itself and leaves the thread-local."""
    path = tmp_path / "ownership.sqlite3"
    store = OwnershipStore(str(path))
    store.record_members_replace("album1", [str(i) for i in range(5000)])
    store._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    assert store.members_of("album1") is not None  # this thread's reader caches pages
    reader = store._readers.reader
    assert reader is not None, "the first read did not use a per-thread reader"

    data = path.read_bytes()
    path.write_bytes(b"\x00" * len(data))
    reader.conn.execute("PRAGMA shrink_memory")
    store._conn.execute("PRAGMA shrink_memory")

    assert store.members_of("album1") is None
    assert store._readers.reader is None, "a failed reader was kept in the thread-local"
    with pytest.raises(sqlite3.ProgrammingError):
        reader.conn.execute("SELECT 1")
    assert _on_fresh_thread(lambda: store.members_of("album1")) is None


def test_a_reader_falling_back_warns_once_per_store(tmp_path, caplog):
    """Four threads race the first read after a replacement: exactly one
    warning, whichever one gets there first."""
    path = tmp_path / "ownership.sqlite3"
    store = OwnershipStore(str(path))
    store.record_members_replace("album1", ["1"])
    _replace_store(path)

    start = threading.Barrier(4)
    results = []

    def read():
        start.wait(10)
        results.append(store.members_of("album1"))

    threads = [threading.Thread(target=read) for _ in range(4)]
    with caplog.at_level("WARNING", logger="waves.ownership"):
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
    assert len(results) == 4
    assert all(sorted(result) == ["1"] for result in results), results
    warnings = [rec for rec in caplog.records if "shared connection" in rec.getMessage()]
    assert len(warnings) == 1, [rec.getMessage() for rec in warnings]


def test_an_unanswerable_members_of_warns_once_per_store(tmp_path, caplog):
    path = tmp_path / "ownership.sqlite3"
    store = OwnershipStore(str(path))
    store.record_members_replace("album1", ["1"])
    con = sqlite3.connect(str(path))
    con.execute("DROP TABLE collection_members")
    con.commit()
    con.close()
    with caplog.at_level("WARNING", logger="waves.ownership"):
        assert store.members_of("album1") is None
        assert store.members_of("album1") is None
        assert _on_fresh_thread(lambda: store.members_of("album1")) is None
    failed = [rec for rec in caplog.records if "members_of could not read" in rec.getMessage()]
    assert len(failed) == 1, [rec.getMessage() for rec in failed]
    fallbacks = [rec for rec in caplog.records if "shared connection" in rec.getMessage()]
    assert len(fallbacks) == 1, [rec.getMessage() for rec in fallbacks]


@pytest.mark.skipif(os.name == "nt", reason="Windows refuses to remove a file sqlite holds open")
def test_writes_reach_both_reader_paths_and_survive_a_fall_back(tmp_path):
    """A reader opened BEFORE the replacement must not answer stale membership
    once the store has fallen back: the post-fallback write goes through the
    shared connection and every later read, on every thread, sees it."""
    path = tmp_path / "ownership.sqlite3"
    store = OwnershipStore(str(path))
    store.record_members_replace("album1", ["1"])

    parked = threading.Event()
    release = threading.Event()
    out: dict = {}

    def worker():
        out["before"] = store.members_of("album1")
        out["reader"] = getattr(store._readers, "reader", None)
        parked.set()
        release.wait(10)
        out["after"] = store.members_of("album1")

    t = threading.Thread(target=worker)
    t.start()
    assert parked.wait(10), "the pre-replacement reader never answered"
    try:
        assert out["before"] == ["1"]
        assert out["reader"] is not None, "the parked thread had no reader to test"

        _replace_store(path)
        assert sorted(_on_fresh_thread(lambda: store.members_of("album1"))) == ["1"]
        assert store._shared_reads is True, "the failed reader never fell back"

        # The write AFTER the fallback, not just before it.
        store.record_members_replace("album1", ["2"])
        assert store.members_of("album1") == ["2"]

        def answer_after_fall_back():
            got = store.members_of("album1")
            return got, getattr(store._readers, "reader", None)

        got, reader = _on_fresh_thread(answer_after_fall_back)
        assert got == ["2"]
        assert reader is None, "a fresh thread opened its own reader after the fallback"
    finally:
        release.set()
        t.join(10)
    assert out["after"] == ["2"], "the pre-replacement reader answered stale membership"


@pytest.mark.skipif(os.name == "nt", reason="Windows refuses to remove a file sqlite holds open")
def test_close_takes_a_reader_created_before_another_reader_fell_back(tmp_path):
    """The whole-file replacement makes one reader fail and hands every read to
    the shared connection, but a reader that was already open on the original
    file stays registered and must still be closed with the store."""
    path = tmp_path / "ownership.sqlite3"
    store = OwnershipStore(str(path))
    store.record_members_replace("album1", ["1"])

    parked = threading.Event()
    release = threading.Event()
    captured: dict = {}

    def reader():
        assert store.members_of("album1") == ["1"]
        captured["conn"] = store._readers.reader.conn
        parked.set()
        release.wait(10)

    t = threading.Thread(target=reader)
    t.start()
    assert parked.wait(10), "the pre-fallback reader never answered"
    try:
        _replace_store(path)
        assert sorted(_on_fresh_thread(lambda: store.members_of("album1"))) == ["1"]
        assert store._shared_reads is True

        store.close()
        with pytest.raises(sqlite3.ProgrammingError):
            captured["conn"].execute("SELECT 1")
    finally:
        release.set()
        t.join(10)


def test_an_in_memory_store_still_answers_membership():
    store = OwnershipStore(":memory:")
    store.record_members_replace("album1", ["1", "2"])
    assert sorted(store.members_of("album1")) == ["1", "2"]
    store.close()
    with pytest.raises(sqlite3.ProgrammingError):
        store._read("SELECT 1")


def test_a_read_after_close_still_raises_and_members_of_reads_as_unknown(tmp_path):
    """_read keeps sqlite's own closed error, and only members_of turns an
    unanswerable store into the unknown state its Slot callers render."""
    store = _store(tmp_path)
    store.record_members_replace("album1", ["1"])
    store.close()
    with pytest.raises(sqlite3.ProgrammingError):
        store._read("SELECT 1")
    assert store.members_of("album1") is None


def test_only_members_of_reads_a_broken_store_as_unknown(tmp_path):
    path = tmp_path / "ownership.sqlite3"
    store = OwnershipStore(str(path))
    audio = _track_file(tmp_path, "song.flac")
    store.record("123", audio, "LOSSLESS")
    store.record_members_replace("album1", ["1"])
    con = sqlite3.connect(str(path))
    con.execute("DROP TABLE downloads")
    con.commit()
    con.close()
    with pytest.raises(sqlite3.OperationalError):
        store.ownership_of("123")
    assert store.members_of("album1") == ["1"]


def test_folder_names_under_lists_the_artist_folders_it_wrote(tmp_path):
    """The seed list for a share whose directory listing is broken: these are
    the exact folder names Waves wrote, so they can be looked up by name even
    when the folder never appears in any listing."""
    store = _store(tmp_path)
    base = str(tmp_path / "music")
    for i, rel in enumerate(
        ("Doomcrusher/[2022] One/1.flac", "Doomcrusher/[2023] Two/1.flac", "Other/[2020] X/1.flac")
    ):
        path = os.path.join(base, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w").close()
        store.record(str(i), path, "LOSSLESS")
    assert sorted(store.folder_names_under(base)) == ["Doomcrusher", "Other"]


def test_folder_names_under_ignores_another_folders_downloads(tmp_path):
    """Switching library folders must never leak the old one's names."""
    store = _store(tmp_path)
    path = str(tmp_path / "elsewhere" / "Artist" / "[2020] Album" / "1.flac")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").close()
    store.record("1", path, "LOSSLESS")
    assert store.folder_names_under(str(tmp_path / "music")) == []
    assert store.folder_names_under("") == []


def test_folder_names_under_respects_its_limit(tmp_path):
    store = _store(tmp_path)
    base = str(tmp_path / "music")
    for i in range(8):
        path = os.path.join(base, f"Artist {i}", "Album", "1.flac")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w").close()
        store.record(str(i), path, "LOSSLESS")
    assert len(store.folder_names_under(base, limit=3)) == 3


def test_folder_names_under_uses_a_recorded_at_index(tmp_path):
    """folder_names_under sorts the append-forever table on every launch; the
    plan must use the recorded_at index, not a full scan plus sort."""
    store = _store(tmp_path)
    plan = store._conn.execute(
        "EXPLAIN QUERY PLAN SELECT path FROM downloads WHERE path IS NOT NULL ORDER BY recorded_at DESC"
    ).fetchall()
    assert any("idx_downloads_recorded" in str(row) for row in plan), f"full scan plus sort: {plan}"


# --------------------------------------------------------------------------- #
# The store lets go of its file
# --------------------------------------------------------------------------- #
def test_close_takes_every_thread_s_read_connection_not_just_its_own_from_the_ownership_store(tmp_path):
    """Reads run on a connection per thread, and the thread-local holding them
    only ever reaches the CALLING thread. Left to close with their threads, a
    pool thread that had answered one ownership question kept a handle on the
    store file open: on Windows an open handle refuses a delete, and
    factoryReset closes this store and then unlinks its file, so the ownership
    database survived the wipe that promises to remove it."""
    store = _store(tmp_path)
    path = _track_file(tmp_path, "song.flac")
    store.record("123", path, "LOSSLESS")
    store.ownership_of("123")  # the calling thread's own reader

    # A pool thread that answers an ownership question and then parks, exactly
    # as a QThreadPool thread does between jobs.
    parked = threading.Event()
    release = threading.Event()

    def reader():
        store.ownership_of("123")
        parked.set()
        release.wait(10)

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    assert parked.wait(10), "the reader never answered"
    closed_over = [r.conn for r in (ref() for ref in store._reader_refs) if r is not None]
    assert len(closed_over) >= 2, "the parked reader was never registered"

    store.close()

    assert store._reader_refs == set(), "the store still holds readers after close()"
    assert closed_over, "close() forgot the readers instead of shutting them"
    for conn in closed_over:
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")
    release.set()
    t.join(10)


def test_a_reader_whose_thread_has_gone_is_dropped_from_the_registry(tmp_path):
    """The registry must not become the thing that keeps a dead thread's
    connection open. It is the only strong reference left once that thread is
    gone, so the weakref callback prunes the entry and the connection with it."""
    store = _store(tmp_path)
    path = _track_file(tmp_path, "song.flac")
    store.record("123", path, "LOSSLESS")

    before = len(store._reader_refs)
    t = threading.Thread(target=lambda: store.ownership_of("123"))
    t.start()
    t.join(10)

    assert len(store._reader_refs) == before, "a dead thread's reader is held open by the store"
    assert all(ref() is not None for ref in store._reader_refs)
    store.close()
