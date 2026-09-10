"""Apple job runner: queue entry, gates, delivery, events, settlement."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from waves.constants import CTX_APPLE, QualityTier, quality_rank
from waves.helper.exceptions import DownloadIncomplete
from waves.providers.base import AudioType
from waves.waves_ui.backend import WavesBridge

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def _ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    assert path is not None  # guarded by needs_ffmpeg
    return path


def _song_resource(song_id="song-1", atmos=True):
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


def _album_resource():
    return {
        "id": "album-1",
        "type": "albums",
        "attributes": {
            "name": "Selected Ambient Works 85-92",
            "artistName": "Aphex Twin",
            "artwork": {"url": "https://img/album/{w}x{h}bb.jpg"},
            "releaseDate": "1992-02-12",
            "trackCount": 13,
            "durationInMillis": 4455000,
            "audioTraits": ["lossless"],
        },
        "relationships": {"tracks": {"data": [_song_resource()]}},
    }


def _track_row():
    return {
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


def _album_row():
    return {
        "id": "apple:album-1",
        "title": "Selected Ambient Works 85-92",
        "artist": "Aphex Twin",
        "artist_id": "apple:artist-1",
        "artists": [{"id": "apple:artist-1", "name": "Aphex Twin", "roles": []}],
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


class _Signal:
    def __init__(self):
        self.emits: list = []

    def emit(self, *args):
        self.emits.append(args[0] if len(args) == 1 else args)


class _Relay:
    """The _ProgressSignals shape the runner drives (captured, not queued)."""

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
    """The Apple seam, with a scripted fetch (copies a fixture file)."""

    def __init__(self, fixture: Path | None = None):
        self.fixture = fixture
        self.fetched: list = []
        self.discarded: list = []

    def row_for(self, kind, item):
        if kind == "track":
            return _track_row()
        if kind == "album":
            return _album_row()
        raise KeyError(kind)

    def collection_items(self, obj, include_videos=True):
        return [_track_row()]

    def collection_has_tracks(self, obj):
        return True

    def cached(self, kind, raw_id):
        return None

    def get_object(self, kind, raw_id):
        if kind == "track":
            return _song_resource()
        return _album_resource()

    def has_atmos(self, item):
        return True

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
        staged = Path(str(self.fixture))
        assert staged.is_file()
        self.fetched.append(audio_type)
        return SimpleNamespace(
            local_file=str(staged),
            delivered={"tier": QualityTier.HIGH.value, "audio_type": str(audio_type)},
            codecs="mp4a.40.2",
        )

    def discard_delivery(self, local_file):
        self.discarded.append(local_file)


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
        default_audio_type="stereo",
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
    )
    for key, value in overrides.items():
        setattr(data, key, value)
    return SimpleNamespace(data=data)


def _stub(base: Path, provider, **overrides):
    stub = SimpleNamespace(
        settings=_settings(base),
        providers={CTX_APPLE: provider},
        _ownership=SimpleNamespace(ownership_of=lambda tid: None),
        _redownload_overrides=set(),
        _queue_index={1: {"askQuality": "HIGH", "quality": "HIGH"}},
        downloadState=_Signal(),
        downloadProgress=_Signal(),
    )
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
        "_apple_guess_ext",
        "_apple_wants_flac",
        "_apple_flac_scope_all",
        "_apple_flac_mode",
        "_apple_flac_ffmpeg",
        "_apple_extract_flac",
        "_apple_verify_staged",
        "_apple_probe",
        "_apple_place_file",
        "_apple_lyrics",
        "_apple_wants_cover",
        "_apple_cover_bytes",
        "_apple_write_sidecars",
        "_apple_cookies_ready",
        "_run_apple_job",
    ):
        setattr(stub, name, getattr(WavesBridge, name).__get__(stub))
    # Per-provider option + template-flag readers used by the bound bodies.
    for name in ("_psetting", "_tag_write_flags"):
        setattr(stub, name, getattr(WavesBridge, name).__get__(stub))
    return stub


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


@needs_ffmpeg
def test_single_track_lands_tagged_with_done_event(tmp_path, monkeypatch):
    from waves import apple_engine

    monkeypatch.setattr(
        apple_engine, "probe_audio_file", lambda path, ffprobe_path="": {"codec": "aac", "sample_rate": "44100"}
    )
    staged = tmp_path / "staged.m4a"
    _tone(staged)
    provider = _FakeProvider(fixture=staged)
    base = tmp_path / "lib"
    stub = _bind(_stub(base, provider))
    relay = _Relay()
    spec = SimpleNamespace(kind="track", collection=False, media_id="apple:song-1")

    summary = WavesBridge._run_apple_job(
        stub, 1, spec, _song_resource(), signals=relay, job_abort=Event(), file_template="{artist_name}/{track_title}"
    )

    assert summary == ""
    landed = base / "Aphex Twin" / "Xtal.m4a"
    assert landed.is_file()
    statuses = [ev["status"] for ev in relay.events if ev["id"] == "apple:song-1"]
    assert statuses[0] == "running" and statuses[-1] == "done"
    done = next(ev for ev in relay.events if ev.get("status") == "done")
    assert done["quality"]["tier"] == QualityTier.HIGH.value
    assert done["path"] == str(landed)
    import mutagen.mp4

    tags = mutagen.mp4.MP4(str(landed)).tags
    assert bytes(tags["----:com.apple.iTunes:WAVES_ITEM_ID"][0]) == b"apple:song-1"
    assert not any("WAVES_TIDAL" in key for key in tags)
    assert relay.pcts[-1] == 100.0
    assert provider.discarded == [str(staged)]


@needs_ffmpeg
def test_owned_track_skips_without_fetching(tmp_path, monkeypatch):
    from waves import apple_engine

    monkeypatch.setattr(
        apple_engine, "probe_audio_file", lambda path, ffprobe_path="": {"codec": "aac", "sample_rate": "44100"}
    )
    staged = tmp_path / "staged.m4a"
    _tone(staged)
    provider = _FakeProvider(fixture=staged)
    base = tmp_path / "lib"
    rec = {
        "path": str(base / "Aphex Twin" / "Xtal.m4a"),
        "quality_rank": quality_rank(QualityTier.HIGH),
        "requested_rank": quality_rank(QualityTier.HIGH),
        "ceiling_rank": quality_rank(QualityTier.HIGH),
        "audio_mode": "STEREO",
    }
    stub = _bind(_stub(base, provider, _ownership=SimpleNamespace(ownership_of=lambda tid: rec)))
    relay = _Relay()
    spec = SimpleNamespace(kind="track", collection=False, media_id="apple:song-1")

    summary = WavesBridge._run_apple_job(
        stub, 1, spec, _song_resource(), signals=relay, job_abort=Event(), file_template="{artist_name}/{track_title}"
    )

    assert summary == " (already downloaded)"
    assert provider.fetched == []
    assert any(ev.get("status") == "skipped" for ev in relay.events)


def test_gate_force_and_miss():
    provider = _FakeProvider()
    stub = _bind(_stub(Path("/tmp"), provider))

    assert WavesBridge._apple_gate_track(stub, provider, "apple:song-1", quality_rank(QualityTier.HIGH), True) == (
        "force",
        None,
    )
    assert WavesBridge._apple_gate_track(stub, provider, "apple:song-1", quality_rank(QualityTier.HIGH), False) == (
        None,
        None,
    )


def test_gate_without_a_store_never_gates():
    provider = _FakeProvider()
    stub = _bind(_stub(Path("/tmp"), provider, _ownership=None))

    assert WavesBridge._apple_gate_track(stub, provider, "apple:song-1", quality_rank(QualityTier.HIGH), False) == (
        None,
        None,
    )


@needs_ffmpeg
def test_both_default_fetches_atmos_and_reports_it(tmp_path, monkeypatch):
    from waves import apple_engine

    monkeypatch.setattr(
        apple_engine, "probe_audio_file", lambda path, ffprobe_path="": {"codec": "eac3", "sample_rate": "48000"}
    )
    staged = tmp_path / "staged.m4a"
    _tone(staged)
    provider = _FakeProvider(fixture=staged)
    base = tmp_path / "lib"
    settings = _settings(base, default_audio_type="both")
    stub = _bind(_stub(base, provider))
    stub.settings = settings
    relay = _Relay()
    spec = SimpleNamespace(kind="track", collection=False, media_id="apple:song-1")

    summary = WavesBridge._run_apple_job(
        stub, 1, spec, _song_resource(), signals=relay, job_abort=Event(), file_template="{artist_name}/{track_title}"
    )

    assert summary == ""
    assert provider.fetched == [AudioType.ATMOS]
    done = next(ev for ev in relay.events if ev.get("status") == "done")
    assert done["quality"]["audio_mode"] == "DOLBY_ATMOS"


def test_album_job_reports_a_partial_shortfall(tmp_path):
    provider = _FakeProvider(fixture=None)

    def fail_resolve(raw, tier, audio_type):
        raise RuntimeError("network died")

    provider.resolve_stream = fail_resolve
    base = tmp_path / "lib"
    stub = _bind(_stub(base, provider))
    relay = _Relay()
    spec = SimpleNamespace(kind="album", collection=True, media_id="apple:album-1")

    with pytest.raises(DownloadIncomplete):
        WavesBridge._run_apple_job(
            stub,
            1,
            spec,
            _album_resource(),
            signals=relay,
            job_abort=Event(),
            file_template="{artist_name}/{track_title}",
        )

    assert any(ev.get("status") == "failed" for ev in relay.events)


def _entry_stub(base: Path, provider, cookies: Path | None):
    from collections import deque
    from threading import Lock

    stub = _bind(_stub(base, provider))
    stub._queue_seq = 0
    stub._queue = []
    stub._queue_index = {}
    stub._qdirty_added = []
    stub._queue_lock = Lock()
    stub._pending_qids = deque()
    stub._job_specs = {}
    stub._job_objs = {}
    stub.statuses = []
    stub._set_status = stub.statuses.append
    stub._enqueue = lambda *a, **k: WavesBridge._enqueue(stub, *a, **k)
    stub._emit_queue = lambda: None
    stub._pump_queue = lambda: None
    stub._download_gate = lambda: "ok"
    stub._ffmpeg_gate_holds = lambda *a: False
    stub._library_bulk_skip_on = lambda: False
    if cookies is not None:
        provider.cookies_path = str(cookies)
    return stub


def test_entry_without_cookies_explains_instead_of_queueing(tmp_path):
    provider = _FakeProvider()
    base = tmp_path / "lib"
    stub = _entry_stub(base, provider, None)

    WavesBridge._download_apple(
        stub, "album", _album_row(), _album_row(), "{artist_name}/{track_title}", True, "apple:album-1"
    )

    assert stub._queue == []
    assert any("cookies" in status for status in stub.statuses)


def test_entry_with_cookies_queues_an_apple_job(tmp_path):
    provider = _FakeProvider()
    base = tmp_path / "lib"
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape\n")
    stub = _entry_stub(base, provider, cookies)

    WavesBridge._download_apple(
        stub, "album", _album_row(), _album_row(), "{artist_name}/{track_title}", True, "apple:album-1"
    )

    (row,) = stub._queue
    assert row["type"] == "album" and row["status"] == "queued"
    assert row["expected"] == "HIGH" and row["quality"] == "HIGH"
    qid, spec = next(iter(stub._job_specs.items()))
    assert spec.provider_id == "apple" and spec.object_id == "apple:album-1"
    assert list(stub._pending_qids) == [qid]


class _InlinePool:
    @staticmethod
    def start(worker, priority: int = 0):
        worker.fn()


def test_track_slot_queues_from_provider_cache_without_network(tmp_path):
    provider = _FakeProvider()
    provider.cached = lambda kind, raw_id: _song_resource() if kind == "track" else None
    base = tmp_path / "lib"
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape\n")
    stub = _entry_stub(base, provider, cookies)
    stub.threadpool = _InlinePool()
    stub.downloadTrack = lambda tid: WavesBridge.downloadTrack(stub, tid)
    stub._download_apple_track = lambda tid: WavesBridge._download_apple_track(stub, tid)
    stub._download_apple = lambda *a, **k: WavesBridge._download_apple(stub, *a, **k)
    stub._objs = {"track": {}}
    stub._refetch_apple_for_download = lambda *a: (_ for _ in ()).throw(AssertionError("no refetch expected"))

    stub.downloadTrack("apple:song-1")

    assert len(stub._queue) == 1
    assert stub._queue[0]["media_id"] == "apple:song-1"


def test_track_slot_refetches_a_cache_miss_on_a_worker(tmp_path):
    provider = _FakeProvider()
    base = tmp_path / "lib"
    stub = _entry_stub(base, provider, None)
    stub.threadpool = _InlinePool()
    stub._objs = {"track": {}}
    stub._refetch_inflight = set()
    stub._browse_gen = 0
    stub._mediaRefetched = _Signal()
    stub._bump_download_groups = lambda *a: None
    stub.downloadTrack = lambda tid: WavesBridge.downloadTrack(stub, tid)
    stub._download_apple_track = lambda tid: WavesBridge._download_apple_track(stub, tid)
    stub._refetch_apple_for_download = lambda *a, **k: WavesBridge._refetch_apple_for_download(stub, *a, **k)

    stub.downloadTrack("apple:song-1")

    assert stub._mediaRefetched.emits == [("track", "apple:song-1")]
    assert ("track", "apple:song-1") in stub._refetch_inflight


def test_configure_apple_provider_reads_settings(tmp_path):
    provider = _FakeProvider()
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape\n")
    stub = SimpleNamespace(
        providers={CTX_APPLE: provider},
        settings=_settings(tmp_path, apple_cookies_path=str(cookies)),
    )
    stub._configure_apple_provider = lambda: WavesBridge._configure_apple_provider(stub)
    stub._apple_cookies_ready = lambda: WavesBridge._apple_cookies_ready(stub)

    stub._configure_apple_provider()

    assert provider.cookies_path == str(cookies)
    assert stub._apple_cookies_ready() is True
    provider.cookies_path = str(tmp_path / "missing.txt")
    assert stub._apple_cookies_ready() is False


def test_second_click_on_a_queued_row_acknowledges_without_requeueing(tmp_path):
    provider = _FakeProvider()
    base = tmp_path / "lib"
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape\n")
    stub = _entry_stub(base, provider, cookies)

    WavesBridge._download_apple(
        stub, "album", _album_row(), _album_row(), "{artist_name}/{track_title}", True, "apple:album-1"
    )
    WavesBridge._download_apple(
        stub, "album", _album_row(), _album_row(), "{artist_name}/{track_title}", True, "apple:album-1"
    )

    assert len(stub._queue) == 1
    assert ("apple:album-1", "queued") in stub.downloadState.emits


@needs_ffmpeg
def test_stale_owned_copy_forces_an_in_place_overwrite(tmp_path, monkeypatch):
    from waves import apple_engine

    monkeypatch.setattr(
        apple_engine, "probe_audio_file", lambda path, ffprobe_path="": {"codec": "aac", "sample_rate": "44100"}
    )
    staged = tmp_path / "staged.m4a"
    _tone(staged)
    provider = _FakeProvider(fixture=staged)
    base = tmp_path / "lib"
    dest = base / "Aphex Twin" / "Xtal.m4a"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"stale-copy")
    rec = {
        "path": str(dest),
        "quality_rank": quality_rank(QualityTier.LOW),
        "requested_rank": quality_rank(QualityTier.LOW),
        "ceiling_rank": quality_rank(QualityTier.HIGH),
        "audio_mode": "STEREO",
    }
    stub = _bind(_stub(base, provider, _ownership=SimpleNamespace(ownership_of=lambda tid: rec)))
    relay = _Relay()
    spec = SimpleNamespace(kind="track", collection=False, media_id="apple:song-1")

    summary = WavesBridge._run_apple_job(
        stub, 1, spec, _song_resource(), signals=relay, job_abort=Event(), file_template="{artist_name}/{track_title}"
    )

    assert summary == ""
    assert dest.is_file() and dest.stat().st_size != len(b"stale-copy")
    assert not (base / "Aphex Twin" / "Xtal_01.m4a").exists()
    done = next(ev for ev in relay.events if ev.get("status") == "done")
    assert done["path"] == str(dest)


def test_retry_reroutes_an_apple_row_through_the_apple_entry(tmp_path):
    provider = _FakeProvider()
    base = tmp_path / "lib"
    stub = _entry_stub(base, provider, None)
    row = {
        "qid": 7,
        "type": "album",
        "name": "N",
        "template": "T",
        "collection": True,
        "media_id": "apple:album-1",
        "askQuality": "HIGH",
        "quality": "HIGH",
        "status": "failed",
    }
    calls = []
    stub._download_apple = lambda *a, **k: calls.append((a, k))

    WavesBridge._start_retry(stub, row, _album_row())

    ((args, kwargs),) = calls
    assert args[0] == "album" and args[5] == "apple:album-1"
    assert kwargs["keep_ask"] == ("HIGH", "HIGH", None)


def test_row_object_falls_back_to_the_provider_cache(tmp_path):
    provider = _FakeProvider()
    provider.cached = lambda kind, raw_id: _album_resource()
    stub = SimpleNamespace(
        _job_objs={},
        _objs={"album": {}},
        providers={CTX_APPLE: provider},
    )
    stub._row_object = lambda item: WavesBridge._row_object(stub, item)

    row = stub._row_object({"qid": 9, "type": "album", "media_id": "apple:album-1"})

    assert row["id"] == "apple:album-1"


@needs_ffmpeg
def test_lone_track_files_no_cover_without_the_single_track_option(tmp_path, monkeypatch):
    from waves import apple_engine

    monkeypatch.setattr(
        apple_engine, "probe_audio_file", lambda path, ffprobe_path="": {"codec": "aac", "sample_rate": "44100"}
    )
    staged = tmp_path / "staged.m4a"
    _tone(staged)
    provider = _FakeProvider(fixture=staged)
    base = tmp_path / "lib"
    stub = _bind(_stub(base, provider))
    relay = _Relay()
    spec = SimpleNamespace(kind="track", collection=False, media_id="apple:song-1")

    summary = WavesBridge._run_apple_job(
        stub, 1, spec, _song_resource(), signals=relay, job_abort=Event(), file_template="{artist_name}/{track_title}"
    )

    assert summary == ""
    assert not (base / "Aphex Twin" / "cover.jpg").exists()


@needs_ffmpeg
def test_album_job_writes_the_promised_playlist_file(tmp_path, monkeypatch):
    from waves import apple_engine

    monkeypatch.setattr(
        apple_engine, "probe_audio_file", lambda path, ffprobe_path="": {"codec": "aac", "sample_rate": "44100"}
    )
    staged = tmp_path / "staged.m4a"
    _tone(staged)
    provider = _FakeProvider(fixture=staged)
    base = tmp_path / "lib"
    settings = _settings(base, playlist_create=True)
    stub = _bind(_stub(base, provider))
    stub.settings = settings
    relay = _Relay()
    spec = SimpleNamespace(kind="album", collection=True, media_id="apple:album-1")

    summary = WavesBridge._run_apple_job(
        stub, 1, spec, _album_resource(), signals=relay, job_abort=Event(), file_template="{artist_name}/{track_title}"
    )

    assert summary == ""
    playlist = base / "Aphex Twin" / "_Selected Ambient Works 85-92.m3u8"
    assert playlist.is_file()
    assert playlist.read_text().splitlines() == ["Xtal.m4a"]


@needs_ffmpeg
def test_throttled_track_retries_in_place_then_lands(tmp_path, monkeypatch):
    from waves import apple_engine
    from waves.providers.apple import AppleProvider as _RealProvider

    monkeypatch.setattr(
        apple_engine, "probe_audio_file", lambda path, ffprobe_path="": {"codec": "aac", "sample_rate": "44100"}
    )
    staged = tmp_path / "staged.m4a"
    _tone(staged)
    provider = _FakeProvider(fixture=staged)
    calls = []

    def flaky_resolve(raw, tier, audio_type):
        calls.append(audio_type)
        if len(calls) == 1:
            raise RuntimeError("HTTP 429 too many requests")
        return _FakeProvider.resolve_stream(provider, raw, tier, audio_type)

    provider.resolve_stream = flaky_resolve
    provider.classify_refusal = lambda exc: _RealProvider.classify_refusal(provider, exc)
    base = tmp_path / "lib"
    stub = _bind(_stub(base, provider))
    stub._apple_sleep_abortable = lambda *a: True
    stub.statuses = []
    stub._set_status = stub.statuses.append
    relay = _Relay()
    spec = SimpleNamespace(kind="track", collection=False, media_id="apple:song-1")

    summary = WavesBridge._run_apple_job(
        stub, 1, spec, _song_resource(), signals=relay, job_abort=Event(), file_template="{artist_name}/{track_title}"
    )

    assert summary == ""
    assert len(calls) == 2
    assert next(ev for ev in relay.events if ev.get("status") == "done")


@needs_ffmpeg
def test_force_overwrites_the_owned_collision_path(tmp_path, monkeypatch):
    from waves import apple_engine

    monkeypatch.setattr(
        apple_engine, "probe_audio_file", lambda path, ffprobe_path="": {"codec": "aac", "sample_rate": "44100"}
    )
    staged = tmp_path / "staged.m4a"
    _tone(staged)
    provider = _FakeProvider(fixture=staged)
    base = tmp_path / "lib"
    sibling = base / "Aphex Twin" / "Xtal.m4a"
    sibling.parent.mkdir(parents=True)
    sibling.write_bytes(b"sibling-audio")
    owned = base / "Aphex Twin" / "Xtal_01.m4a"
    owned.write_bytes(b"stale-copy")
    rec = {
        "path": str(owned),
        "quality_rank": quality_rank(QualityTier.LOW),
        "requested_rank": quality_rank(QualityTier.LOW),
        "ceiling_rank": quality_rank(QualityTier.HIGH),
        "audio_mode": "STEREO",
    }
    stub = _bind(_stub(base, provider, _ownership=SimpleNamespace(ownership_of=lambda tid: rec)))
    relay = _Relay()
    spec = SimpleNamespace(kind="track", collection=False, media_id="apple:song-1")

    summary = WavesBridge._run_apple_job(
        stub, 1, spec, _song_resource(), signals=relay, job_abort=Event(), file_template="{artist_name}/{track_title}"
    )

    assert summary == ""
    assert sibling.read_bytes() == b"sibling-audio"
    assert owned.stat().st_size != len(b"stale-copy")
    done = next(ev for ev in relay.events if ev.get("status") == "done")
    assert done["path"] == str(owned)


def test_place_file_leaves_no_partials(tmp_path):
    stub = _bind(_stub(tmp_path, _FakeProvider()))
    src = tmp_path / "src.m4a"
    src.write_bytes(b"audio")
    dest = tmp_path / "lib" / "Xtal.m4a"
    dest.parent.mkdir(parents=True)

    WavesBridge._apple_place_file(stub, src, dest)

    assert dest.read_bytes() == b"audio"
    assert list(tmp_path.rglob("*.part-*")) == []
