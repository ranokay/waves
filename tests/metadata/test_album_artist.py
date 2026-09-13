"""The opt-in 'Clean album-artist tag' setting, at its write contract.

The album-artist METADATA tag is written by the engine's tag writer from the
provider's ``track_facts`` (album_artists). The collapse to the primary artist
(multi-value album-artist fields confuse Plex) is a TAG-WRITING policy: the
engine holds the rule (``clean_album_artists``) and reads the pref live
through the ``album_artist_tag_clean`` hook at tag-write time, so a settings
change applies without a restart. Folder paths are untouched (they read a
different binding).

These drive the real write path -- the provider's facts pull (with a featured
credit before two main credits), ``Download.metadata_write`` and the saved
FLAC -- so a revert that stops consulting the hook fails here.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from mutagen import File as MutagenFile
from tidalapi.artist import Role
from tidalapi.media import Track

from waves.download import Download, clean_album_artists
from waves.providers.tidal import TidalProvider


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


# ---- the write path ----------------------------------------------------------
def _artist(name, roles, artist_id):
    return SimpleNamespace(id=artist_id, name=name, roles=list(roles))


def _track() -> Track:
    """A real Track whose album credits a featured guest before two mains.

    ``get_album_artists`` drops the featured credit and keeps the mains in
    album order; cleaning then collapses that list to the primary.
    """
    featured = _artist("Featured Guest", (Role.featured,), 3)
    primary = _artist("Primary", (Role.main,), 1)
    second = _artist("Second Main", (Role.main,), 2)
    track = Track.__new__(Track)
    track.name = "Song"
    track.album = SimpleNamespace(
        name="Album",
        num_tracks=1,
        num_volumes=None,
        available_release_date=None,
        release_date=None,
        type="ALBUM",
        upc="",
        artists=[featured, primary, second],
    )
    track.artists = [featured, primary, second]
    track.artist = primary
    track.track_num = 1
    track.volume_num = 1
    track.explicit = False
    track.isrc = ""
    track.copyright = ""
    track.share_url = ""
    track.id = 1
    track.bpm = None
    track.key = None
    track.key_scale = None
    return track


def _tone(path) -> None:
    subprocess.run(  # noqa: S603 (fixed argv: a local tone fixture, no user input)
        [
            shutil.which("ffmpeg"),
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=0.2",
            "-c:a",
            "flac",
            str(path),
        ],
        check=True,
    )


def _download(tmp_path, *, clean: bool) -> Download:
    dl = Download(
        tidal_obj=MagicMock(),
        skip_existing=False,
        path_base=str(tmp_path),
        fn_logger=MagicMock(),
        provider=TidalProvider(MagicMock()),
        album_artist_tag_clean=lambda: clean,
    )
    dl.settings = MagicMock()
    data = dl.settings.data
    for key, value in (
        ("lyrics_embed", False),
        ("lyrics_file", False),
        ("metadata_cover_embed", False),
        ("cover_album_file", False),
        ("cover_single_track_file", False),
        ("metadata_write_url", False),
        ("metadata_replay_gain", False),
        ("mark_explicit", False),
        ("metadata_target_upc", "UPC"),
        ("tidal_lyrics_embed", False),
        ("tidal_lyrics_file", False),
        ("tidal_lyrics_prefer_lrclib", False),
        ("tidal_metadata_cover_embed", False),
        ("tidal_cover_album_file", False),
        ("tidal_cover_single_track_file", False),
    ):
        setattr(data, key, value)
    dl.event_abort = threading.Event()
    dl.event_run = threading.Event()
    dl.event_run.set()
    return dl


@pytest.mark.ffmpeg
@pytest.mark.parametrize(
    ("clean", "expected"),
    [
        # The featured credit is dropped upstream; cleaning keeps the first main.
        (False, ["Primary", "Second Main"]),
        (True, ["Primary"]),
    ],
)
def test_the_album_artist_write_honours_the_live_cleaning_pref(tmp_path, clean, expected):
    media = tmp_path / "t.flac"
    _tone(media)
    track = _track()

    ok, *_ = _download(tmp_path, clean=clean).metadata_write(track, media, False)

    assert ok
    tags = MutagenFile(str(media))
    assert list(tags["ALBUMARTIST"]) == expected
