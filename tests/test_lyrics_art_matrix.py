"""Lyrics & art matrix (issue #34, spec section 9.1)."""

import shutil
import subprocess

import pytest

from waves.lyrics import lyrics_sidecar_choices
from waves.ttml_lyrics import (
    format_lrc_timestamp,
    parse_timestamp,
    ttml_timing_mode,
    ttml_to_enhanced_lrc,
    ttml_to_lrc,
    ttml_to_text,
)

SYLLABLE_TTML = """<?xml version="1.0" encoding="UTF-8"?>
<tt xmlns:itunes="http://music.apple.com/lyrics" itunes:timing="Word">
<body><div>
<p begin="00:01.00" end="00:05.00"><span begin="00:01.00" end="00:02.00">Hello</span> <span begin="00:02.00" end="00:03.00">world</span></p>
<p begin="00:05.00" end="00:08.00"><span begin="00:05.00" end="00:06.00">Second</span> <span begin="00:06.00" end="00:07.00">line</span></p>
</div></body></tt>"""

LINE_TTML = """<?xml version="1.0" encoding="UTF-8"?>
<tt xmlns:itunes="http://music.apple.com/lyrics" itunes:timing="Line">
<body><div>
<p begin="00:10.00" end="00:12.00">First line</p>
<p begin="00:12.00" end="00:15.00">Second line</p>
</div></body></tt>"""

PLAIN_TTML = """<?xml version="1.0" encoding="UTF-8"?>
<tt xmlns:itunes="http://music.apple.com/lyrics" itunes:timing="None">
<body><div>
<p>Unsynced words here</p>
<p>More words</p>
</div></body></tt>"""


def test_timing_mode_reads_itunes_attribute():
    assert ttml_timing_mode(SYLLABLE_TTML) == "word"
    assert ttml_timing_mode(LINE_TTML) == "line"
    assert ttml_timing_mode(PLAIN_TTML) == "none"
    assert ttml_timing_mode("") == "none"
    assert ttml_timing_mode("not xml") == "none"


def test_parse_timestamp_shapes():
    assert parse_timestamp("00:01.00") == 1.0
    assert parse_timestamp("12.34s") == 12.34
    assert parse_timestamp("00:01:02.50") == 62.5
    assert parse_timestamp("") is None
    assert parse_timestamp("nonsense") is None


def test_line_ttml_to_lrc():
    lrc = ttml_to_lrc(LINE_TTML)
    assert "[00:10.00]First line" in lrc
    assert "[00:12.00]Second line" in lrc


def test_syllable_ttml_to_enhanced_lrc():
    enhanced = ttml_to_enhanced_lrc(SYLLABLE_TTML)
    assert "[00:01.00]" in enhanced
    assert "<00:01.00>Hello" in enhanced
    assert "<00:02.00>world" in enhanced
    # Plain LRC of the same document collapses word spans.
    plain = ttml_to_lrc(SYLLABLE_TTML)
    assert "Hello" in plain and "world" in plain
    assert "<00:" not in plain


def test_ttml_to_text():
    assert ttml_to_text(LINE_TTML) == "First line\nSecond line"
    assert ttml_to_text(PLAIN_TTML) == "Unsynced words here\nMore words"
    assert ttml_to_text("") == ""


def test_format_lrc_timestamp():
    assert format_lrc_timestamp(61.5) == "[01:01.50]"
    assert format_lrc_timestamp(0) == "[00:00.00]"


def test_sidecar_matrix_extensions_never_faked():
    # Timed wins as .lrc, never .txt pretending to be synced.
    assert lyrics_sidecar_choices(synced="[00:01]hi", plain="hi", lyrics_file=True) == [("[00:01]hi", ".lrc")]
    # Untimed goes to .txt, suppressed by synced_only.
    assert lyrics_sidecar_choices(plain="hi", lyrics_file=True) == [("hi", ".txt")]
    assert lyrics_sidecar_choices(plain="hi", lyrics_file=True, synced_only=True) == []
    # TTML is independent: Apple verbatim zero-conversion, sidecar-only.
    assert lyrics_sidecar_choices(ttml="<tt/>", ttml_file=True, is_apple=True) == [("<tt/>", ".ttml")]
    # TIDAL has no TTML source: the toggle is inert there.
    assert lyrics_sidecar_choices(ttml="<tt/>", ttml_file=True, is_apple=False) == []
    # All embed x sidecar combinations valid: both sidecars at once.
    both = lyrics_sidecar_choices(synced="[00:01]hi", ttml="<tt/>", lyrics_file=True, ttml_file=True, is_apple=True)
    assert both == [("[00:01]hi", ".lrc"), ("<tt/>", ".ttml")]
    # Nothing enabled means nothing written.
    assert lyrics_sidecar_choices(synced="x", plain="y", ttml="z") == []


def test_apple_origin_raw_url():
    from waves.providers.apple import AppleProvider

    template = "https://is1-ssl.mzstatic.com/image/thumb/Music/ab/cd/ef/{w}x{h}bb.jpg"
    raw = AppleProvider.cover_raw_url({"attributes": {"artwork": {"url": template}}})
    assert "is1-ssl" not in raw
    assert "image/thumb/" not in raw
    assert "{w}" not in raw
    assert raw.startswith("https://a1")
    assert AppleProvider.cover_raw_url({}) == ""


def test_apple_cover_url_clamps_to_5000():
    from waves.providers.apple import AppleProvider

    template = "https://example.com/{w}x{h}bb.jpg"
    url = AppleProvider._art({"artwork": {"url": template}}, 99999)
    assert "5000x5000" in url


needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


@needs_ffmpeg
def test_tidal_standalone_art_converts_to_the_selected_format(tmp_path):
    """The standalone action never writes JPEG bytes into a .png (S08)."""
    from types import SimpleNamespace

    from waves.metadata import sniff_image_format
    from waves.model.cfg import Settings
    from waves.waves_ui.backend import WavesBridge

    jpeg = tmp_path / "src.jpg"
    subprocess.run(  # noqa: S603 (fixed argv: a local fixture, no user input)
        [
            shutil.which("ffmpeg"),
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
            "mjpeg",
            str(jpeg),
        ],
        check=True,
    )
    data = Settings()
    data.tidal_cover_file_format = "png"
    track = SimpleNamespace(album=SimpleNamespace(image=lambda size: "http://img/320.jpg"))

    class _Download:
        def cover_data_cached(self, url):
            return jpeg.read_bytes()

    stub = SimpleNamespace(settings=SimpleNamespace(data=data), _dl=_Download())
    stub._standalone_base_dir = lambda: tmp_path
    stub._standalone_tidal_tracks = lambda media_id: [(track, None, False)]
    stub._tidal_standalone_dest = lambda base, track_obj, collection: (tmp_path, "S1")
    stub._cover_convert_ffmpeg = lambda: shutil.which("ffmpeg")
    stub._psetting = lambda provider, name, default: {
        "metadata_cover_dimension": 320,
        "metadata_cover_embed": False,
        "cover_album_file": True,
    }.get(name, default)
    stub._standalone_tidal = WavesBridge._standalone_tidal.__get__(stub, SimpleNamespace)

    assert stub._standalone_tidal("123", "art") == 1
    target = tmp_path / "cover.png"
    assert target.is_file()
    assert sniff_image_format(target.read_bytes()) == "png"
