"""Updater tree swap confirming the executable before it discards the backup.

A payload without the executable restores the old install; with it, the swap
succeeds.
"""

import pytest

from waves.desktop.updater import AppUpdater, UpdaterError

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
