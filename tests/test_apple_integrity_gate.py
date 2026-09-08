"""Integrity gate: verify, retry, quarantine, skip-list (issue #30, spec §6)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from waves.apple_integrity import (
    INTEGRITY_FAIL_MESSAGE,
    QUARANTINE_DIR_NAME,
    integrity_retries,
    integrity_retry_delay,
    is_outbreak_era,
    parse_encoded_date,
    quarantine_dest,
    resolve_quarantine_dir,
)
from waves.constants import CTX_APPLE, QualityTier, quality_rank
from waves.helper.exceptions import DownloadIncomplete
from waves.waves_ui.backend import WavesBridge

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def _ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    assert path is not None
    return path


def _tone(path: Path):
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
            "aac",
            str(path),
        ],
        check=True,
    )


def _song_resource(song_id="song-1", atmos=False):
    traits = ["lossless"]
    if atmos:
        traits.append("dolby-atmos")
    return {
        "id": song_id,
        "type": "songs",
        "attributes": {
            "name": "Xtal",
            "artistName": "Aphex Twin",
            "albumName": "Selected Ambient Works 85-92",
            "url": "https://music.apple.com/us/album/x/album-1?i=song-1",
            "artwork": {"url": "https://img/song/{w}x{h}bb.jpg"},
            "releaseDate": "1992-02-12",
            "durationInMillis": 293000,
            "trackNumber": 1,
            "discNumber": 1,
            "audioTraits": traits,
            "isrc": "GBAAA9200001",
        },
        "relationships": {"artists": {"data": [{"id": "artist-1"}]}},
    }


def _fragile_violet_resource():
    """The known-bad fixture album's title (TOGENASHI TOGEARI – Fragile Violet).

    Synthetic corrupt bytes stand in for Apple's unre-encoded source: the
    shape under test is quarantine + FAILED, not the network fetch.
    """
    res = _song_resource(song_id="fragile-violet-1")
    res["attributes"]["name"] = "Fragile Violet"
    res["attributes"]["artistName"] = "TOGENASHI TOGEARI"
    res["attributes"]["albumName"] = "Fragile Violet - Single"
    return res


def _track_row(track_id="apple:song-1", title="Xtal"):
    return {
        "id": track_id,
        "title": title,
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


def _album_resource():
    return {
        "id": "album-1",
        "type": "albums",
        "attributes": {
            "name": "Selected Ambient Works 85-92",
            "artistName": "Aphex Twin",
            "artwork": {"url": "https://img/album/{w}x{h}bb.jpg"},
            "releaseDate": "1992-02-12",
            "trackCount": 1,
            "durationInMillis": 293000,
            "audioTraits": ["lossless"],
        },
        "relationships": {"tracks": {"data": [_song_resource()]}},
    }


class _Signal:
    def __init__(self):
        self.emits: list = []

    def emit(self, *args):
        self.emits.append(args[0] if len(args) == 1 else args)


class _Relay:
    def __init__(self):
        self.events: list = []
        self.pcts: list = []

    class _E:
        def __init__(self, outer, name):
            self._outer = outer
            self._name = name

        def emit(self, value):
            if self._name == "track_event":
                self._outer.events.append(dict(value))
            else:
                self._outer.pcts.append(float(value))

    def __getattr__(self, name):
        if name in ("track_event", "list_item", "item"):
            return _Relay._E(self, name)
        raise AttributeError(name)


class _FakeProvider:
    """Apple seam with scripted staged files per attempt."""

    def __init__(self, staged_files: list[Path]):
        self._staged = list(staged_files)
        self.fetched: list = []
        self.discarded: list = []

    def row_for(self, kind, item):
        if kind == "track":
            attrs = (item.get("attributes") or {}) if isinstance(item, dict) else {}
            return _track_row(
                track_id=f"apple:{item.get('id', 'song-1')}",
                title=str(attrs.get("name") or "Xtal"),
            )
        return {
            "id": "apple:album-1",
            "title": "Selected Ambient Works 85-92",
            "artist": "Aphex Twin",
            "artist_id": "apple:artist-1",
            "artists": [],
            "art": "",
            "year": "1992",
            "date": "1992-02-12",
            "tracks": 1,
            "duration_sec": 293,
            "quality": "LOSSLESS",
            "popularity": -1,
            "explicit": False,
            "added": "",
        }

    def collection_items(self, obj, include_videos=True):
        return [_track_row()]

    def collection_has_tracks(self, obj):
        return True

    def cached(self, kind, raw_id):
        return None

    def get_object(self, kind, raw_id):
        if kind == "track":
            return _song_resource(raw_id)
        return _album_resource()

    def has_atmos(self, item):
        return False

    def track_facts(self, raw):
        raw_id = str((raw or {}).get("id") or "song-1") if isinstance(raw, dict) else "song-1"
        return {
            "item_id": f"apple:{raw_id}",
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
        if not self._staged:
            raise RuntimeError("no more staged fixtures")
        staged = self._staged.pop(0)
        self.fetched.append(audio_type)
        return SimpleNamespace(
            local_file=str(staged),
            delivered={"tier": QualityTier.HIGH.value, "audio_type": str(audio_type)},
            codecs="mp4a.40.2",
        )

    def discard_delivery(self, local_file):
        self.discarded.append(local_file)


class _SkipStore:
    """Minimal ownership stand-in with the skip-list surface."""

    def __init__(self):
        self.marks: dict[tuple[str, str], dict] = {}

    def ownership_of(self, tid, audio_type=None):
        return None

    def quarantine_add(self, track_id, audio_type=None, encoded_date=None):
        key = str(audio_type or "").strip().lower()
        key = key if key in ("stereo", "atmos") else ""
        self.marks[(str(track_id), key)] = {"encoded_date": encoded_date}

    def quarantine_remove(self, track_id, audio_type=None):
        if audio_type is None:
            for key in [k for k in self.marks if k[0] == str(track_id)]:
                del self.marks[key]
        else:
            key = str(audio_type or "").strip().lower()
            key = key if key in ("stereo", "atmos") else ""
            self.marks.pop((str(track_id), key), None)

    def is_quarantined(self, track_id, audio_type=None):
        if audio_type is None:
            for (tid, _), mark in self.marks.items():
                if tid == str(track_id):
                    return {"track_id": tid, **mark}
            return None
        key = str(audio_type or "").strip().lower()
        key = key if key in ("stereo", "atmos") else ""
        mark = self.marks.get((str(track_id), key))
        return {"track_id": str(track_id), **mark} if mark is not None else None


def _settings(base: Path, **overrides):
    data = SimpleNamespace(
        download_base_path=str(base),
        skip_existing=True,
        lyrics_embed=False,
        lyrics_file=False,
        lyrics_prefer_lrclib=True,
        lyrics_file_synced_only=False,
        metadata_cover_embed=False,
        metadata_cover_dimension="320",
        metadata_cover_file_dimension="follow",
        cover_album_file=False,
        cover_single_track_file=False,
        mark_explicit=False,
        metadata_target_upc="UPC",
        apple_quality_audio="HIGH",
        download_dolby_atmos=False,
        apple_cookies_path="",
        path_binary_ffmpeg="",
        format_track="{artist_name}/{track_title}",
        format_album="{artist_name}/{album_title}/{track_title}",
        format_playlist="Playlists/{playlist_name}/{track_title}",
        album_track_num_pad_min=1,
        filename_delimiter_artist=", ",
        filename_delimiter_album_artist=", ",
        filename_illegal_replacement="",
        filename_illegal_map=None,
        apple_integrity_retries=2,
        apple_integrity_retry_delay_sec=0,
        apple_quarantine_dir="",
        apple_quarantine_keep=True,
        playlist_create=False,
    )
    for key, value in overrides.items():
        setattr(data, key, value)
    return SimpleNamespace(data=data)


def _stub(base: Path, provider, **overrides):
    store = overrides.pop("_ownership_store", _SkipStore())
    stub = SimpleNamespace(
        settings=_settings(base),
        providers={CTX_APPLE: provider},
        _ownership=store,
        _redownload_overrides=set(),
        _queue_index={1: {"askQuality": "HIGH", "quality": "HIGH"}},
        downloadState=_Signal(),
        downloadProgress=_Signal(),
        statuses=[],
    )
    stub._set_status = stub.statuses.append
    stub._queue_item = lambda qid: stub._queue_index.get(qid)
    stub._job_quality = lambda qid: WavesBridge._job_quality(stub, qid)
    for key, value in overrides.items():
        setattr(stub, key, value)
    return stub


def _bind(stub):
    for name in (
        "_apple_audio_type",
        "_apple_wants_atmos",
        "_apple_target_rank",
        "_apple_emit_progress",
        "_apple_gate_track",
        "_apple_track_relative",
        "_apple_deliver_track",
        "_apple_verify_staged",
        "_apple_probe",
        "_apple_place_file",
        "_apple_lyrics",
        "_apple_wants_cover",
        "_apple_cover_bytes",
        "_apple_write_sidecars",
        "_apple_cookies_ready",
        "_apple_quarantine_root",
        "_apple_quarantine_keep",
        "_apple_skiplist_get",
        "_apple_skiplist_add",
        "_apple_skiplist_clear",
        "_apple_quarantine_file",
        "_apple_staged_encoded_date",
        "_run_apple_job",
    ):
        setattr(stub, name, getattr(WavesBridge, name).__get__(stub))
    # _is_integrity_failure is a staticmethod: bind without instance.
    stub._is_integrity_failure = WavesBridge._is_integrity_failure
    stub._apple_sleep_abortable = lambda *a: True
    return stub


# ----- pure helpers ----------------------------------------------------------


def test_quarantine_dir_defaults_inside_the_download_folder(tmp_path):
    root = resolve_quarantine_dir(tmp_path / "lib", None)
    assert root == tmp_path / "lib" / QUARANTINE_DIR_NAME


def test_quarantine_dir_custom_override_is_the_full_path(tmp_path):
    custom = tmp_path / "elsewhere" / "Q"
    assert resolve_quarantine_dir(tmp_path / "lib", custom) == custom


def test_quarantine_dir_matching_the_download_root_falls_back(tmp_path):
    base = tmp_path / "lib"
    assert resolve_quarantine_dir(base, base) == base / QUARANTINE_DIR_NAME
    assert resolve_quarantine_dir(base, str(base) + "/") == base / QUARANTINE_DIR_NAME


def test_quarantine_dir_above_the_download_root_falls_back(tmp_path):
    base = tmp_path / "lib" / "Waves"
    assert resolve_quarantine_dir(base, tmp_path) == base / QUARANTINE_DIR_NAME
    assert resolve_quarantine_dir(base, tmp_path / "lib") == base / QUARANTINE_DIR_NAME


def test_quarantine_dir_case_only_difference_stays_distinct(tmp_path):
    # On a case-sensitive filesystem these are two different folders: the
    # custom location stands, no silent fallback to the default.
    base = tmp_path / "music"
    base.mkdir()
    custom = tmp_path / "MUSIC"
    if os.path.exists(custom) and os.path.samefile(base, custom):
        pytest.skip("case-insensitive volume: spellings alias by design")
    assert resolve_quarantine_dir(base, custom) == custom


def test_quarantine_dest_keeps_the_intended_name(tmp_path):
    dest = quarantine_dest(tmp_path / "Q", "Aphex Twin/Xtal", ".m4a")
    assert dest == tmp_path / "Q" / "Aphex Twin" / "Xtal.m4a"


def test_encoded_date_parses_creation_time_and_bare_dates():
    assert parse_encoded_date("2025-06-23T04:06:21Z").isoformat() == "2025-06-23"
    assert parse_encoded_date("2025-05").isoformat() == "2025-05-01"
    assert parse_encoded_date("garbage") is None
    assert is_outbreak_era("2025-06-23") is True
    assert is_outbreak_era("2025-05-01") is True
    assert is_outbreak_era("2025-04-30") is False
    assert is_outbreak_era(None) is False


def test_integrity_budget_sharpens_for_outbreak_era():
    data = SimpleNamespace(apple_integrity_retries=2)
    assert integrity_retries(data, outbreak=False) == 2
    assert integrity_retries(data, outbreak=True) == 1
    assert integrity_retry_delay(SimpleNamespace(apple_integrity_retry_delay_sec=5.0)) == 5.0


def test_library_scan_excludes_the_quarantine_folder(tmp_path):
    from waves import library_index

    assert library_index._is_skipped_dir_name("Waves Quarantine") is True
    # A custom location is excluded by full path, never by basename: a common
    # basename must not prune legitimate same-named folders elsewhere.
    custom = tmp_path / "somewhere" / "Music"
    library_index.register_quarantine_dir(str(custom))
    assert library_index._is_skipped_dir_name("Music") is False
    assert library_index._is_quarantine_path(str(custom)) is True
    assert library_index._is_quarantine_path(str(custom / "Aphex Twin" / "Xtal.m4a")) is True
    assert library_index._is_quarantine_path(str(tmp_path / "lib" / "Music")) is False
    assert library_index._has_skipped_segment(str(custom / "Xtal.m4a"), str(tmp_path / "lib")) is True


def test_ownership_skiplist_is_per_version(tmp_path):
    from waves.ownership import OwnershipStore

    store = OwnershipStore(str(tmp_path / "own.db"))
    try:
        store.quarantine_add("apple:song-1", "atmos", "2025-06-23")
        assert store.is_quarantined("apple:song-1", "atmos") is not None
        assert store.is_quarantined("apple:song-1", "stereo") is None
        assert store.is_quarantined("apple:song-1") is not None
        store.quarantine_remove("apple:song-1", "atmos")
        assert store.is_quarantined("apple:song-1", "atmos") is None
    finally:
        store.close()


# ----- verification + retry + quarantine ------------------------------------


@needs_ffmpeg
def test_corrupt_staged_file_fails_verification(tmp_path, monkeypatch):
    from waves import apple_engine

    monkeypatch.setattr(
        apple_engine, "probe_audio_file", lambda path, ffprobe_path="": {"codec": "aac", "sample_rate": "44100"}
    )
    bad = tmp_path / "bad.m4a"
    bad.write_bytes(b"not audio at all, just text padding " * 100)
    provider = _FakeProvider([bad])
    base = tmp_path / "lib"
    stub = _bind(_stub(base, provider))

    with pytest.raises(apple_engine.AppleDownloadError):
        WavesBridge._apple_verify_staged(stub, bad, expect_atmos=False)


@needs_ffmpeg
def test_known_bad_fixture_quarantines_and_fails_in_plain_words(tmp_path, monkeypatch):
    from waves import apple_engine

    monkeypatch.setattr(
        apple_engine, "probe_audio_file", lambda path, ffprobe_path="": {"codec": "aac", "sample_rate": "44100"}
    )
    # Three corrupt attempts: the initial fetch + 2 automatic re-downloads.
    bad_files = []
    for i in range(3):
        bad = tmp_path / f"bad-{i}.m4a"
        bad.write_bytes(b"not audio at all, just text padding " * 100)
        bad_files.append(bad)
    provider = _FakeProvider(bad_files)
    base = tmp_path / "lib"
    store = _SkipStore()
    stub = _bind(_stub(base, provider, _ownership_store=store))
    relay = _Relay()
    spec = SimpleNamespace(kind="track", collection=False, media_id="apple:song-1")

    with pytest.raises(DownloadIncomplete) as excinfo:
        WavesBridge._run_apple_job(
            stub,
            1,
            spec,
            _song_resource(),
            signals=relay,
            job_abort=Event(),
            file_template="{artist_name}/{track_title}",
        )

    assert INTEGRITY_FAIL_MESSAGE in str(excinfo.value)
    assert len(provider.fetched) == 3
    assert any(ev.get("status") == "failed" for ev in relay.events)
    # Quarantine kept the bytes under the default folder with the intended name.
    quarantined = list((base / QUARANTINE_DIR_NAME).rglob("*.m4a"))
    assert len(quarantined) == 1
    assert store.is_quarantined("apple:song-1", "stereo") is not None
    # Nothing landed in the library.
    assert not (base / "Aphex Twin" / "Xtal.m4a").exists()


@needs_ffmpeg
def test_outbreak_era_file_quarantines_after_one_retry(tmp_path, monkeypatch):
    from waves import apple_engine

    monkeypatch.setattr(
        apple_engine, "probe_audio_file", lambda path, ffprobe_path="": {"codec": "aac", "sample_rate": "44100"}
    )
    # Outbreak-era Encoded date forces the sharpened budget: 2 attempts total.
    monkeypatch.setattr(WavesBridge, "_apple_staged_encoded_date", lambda self, staged: "2025-06-23")
    bad_files = []
    for i in range(3):
        bad = tmp_path / f"bad-{i}.m4a"
        bad.write_bytes(b"not audio at all, just text padding " * 100)
        bad_files.append(bad)
    provider = _FakeProvider(bad_files)
    base = tmp_path / "lib"
    stub = _bind(_stub(base, provider))
    relay = _Relay()
    spec = SimpleNamespace(kind="track", collection=False, media_id="apple:song-1")

    with pytest.raises(DownloadIncomplete):
        WavesBridge._run_apple_job(
            stub,
            1,
            spec,
            _song_resource(),
            signals=relay,
            job_abort=Event(),
            file_template="{artist_name}/{track_title}",
        )

    assert len(provider.fetched) == 2


@needs_ffmpeg
def test_clean_album_downloads_normally_after_a_quarantine(tmp_path, monkeypatch):
    from waves import apple_engine

    monkeypatch.setattr(
        apple_engine, "probe_audio_file", lambda path, ffprobe_path="": {"codec": "aac", "sample_rate": "44100"}
    )
    good = tmp_path / "good.m4a"
    _tone(good)
    provider = _FakeProvider([good])
    base = tmp_path / "lib"
    stub = _bind(_stub(base, provider))
    relay = _Relay()
    spec = SimpleNamespace(kind="track", collection=False, media_id="apple:song-1")

    summary = WavesBridge._run_apple_job(
        stub, 1, spec, _song_resource(), signals=relay, job_abort=Event(), file_template="{artist_name}/{track_title}"
    )

    assert summary == ""
    assert (base / "Aphex Twin" / "Xtal.m4a").is_file()


@needs_ffmpeg
def test_skiplisted_track_autoskips_bulk_runs_plainly(tmp_path, monkeypatch):
    from waves import apple_engine

    monkeypatch.setattr(
        apple_engine, "probe_audio_file", lambda path, ffprobe_path="": {"codec": "aac", "sample_rate": "44100"}
    )
    good = tmp_path / "good.m4a"
    _tone(good)
    provider = _FakeProvider([good])
    base = tmp_path / "lib"
    store = _SkipStore()
    store.quarantine_add("apple:song-1", "stereo", "2025-06-23")
    stub = _bind(_stub(base, provider, _ownership_store=store))
    relay = _Relay()
    spec = SimpleNamespace(kind="album", collection=True, media_id="apple:album-1")

    summary = WavesBridge._run_apple_job(
        stub, 1, spec, _album_resource(), signals=relay, job_abort=Event(), file_template="{artist_name}/{track_title}"
    )

    assert summary == " (already downloaded)"
    assert provider.fetched == []
    assert any(ev.get("status") == "skipped" for ev in relay.events)


@needs_ffmpeg
def test_redownload_reattempts_and_clears_when_apple_reencodes(tmp_path, monkeypatch):
    from waves import apple_engine

    monkeypatch.setattr(
        apple_engine, "probe_audio_file", lambda path, ffprobe_path="": {"codec": "aac", "sample_rate": "44100"}
    )
    good = tmp_path / "good.m4a"
    _tone(good)
    provider = _FakeProvider([good])
    base = tmp_path / "lib"
    store = _SkipStore()
    store.quarantine_add("apple:song-1", "stereo", "2025-06-23")
    stub = _bind(_stub(base, provider, _ownership_store=store))
    stub._redownload_overrides = {"apple:song-1"}
    relay = _Relay()
    spec = SimpleNamespace(kind="track", collection=False, media_id="apple:song-1")

    summary = WavesBridge._run_apple_job(
        stub, 1, spec, _song_resource(), signals=relay, job_abort=Event(), file_template="{artist_name}/{track_title}"
    )

    assert summary == ""
    assert len(provider.fetched) == 1
    assert store.is_quarantined("apple:song-1", "stereo") is None


@needs_ffmpeg
def test_corrupt_atmos_never_blocks_its_stereo_sibling(tmp_path, monkeypatch):
    from waves import apple_engine

    monkeypatch.setattr(
        apple_engine, "probe_audio_file", lambda path, ffprobe_path="": {"codec": "aac", "sample_rate": "44100"}
    )
    store = _SkipStore()
    store.quarantine_add("apple:song-1", "atmos", "2025-06-23")
    # A stereo job must not see the Atmos mark.
    assert store.is_quarantined("apple:song-1", "stereo") is None
    good = tmp_path / "good.m4a"
    _tone(good)
    provider = _FakeProvider([good])
    base = tmp_path / "lib"
    stub = _bind(_stub(base, provider, _ownership_store=store))
    relay = _Relay()
    spec = SimpleNamespace(kind="track", collection=False, media_id="apple:song-1")

    summary = WavesBridge._run_apple_job(
        stub, 1, spec, _song_resource(), signals=relay, job_abort=Event(), file_template="{artist_name}/{track_title}"
    )

    assert summary == ""
    assert (base / "Aphex Twin" / "Xtal.m4a").is_file()


@needs_ffmpeg
def test_stereo_verification_accepts_alac_for_the_wrapper_tier(tmp_path, monkeypatch):
    from waves import apple_engine

    monkeypatch.setattr(
        apple_engine, "probe_audio_file", lambda path, ffprobe_path="": {"codec": "alac", "sample_rate": "44100"}
    )
    monkeypatch.setattr(apple_engine, "decode_check", lambda staged, ffmpeg_path="": None)
    good = tmp_path / "good.m4a"
    good.write_bytes(b"fake-alac-bytes")
    provider = _FakeProvider([good])
    base = tmp_path / "lib"
    stub = _bind(_stub(base, provider))

    # Must not raise: ALAC stereo is a valid delivery, not a codec mismatch.
    WavesBridge._apple_verify_staged(stub, good, expect_atmos=False)


@needs_ffmpeg
def test_retry_spec_bypasses_the_skiplist(tmp_path, monkeypatch):
    """A retried row carries is_retry on its spec and bypasses the auto-skip;
    a fresh click afterwards skips again (REDOWNLOAD stays the way back)."""
    from waves import apple_engine

    monkeypatch.setattr(
        apple_engine, "probe_audio_file", lambda path, ffprobe_path="": {"codec": "aac", "sample_rate": "44100"}
    )
    good = tmp_path / "good.m4a"
    _tone(good)
    provider = _FakeProvider([good])
    base = tmp_path / "lib"
    store = _SkipStore()
    store.quarantine_add("apple:song-1", "stereo", "2025-06-23")
    stub = _bind(_stub(base, provider, _ownership_store=store))
    relay = _Relay()
    spec = SimpleNamespace(kind="track", collection=False, media_id="apple:song-1", is_retry=True)

    summary = WavesBridge._run_apple_job(
        stub, 1, spec, _song_resource(), signals=relay, job_abort=Event(), file_template="{artist_name}/{track_title}"
    )

    assert summary == ""
    assert len(provider.fetched) == 1
    # The verified copy cleared the mark, so the suite's other half (a fresh
    # spec skipping a live mark) is covered by the bulk auto-skip test.
    assert store.is_quarantined("apple:song-1", "stereo") is None


@needs_ffmpeg
def test_resolve_stage_integrity_failure_retries_and_marks_the_skiplist(tmp_path, monkeypatch):
    """The engine's own decode check can raise from resolve_stream (no staged
    file): the retry/quarantine path still applies, minus the quarantine bytes."""
    from waves import apple_engine
    from waves.apple_engine import AppleDownloadError

    monkeypatch.setattr(
        apple_engine, "probe_audio_file", lambda path, ffprobe_path="": {"codec": "aac", "sample_rate": "44100"}
    )
    calls: list = []

    class _RaisingProvider(_FakeProvider):
        def resolve_stream(self, raw, tier, audio_type):
            calls.append(audio_type)
            raise AppleDownloadError("The Apple download failed its integrity check")

    provider = _RaisingProvider([])
    base = tmp_path / "lib"
    store = _SkipStore()
    stub = _bind(_stub(base, provider, _ownership_store=store))
    relay = _Relay()
    spec = SimpleNamespace(kind="track", collection=False, media_id="apple:song-1")

    with pytest.raises(DownloadIncomplete) as excinfo:
        WavesBridge._run_apple_job(
            stub,
            1,
            spec,
            _song_resource(),
            signals=relay,
            job_abort=Event(),
            file_template="{artist_name}/{track_title}",
        )

    assert INTEGRITY_FAIL_MESSAGE in str(excinfo.value)
    assert len(calls) == 3
    assert store.is_quarantined("apple:song-1", "stereo") is not None
    assert not list((base / QUARANTINE_DIR_NAME).rglob("*.m4a"))


@needs_ffmpeg
def test_retry_bypass_covers_every_track_of_a_collection(tmp_path, monkeypatch):
    from waves import apple_engine

    monkeypatch.setattr(
        apple_engine, "probe_audio_file", lambda path, ffprobe_path="": {"codec": "aac", "sample_rate": "44100"}
    )

    def _row(song_id, title):
        row = _track_row(track_id=f"apple:{song_id}", title=title)
        return row

    def _res(song_id, title):
        res = _song_resource(song_id)
        res["attributes"]["name"] = title
        return res

    class _TwoTrackProvider(_FakeProvider):
        def collection_items(self, obj, include_videos=True):
            return [_row("song-1", "One"), _row("song-2", "Two")]

        def get_object(self, kind, raw_id):
            if kind == "track":
                return _res(raw_id, "One" if raw_id == "song-1" else "Two")
            return _album_resource()

    good_files = []
    for i in range(2):
        good = tmp_path / f"good-{i}.m4a"
        _tone(good)
        good_files.append(good)
    provider = _TwoTrackProvider(good_files)
    base = tmp_path / "lib"
    store = _SkipStore()
    store.quarantine_add("apple:song-1", "stereo", "2025-06-23")
    store.quarantine_add("apple:song-2", "stereo", "2025-06-23")
    stub = _bind(_stub(base, provider, _ownership_store=store))
    relay = _Relay()
    spec = SimpleNamespace(kind="album", collection=True, media_id="apple:album-1", is_retry=True)

    summary = WavesBridge._run_apple_job(
        stub, 1, spec, _album_resource(), signals=relay, job_abort=Event(), file_template="{artist_name}/{track_title}"
    )

    assert summary == ""
    assert len(provider.fetched) == 2


@needs_ffmpeg
def test_atmos_rejects_plain_ac3(tmp_path, monkeypatch):
    from waves import apple_engine
    from waves.apple_engine import AppleDownloadError

    monkeypatch.setattr(
        apple_engine, "probe_audio_file", lambda path, ffprobe_path="": {"codec": "ac3", "sample_rate": "48000"}
    )
    monkeypatch.setattr(apple_engine, "decode_check", lambda staged, ffmpeg_path="": None)
    bad = tmp_path / "ac3.m4a"
    bad.write_bytes(b"fake-ac3-bytes")
    provider = _FakeProvider([bad])
    base = tmp_path / "lib"
    stub = _bind(_stub(base, provider))

    with pytest.raises(AppleDownloadError):
        WavesBridge._apple_verify_staged(stub, bad, expect_atmos=True)


@needs_ffmpeg
def test_success_after_a_retry_leaves_no_hold_dirs(tmp_path, monkeypatch):

    from waves import apple_engine

    monkeypatch.setenv("TMPDIR", str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()
    monkeypatch.setattr(
        apple_engine, "probe_audio_file", lambda path, ffprobe_path="": {"codec": "aac", "sample_rate": "44100"}
    )
    bad = tmp_path / "bad.m4a"
    bad.write_bytes(b"not audio at all, just text padding " * 100)
    good = tmp_path / "good.m4a"
    _tone(good)
    provider = _FakeProvider([bad, good])
    base = tmp_path / "lib"
    stub = _bind(_stub(base, provider))
    relay = _Relay()
    spec = SimpleNamespace(kind="track", collection=False, media_id="apple:song-1")

    summary = WavesBridge._run_apple_job(
        stub, 1, spec, _song_resource(), signals=relay, job_abort=Event(), file_template="{artist_name}/{track_title}"
    )

    assert summary == ""
    assert len(provider.fetched) == 2
    leftovers = [p for p in (tmp_path / "tmp").iterdir() if p.name.startswith("waves-apple-quarantine-")]
    assert leftovers == []


@needs_ffmpeg
def test_engine_rejected_bytes_are_quarantined_with_their_date(tmp_path, monkeypatch):
    """An integrity failure raised from resolve_stream carries the rejected
    bytes on the exception (the engine transfers workdir ownership outward):
    they are quarantined with their Encoded date, and the workdir is removed."""
    from waves import apple_engine
    from waves.apple_engine import AppleIntegrityError

    monkeypatch.setattr(
        apple_engine, "probe_audio_file", lambda path, ffprobe_path="": {"codec": "aac", "sample_rate": "44100"}
    )
    workdir = tmp_path / "engine-workdir"
    workdir.mkdir()
    bad = workdir / "staged.m4a"
    bad.write_bytes(b"not audio at all, just text padding " * 100)

    calls: list = []

    class _EngineRejectingProvider(_FakeProvider):
        def resolve_stream(self, raw, tier, audio_type):
            calls.append(audio_type)
            if len(calls) < 3:
                raise AppleIntegrityError(
                    "The Apple download failed its integrity check",
                    staged_path=str(bad),
                    workdir=str(workdir),
                )
            return _FakeProvider.resolve_stream(self, raw, tier, audio_type)

    good = tmp_path / "good.m4a"
    _tone(good)
    provider = _EngineRejectingProvider([good])
    base = tmp_path / "lib"
    store = _SkipStore()
    stub = _bind(_stub(base, provider, _ownership_store=store))
    relay = _Relay()
    spec = SimpleNamespace(kind="track", collection=False, media_id="apple:song-1")

    summary = WavesBridge._run_apple_job(
        stub, 1, spec, _song_resource(), signals=relay, job_abort=Event(), file_template="{artist_name}/{track_title}"
    )

    assert summary == ""
    assert len(calls) == 3
    assert not workdir.exists()
    assert (base / "Aphex Twin" / "Xtal.m4a").is_file()


@needs_ffmpeg
def test_no_audio_probe_failure_counts_as_integrity(tmp_path, monkeypatch):
    from waves import apple_engine
    from waves.apple_engine import AppleDownloadError

    def _no_audio(path, ffprobe_path=""):
        raise AppleDownloadError("The Apple download has no playable audio stream")

    monkeypatch.setattr(apple_engine, "probe_audio_file", _no_audio)
    bad_files = []
    for i in range(3):
        bad = tmp_path / f"bad-{i}.m4a"
        bad.write_bytes(b"not audio at all, just text padding " * 100)
        bad_files.append(bad)
    provider = _FakeProvider(bad_files)
    base = tmp_path / "lib"
    store = _SkipStore()
    stub = _bind(_stub(base, provider, _ownership_store=store))
    relay = _Relay()
    spec = SimpleNamespace(kind="track", collection=False, media_id="apple:song-1")

    with pytest.raises(DownloadIncomplete) as excinfo:
        WavesBridge._run_apple_job(
            stub, 1, spec, _song_resource(), signals=relay, job_abort=Event(), file_template="{artist_name}/{track_title}"
        )

    assert INTEGRITY_FAIL_MESSAGE in str(excinfo.value)
    assert len(provider.fetched) == 3
    assert store.is_quarantined("apple:song-1", "stereo") is not None


def test_custom_quarantine_cached_rows_retire_on_rescan(tmp_path):
    import os

    from waves import library_index
    from waves.library_index import LibraryIndex

    lib = os.path.join(str(tmp_path), "lib")
    album = os.path.join(lib, "Aphex Twin", "[1992] SAW")
    os.makedirs(album, exist_ok=True)
    open(os.path.join(album, "01.flac"), "w").close()
    custom = os.path.join(lib, "Holding Bay")
    os.makedirs(custom, exist_ok=True)
    open(os.path.join(custom, "bad.m4a"), "w").close()
    tags = {
        album: {"album": "SAW", "artist": "Aphex Twin", "date": "1992"},
        custom: {"album": "Holding Bay", "artist": "Nobody", "date": "2025"},
    }

    def read_tags(path):
        return tags.get(os.path.dirname(path))

    idx = LibraryIndex(str(tmp_path / "lib.sqlite3"), read_tags=read_tags)
    try:
        assert idx.refresh(lib) == 2
        # Registering the custom folder retires its cached subtree on the
        # next scan (warm, unchanged mtimes): no re-list, no badge.
        library_index.register_quarantine_dir(custom)
        assert idx.refresh(lib) == 1
        assert [a["id"] for a in idx.iter_albums()] != []
        assert all("Holding Bay" not in str(a.get("id", "")) for a in idx.iter_albums())
    finally:
        idx.close()


@needs_ffmpeg
def test_dual_version_retry_bypasses_both_versions(tmp_path, monkeypatch):
    """Two failed rows sharing one media_id each carry is_retry on their own
    spec, so both Version jobs bypass on their own with nothing counted,
    released, or leaked (the Codex dual-RETRY ALL case)."""
    from waves import apple_engine

    # The staged fixture's name decides the probed codec, so each Version
    # verifies against the family it asked for (a real run probes real bytes).
    monkeypatch.setattr(
        apple_engine,
        "probe_audio_file",
        lambda path, ffprobe_path="": {
            "codec": "eac3" if "atmos" in str(path) else "aac",
            "sample_rate": "48000" if "atmos" in str(path) else "44100",
        },
    )
    store = _SkipStore()
    store.quarantine_add("apple:song-1", "stereo", "2025-06-23")
    store.quarantine_add("apple:song-1", "atmos", "2025-06-23")
    base = tmp_path / "lib"
    relay = _Relay()

    good_stereo = tmp_path / "good-stereo.m4a"
    _tone(good_stereo)
    good_atmos = tmp_path / "good-atmos.m4a"
    _tone(good_atmos)

    def _run_shared(version, fixture):
        provider = _FakeProvider([fixture])
        if version == "atmos":
            provider.has_atmos = lambda item: True
        stub = _bind(_stub(base, provider, _ownership_store=store))
        # Dual rows land through different templates (the Atmos subfolder),
        # so the sibling's file is not an owned collision.
        template = "{artist_name}/{track_title}" if version == "stereo" else "{artist_name}/Dolby Atmos/{track_title}"
        spec = SimpleNamespace(
            kind="track", collection=False, media_id="apple:song-1", audio_type=version, is_retry=True
        )
        summary = WavesBridge._run_apple_job(
            stub, 1, spec, _song_resource(), signals=relay, job_abort=Event(), file_template=template
        )
        return summary, provider

    summary_st, provider_st = _run_shared("stereo", good_stereo)
    summary_at, provider_at = _run_shared("atmos", good_atmos)

    assert summary_st == "" and summary_at == ""
    assert len(provider_st.fetched) == 1 and len(provider_at.fetched) == 1
    assert store.is_quarantined("apple:song-1", "stereo") is None
    assert store.is_quarantined("apple:song-1", "atmos") is None


@needs_ffmpeg
def test_hold_cleaned_when_retry_fails_non_integrity(tmp_path, monkeypatch):

    from waves import apple_engine

    monkeypatch.setenv("TMPDIR", str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()
    monkeypatch.setattr(
        apple_engine, "probe_audio_file", lambda path, ffprobe_path="": {"codec": "aac", "sample_rate": "44100"}
    )
    bad = tmp_path / "bad.m4a"
    bad.write_bytes(b"not audio at all, just text padding " * 100)

    calls: list = []

    class _FlakyProvider(_FakeProvider):
        def resolve_stream(self, raw, tier, audio_type):
            calls.append(audio_type)
            if len(calls) == 1:
                return _FakeProvider.resolve_stream(self, raw, tier, audio_type)
            raise RuntimeError("network died")

    provider = _FlakyProvider([bad])
    base = tmp_path / "lib"
    store = _SkipStore()
    stub = _bind(_stub(base, provider, _ownership_store=store))
    relay = _Relay()
    spec = SimpleNamespace(kind="track", collection=False, media_id="apple:song-1")

    with pytest.raises(DownloadIncomplete):
        WavesBridge._run_apple_job(
            stub, 1, spec, _song_resource(), signals=relay, job_abort=Event(), file_template="{artist_name}/{track_title}"
        )

    # An ordinary failure: no quarantine wording, no skip-list mark, and the
    # earlier integrity hold was dropped instead of leaking into temp.
    assert len(calls) == 2
    assert store.is_quarantined("apple:song-1", "stereo") is None
    leftovers = [p for p in (tmp_path / "tmp").iterdir() if p.name.startswith("waves-apple-quarantine-")]
    assert leftovers == []


def test_quarantine_sidecar_remembers_previous_roots(tmp_path):
    from waves.apple_integrity import known_quarantine_dirs, remember_quarantine_dir

    config = tmp_path / "config"
    assert known_quarantine_dirs(config) == []
    remember_quarantine_dir(config, str(tmp_path / "Q1"))
    remember_quarantine_dir(config, str(tmp_path / "Q2"))
    assert known_quarantine_dirs(config) == [str(tmp_path / "Q2"), str(tmp_path / "Q1")]
    # Re-remembering moves to the front without duplicating.
    remember_quarantine_dir(config, str(tmp_path / "Q1"))
    assert known_quarantine_dirs(config) == [str(tmp_path / "Q1"), str(tmp_path / "Q2")]


@needs_ffmpeg
def test_fallback_delivery_files_under_stereo(tmp_path, monkeypatch):
    """An Atmos ask for a stereo-only track falls back: the failure is filed
    under stereo, so the next stereo run sees the mark instead of refetching."""
    from waves import apple_engine

    monkeypatch.setattr(
        apple_engine, "probe_audio_file", lambda path, ffprobe_path="": {"codec": "aac", "sample_rate": "44100"}
    )
    bad_files = []
    for i in range(3):
        bad = tmp_path / f"bad-{i}.m4a"
        bad.write_bytes(b"not audio at all, just text padding " * 100)
        bad_files.append(bad)
    provider = _FakeProvider(bad_files)
    base = tmp_path / "lib"
    store = _SkipStore()
    stub = _bind(_stub(base, provider, _ownership_store=store))
    # The Atmos toggle is ON (a legacy single row asks Atmos); the track
    # itself is stereo-only, so the delivery falls back to stereo.
    stub.settings.data.download_dolby_atmos = True
    orig_resolve = provider.resolve_stream

    def _fallback_resolve(raw, tier, audio_type):
        # Mirror AppleProvider._delivery_atmos: the delivered word names the
        # actual fallback (stereo), never the ask.
        info = orig_resolve(raw, tier, audio_type)
        info.delivered["audio_type"] = "stereo"
        return info

    provider.resolve_stream = _fallback_resolve
    relay = _Relay()
    spec = SimpleNamespace(kind="track", collection=False, media_id="apple:song-1")

    with pytest.raises(DownloadIncomplete):
        WavesBridge._run_apple_job(
            stub, 1, spec, _song_resource(atmos=False), signals=relay, job_abort=Event(),
            file_template="{artist_name}/{track_title}",
        )

    assert store.is_quarantined("apple:song-1", "stereo") is not None
    assert store.is_quarantined("apple:song-1", "atmos") is None

    # And the next stereo-asked run sees the stereo mark (no refetch): the
    # gate reads the effective Version, not the Atmos ask.
    provider2 = _FakeProvider([])
    stub2 = _bind(_stub(base, provider2, _ownership_store=store))
    stub2.settings.data.download_dolby_atmos = False
    relay2 = _Relay()
    spec2 = SimpleNamespace(kind="track", collection=False, media_id="apple:song-1")
    summary2 = WavesBridge._run_apple_job(
        stub2, 1, spec2, _song_resource(atmos=False), signals=relay2, job_abort=Event(),
        file_template="{artist_name}/{track_title}",
    )
    assert summary2 == " (already downloaded)"
    assert provider2.fetched == []
    assert any(ev.get("status") == "skipped" for ev in relay2.events)


def test_quarantine_sidecar_keeps_every_root(tmp_path):
    from waves.apple_integrity import known_quarantine_dirs, remember_quarantine_dir

    config = tmp_path / "config"
    for i in range(12):
        remember_quarantine_dir(config, str(tmp_path / f"Q{i}"))
    assert len(known_quarantine_dirs(config)) == 12


@needs_ffmpeg
def test_resolve_stage_failure_files_under_effective_version(tmp_path, monkeypatch):
    """An engine-raised integrity failure (no StreamInfo) still files under
    the effective Version: an Atmos ask for a stereo-only track lands under
    stereo, with its preserved bytes quarantined."""
    from waves import apple_engine
    from waves.apple_engine import AppleIntegrityError

    monkeypatch.setattr(
        apple_engine, "probe_audio_file", lambda path, ffprobe_path="": {"codec": "aac", "sample_rate": "44100"}
    )
    workdir = tmp_path / "engine-workdir"
    workdir.mkdir()
    bad = workdir / "staged.m4a"
    bad.write_bytes(b"not audio at all, just text padding " * 100)

    class _EngineRejectingProvider(_FakeProvider):
        def resolve_stream(self, raw, tier, audio_type):
            raise AppleIntegrityError(
                "The Apple download failed its integrity check",
                staged_path=str(bad),
                workdir=str(workdir),
            )

    provider = _EngineRejectingProvider([])
    base = tmp_path / "lib"
    store = _SkipStore()
    stub = _bind(_stub(base, provider, _ownership_store=store))
    stub.settings.data.download_dolby_atmos = True
    relay = _Relay()
    spec = SimpleNamespace(kind="track", collection=False, media_id="apple:song-1")

    with pytest.raises(DownloadIncomplete) as excinfo:
        WavesBridge._run_apple_job(
            stub, 1, spec, _song_resource(atmos=False), signals=relay, job_abort=Event(),
            file_template="{artist_name}/{track_title}",
        )

    assert INTEGRITY_FAIL_MESSAGE in str(excinfo.value)
    assert store.is_quarantined("apple:song-1", "stereo") is not None
    assert store.is_quarantined("apple:song-1", "atmos") is None
    assert list((base / QUARANTINE_DIR_NAME).rglob("*.m4a")) != []
