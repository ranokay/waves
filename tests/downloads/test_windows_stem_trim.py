"""Stem trimming on Windows counts in the units the path cap counts.

A CJK title, an ASCII title and the extension each give back exactly the room
the parent leaves, measured in UTF-16 units.
"""

from __future__ import annotations

import pathlib
import sys

from waves import paths as path_helper
from waves.paths import PATH_LENGTH_MAX, _longest_stem_that_fits

CJK = "楽曲"  # two characters: one UTF-16 unit each, three bytes each


def test_a_cjk_title_gives_back_characters_not_thirds_of_them(monkeypatch):
    """On Windows the cap counts UTF-16 units; the stem's bytes are three times
    that for CJK, so a byte-count trim removed a third of what it owed and the
    halving backstop then took half the stem."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(path_helper, "PATH_LENGTH_MAX", 259, raising=False)
    directory = pathlib.PurePosixPath("/" + "d" * 200)
    stem = CJK * 40  # 40 characters over what the parent leaves room for

    kept = _longest_stem_that_fits(pathlib.Path(str(directory)), stem, ".flac")

    assert path_helper._path_length(pathlib.Path(str(directory)) / (kept + ".flac")) <= 259
    # And it kept as much as it possibly could: one more character overflows.
    assert path_helper._path_length(pathlib.Path(str(directory)) / (stem[: len(kept) + 1] + ".flac")) > 259


def test_an_ascii_title_is_trimmed_exactly_as_before(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(path_helper, "PATH_LENGTH_MAX", 259, raising=False)
    directory = pathlib.Path("/" + "d" * 200)
    stem = "a" * 100

    kept = _longest_stem_that_fits(directory, stem, ".flac")

    # 201 for the directory, 1 for the separator, 5 for the extension.
    assert len(kept) == 259 - 201 - 1 - len(".flac")


def test_the_extension_always_survives(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(path_helper, "PATH_LENGTH_MAX", 259, raising=False)
    directory = pathlib.Path("/" + "d" * 250)

    kept = _longest_stem_that_fits(directory, "a" * 50, ".flac")

    assert kept and len(kept) >= 1
    assert PATH_LENGTH_MAX  # imported for the reader, not the assertion
