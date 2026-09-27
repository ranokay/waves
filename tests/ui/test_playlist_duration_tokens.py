"""Playlist duration tokens resolve on playlists.

{playlist_duration_seconds} renders the playlist's own length in seconds and
{playlist_duration_minutes} its minutes-and-seconds form (":" is illegal in
file names, so the path carries the digits, as with the album and track
minutes tokens).
"""

from __future__ import annotations

from tidalapi import Playlist

from waves.paths import format_path_media


def _playlist(**over) -> Playlist:
    p = Playlist.__new__(Playlist)
    p.id = 7
    p.name = "Night Drives"
    p.duration = 3720
    for key, value in over.items():
        setattr(p, key, value)
    return p


def test_playlist_duration_seconds_renders_the_playlist_length():
    assert format_path_media("{playlist_duration_seconds}", _playlist()) == "3720"


def test_playlist_duration_minutes_renders_minutes_and_seconds():
    # ":" is illegal in file names, so the path carries "6200" — the same
    # answer the album and track minutes tokens give in a path.
    assert format_path_media("{playlist_duration_minutes}", _playlist()) == "6200"
