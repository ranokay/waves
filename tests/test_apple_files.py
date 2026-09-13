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
    write_collection_playlist,
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


def test_pick_destination_numbers_past_the_first_collision(tmp_path):
    first = pick_destination(tmp_path, "Aphex Twin/Xtal", ".m4a")
    first.touch()
    second = pick_destination(tmp_path, "Aphex Twin/Xtal", ".m4a")
    second.touch()

    third = pick_destination(tmp_path, "Aphex Twin/Xtal", ".m4a")

    assert third.name == "Xtal_02.m4a"


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


PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _image_bytes(tmp_path, name: str, codec: str) -> bytes:
    path = tmp_path / name
    subprocess.run(  # noqa: S603 (fixed argv: a local fixture, no user input)
        [
            _ffmpeg(),
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=32x32",
            "-frames:v",
            "1",
            "-c:v",
            codec,
            str(path),
        ],
        check=True,
    )
    return path.read_bytes()


def test_sniff_image_format_reads_magic_bytes():
    from waves.metadata import sniff_image_format

    assert sniff_image_format(PNG_MAGIC + b"rest") == "png"
    assert sniff_image_format(b"\xff\xd8\xff\xe0rest") == "jpg"
    assert sniff_image_format(b"RIFF....WEBP") == ""
    assert sniff_image_format(b"") == ""


@needs_ffmpeg
def test_cover_sidecar_converts_to_the_selected_format(tmp_path):
    from waves.metadata import sniff_image_format

    jpeg = _image_bytes(tmp_path, "src.jpg", "mjpeg")
    png = _image_bytes(tmp_path, "src.png", "png")
    (tmp_path / "as-png").mkdir()
    (tmp_path / "as-jpg").mkdir()

    as_png = write_cover_sidecar(tmp_path / "as-png", jpeg, "png", ffmpeg_path=_ffmpeg())
    as_jpg = write_cover_sidecar(tmp_path / "as-jpg", png, "jpg", ffmpeg_path=_ffmpeg())

    assert as_png is not None and as_png.name == "cover.png"
    assert sniff_image_format(as_png.read_bytes()) == "png"
    assert as_jpg is not None and as_jpg.name == "cover.jpg"
    assert sniff_image_format(as_jpg.read_bytes()) == "jpg"


def test_raw_sidecar_keeps_the_master_bytes(tmp_path):
    png = PNG_MAGIC + b"master"
    target = write_cover_sidecar(tmp_path, png, "raw")

    assert target is not None and target.name == "cover.png"
    assert target.read_bytes() == png


def test_sidecar_without_a_converter_keeps_the_true_extension(tmp_path, monkeypatch):
    monkeypatch.setattr("waves.apple_files.shutil.which", lambda name: None)
    jpeg = b"\xff\xd8\xff\xe0" + b"jpeg"

    target = write_cover_sidecar(tmp_path, jpeg, "png", ffmpeg_path="")

    assert target is not None and target.name == "cover.jpg"
    assert target.read_bytes() == jpeg, "the served bytes are never relabelled"


@needs_ffmpeg
def test_embedded_png_cover_keeps_its_true_format(tmp_path):
    import mutagen.flac

    src = tmp_path / "src.m4a"
    subprocess.run(  # noqa: S603 (fixed argv: a local tone fixture, no user input)
        [_ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:a", "aac", str(src)],
        check=True,
    )
    png = _image_bytes(tmp_path, "cover.png", "png")

    assert tag_apple_file(src, title="Xtal", facts={}, cover_data=png) is True
    cover = mutagen.mp4.MP4(str(src)).tags["covr"][0]
    assert cover.imageformat == mutagen.mp4.MP4Cover.FORMAT_PNG

    flac_src = tmp_path / "src.flac"
    subprocess.run(  # noqa: S603 (fixed argv: a local tone fixture, no user input)
        [
            _ffmpeg(),
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-c:a",
            "flac",
            str(flac_src),
        ],
        check=True,
    )
    assert tag_apple_file(flac_src, title="Xtal", facts={}, cover_data=png) is True
    assert mutagen.flac.FLAC(str(flac_src)).pictures[0].mime == "image/png"


@needs_ffmpeg
def test_embed_cover_bytes_converts_png_for_the_tag(tmp_path):
    from types import SimpleNamespace

    from waves.metadata import sniff_image_format
    from waves.waves_ui.backend import WavesBridge

    png = _image_bytes(tmp_path, "c.png", "png")
    stub = SimpleNamespace()
    stub._cover_convert_ffmpeg = lambda: _ffmpeg()
    stub._embed_cover_bytes = WavesBridge._embed_cover_bytes.__get__(stub, SimpleNamespace)

    assert sniff_image_format(stub._embed_cover_bytes(png)) == "jpg"

    jpeg = _image_bytes(tmp_path, "c.jpg", "mjpeg")
    assert stub._embed_cover_bytes(jpeg) is jpeg
    assert stub._embed_cover_bytes(None) is None


def test_an_apple_partial_run_keeps_a_complete_playlist(tmp_path):
    # A re-run that skipped owned tracks lands one path; the folder already
    # holds the full album, so the playlist must not shrink to that one line.
    album = tmp_path / "Album"
    album.mkdir()
    for name in ("01 One.m4a", "02 Two.m4a", "03 Three.m4a"):
        (album / name).write_bytes(b"x")
    playlist = album / "_Album.m3u8"
    playlist.write_text("01 One.m4a\n02 Two.m4a\n03 Three.m4a\n", encoding="utf-8")

    write_collection_playlist([album / "01 One.m4a"], "Album", is_album=True)

    assert playlist.read_text().splitlines() == ["01 One.m4a", "02 Two.m4a", "03 Three.m4a"]


def test_an_apple_playlist_keeps_an_existing_legacy_name(tmp_path):
    album = tmp_path / "Album"
    album.mkdir()
    (album / "01 One.m4a").write_bytes(b"x")
    legacy = album / "_Album.m3u"
    legacy.write_text("01 One.m4a\n", encoding="utf-8")

    write_collection_playlist([album / "01 One.m4a"], "Album", is_album=True)

    assert legacy.read_text() == "01 One.m4a\n"
    assert not (album / "_Album.m3u8").exists()


def test_one_failing_directory_does_not_drop_the_others(tmp_path, monkeypatch):
    from waves import playlists as playlists_mod

    good = tmp_path / "Good"
    bad = tmp_path / "Bad"
    for folder in (good, bad):
        folder.mkdir()
        (folder / "01 One.m4a").write_bytes(b"x")

    real = playlists_mod._write_one_playlist

    def flaky(directory, *args, **kwargs):
        if directory == bad:
            raise OSError("locked")
        return real(directory, *args, **kwargs)

    monkeypatch.setattr(playlists_mod, "_write_one_playlist", flaky)

    write_collection_playlist([good / "01 One.m4a", bad / "01 One.m4a"], "Album", is_album=True)

    assert (good / "_Album.m3u8").is_file()
    assert not (bad / "_Album.m3u8").exists()
