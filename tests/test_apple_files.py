"""Apple file layout: template paths, collision names, tags, sidecars."""

from __future__ import annotations

import shutil
import subprocess

import mutagen.mp4
import pytest

from waves.apple_files import (
    format_apple_path,
    pick_destination,
    tag_apple_file,
    write_cover_sidecar,
    write_text_sidecar,
)

_TRACK = {
    "id": "apple:song-1",
    "title": "Xtal",
    "artist": "Aphex Twin",
    "artist_id": "apple:artist-1",
    "artists": [{"id": "apple:artist-1", "name": "Aphex Twin", "roles": []}],
    "album": "Selected Ambient Works 85-92",
    "album_id": "apple:album-1",
    "num": 1,
    "vol": 1,
    "art": "",
    "year": "1992",
    "date": "1992-02-12",
    "duration": "4:53",
    "duration_sec": 293,
    "quality": "HI-RES",
    "popularity": -1,
    "explicit": False,
    "added": "",
}

_ALBUM = {
    "id": "apple:album-1",
    "title": "Selected Ambient Works 85-92",
    "artist": "Aphex Twin",
    "artist_id": "apple:artist-1",
    "artists": [{"id": "apple:artist-1", "name": "Aphex Twin", "roles": []}],
    "art": "",
    "year": "1992",
    "date": "1992-02-12",
    "tracks": 13,
    "duration_sec": 4455,
    "quality": "LOSSLESS",
    "popularity": -1,
    "explicit": False,
    "added": "",
}


def test_default_album_template_renders_from_rows():
    out = format_apple_path(
        "{artist_name}/[{album_year}] {album_title}/{album_track_num}. {artist_name} - {track_title}",
        track=_TRACK,
        album=_ALBUM,
    )

    assert out == "Aphex Twin/[1992] Selected Ambient Works 85-92/01. Aphex Twin - Xtal"


def test_multi_disc_prefix_and_ids_use_raw_spellings():
    track = dict(_TRACK, vol=2)
    out = format_apple_path(
        "{track_volume_num_optional}{album_track_num} {track_id} {album_id} {isrc}",
        track=track,
        album=_ALBUM,
        num_volumes=2,
        isrc="GBAAA9200001",
    )

    assert out == "2-01 song-1 album-1 GBAAA9200001"


def test_unknown_tokens_render_empty():
    out = format_apple_path("{track_title} {video_quality} {mix_name}", track=_TRACK)

    assert out == "Xtal  "


def test_emptied_and_dot_segments_cannot_escape_the_library():
    track = dict(_TRACK, artist="?", title="..")
    out = format_apple_path("{artist_name}/{track_title}", track=track)

    assert not out.startswith("/")
    assert "/../" not in f"/{out}/"
    assert ".." not in out.split("/")


def test_collection_playlist_lists_landings_in_order(tmp_path):
    from waves.apple_files import write_collection_playlist

    first = tmp_path / "A" / "01.m4a"
    second = tmp_path / "A" / "02.m4a"
    first.parent.mkdir(parents=True)
    first.touch()
    second.touch()

    write_collection_playlist([first, second], "Selected Ambient Works")

    playlist = tmp_path / "A" / "_Selected Ambient Works.m3u8"
    assert playlist.read_text().splitlines() == ["01.m4a", "02.m4a"]


def test_explicit_marker_follows_the_shared_word():
    track = dict(_TRACK, explicit=True)
    out = format_apple_path("{track_title}{track_explicit}", track=track)

    assert out == "Xtal (Explicit)"


def test_pick_destination_steps_aside_on_collision(tmp_path):
    first = pick_destination(tmp_path, "Aphex Twin/Xtal", ".m4a")
    first.touch()

    second = pick_destination(tmp_path, "Aphex Twin/Xtal", ".m4a")

    assert second.name == "Xtal_01.m4a"
    assert second.parent == first.parent


def test_sidecars_land_beside_the_track(tmp_path):
    lyrics = write_text_sidecar(tmp_path, "Xtal", ".lrc", "[00:01.00]line")
    cover = write_cover_sidecar(tmp_path, b"fake-jpeg")

    assert lyrics is not None and lyrics.read_text() == "[00:01.00]line"
    assert cover is not None and cover.name == "cover.jpg"
    assert write_text_sidecar(tmp_path, "Xtal", ".lrc", "") is None
    assert write_cover_sidecar(tmp_path, b"") is None


needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def _ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    assert path is not None  # guarded by needs_ffmpeg
    return path


@needs_ffmpeg
def test_tag_apple_file_writes_generic_only_tags(tmp_path):
    src = tmp_path / "src.m4a"
    subprocess.run(  # noqa: S603 (fixed argv: a local tone fixture, no user input)
        [_ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:a", "aac", str(src)],
        check=True,
    )
    facts = {
        "item_id": "apple:song-1",
        "artist_ids": ["apple:artist-1"],
        "album_artist_ids": ["apple:artist-1"],
        "artists": [("apple:artist-1", "Aphex Twin")],
        "album_artists": ["Aphex Twin"],
        "copyright": "",
        "isrc": "GBAAA9200001",
        "explicit": False,
        "share_url": "https://music.apple.com/x",
        "volume_num": 1,
        "track_num": 1,
        "release_date": "1992-02-12",
        "release_type": "",
        "album": {"name": "Selected Ambient Works 85-92", "num_tracks": 13, "num_volumes": None, "upc": "", "type": ""},
    }

    assert tag_apple_file(src, title="Xtal", facts=facts, cover_data=None) is True

    tags = mutagen.mp4.MP4(str(src)).tags
    assert bytes(tags["----:com.apple.iTunes:WAVES_ITEM_ID"][0]) == b"apple:song-1"
    assert tags["\xa9nam"] == ["Xtal"]
    assert not any("WAVES_TIDAL" in key for key in tags)
