"""Staging names that fit beside a destination that also fits.

Even under a deep parent the staging name stays inside the path budget, keeps
a unique part, and uses a full uuid on an ordinary path.
"""

from __future__ import annotations

import pathlib

import pytest

from waves import paths as path_mod
from waves.paths import staging_path as _staging_path


@pytest.mark.parametrize("parent_len", [200, 230, 243, 248, 250, 251])
def test_a_deep_parent_still_gets_a_staging_name_that_fits(parent_len, monkeypatch):
    """The band the ten-character floor could not reach. The destination itself
    fits at these depths (a one-character stem plus '.flac'), so the staging
    name has to as well or the track can never land."""
    monkeypatch.setattr(path_mod, "PATH_LENGTH_MAX", 259)
    parent = pathlib.PurePosixPath("/" + "d" * (parent_len - 1))
    destination = pathlib.Path(str(parent)) / "X.flac"

    staged = _staging_path(destination)

    assert len(str(staged)) <= 259, f"{len(str(staged))} > 259 at parent {parent_len}"
    assert staged.name.endswith(".tmp")


def test_the_staging_name_keeps_something_unique_however_deep(monkeypatch):
    """A name with nothing unique in it is shared by every track in the folder."""
    monkeypatch.setattr(path_mod, "PATH_LENGTH_MAX", 259)
    destination = pathlib.Path("/" + "d" * 251) / "X.flac"

    staged = _staging_path(destination)

    assert len(staged.name) > len("...tmp"), "no unique part left at all"


def test_an_ordinary_path_still_gets_a_full_uuid(tmp_path):
    staged = _staging_path(tmp_path / "Song.flac")

    assert staged.name.startswith(".Song.flac.")
    assert staged.name.endswith(".tmp")
    assert len(staged.name) == len(".Song.flac.") + 36 + len(".tmp")
