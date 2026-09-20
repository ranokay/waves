"""The download pipeline routed through the Provider seam.

``Download`` is composed with a Provider,
stream resolution arrives as a neutral StreamInfo, the tag writer reads its
attribute facts from ``track_facts``, refusals classify through the provider,
and a queued job names its object as (provider_id, kind, namespaced id)
resolved via ``get_object`` at dispatch. TIDAL's own end-to-end behavior is
pinned byte-identical by the pre-existing suite; these tests pin the seam's
side of each contract, plus the two places the seam changes what a row can
say (dispatch-time resolution and its refusals).
"""

from __future__ import annotations

import base64
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from support.provider_fakes import BareProvider
from tidalapi.media import AudioMode, Quality

from waves.desktop.backend import WavesBridge
from waves.download import Download
from waves.model.downloader import TrackStreamInfo
from waves.providers import (
    AudioType,
    Capability,
    DownloadAdapter,
    QualityTier,
    Refusal,
    RefusalKind,
    StreamInfo,
    TidalProvider,
)

# ----------------------------------------------------------------- the fakes


def _dash_manifest(n_urls: int, repeats: int = 1) -> SimpleNamespace:
    """A stand-in TIDAL DASH manifest whose timeline proves ``n_urls`` carries
    ``tail`` over-generated URLs (the real arithmetic in providers/tidal_manifest.py
    runs on it: required = 1 init + (r+1) per S element)."""
    xml = (
        "<MPD><Period><AdaptationSet><Representation>"
        "<SegmentTimeline>"
        f'<S t="0" d="96000" r="{repeats}"/>'
        "</SegmentTimeline>"
        "</Representation></AdaptationSet></Period></MPD>"
    )
    required = 1 + repeats + 1
    urls = [f"https://seg/{i}" for i in range(max(n_urls, required))]
    manifest = SimpleNamespace(
        manifest_mime_type="application/dash+xml",
        manifest=base64.b64encode(xml.encode()).decode(),
        codecs="flac",
        is_encrypted=False,
    )
    manifest.urls = urls
    manifest.get_urls = lambda: list(urls)
    return manifest


def _engine_info(manifest=None, stream=None, file_extension=".flac", requires_flac_extraction=False):
    return TrackStreamInfo(
        stream_manifest=manifest,
        file_extension=file_extension,
        requires_flac_extraction=requires_flac_extraction,
        media_stream=stream,
    )


def _stream(**attrs) -> SimpleNamespace:
    base = {
        "audio_quality": Quality.high_lossless,
        "audio_mode": AudioMode.stereo,
        "bit_depth": 16,
        "sample_rate": 44100,
        "album_replay_gain": -7.89,
        "album_peak_amplitude": 0.98,
        "track_replay_gain": -8.12,
        "track_peak_amplitude": 0.99,
        "is_bts": False,
    }
    base.update(attrs)
    return SimpleNamespace(**base)


class _StubProvider:
    """The seam's download half, scripted per test."""

    id = "tidal"
    name = "TIDAL"

    def __init__(self, stream_info=None, refusal=None):
        self.stream_info = stream_info
        self.refusal = refusal
        self.resolved: list = []
        self.facts_of: list = []
        self.facts: dict = {}

    def resolve_stream(self, track, tier, audio_type):
        self.resolved.append((track, tier, audio_type))
        if isinstance(self.stream_info, Exception):
            raise self.stream_info
        return self.stream_info

    def classify_refusal(self, exc):
        return self.refusal or Refusal(RefusalKind.FAILURE, str(exc))

    def track_facts(self, track):
        self.facts_of.append(track)
        return self.facts


def _make_download(provider, tmp_path=None, **kwargs) -> Download:
    dl = Download(
        tidal_obj=MagicMock(),
        skip_existing=False,
        path_base=str(tmp_path or "."),
        fn_logger=MagicMock(),
        progress=MagicMock(),
        provider=provider,
        **kwargs,
    )
    dl.settings = MagicMock()
    dl.event_abort = threading.Event()
    dl.event_run = threading.Event()
    dl.event_run.set()
    return dl


def _track(item_id: str = "1"):
    """A stand-in that passes the engine's isinstance dispatch."""
    from tidalapi import Track

    track = MagicMock(spec=Track)
    track.id = item_id
    return track


# ------------------------------------------------- the neutral stream answer


class TestStreamInfoTranslation:
    def test_replay_gains_ride_the_stream_info(self):
        # The tag writer reads its ReplayGain facts off the StreamInfo now;
        # a stream without them answers None, never a dict of Nones.
        info = _engine_info(manifest=_dash_manifest(4), stream=_stream())

        resolved = TidalProvider._as_stream_info(info)

        assert resolved.replay_gain == {
            "album_replay_gain": -7.89,
            "album_peak_amplitude": 0.98,
            "track_replay_gain": -8.12,
            "track_peak_amplitude": 0.99,
        }

    def test_a_stream_without_measurements_leaves_the_tags_untagged(self):
        stream = _stream()
        del stream.album_replay_gain
        resolved = TidalProvider._as_stream_info(_engine_info(manifest=_dash_manifest(4), stream=stream))
        assert resolved.replay_gain["album_replay_gain"] is None

    def test_no_stream_translates_to_the_empty_answer(self):
        # The engine's "could not fetch" payload (no manifest) must arrive as
        # the all-default StreamInfo: empty urls IS the no-stream contract.
        resolved = TidalProvider._as_stream_info(_engine_info(manifest=None, stream=None))
        assert resolved.urls == []
        assert resolved.file_extension == ""
        assert resolved.replay_gain is None

    def test_dash_tail_arithmetic_rides_the_stream_info(self):
        # The pipeline's leniency decision is provider-proven: the manifest's
        # own timeline says how many trailing URLs are padding.
        resolved = TidalProvider._as_stream_info(_engine_info(manifest=_dash_manifest(4)))
        assert resolved.tail_spurious == 1  # 1 init + (r+1) per S element, against 4 URLs

    def test_a_non_dash_delivery_proves_nothing(self):
        manifest = _dash_manifest(4)
        manifest.manifest_mime_type = "application/octet-stream"
        assert TidalProvider._as_stream_info(_engine_info(manifest=manifest)).tail_spurious is None

    def test_an_encrypted_manifest_is_flagged(self):
        manifest = _dash_manifest(4)
        manifest.is_encrypted = True
        assert TidalProvider._as_stream_info(_engine_info(manifest=manifest)).encrypted is True
        assert TidalProvider._as_stream_info(_engine_info(manifest=_dash_manifest(4))).encrypted is False

    def test_a_single_file_delivery_is_flagged(self):
        # A BTS stream arrives as one complete file: no fragmented merge, so
        # no duration-repairing remux downstream.
        resolved = TidalProvider._as_stream_info(_engine_info(manifest=_dash_manifest(1), stream=_stream(is_bts=True)))
        assert resolved.single_file is True
        plain = TidalProvider._as_stream_info(_engine_info(manifest=_dash_manifest(4), stream=_stream()))
        assert plain.single_file is False

    def test_the_delivery_words_carry_the_audio_type(self):
        atmos = TidalProvider._as_stream_info(
            _engine_info(manifest=_dash_manifest(4), stream=_stream(audio_mode=AudioMode.dolby_atmos))
        )
        assert atmos.delivered["audio_type"] == str(AudioType.ATMOS)
        stereo = TidalProvider._as_stream_info(_engine_info(manifest=_dash_manifest(4), stream=_stream()))
        assert stereo.delivered["audio_type"] == str(AudioType.STEREO)


class TestResolveStreamRouting:
    def test_the_bound_engine_resolver_answers(self):
        provider = TidalProvider(MagicMock())
        info = _engine_info(manifest=_dash_manifest(4), stream=_stream())

        with provider.stream_resolver_bound(lambda track, tier, audio_type: info):
            resolved = provider.resolve_stream(object(), QualityTier.LOSSLESS, AudioType.STEREO)

        assert isinstance(resolved, StreamInfo)
        assert resolved.file_extension == ".flac"
        assert resolved.urls

    def test_an_empty_engine_answer_resolves_to_no_stream(self):
        provider = TidalProvider(MagicMock())

        with provider.stream_resolver_bound(lambda *a: TrackStreamInfo(None, "", False, None)):
            resolved = provider.resolve_stream(object(), QualityTier.LOSSLESS, AudioType.STEREO)

        assert resolved.urls == []

    def test_the_binding_is_restored_after_the_resolve(self):
        provider = TidalProvider(MagicMock())
        with pytest.raises(RuntimeError, match="bound"):
            provider.resolve_stream(object(), QualityTier.LOSSLESS, AudioType.STEREO)
        with provider.stream_resolver_bound(lambda *a: TrackStreamInfo(None, "", False, None)):
            provider.resolve_stream(object(), QualityTier.LOSSLESS, AudioType.STEREO)
        # The bind is scoped, not sticky: after it lifts, the provider is
        # resolver-free again -- nothing survived that could answer for a
        # different engine.
        with pytest.raises(RuntimeError, match="bound"):
            provider.resolve_stream(object(), QualityTier.LOSSLESS, AudioType.STEREO)


# ------------------------------------------- the engine consumes the answer


class TestEngineStreamRouting:
    def _dl(self, provider, tmp_path) -> Download:
        return _make_download(provider, tmp_path)

    def test_get_stream_info_returns_the_provider_answer(self, tmp_path):
        provider = _StubProvider(StreamInfo(urls=["https://seg/1"], file_extension=".flac", codecs="flac"))
        dl = self._dl(provider, tmp_path)
        track = _track("1")

        info = dl._get_stream_info(track)

        assert provider.resolved and provider.resolved[0][0] is track
        assert info is not None and info.urls == ["https://seg/1"]

    def test_the_jobs_request_crosses_the_seam(self, tmp_path):
        # The job's pinned rung and Version are the resolve's arguments
        # (one immutable ask), never state the provider has to guess. A legacy
        # job that pinned neither keeps the None/None shape.
        provider = _StubProvider(StreamInfo(urls=["https://seg/1"], file_extension=".flac", codecs="flac"))
        pinned = _make_download(provider, tmp_path, pinned_tier=QualityTier.LOSSLESS, pinned_audio_type="atmos")
        pinned._get_stream_info(_track("1"))
        assert provider.resolved[0][1:] == (QualityTier.LOSSLESS, AudioType.ATMOS)

        legacy = _make_download(provider, tmp_path)
        legacy._get_stream_info(_track("2"))
        assert provider.resolved[1][1:] == (None, None)

    def test_an_empty_stream_answer_is_a_failed_fetch(self, tmp_path):
        provider = _StubProvider(StreamInfo())
        dl = self._dl(provider, tmp_path)

        assert dl._get_stream_info(_track("1")) is None

    def test_a_resolution_refusal_maps_through_classify_refusal(self, tmp_path):
        provider = _StubProvider(
            RuntimeError("gone"),
            Refusal(RefusalKind.UNAVAILABLE, "this item is not available on TIDAL"),
        )
        dl = self._dl(provider, tmp_path)
        marks: list = []
        dl._note_unavailable = lambda media: marks.append(media)

        assert dl._get_stream_info(_track("1")) is None
        assert marks, "a refusal must be marked unavailable, not silently dropped"

    def test_a_throttle_maps_to_no_unavailable_mark(self, tmp_path):
        provider = _StubProvider(RuntimeError("429"), Refusal(RefusalKind.THROTTLED, "TIDAL is rate-limiting"))
        dl = self._dl(provider, tmp_path)
        marks: list = []
        dl._note_unavailable = lambda media: marks.append(media)

        assert dl._get_stream_info(_track("1")) is None
        assert not marks
        dl.fn_logger.exception.assert_called()  # logged loudly, never marked

    def test_a_plain_failure_keeps_the_something_went_wrong_path(self, tmp_path):
        provider = _StubProvider(RuntimeError("socket died"), Refusal(RefusalKind.FAILURE, "socket died"))
        dl = self._dl(provider, tmp_path)
        marks: list = []
        dl._note_unavailable = lambda media: marks.append(media)

        assert dl._get_stream_info(_track("1")) is None
        assert not marks

    def test_a_resolve_answers_through_the_engine_that_asked(self, tmp_path):
        # One shared provider, two engines -- the GUI's exact shape: an idle
        # Download rebuilt by a settings save while a job is running. Each
        # resolve must come straight back to the engine that asked, or the
        # idle engine's answer would bypass the running job's quality pinning
        # and delivered-quality capture.
        provider = TidalProvider(MagicMock())
        job = self._dl(provider, tmp_path)
        idle = self._dl(provider, tmp_path)
        asked_by: list[str] = []

        def _resolver_for(tag: str, extension: str):
            def _resolver(track, tier, audio_type):
                asked_by.append(tag)
                return _engine_info(manifest=_dash_manifest(4), stream=_stream(), file_extension=extension)

            return _resolver

        job._get_track_stream_info = _resolver_for("job", ".job")
        idle._get_track_stream_info = _resolver_for("idle", ".idle")

        # Interleaved, deliberately: the idle engine resolving between the
        # job's resolves must not leave its binding behind.
        job_info = job._get_stream_info(_track("1"))
        assert job_info is not None and job_info.file_extension == ".job"
        idle_info = idle._get_stream_info(_track("1"))
        assert idle_info is not None and idle_info.file_extension == ".idle"
        job_info = job._get_stream_info(_track("1"))
        assert job_info is not None and job_info.file_extension == ".job"

        assert asked_by == ["job", "idle", "job"]


# --------------------------------------------------------- the tag fact pull


class TestTrackFactsConsumption:
    def _settings(self):
        settings = SimpleNamespace(
            lyrics_embed=False,
            lyrics_file=False,
            metadata_cover_embed=False,
            cover_album_file=False,
            cover_single_track_file=False,
            metadata_cover_dimension="1280",
            metadata_cover_file_dimension="follow",
            mark_explicit=True,
            metadata_write_url=False,
            metadata_replay_gain=True,
            metadata_target_upc="UPC",
            initial_key_format="alphanumeric",
        )
        return settings

    def _track(self):
        return SimpleNamespace(
            id="42",
            name="Song",
            artists=[SimpleNamespace(id="7", name="Artist")],
            album=None,
        )

    def test_metadata_write_reads_its_facts_from_the_provider(self, tmp_path, monkeypatch):
        import waves.download as download_mod

        provider = _StubProvider()
        provider.facts = {
            "item_id": "tidal:42",
            "artist_ids": ["tidal:7"],
            "album_artist_ids": ["tidal:7"],
            "artists": [("tidal:7", "Artist")],
            "album_artists": ["Artist"],
            "copyright": "2024 The Owner",
            "isrc": "GBAHT9200001",
            "explicit": True,
            "bpm": 120,
            "key": None,
            "key_scale": None,
            "share_url": "https://tidal.com/browse/track/42",
            "volume_num": 2,
            "track_num": 3,
            "release_date": "2024-03-01",
            "release_type": "album",
            "album": {"name": "Album", "num_tracks": 10, "num_volumes": 2, "upc": "0060254", "type": "ALBUM"},
        }
        dl = _make_download(provider, tmp_path)
        dl.settings = SimpleNamespace(data=self._settings())
        captured = {}

        class _RecordingMetadata:
            def __init__(self, **kwargs):
                captured.update(kwargs)
                self.save = MagicMock()

        monkeypatch.setattr(download_mod, "Metadata", _RecordingMetadata)

        track = self._track()
        ok, _lyr, _suf, _cover = dl.metadata_write(
            track,
            tmp_path / "s.flac",
            False,
            {
                "album_replay_gain": None,
                "album_peak_amplitude": None,
                "track_replay_gain": None,
                "track_peak_amplitude": None,
            },
        )

        assert ok is True
        assert provider.facts_of == [track]
        assert captured["copy_right"] == "2024 The Owner"
        assert captured["isrc"] == "GBAHT9200001"
        assert captured["explicit"] is True
        assert captured["bpm"] == 120
        assert captured["date"] == "2024-03-01"
        assert captured["release_type"] == "album"
        assert captured["tracknumber"] == 3
        assert captured["discnumber"] == 2
        assert captured["totaltrack"] == 10
        assert captured["totaldisc"] == 2
        assert captured["album"] == "Album"
        assert captured["upc"] == "0060254"
        assert captured["artists"] == ["Artist"]
        assert captured["albumartist"] == ["Artist"]
        # The namespaced ids arrive as facts, unchanged: stripping them to the
        # legacy tags' bare spelling is the tag writer's own business (pinned
        # just below, through the real Metadata).
        assert captured["item_id"] == "tidal:42"
        assert captured["artist_ids"] == ["tidal:7"]
        assert captured["album_artist_ids"] == ["tidal:7"]
        # The ReplayGain facts ride the stream's dict, not a stream object.
        assert captured["album_replay_gain"] is None

    def test_the_legacy_tag_writer_strips_the_namespace(self, tmp_path, monkeypatch):
        # The WAVES_TIDAL_* tags stay bare (every existing file and reader
        # speaks that spelling): the tag writer strips the seam's prefix.
        import mutagen.flac

        from waves.metadata.tags import ALBUM_ARTIST_ID_TAG, ARTIST_ID_TAG, ITEM_ID_TAG, Metadata

        stub = mutagen.flac.FLAC.__new__(mutagen.flac.FLAC)
        stub.tags = None
        stub.metadata_blocks = []
        stub.save = lambda *a, **k: True
        monkeypatch.setattr("waves.metadata.tags.mutagen.File", lambda _path: stub)

        m = Metadata(
            path_file=tmp_path / "s.flac",
            target_upc={"FLAC": "UPC"},
            item_id="tidal:42",
            artist_ids=["tidal:7", "tidal:8"],
            album_artist_ids=["tidal:7"],
        )
        m.save()

        assert stub.tags[ITEM_ID_TAG] == ["42"]  # FLAC vorbis comments are lists
        assert stub.tags[ARTIST_ID_TAG] == ["7", "8"]
        assert stub.tags[ALBUM_ARTIST_ID_TAG] == ["7"]

    def test_a_bare_id_passes_through_the_strip_unchanged(self):
        from waves.metadata.tags import _legacy_id

        assert _legacy_id("42") == "42"
        assert _legacy_id("") == ""
        assert _legacy_id(None) == ""

    def test_replay_gains_flow_from_the_stream_info_dict(self, tmp_path, monkeypatch):
        import waves.download as download_mod

        provider = _StubProvider()
        provider.facts = {
            "item_id": "tidal:42",
            "artist_ids": [],
            "album_artist_ids": [],
            "artists": [],
            "album_artists": [],
            "copyright": "",
            "isrc": "",
            "explicit": False,
            "bpm": 0,
            "key": None,
            "key_scale": None,
            "share_url": "",
            "volume_num": 1,
            "track_num": 1,
            "release_date": "",
            "release_type": "",
            "album": {"name": "", "num_tracks": None, "num_volumes": None, "upc": "", "type": ""},
        }
        dl = _make_download(provider, tmp_path)
        dl.settings = SimpleNamespace(data=self._settings())
        captured = {}

        class _RecordingMetadata:
            def __init__(self, **kwargs):
                captured.update(kwargs)
                self.save = MagicMock()

        monkeypatch.setattr(download_mod, "Metadata", _RecordingMetadata)

        gains = {
            "album_replay_gain": -7.89,
            "album_peak_amplitude": 0.98,
            "track_replay_gain": -8.12,
            "track_peak_amplitude": 0.99,
        }
        dl.metadata_write(self._track(), tmp_path / "s.flac", False, gains)

        assert captured["album_replay_gain"] == -7.89
        assert captured["album_peak_amplitude"] == 0.98
        assert captured["track_replay_gain"] == -8.12
        assert captured["track_peak_amplitude"] == 0.99


# ------------------------------------------------------------ the job spec


class TestJobSpecDispatch:
    """A queued row names its object; the job resolves it through the provider."""

    def _stub_bridge(self, provider, tmp_path, *, skip=False, claim_records=None, provider_id="tidal"):
        from support.dispatch_stub import arm_dispatch

        class _Signal:
            def emit(self, *args) -> None:
                pass

        class _Engine:
            path_base = str(tmp_path)
            write_count = ok_count = 1
            fail_count = unavailable_count = 0
            list_unavailable = False
            list_item_count = 1
            items_called = None
            library_claim = None

            def items(self, **kwargs):
                self.items_called = kwargs
                # The tracked engine consults the claim gate per track inside
                # item(); one call here stands in for it.
                if self.library_claim is not None:
                    self.library_claim(SimpleNamespace(id="t1", name="Song"))

        def _build_download(signals, **kwargs):
            stub.dl.library_claim = kwargs.get("library_claim")
            stub.dl.built_kwargs = kwargs
            return stub.dl

        class _Pool:
            def start(self, worker) -> None:
                worker.run()

        stub = SimpleNamespace()
        stub._logged_in = True
        stub._job_aborts = {}
        stub._job_signals = {}
        stub._job_dls = {}
        stub._job_tracks = {}
        stub._merge_plans = {}
        stub._redownload_overrides = set()
        stub._library_claim_overrides = set()
        stub._library_claim_records = claim_records if claim_records is not None else []
        stub._queue = [{"qid": 1, "media_id": "m1", "status": "queued", "type": "album", "name": "Album"}]
        stub._queue_index = {1: stub._queue[0]}
        stub._queue_lock = threading.Lock()
        stub.settings = SimpleNamespace(data=SimpleNamespace(download_base_path=str(tmp_path), download_delay=False))
        stub.dl = _Engine()
        stub.dl_pool = _Pool()
        stub.downloadState = _Signal()
        stub.downloadProgress = _Signal()
        stub.statuses = []
        stub.providers = {provider_id: provider}
        stub._track_poll = SimpleNamespace(isActive=lambda: True, start=lambda *a: None)
        stub._set_queue_status = lambda qid, status, reason="": (
            stub._queue[0].__setitem__("status", status),
            stub.statuses.append((status, reason)),
        )
        stub._set_queue_progress = lambda qid, pct: None
        stub._set_status = lambda msg: None
        stub._job_library_skip = lambda qid: skip
        stub._job_quality = lambda qid: None
        stub._queue_item = lambda qid: stub._queue_index.get(qid)
        stub._row_ask = lambda qid: None
        stub._build_download = _build_download
        stub._release_job_signals = lambda qid: stub._job_signals.pop(qid, None)
        stub._gate_reachability = lambda retry, media_id: True
        stub._library_claim_media = lambda media, album=None: stub._library_claim_records.append(album) or False
        arm_dispatch(stub)
        return stub

    def _spec(
        self,
        *,
        collection=True,
        kind="album",
        object_id="tidal:m1",
        media_id="m1",
        audio_type=None,
        provider_id="tidal",
    ):
        from waves.desktop.backend import _JobSpec

        return _JobSpec(
            provider_id=provider_id,
            kind=kind,
            object_id=object_id,
            name="Album",
            file_template="{title}",
            collection=collection,
            media_id=media_id,
            merge_plan=None,
            audio_type=audio_type,
        )

    def _drive(self, stub, spec):
        from unittest.mock import patch

        from waves.desktop import backend

        with patch.object(backend, "_ProgressSignals", lambda *a, **k: object()):
            backend.WavesBridge._start_job(stub, 1, spec)

    def test_the_job_resolves_its_object_through_get_object(self, tmp_path):
        provider = _StubProvider()
        provider.get_object = lambda kind, raw_id: SimpleNamespace(kind=kind, raw_id=raw_id)
        stub = self._stub_bridge(provider, tmp_path)

        self._drive(stub, self._spec())

        assert stub.dl.items_called is not None
        resolved = stub.dl.items_called["media"]
        assert (resolved.kind, resolved.raw_id) == ("album", "m1")

    def test_a_dispatch_refusal_fails_the_row_in_the_providers_words(self, tmp_path):
        from tidalapi.exceptions import ObjectNotFound

        calls = {"get": False}

        def _get(kind, raw_id):
            calls["get"] = True
            raise ObjectNotFound()

        provider = _StubProvider()
        provider.get_object = _get
        provider.refusal = Refusal(RefusalKind.UNAVAILABLE, "this item is not available on TIDAL")
        stub = self._stub_bridge(provider, tmp_path)

        self._drive(stub, self._spec())

        assert calls["get"] is True
        assert stub._queue[0]["status"] == "failed"
        assert any("not available" in reason for _s, reason in stub.statuses)

    def test_a_dispatch_failure_fails_the_row_without_the_refusal_words(self, tmp_path):
        provider = _StubProvider()
        provider.get_object = lambda kind, raw_id: (_ for _ in ()).throw(RuntimeError("socket died"))
        provider.refusal = Refusal(RefusalKind.FAILURE, "socket died")
        stub = self._stub_bridge(provider, tmp_path)

        self._drive(stub, self._spec())

        assert stub._queue[0]["status"] == "failed"
        assert stub.statuses[-1][0] == "failed"

    def test_the_claim_gate_sees_the_resolved_album(self, tmp_path):
        # The library-claim gate's album binding (the only place a job's
        # release year is spelled out) reads the dispatch-resolved object.
        provider = _StubProvider()
        album = SimpleNamespace(id="m1", name="Album")
        provider.get_object = lambda kind, raw_id: album
        records: list = []
        stub = self._stub_bridge(provider, tmp_path, skip=True, claim_records=records)

        self._drive(stub, self._spec())

        assert records == [album]

    def test_the_built_download_carries_the_rows_request(self, tmp_path):
        """The runner hands the download the row's own rung and Version,
        never a live Settings read: that carry is what makes a per-click ask
        independent of the saved defaults. The source guard in
        tests/settings/test_quality_pinned_per_job.py pairs with this."""
        provider = _StubProvider()
        provider.get_object = lambda kind, raw_id: SimpleNamespace(id=raw_id)
        stub = self._stub_bridge(provider, tmp_path)
        stub._job_quality = lambda qid: QualityTier.HI_RES_LOSSLESS

        self._drive(stub, self._spec(audio_type="atmos"))

        assert stub.dl.built_kwargs["pinned_quality"] == QualityTier.HI_RES_LOSSLESS
        assert stub.dl.built_kwargs["audio_type"] == "atmos"


# ---------------------------------------------- the third provider's adapter


class _ThirdDownloads(DownloadAdapter):
    """A third provider's download surface: records every ask the bridge
    routes, and runs queued jobs through its own pipeline -- no engine, no
    TIDAL session (the fake stands in for a provider whose deliveries come
    from somewhere else entirely)."""

    def __init__(self, bridge):
        self.bridge = bridge
        self.entries: list = []
        self.retries: list = []
        self.rows: list = []
        self.refetches: list = []
        self.standalones: list = []
        self.jobs: list = []

    def serve_entry(self, kind, media_id, *, chooser=False, chooser_ask=None, chooser_audio=None, chooser_toggles=None):
        self.entries.append((kind, media_id, chooser, chooser_ask, chooser_audio, chooser_toggles))
        return True

    def serve_retry(self, item, obj):
        self.retries.append((item["media_id"], obj))
        return True

    def cached_row(self, kind, media_id):
        self.rows.append((kind, media_id))
        return {"id": media_id, "kind": kind}

    def refetch_retry(self, item):
        self.refetches.append(item["media_id"])
        return True

    def standalone(self, media_id, mode):
        self.standalones.append((media_id, mode))
        return 3

    def job_runner(self, qid, spec, *, signals, job_abort, row_ask, name):
        def run(obj):
            self.jobs.append((qid, spec.kind, obj, name))
            self.bridge._set_queue_status(qid, "done")
            self.bridge.downloadState.emit(spec.media_id, "done")

        return run


class _ThirdProvider(BareProvider):
    id = "third"
    name = "Third"
    capabilities = frozenset({Capability.DOWNLOAD})


class TestTheThirdProviderAdapter:
    """A third provider with Capability.DOWNLOAD drives every download road
    through its own adapter, with no bridge edit: the id's namespace resolves
    to the provider, and the provider's adapter serves the click, the retry,
    the standalone fetch and the job body."""

    def _bridge(self, tmp_path):
        provider = _ThirdProvider()
        stub = TestJobSpecDispatch()._stub_bridge(provider, tmp_path, provider_id="third")
        downloads = _ThirdDownloads(stub)
        provider.downloads = downloads
        stub._objs = {"track": {}, "album": {}, "playlist": {}, "mix": {}, "video": {}}
        return provider, stub, downloads

    def test_a_third_provider_serves_its_own_clicks(self, tmp_path):
        _provider, stub, downloads = self._bridge(tmp_path)
        obj = SimpleNamespace(id="third:t1", name="Song")
        stub._objs["track"] = {"third:t1": obj, "t1": obj}
        stub.settings.data.format_track = "{title}"
        engine_calls: list = []
        stub._download = lambda *a, **k: engine_calls.append(a) or True

        for kind, slot in (
            ("track", "downloadTrack"),
            ("album", "downloadAlbum"),
            ("playlist", "downloadPlaylist"),
            ("mix", "downloadMix"),
            ("video", "downloadVideo"),
        ):
            getattr(WavesBridge, slot)(stub, f"third:{kind}1")

        assert [(kind, media_id) for kind, media_id, *_ in downloads.entries] == [
            ("track", "third:track1"),
            ("album", "third:album1"),
            ("playlist", "third:playlist1"),
            ("mix", "third:mix1"),
            ("video", "third:video1"),
        ]
        assert all(entry[2] is False for entry in downloads.entries)
        assert engine_calls == [], "a provider-run click must not reach the engine entry"

        # The engine entry still serves the ids whose provider has no adapter.
        WavesBridge.downloadTrack(stub, "t1")
        assert len(engine_calls) == 1 and engine_calls[0][1] == "track"
        assert len(downloads.entries) == 5

    def test_a_third_provider_serves_a_chooser_click_with_its_pins(self, tmp_path):
        _provider, stub, downloads = self._bridge(tmp_path)
        for name in (
            "_provider_meta",
            "_chooser_provider_of",
            "_chooser_ask_for",
            "_chooser_toggle_pins",
            "_chooser_normalize_audio",
        ):
            setattr(stub, name, getattr(WavesBridge, name).__get__(stub))

        WavesBridge.downloadWithChooser(stub, "third:t1", "track", "HIGH", "stereo", {"lyrics_embed": True})

        assert downloads.entries == [("track", "third:t1", True, None, "stereo", {"lyrics_embed": True})]

    def test_a_third_provider_drives_a_job_end_to_end(self, tmp_path):
        provider, stub, downloads = self._bridge(tmp_path)
        provider.get_object = lambda kind, raw_id: SimpleNamespace(kind=kind, raw_id=raw_id)
        stub._build_download = lambda *a, **k: (_ for _ in ()).throw(AssertionError("the engine was built"))

        spec = TestJobSpecDispatch()._spec(provider_id="third", object_id="third:m1", media_id="third:m1")
        TestJobSpecDispatch()._drive(stub, spec)

        assert downloads.jobs, "the provider's job body never ran"
        qid, kind, obj, name = downloads.jobs[0]
        assert (qid, kind, name) == (1, "album", "Album")
        assert (obj.kind, obj.raw_id) == ("album", "m1"), "the job resolves through the spec's provider"
        assert stub._queue[0]["status"] == "done"

    def test_the_retry_roads_ask_the_rows_provider(self, tmp_path):
        _provider, stub, downloads = self._bridge(tmp_path)
        item = {
            "qid": 1,
            "type": "album",
            "media_id": "third:m1",
            "name": "Album",
            "template": "T",
            "collection": True,
            "askQuality": "HIGH",
            "quality": "HIGH",
        }

        assert WavesBridge._start_retry(stub, item, {"id": "third:m1"}) is True
        assert downloads.retries == [("third:m1", {"id": "third:m1"})]

        assert WavesBridge._row_object(stub, item) == {"id": "third:m1", "kind": "album"}
        assert downloads.rows == [("album", "third:m1")]

        from waves.desktop import backend

        backend._refetch_retry(stub, item)
        assert downloads.refetches == ["third:m1"]

    def test_a_standalone_fetch_asks_the_providers_adapter(self, tmp_path):
        from conftest import _InlinePool

        _provider, stub, downloads = self._bridge(tmp_path)
        stub.threadpool = _InlinePool()
        stub._download_gate = lambda: "ok"
        stub._set_status = stub.statuses.append

        WavesBridge._standalone_fetch(stub, "third:m1", "lyrics")

        assert downloads.standalones == [("third:m1", "lyrics")]
        assert stub.statuses[-1] == "Saved lyrics for 3 tracks"
