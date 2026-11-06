"""A replacement moves ownership, and a re-record never keeps a stale digest."""

from __future__ import annotations

import pathlib

from waves.library.ownership import OwnershipStore


def _file(path: pathlib.Path, data: bytes = b"audio") -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_re_recording_the_same_path_replaces_the_old_digest(tmp_path):
    store = OwnershipStore(str(tmp_path / "own.db"))
    file_path = _file(tmp_path / "Song.flac")

    store.record("tidal:1", str(file_path), "LOSSLESS", audio_digest="old-digest")
    store.record("tidal:1", str(file_path), "HI_RES_LOSSLESS", audio_digest="new-digest")

    info = store.ownership_of("tidal:1")
    assert info["quality_tier"] == "HI_RES_LOSSLESS"
    assert info["audio_digest"] == "new-digest"


def test_a_replacement_retires_the_origin_row_and_records_the_delivering_one(tmp_path):
    store = OwnershipStore(str(tmp_path / "own.db"))
    old = _file(tmp_path / "Song.flac")
    new = _file(tmp_path / "Song.m4a", b"new audio")
    store.record("tidal:1", str(old), "LOSSLESS", audio_digest="old")

    store.record_replacement(
        "tidal:1",
        str(old),
        "apple:42",
        str(new),
        "HI_RES_LOSSLESS",
        audio_type="stereo",
        audio_digest="new",
    )

    assert store.ownership_of("tidal:1") is None
    info = store.ownership_of("apple:42")
    assert info["path"] == str(new)
    assert info["quality_tier"] == "HI_RES_LOSSLESS"
    assert info["audio_digest"] == "new"


def test_a_legacy_row_without_a_digest_still_reads(tmp_path):
    store = OwnershipStore(str(tmp_path / "own.db"))
    file_path = _file(tmp_path / "Song.flac")
    store.record("tidal:1", str(file_path), "LOSSLESS")

    info = store.ownership_of("tidal:1")

    assert info is not None
    assert info["audio_digest"] is None


def test_a_failed_delivered_insert_keeps_the_origin_row(tmp_path, monkeypatch):
    import sqlite3

    import pytest

    store = OwnershipStore(str(tmp_path / "own.db"))
    old = _file(tmp_path / "Song.ogg")
    new = _file(tmp_path / "Song.m4a", b"new audio")
    store.record("tidal:1", str(old), "LOSSLESS", audio_digest="old")

    def fail(_row):
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(store, "_write_locked", fail)

    with pytest.raises(sqlite3.OperationalError):
        store.record_replacement("tidal:1", str(old), "apple:42", str(new), "HI_RES_LOSSLESS")

    assert store.ownership_of("tidal:1") is not None
