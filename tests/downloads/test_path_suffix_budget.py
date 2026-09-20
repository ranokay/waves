"""The path budget behind the unique suffix.

The suffix is charged in the platform's own units, a Windows stem keeps every
character the path cap allows, and the stem is trimmed to fit both caps.
"""

from __future__ import annotations

import os
import pathlib


def test_the_unique_suffix_budget_measures_the_path_the_way_the_platform_does(monkeypatch):
    """_path_with_unique_suffix subtracted a UTF-8 BYTE count for the suffix
    from a whole-path budget the platform measures in UTF-16 units. On POSIX
    the two are the same number; on Windows a CJK or emoji suffix is charged
    three or four units against a cap that charges one or two, so a name near
    the path cap gives up stem it does not have to."""
    from waves import paths as path_mod

    # A suffix whose two measures differ: three bytes in UTF-8, one UTF-16
    # unit. The path budget must charge the platform's number.
    assert path_mod._text_length("字") == len("字".encode())  # POSIX: bytes
    monkeypatch.setattr(path_mod.sys, "platform", "win32")
    assert path_mod._text_length("字") == 1, "Windows counts UTF-16 units"
    assert path_mod._text_length("\U0001f600") == 2, "an astral character costs two"


def test_a_windows_stem_keeps_every_character_the_path_cap_allows(monkeypatch):
    """The cost of the mixed units, in characters of the user's song title.

    On Windows the whole-path budget is UTF-16 units, and trimming the stem
    against it in UTF-8 BYTES charges a CJK title three units per character
    where MAX_PATH charges one, losing two thirds of the name it is entitled to
    keep. The result always fits either way; measured wrongly it is just
    needlessly short.
    """
    from waves import paths as path_mod

    monkeypatch.setattr(path_mod.sys, "platform", "win32")
    monkeypatch.setattr(path_mod, "PATH_LENGTH_MAX", 120)
    parent = pathlib.Path("/" + "d" * 90)
    destination = parent / ("字" * 40 + ".flac")

    got = path_mod._path_with_unique_suffix(destination, "_01")
    stem = got.name[: -len("_01.flac")]

    # 120 - 91 (the parent, leading slash included) - 1 (separator)
    # - 8 ("_01.flac") = 20 units of stem. Measured in bytes that budget is 6.
    assert len(stem) == 20, f"kept {len(stem)} of the 20 characters that fit"
    assert path_mod._path_length(got) == 120, "and it uses the budget exactly, never overruns it"


def test_a_stem_is_trimmed_to_fit_both_caps(monkeypatch):
    """Whatever the units, the result must satisfy the filename cap in bytes
    AND the path cap in the platform's own measure: the two-budget form has to
    keep both."""
    from waves import paths as path_mod

    monkeypatch.setattr(path_mod, "PATH_LENGTH_MAX", 120)
    parent = pathlib.Path("/" + "d" * 90)
    destination = parent / ("字" * 40 + ".flac")

    got = path_mod._path_with_unique_suffix(destination, "_01")

    assert len(os.fsencode(got.name)) <= path_mod.FILENAME_LENGTH_MAX
    assert path_mod._path_length(got) <= 120, path_mod._path_length(got)
    assert got.name.endswith("_01.flac"), "the part that makes it unique is never trimmed"


def test_an_ordinary_name_is_untouched():
    from waves import paths as path_mod

    got = path_mod._path_with_unique_suffix(pathlib.Path("/music/Artist/Album/Song.flac"), "_01")

    assert got == pathlib.Path("/music/Artist/Album/Song_01.flac")
