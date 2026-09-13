"""The Apple runner's neutral seam: one job through a minimal hooks object.

No bridge and no Qt: the provider, live settings and a status sink are the
only callables this path needs; every other hook keeps its inert default, so
the test pins that the runner holds the policy and reaches the bridge only
through the declared hooks.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from waves.constants import QualityTier, quality_rank
from waves.providers.apple import runner

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def _tone(path: Path) -> None:
    subprocess.run(  # noqa: S603 (fixed argv: a local tone fixture, no user input)
        [
            shutil.which("ffmpeg") or "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-c:a",
            "aac",
            str(path),
        ],
        check=True,
    )


class _Signal:
    def __init__(self):
        self.values: list = []

    def emit(self, value):
        self.values.append(value)


class _Relay:
    def __init__(self):
        self.track_event = _Signal()
        self.item = _Signal()
        self.list_item = _Signal()


class _Provider:
    """The Apple seam with one staged file and no network."""

    def __init__(self, staged: Path):
        self.staged = staged
        self.discarded: list = []

    def row_for(self, kind, item):
        return {
            "id": "apple:song-1",
            "title": "Xtal",
            "artist": "Aphex Twin",
            "artist_id": "apple:artist-1",
            "artists": [],
            "album": "Selected Ambient Works 85-92",
            "album_id": "apple:album-1",
            "num": 1,
            "vol": 1,
            "art": "",
            "year": "1992",
            "date": "1992-02-12",
            "duration": "4:53",
            "duration_sec": 293,
            "quality": "HIGH",
            "popularity": -1,
            "explicit": False,
            "added": "",
        }

    def get_object(self, kind, raw_id):
        return {"id": raw_id}

    def has_atmos(self, item):
        return False

    def track_facts(self, raw):
        return {
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
            "album": {
                "name": "Selected Ambient Works 85-92",
                "num_tracks": 1,
                "num_volumes": None,
                "upc": "",
                "type": "",
            },
        }

    def cover_url(self, obj, dimension):
        return ""

    def advertised_ceiling(self, obj):
        return quality_rank(QualityTier.HIGH)

    def classify_refusal(self, exc):
        from waves.providers.base import Refusal, RefusalKind

        return Refusal(RefusalKind.FAILURE, str(exc))

    def resolve_stream(self, raw, tier, audio_type):
        return SimpleNamespace(
            local_file=str(self.staged),
            delivered={"tier": QualityTier.HIGH.value, "audio_type": "stereo"},
            codecs="mp4a.40.2",
        )

    def discard_delivery(self, local_file):
        self.discarded.append(local_file)


def _settings(base: Path):
    return SimpleNamespace(
        data=SimpleNamespace(
            download_base_path=str(base),
            skip_existing=True,
            apple_quality_audio="HIGH",
            default_audio_type="stereo",
            mark_explicit=False,
            metadata_target_upc="UPC",
            path_binary_ffmpeg="",
            extract_flac=True,
            extract_flac_all=False,
        )
    )


@needs_ffmpeg
def test_one_job_lands_through_a_minimal_hooks_object(tmp_path):
    staged = tmp_path / "staged.m4a"
    _tone(staged)
    provider = _Provider(staged)
    base = tmp_path / "lib"
    relay = _Relay()
    statuses: list[str] = []
    hooks = runner.AppleJobHooks(
        provider=lambda: provider,
        settings=lambda: _settings(base),
        status=statuses.append,
    )
    spec = SimpleNamespace(kind="track", collection=False, media_id="apple:song-1")

    summary = runner.run_apple_job(
        hooks,
        1,
        spec,
        {"id": "song-1"},
        signals=relay,
        job_abort=Event(),
        file_template="{artist_name}/{track_title}",
    )

    assert summary == ""
    landed = base / "Aphex Twin" / "Xtal.m4a"
    assert landed.is_file()
    assert [ev["status"] for ev in relay.track_event.values] == ["running", "done"]
    assert relay.item.values[-1] == 100.0
    assert provider.discarded == [str(staged)]
