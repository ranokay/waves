"""Standalone Apple destinations render through the shared path core.

`_apple_standalone_dest` falls back to the title when the template render
raises, and again when the rendered name comes out empty; that fallback goes
through the same per-component sanitizer the template tokens use, so a title
carrying a path separator becomes one file name, never a subfolder. The render
itself goes through the same formatter the download job uses, so a sidecar
lands wherever the audio of the same track would (provider segment included).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import waves.waves_ui.backend as backend
from waves.waves_ui.backend import WavesBridge


def _stub(**data_overrides) -> SimpleNamespace:
    data = SimpleNamespace(
        format_album="{artist_name}/{album_title}/{track_title}",
        format_track="{track_title}",
        album_track_num_pad_min=1,
        filename_delimiter_artist=", ",
        filename_delimiter_album_artist=", ",
        filename_illegal_replacement="",
        filename_illegal_map=None,
    )
    for key, value in data_overrides.items():
        setattr(data, key, value)
    stub = SimpleNamespace(settings=SimpleNamespace(data=data), providers={})
    for name in ("_apple_standalone_dest", "_apple_relative_path"):
        setattr(stub, name, getattr(WavesBridge, name).__get__(stub, SimpleNamespace))
    return stub


def test_a_standalone_dest_matches_the_audio_relative_path(tmp_path):
    template = "{provider_name}/{track_title}"
    stub = _stub(format_track=template)
    track = {"title": "Xtal"}

    relative = stub._apple_relative_path(track=track, album=None, playlist=None, file_template=template)
    folder, stem = stub._apple_standalone_dest(tmp_path, track, None, False)

    assert (folder / f"{stem}.m4a").relative_to(tmp_path) == Path(relative).with_suffix(".m4a")


def test_a_collection_standalone_dest_matches_the_album_relative_path(tmp_path):
    template = "{provider_name}/{artist_name}/{album_title}/{track_title}"
    stub = _stub(format_album=template)
    track = {"title": "Xtal", "artist": "Aphex Twin", "num": 1, "vol": 1}
    album = {"title": "Selected Ambient Works", "artist": "Aphex Twin"}

    relative = stub._apple_relative_path(track=track, album=album, playlist=None, file_template=template)
    folder, stem = stub._apple_standalone_dest(tmp_path, track, album, True)

    assert (folder / f"{stem}.m4a").relative_to(tmp_path) == Path(relative).with_suffix(".m4a")


def test_a_template_failure_writes_one_sanitized_name(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise ValueError("bad template")

    monkeypatch.setattr(backend, "format_apple_path", boom)
    stub = _stub()

    folder, stem = stub._apple_standalone_dest(tmp_path, {"title": "Live/Demo"}, None, False)

    assert folder == tmp_path
    assert stem == "LiveDemo"
    assert not (tmp_path / "Live").exists(), "the fallback must not create a subfolder"


def test_the_fallback_honors_the_configured_stand_in(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise ValueError("bad template")

    monkeypatch.setattr(backend, "format_apple_path", boom)
    stub = _stub(filename_illegal_replacement="-", filename_illegal_map={"/": " · "})

    _folder, stem = stub._apple_standalone_dest(tmp_path, {"title": "Live/Demo"}, None, False)

    assert stem == "Live · Demo"


def test_a_title_with_nothing_left_falls_back_to_track(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise ValueError("bad template")

    monkeypatch.setattr(backend, "format_apple_path", boom)
    stub = _stub()

    _folder, stem = stub._apple_standalone_dest(tmp_path, {"title": "///"}, None, False)

    assert stem == "track"


def test_a_render_that_comes_back_empty_uses_the_sanitized_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, "format_apple_path", lambda *args, **kwargs: "")
    stub = _stub()

    _folder, stem = stub._apple_standalone_dest(tmp_path, {"title": "X/Y"}, None, False)

    assert stem == "XY"
