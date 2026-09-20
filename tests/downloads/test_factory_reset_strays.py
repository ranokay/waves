"""What a factory reset must take out of the updates and bin folders.

The updater log and helper, the staged-swap marker and the per-pid helper, and
the ffmpeg installer's stray temp files all quote or pin user paths.
"""

from __future__ import annotations

import os

from waves.desktop.backend import _FACTORY_WIPE_SUBDIRS


def test_the_updater_log_and_helper_are_named_in_the_factory_wipe():
    named = {name for _sub, names, _pats in _FACTORY_WIPE_SUBDIRS for name in names}

    assert "update.log" in named, "update.log quotes install paths that carry the user's name"
    assert "apply_update.bat" in named, "a crashed helper's script kept the updates folder alive"


def test_the_wipe_still_names_what_it_always_did():
    subdirs = {sub for sub, _names, _pats in _FACTORY_WIPE_SUBDIRS}

    assert os.path.join("updates", "staged") in subdirs
    assert "bin" in subdirs
    assert "applied.json" in {name for _sub, names, _pats in _FACTORY_WIPE_SUBDIRS for name in names}


def _wipes(subdir: str, name: str) -> bool:
    """Would the reset take this file out of that subdirectory?"""
    for rel, names, patterns in _FACTORY_WIPE_SUBDIRS:
        if rel == subdir:
            return name in names or any(pat.match(name) for pat in patterns)
    raise AssertionError(f"{subdir} is not in the wipe list at all")


def test_the_staged_swap_marker_falls_with_the_updates_folder():
    """The install path the marker records is the leak the wipe exists to take.

    armed.json holds the whole install result, "applied_to" included, which on
    Windows is C:\\Users\\<name>\\... . It arrived after update.log was listed
    and inherited none of its treatment, so the folder stopped falling at all
    and the path stayed on disk across a reset that promises otherwise.
    """
    assert _wipes("updates", "armed.json"), "the staged-swap marker records the install path"
    assert _wipes("updates", "install.lock"), "an orphaned lock kept the updates folder alive"


def test_the_per_pid_swap_helper_falls_too():
    """The helper is named per pid (apply_update_<pid>.bat), so the exact name
    in the list has not matched anything since it was renamed."""
    assert _wipes("updates", "apply_update_66648.bat")
    assert _wipes("updates", "apply_update_1.bat")
    # Anchored at both ends: nothing that merely looks similar is deletable.
    assert not _wipes("updates", "apply_update_.bat")
    assert not _wipes("updates", "apply_update_12.bat.bak")
    assert not _wipes("updates", "my_apply_update_12.bat")


def test_the_ffmpeg_installer_strays_fall_with_the_bin_folder():
    """Both mkstemp shapes ffmpeg_manager stages through, so a crashed install
    cannot keep bin/ alive forever."""
    assert _wipes("bin", "ffmpeg.QmX7d2.new")
    assert _wipes("bin", "ffmpeg.exe.QmX7d2.new")
    assert _wipes("bin", "ffmpeg.json.a1b2c3.tmp")
    # The download temp has no Waves-written prefix to anchor on: it stays, on
    # purpose, and keeps its directory alive rather than widening the match.
    assert not _wipes("bin", "tmpq8s7d1.zip")
    assert not _wipes("bin", "notffmpeg.x.new")
