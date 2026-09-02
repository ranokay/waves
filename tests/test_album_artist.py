"""The opt-in 'Clean album-artist tag' setting, at its contract-pass home.

The album-artist METADATA tag is written by the engine's tag writer from the
provider's ``track_facts`` (album_artists). The collapse to the primary artist
(multi-value album-artist fields confuse Plex) is a TAG-WRITING policy, so it
lives in the engine beside the write it shapes: the engine holds the rule
(``clean_album_artists``), the bridge holds the pref (a waves.json pref, read
live through the ``album_artist_tag_clean`` hook it passes at job
construction). Folder paths are untouched (they read a different binding).

Pure-function tests: no Qt, no network.
"""

import pytest
from tidalapi.artist import Role

from waves.download import Download, clean_album_artists


class _Artist:
    def __init__(self, name, roles=(Role.main,)):
        self.name = name
        self.roles = list(roles)


class _Media:
    """Non-Track media (e.g. an Album): the helper reads ``.artists``."""

    def __init__(self, artists):
        self.artists = artists


# ---- clean_album_artists (pure) ---------------------------------------------
@pytest.mark.parametrize(
    "names,expected",
    [
        (["Solo"], ["Solo"]),
        (["A", "B", "C"], ["A"]),
        ([], []),
    ],
)
def test_clean_album_artists(names, expected):
    assert clean_album_artists(names) == expected


# ---- the engine hook wiring --------------------------------------------------
def _download(album_artist_tag_clean=None) -> Download:
    from unittest.mock import MagicMock

    return Download(
        tidal_obj=MagicMock(),
        path_base="/tmp",
        fn_logger=MagicMock(),
        album_artist_tag_clean=album_artist_tag_clean,
    )


def test_the_hook_defaults_to_off():
    dl = _download()
    assert dl._album_artist_tag_clean() is False


def test_the_hook_is_read_live_at_tag_write_time():
    # A settings change mid-run applies to the job's later tracks without a
    # restart, exactly as the old module flag did.
    state = {"clean": False}
    dl = _download(album_artist_tag_clean=lambda: state["clean"])
    assert dl._album_artist_tag_clean() is False
    state["clean"] = True
    assert dl._album_artist_tag_clean() is True


def test_the_engine_owns_the_rule_not_the_pref():
    # The collapse reduces a MAIN-credit list to the primary; the featured-only
    # filtering happened upstream in the fact pull. The engine's rule is pure.
    assert clean_album_artists(["Primary", "Second Main"]) == ["Primary"]
