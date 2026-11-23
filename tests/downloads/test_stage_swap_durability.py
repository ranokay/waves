"""Durability and zero-byte gates around the stage-and-swap copy.

The copied bytes are fsynced before the caller renames the staging file over
the destination, every existence gate rejects zero-byte truncation artifacts,
and ownership skips a truncated copy while still crediting the real one.
"""

import os

from waves.download import Download
from waves.library.ownership import OwnershipStore
from waves.paths import check_file_exists

# --------------------------------------------------- durable copy and gates


class _CopyHost:
    _COPY_BUFFER_BYTES = Download._COPY_BUFFER_BYTES


def test_copy_file_contents_fsyncs_before_returning(tmp_path, monkeypatch):
    """The bytes must be durable before the caller renames the temp over the
    final name, or a power cut can leave a truncated file under a trusted name."""
    src = tmp_path / "src.bin"
    src.write_bytes(b"x" * 1024)
    dst = tmp_path / "dst.bin"
    synced: list[int] = []
    real_fsync = os.fsync

    def spy_fsync(fd):
        synced.append(fd)
        real_fsync(fd)

    monkeypatch.setattr("waves.download.os.fsync", spy_fsync)
    Download._copy_file_contents(_CopyHost(), src, dst)
    assert synced, "destination file was never fsynced"
    assert dst.read_bytes() == b"x" * 1024


def test_check_file_exists_rejects_zero_byte_file(tmp_path):
    empty = tmp_path / "track.flac"
    empty.touch()
    assert check_file_exists(empty) is False
    empty.write_bytes(b"audio")
    assert check_file_exists(empty) is True


def test_check_file_exists_extension_ignore_rejects_zero_byte(tmp_path):
    (tmp_path / "track.m4a").touch()
    assert check_file_exists(tmp_path / "track.flac", extension_ignore=True) is False
    (tmp_path / "track.m4a").write_bytes(b"audio")
    assert check_file_exists(tmp_path / "track.flac", extension_ignore=True) is True


def test_ownership_skips_zero_byte_copy(tmp_path):
    store = OwnershipStore(str(tmp_path / "ownership.sqlite3"))
    truncated = tmp_path / "song.flac"
    truncated.touch()
    store.record("123", str(truncated), "LOSSLESS")
    assert store.ownership_of("123") is None
    truncated.write_bytes(b"audio")
    info = store.ownership_of("123")
    assert info is not None and info["owned"] is True
    store.close()


def test_ownership_zero_byte_falls_through_to_real_copy(tmp_path):
    store = OwnershipStore(str(tmp_path / "ownership.sqlite3"))
    truncated = tmp_path / "hi_res.flac"
    truncated.touch()
    real = tmp_path / "lossless.flac"
    real.write_bytes(b"audio")
    store.record("123", str(truncated), "HI_RES_LOSSLESS")
    store.record("123", str(real), "LOSSLESS")
    info = store.ownership_of("123")
    assert info is not None
    assert info["path"] == str(real)
    store.close()
