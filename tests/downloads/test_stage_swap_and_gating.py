"""Crash-safety and UI pins around downloads, the updater and the QML tree.

* the stage-and-swap copy is durable before the rename (fsync), and both
  existence gates reject zero-byte truncation artifacts;
* the updater's tree swap confirms the executable exists before discarding the
  backup, and restores the install when it does not;
* the bridge, the QML tree and BRIDGE.md carry no recentlyAdded members;
* the video preview passes the same padding downloads use;
* ArtCard runs no collection ownership rollups whose results can never render;
* QueueStack's marching step is gated on visible, so idle download controls
  stop re-evaluating a binding 20 times a second.
"""

import os

import pytest
from support.paths import REPO_ROOT

from waves.desktop.updater import AppUpdater, UpdaterError
from waves.download import Download
from waves.library.ownership import OwnershipStore
from waves.paths import check_file_exists

BACKEND_SRC = (REPO_ROOT / "waves" / "desktop" / "backend.py").read_text()
QML_DIR = REPO_ROOT / "waves" / "desktop" / "qml"
# The whole QML tree: the negative pins below must not go vacuous when the
# surface they fence moves to another QML file.
ALL_QML = "\n".join(path.read_text(encoding="utf-8") for path in sorted(QML_DIR.glob("*.qml")))
QUEUE_STACK_QML = (QML_DIR / "QueueStack.qml").read_text()
BRIDGE_MD = (REPO_ROOT / "waves" / "desktop" / "BRIDGE.md").read_text()


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


# ------------------------------------------------------- updater tree swap


class _TreeHost:
    # The reclaim asks what the previous build shipped, so a file the new
    # release legitimately dropped is not mistaken for one of the user's and
    # put back. Nothing recorded here: unknown means "the user's".
    def _shipped_by_the_old_build(self):
        return None


def _tree_setup(tmp_path):
    install_root = tmp_path / "waves.dist"
    install_root.mkdir()
    target = install_root / "waves.bin"
    target.write_bytes(b"OLD")
    (install_root / "lib.so").write_bytes(b"OLDLIB")
    return install_root, target


def test_tree_swap_missing_executable_restores_old_install(tmp_path):
    install_root, target = _tree_setup(tmp_path)
    new_tree = tmp_path / "staged" / "waves.dist"
    new_tree.mkdir(parents=True)
    (new_tree / "lib.so").write_bytes(b"NEWLIB")  # no waves.bin in the payload
    with pytest.raises(UpdaterError):
        AppUpdater._apply_unix_tree(_TreeHost(), new_tree, target, lambda *_: None)
    assert target.read_bytes() == b"OLD", "old install was not restored"
    assert not install_root.with_name(install_root.name + ".old").exists()
    assert not install_root.with_name(install_root.name + ".new").exists()


def test_tree_swap_with_executable_still_succeeds(tmp_path):
    install_root, target = _tree_setup(tmp_path)
    new_tree = tmp_path / "staged" / "waves.dist"
    new_tree.mkdir(parents=True)
    (new_tree / "waves.bin").write_bytes(b"NEW")
    out = AppUpdater._apply_unix_tree(_TreeHost(), new_tree, target, lambda *_: None)
    assert out == target
    assert target.read_bytes() == b"NEW"
    assert not install_root.with_name(install_root.name + ".old").exists()


# ------------------------------------------------------- retired bridge API


def test_dead_recently_added_pair_removed():
    assert "recentlyAdded" not in BACKEND_SRC
    assert "loadRecentlyAdded" not in BACKEND_SRC
    assert "recentlyAdded" not in ALL_QML
    assert "recentlyAddedLoaded" not in BRIDGE_MD


# ------------------------------------------------------- video preview padding


def test_video_preview_passes_padding():
    assert 'format_path_media(template, vid, pad, **kw) + ".mp4"' in BACKEND_SRC


# --------------------------------------------------- ArtCard collection rollups


def test_artcard_runs_no_unrenderable_collection_rollups():
    """Both ArtCard download controls must opt out of the collection rollup:
    one is only visible with live state (which outranks the rollup), the other
    only renders for non-collection kinds. ArtCard lives in its own file, so
    the negative pin reads the whole QML tree."""
    assert "collectionCheck: ac.kind ===" not in ALL_QML


# ------------------------------------------------------- QueueStack marching step


def test_queuestack_step_is_gated_on_visible():
    line = next(ln for ln in QUEUE_STACK_QML.splitlines() if "readonly property int step:" in ln)
    assert "visible ?" in line, "step must not depend on marchTick while hidden"
