"""FLAC format matrix (issue #64): lossless stereo lands FLAC, the rest stays .m4a.

Default (lossless-only) scope: TIDAL FLAC stays .flac, Apple ALAC converts to
.flac (a lossless decode + FLAC encode, bit for bit identical -- the FLAC
container cannot hold ALAC packets), AAC stays .m4a, Atmos stays .m4a. The scope
toggle (``extract_flac_all``) additionally re-encodes lossy stereo into FLAC;
the master switch (``extract_flac``) off keeps every original. Atmos never
converts on either provider, and a transcoded AAC keeps its HIGH tier (a FLAC
container must never promote lossy bytes to LOSSLESS).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from threading import Event, Lock
from types import SimpleNamespace

import pytest

from waves.constants import CTX_APPLE, QualityTier, quality_rank
from waves.providers.base import AudioType, StreamInfo
from waves.waves_ui.backend import WavesBridge

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def _ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    assert path is not None  # guarded by needs_ffmpeg
    return path


def _tone(path: Path, codec: str = "aac") -> None:
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
            codec,
            str(path),
        ],
        check=True,
    )


def _song_resource(song_id="song-1"):
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
            "audioTraits": ["lossless"],
            "isrc": "GBAAA9200001",
        },
        "relationships": {"artists": {"data": [{"id": "artist-1"}]}},
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
        "quality": "LOSSLESS",
        "popularity": -1,
        "explicit": False,
        "added": "",
    }


# ------------------------------------------------------- provider-level matrix


def test_provider_alac_reports_flac_while_aac_and_atmos_stay_m4a(tmp_path, monkeypatch):
    import waves.providers.apple.engine as engine
    from waves.providers.apple import AppleProvider

    staged = tmp_path / "staged.m4a"
    staged.write_bytes(b"fake")
    workdir = tmp_path / "work"
    workdir.mkdir()

    def fake_alac(**kwargs):
        return SimpleNamespace(staged_path=staged, workdir=workdir, is_atmos=False, codec="alac")

    def fake_aac(**kwargs):
        return SimpleNamespace(staged_path=staged, workdir=workdir, is_atmos=kwargs.get("atmos", False), codec="")

    monkeypatch.setattr(engine, "download_song_alac_file", fake_alac)
    monkeypatch.setattr(engine, "download_song_file", fake_aac)
    monkeypatch.setattr(
        engine,
        "probe_audio_file",
        lambda path, ffprobe_path="": {"codec": "alac", "sample_rate": "44100", "bit_depth": 16},
    )

    provider = AppleProvider(catalog=None)
    provider.wrapper_url = "http://127.0.0.1:51234"
    provider.cookies_path = "/cookies.txt"

    alac = provider.resolve_stream(_song_resource(), QualityTier.HI_RES_LOSSLESS, AudioType.STEREO)
    assert alac.file_extension == ".flac"
    assert alac.requires_flac_extraction is True
    assert alac.delivered["tier"] == QualityTier.LOSSLESS.value
    provider.discard_delivery(alac.local_file)

    monkeypatch.setattr(
        engine, "probe_audio_file", lambda path, ffprobe_path="": {"codec": "aac", "sample_rate": "44100"}
    )
    provider.wrapper_url = ""
    aac = provider.resolve_stream(_song_resource(), QualityTier.HIGH, AudioType.STEREO)
    assert (aac.file_extension, aac.requires_flac_extraction) == (".m4a", False)
    provider.discard_delivery(aac.local_file)

    provider.wrapper_url = "http://127.0.0.1:51234"
    atmos = provider.resolve_stream(_song_resource(), QualityTier.HIGH, AudioType.ATMOS)
    assert (atmos.file_extension, atmos.requires_flac_extraction) == (".m4a", False)
    provider.discard_delivery(atmos.local_file)


def test_tier_mapping_treats_flac_like_alac():
    from waves.providers.apple.engine import apple_tier_for_delivery

    assert apple_tier_for_delivery("flac", 16, 44100) == QualityTier.LOSSLESS.value
    assert apple_tier_for_delivery("flac", 24, 96000) == QualityTier.HI_RES_LOSSLESS.value
    assert apple_tier_for_delivery("flac", 24, 192000) == QualityTier.HI_RES_LOSSLESS.value
    assert apple_tier_for_delivery("flac", 16, 44100) == apple_tier_for_delivery("alac", 16, 44100)
    assert apple_tier_for_delivery("aac", None, "44100") == QualityTier.HIGH.value


# ---------------------------------------------------------- TIDAL seam matrix


def _tidal_dl(*, extract=True, scope_all=False, atmos_on=False):
    from waves.waves_ui import backend

    dl = backend._TrackedDownload.__new__(backend._TrackedDownload)

    class _Tidal:
        stream_lock = Lock()

        def switch_to_atmos_session(self):
            return True

        def restore_normal_session(self):
            return True

    dl.tidal = _Tidal()
    dl.session = SimpleNamespace(track=lambda tid: SimpleNamespace(get_stream=lambda: _TRACK_STREAMS["atmos"]))
    dl.settings = SimpleNamespace(
        data=SimpleNamespace(
            default_audio_type="both" if atmos_on else "stereo", extract_flac=extract, extract_flac_all=scope_all
        )
    )
    dl.fn_logger = SimpleNamespace(error=lambda *a, **k: None, info=lambda *a, **k: None)
    # The _TrackedDownload override stamps the delivered snapshot; give it
    # the ledger it writes into (see test_quality_pinned_per_job).
    dl._pinned_quality = None
    dl._target_rank = -1
    dl._delivered = {}
    dl._delivered_lock = Lock()
    return dl


_TRACK_STREAMS: dict[str, object] = {}


def _stereo_media(codecs, extension, atmos=False):
    from tidalapi.media import AudioMode

    manifest = SimpleNamespace(file_extension=extension, codecs=codecs)
    stream = SimpleNamespace(get_stream_manifest=lambda: manifest)
    modes = [AudioMode.dolby_atmos.value] if atmos else []
    return SimpleNamespace(id="s", audio_modes=modes, get_stream=lambda: stream)


def test_tidal_flac_stays_flac_and_toggle_off_keeps_the_container():
    from waves.waves_ui import backend

    dl = _tidal_dl(extract=True)
    info = backend._TrackedDownload._get_track_stream_info(dl, _stereo_media("FLAC", ".mp4"))
    assert (info.file_extension, info.requires_flac_extraction) == (".flac", True)

    dl = _tidal_dl(extract=False)
    info = backend._TrackedDownload._get_track_stream_info(dl, _stereo_media("FLAC", ".mp4"))
    assert (info.file_extension, info.requires_flac_extraction) == (".mp4", False)


def test_tidal_lossy_converts_only_under_the_all_scope():
    from waves.waves_ui import backend

    dl = _tidal_dl(extract=True, scope_all=False)
    info = backend._TrackedDownload._get_track_stream_info(dl, _stereo_media("mp4a.40.2", ".m4a"))
    assert (info.file_extension, info.requires_flac_extraction) == (".m4a", False)

    dl = _tidal_dl(extract=True, scope_all=True)
    info = backend._TrackedDownload._get_track_stream_info(dl, _stereo_media("mp4a.40.2", ".m4a"))
    assert (info.file_extension, info.requires_flac_extraction) == (".flac", True)


def test_tidal_atmos_never_converts_even_under_the_all_scope():
    from waves.waves_ui import backend

    _TRACK_STREAMS["atmos"] = SimpleNamespace(
        get_stream_manifest=lambda: SimpleNamespace(file_extension=".m4a", codecs="eac3")
    )
    try:
        dl = _tidal_dl(extract=True, scope_all=True, atmos_on=True)
        info = backend._TrackedDownload._get_track_stream_info(dl, _stereo_media("eac3", ".m4a", atmos=True))
        assert (info.file_extension, info.requires_flac_extraction) == (".m4a", False)
    finally:
        _TRACK_STREAMS.pop("atmos", None)


def test_tidal_extract_copies_lossless_and_reencodes_lossy(monkeypatch):
    import waves.download as download_mod

    seen: dict = {}

    class _FakeFFmpeg:
        def __init__(self, executable=None):
            self.executable = executable

        def option(self, *a):
            return self

        def input(self, **k):
            return self

        def output(self, **k):
            seen.update(k)
            return self

        def execute(self):
            return None

    monkeypatch.setattr(download_mod, "FFmpeg", _FakeFFmpeg)
    dl = download_mod.Download.__new__(download_mod.Download)
    dl.settings = SimpleNamespace(data=SimpleNamespace(path_binary_ffmpeg="ffmpeg"))

    dl._extract_flac(Path("/tmp/x.m4a"))
    assert seen.get("acodec") == "copy"

    seen.clear()
    dl._extract_flac(Path("/tmp/x.m4a"), transcode=True)
    assert seen.get("acodec") == "flac"
    assert "sample_rate" not in seen and "audio_bitrate" not in seen and "ar" not in seen


# ---------------------------------------------------------- Apple guess + mode


def _apple_stub(base: Path, provider, **overrides):
    data = SimpleNamespace(
        download_base_path=str(base),
        skip_existing=True,
        extract_flac=True,
        extract_flac_all=False,
        lyrics_embed=False,
        lyrics_file=False,
        lyrics_prefer_lrclib=True,
        lyrics_file_synced_only=False,
        lyrics_ttml_file=False,
        lyrics_word_timed=True,
        metadata_cover_embed=False,
        metadata_cover_dimension="320",
        metadata_cover_file_dimension="follow",
        cover_album_file=False,
        cover_single_track_file=False,
        cover_file_format="jpg",
        mark_explicit=False,
        metadata_target_upc="UPC",
        metadata_custom=False,
        apple_quality_audio="HI_RES_LOSSLESS",
        default_audio_type="stereo",
        path_binary_ffmpeg="",
        format_track="{artist_name}/{track_title}",
        album_track_num_pad_min=1,
        filename_delimiter_artist=", ",
        filename_delimiter_album_artist=", ",
        filename_illegal_replacement="",
        filename_illegal_map=None,
    )
    for key, value in overrides.items():
        setattr(data, key, value)
    stub = SimpleNamespace(
        settings=SimpleNamespace(data=data),
        providers={CTX_APPLE: provider},
        _ownership=SimpleNamespace(ownership_of=lambda *a, **k: None),
    )
    for name in (
        "_apple_guess_ext",
        "_apple_options",
        "_apple_wants_flac",
        "_apple_flac_scope_all",
        "_apple_flac_mode",
        "_apple_flac_ffmpeg",
        "_apple_extract_flac",
        "_apple_track_relative",
        "_apple_relative_path",
        "_apple_deliver_track",
        "_apple_verify_staged",
        "_apple_probe",
        "_apple_place_file",
        "_apple_lyrics",
        "_apple_wants_cover",
        "_apple_cover_bytes",
        "_apple_write_sidecars",
        "_apple_skiplist_add",
        "_psetting",
        "_tag_write_flags",
    ):
        setattr(stub, name, getattr(WavesBridge, name).__get__(stub))
    return stub


def _alac_info(local_file: str) -> SimpleNamespace:
    return SimpleNamespace(
        local_file=local_file,
        delivered={"tier": QualityTier.LOSSLESS.value, "audio_type": str(AudioType.STEREO)},
        codecs="alac",
        requires_flac_extraction=True,
    )


def _aac_info(local_file: str) -> SimpleNamespace:
    return SimpleNamespace(
        local_file=local_file,
        delivered={"tier": QualityTier.HIGH.value, "audio_type": str(AudioType.STEREO)},
        codecs="mp4a.40.2",
        requires_flac_extraction=False,
    )


def _atmos_info(local_file: str) -> SimpleNamespace:
    return SimpleNamespace(
        local_file=local_file,
        delivered={"tier": QualityTier.HIGH.value, "audio_type": str(AudioType.ATMOS)},
        codecs="ec-3",
        requires_flac_extraction=False,
    )


class _Provider:
    wrapper_available = True

    def __init__(self, info):
        self._info = info
        self.discarded: list = []

    def get_object(self, kind, raw_id):
        return _song_resource()

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

    def advertised_ceiling(self, obj):
        return quality_rank(QualityTier.HI_RES_LOSSLESS)

    def classify_refusal(self, exc):
        from waves.providers.base import Refusal, RefusalKind

        return Refusal(RefusalKind.FAILURE, str(exc))

    def resolve_stream(self, raw, tier, audio_type):
        return self._info

    def discard_delivery(self, local_file):
        self.discarded.append(local_file)


def _deliver(stub, provider):
    info = provider._info if isinstance(provider, _Provider) else provider
    return WavesBridge._apple_deliver_track(
        stub,
        provider if isinstance(provider, _Provider) else _Provider(info),
        _track_row(),
        None,
        type_media="track",
        file_template="{artist_name}/{track_title}",
        collection=False,
        list_pos=1,
        list_total=1,
        num_volumes=1,
        audio_type=AudioType.STEREO,
        requested_rank=quality_rank(QualityTier.HI_RES_LOSSLESS),
        requested_tier=QualityTier.HI_RES_LOSSLESS,
        ceiling_rank=quality_rank(QualityTier.HI_RES_LOSSLESS),
        force=False,
        owned_path=None,
        job_abort=Event(),
        signals=None,
    )


def test_guess_and_mode_matrix():
    stub = _apple_stub(Path("/tmp"), _Provider(None))

    assert stub._apple_guess_ext(_Provider(None), AudioType.ATMOS, quality_rank(QualityTier.HI_RES_LOSSLESS)) == ".m4a"
    stub.settings.data.extract_flac = False
    assert stub._apple_guess_ext(_Provider(None), AudioType.STEREO, quality_rank(QualityTier.HI_RES_LOSSLESS)) == ".m4a"
    stub.settings.data.extract_flac = True
    assert (
        stub._apple_guess_ext(_Provider(None), AudioType.STEREO, quality_rank(QualityTier.HI_RES_LOSSLESS)) == ".flac"
    )
    assert stub._apple_guess_ext(_Provider(None), AudioType.STEREO, quality_rank(QualityTier.HIGH)) == ".m4a"
    stub.settings.data.extract_flac_all = True
    assert stub._apple_guess_ext(_Provider(None), AudioType.STEREO, quality_rank(QualityTier.HIGH)) == ".flac"

    assert stub._apple_flac_mode(_alac_info("/x"), atmos=False) == "lossless"
    assert stub._apple_flac_mode(_aac_info("/x"), atmos=False) == "lossy"
    stub.settings.data.extract_flac_all = False
    assert stub._apple_flac_mode(_aac_info("/x"), atmos=False) == ""
    assert stub._apple_flac_mode(_atmos_info("/x"), atmos=True) == ""
    stub.settings.data.extract_flac_all = True
    assert stub._apple_flac_mode(_atmos_info("/x"), atmos=True) == ""
    stub.settings.data.extract_flac = False
    assert stub._apple_flac_mode(_alac_info("/x"), atmos=False) == ""


def test_master_switch_off_keeps_the_m4a(tmp_path, monkeypatch):
    import waves.providers.apple.engine as engine

    monkeypatch.setattr(
        engine, "probe_audio_file", lambda path, ffprobe_path="": {"codec": "alac", "sample_rate": "44100"}
    )
    monkeypatch.setattr(engine, "decode_check", lambda *a, **k: None)
    staged = tmp_path / "staged.m4a"
    staged.write_bytes(b"original-bytes")
    provider = _Provider(_alac_info(str(staged)))
    stub = _apple_stub(tmp_path / "lib", provider, extract_flac=False)

    delivered = _deliver(stub, provider)

    assert delivered["path"] == str(tmp_path / "lib" / "Aphex Twin" / "Xtal.m4a")
    assert Path(delivered["path"]).read_bytes() == b"original-bytes"


def test_aac_stays_m4a_under_the_lossless_scope(tmp_path, monkeypatch):
    import waves.providers.apple.engine as engine

    monkeypatch.setattr(
        engine, "probe_audio_file", lambda path, ffprobe_path="": {"codec": "aac", "sample_rate": "44100"}
    )
    monkeypatch.setattr(engine, "decode_check", lambda *a, **k: None)
    staged = tmp_path / "staged.m4a"
    staged.write_bytes(b"original-bytes")
    provider = _Provider(_aac_info(str(staged)))
    stub = _apple_stub(tmp_path / "lib", provider)

    delivered = _deliver(stub, provider)

    assert delivered["path"].endswith(".m4a")
    assert delivered["quality"]["tier"] == QualityTier.HIGH.value


def test_atmos_stays_m4a_even_under_the_all_scope(tmp_path, monkeypatch):
    import waves.providers.apple.engine as engine

    monkeypatch.setattr(
        engine, "probe_audio_file", lambda path, ffprobe_path="": {"codec": "eac3", "sample_rate": "48000"}
    )
    monkeypatch.setattr(engine, "decode_check", lambda *a, **k: None)
    staged = tmp_path / "staged.m4a"
    staged.write_bytes(b"original-bytes")
    provider = _Provider(_atmos_info(str(staged)))
    stub = _apple_stub(tmp_path / "lib", provider, extract_flac_all=True)

    delivered = WavesBridge._apple_deliver_track(
        stub,
        provider,
        _track_row(),
        None,
        type_media="track",
        file_template="{artist_name}/{track_title}",
        collection=False,
        list_pos=1,
        list_total=1,
        num_volumes=1,
        audio_type=AudioType.ATMOS,
        requested_rank=quality_rank(QualityTier.HIGH),
        requested_tier=QualityTier.HIGH,
        ceiling_rank=quality_rank(QualityTier.HIGH),
        force=False,
        owned_path=None,
        job_abort=Event(),
        signals=None,
    )

    assert delivered["path"].endswith(".m4a")


@needs_ffmpeg
def test_alac_converts_to_flac_by_default(tmp_path, monkeypatch):
    import waves.providers.apple.engine as engine

    real_probe = engine.probe_audio_file
    real_decode = engine.decode_check
    monkeypatch.setattr(engine, "probe_audio_file", lambda path, ffprobe_path="": real_probe(path, ffprobe_path))
    monkeypatch.setattr(engine, "decode_check", lambda *a, **k: real_decode(*a, **k))
    staged = tmp_path / "staged.m4a"
    _tone(staged, codec="alac")
    provider = _Provider(_alac_info(str(staged)))
    stub = _apple_stub(tmp_path / "lib", provider)

    delivered = _deliver(stub, provider)

    assert delivered["path"] == str(tmp_path / "lib" / "Aphex Twin" / "Xtal.flac")
    assert not (tmp_path / "lib" / "Aphex Twin" / "Xtal.m4a").exists()
    landed_probe = real_probe(delivered["path"], "")
    assert str(landed_probe.get("codec") or "") == "flac"
    assert delivered["quality"]["tier"] == QualityTier.LOSSLESS.value
    assert delivered["quality"]["audio_mode"] == "STEREO"
    assert provider.discarded == [str(staged)]
    # Bit for bit identical: the ALAC->FLAC step is a lossless decode +
    # encode pair (a stream copy is impossible: FLAC holds FLAC packets
    # only), so both files decode to the same PCM.
    pcm_src = subprocess.run(  # noqa: S603 (fixed argv: local fixtures, no user input)
        [_ffmpeg(), "-v", "error", "-i", str(staged), "-f", "s16le", "-acodec", "pcm_s16le", "-"],
        check=True,
        capture_output=True,
    ).stdout
    pcm_out = subprocess.run(  # noqa: S603 (fixed argv: local fixtures, no user input)
        [_ffmpeg(), "-v", "error", "-i", delivered["path"], "-f", "s16le", "-acodec", "pcm_s16le", "-"],
        check=True,
        capture_output=True,
    ).stdout
    assert pcm_src == pcm_out


@needs_ffmpeg
def test_aac_transcodes_to_flac_under_the_all_scope_without_promotion(tmp_path, monkeypatch):
    import waves.providers.apple.engine as engine

    real_probe = engine.probe_audio_file
    real_decode = engine.decode_check
    monkeypatch.setattr(engine, "probe_audio_file", lambda path, ffprobe_path="": real_probe(path, ffprobe_path))
    monkeypatch.setattr(engine, "decode_check", lambda *a, **k: real_decode(*a, **k))
    staged = tmp_path / "staged.m4a"
    _tone(staged, codec="aac")
    provider = _Provider(_aac_info(str(staged)))
    stub = _apple_stub(tmp_path / "lib", provider, extract_flac_all=True)

    delivered = _deliver(stub, provider)

    assert delivered["path"] == str(tmp_path / "lib" / "Aphex Twin" / "Xtal.flac")
    landed_probe = real_probe(delivered["path"], "")
    assert str(landed_probe.get("codec") or "") == "flac"
    # Transcoded lossy keeps its HIGH tier: the FLAC container never promotes it.
    assert delivered["quality"]["tier"] == QualityTier.HIGH.value


def test_conversion_encodes_flac_without_resampling(tmp_path, monkeypatch):
    """The Apple FLAC step is always a FLAC encode with no rate/depth flags.

    ALAC cannot stream-copy into a FLAC container, so even the lossless mode
    encodes -- losslessly, with the source's own rate and channels.
    """
    import waves.providers.apple.engine as engine

    monkeypatch.setattr(engine, "decode_check", lambda *a, **k: None)
    calls: list = []

    class _FakeFFmpeg:
        def __init__(self, executable=None):
            pass

        def option(self, *a):
            return self

        def input(self, **k):
            return self

        def output(self, **k):
            calls.append(dict(k))
            self._out = Path(str(k["url"]))
            return self

        def execute(self):
            self._out.write_bytes(b"converted")

    monkeypatch.setattr("ffmpeg.FFmpeg", _FakeFFmpeg)
    ffmpeg_bin = tmp_path / "ffmpeg"
    ffmpeg_bin.write_bytes(b"x")
    stub = _apple_stub(tmp_path / "lib", _Provider(None), path_binary_ffmpeg=str(ffmpeg_bin))
    staged = tmp_path / "staged.m4a"
    staged.write_bytes(b"audio")

    out, tmpdir = stub._apple_extract_flac(staged)
    assert out.suffix == ".flac" and Path(tmpdir) in out.parents
    assert calls[-1].get("acodec") == "flac"
    assert "sample_rate" not in calls[-1] and "audio_bitrate" not in calls[-1] and "ar" not in calls[-1]


@needs_ffmpeg
def test_verify_runs_before_conversion(tmp_path, monkeypatch):
    import waves.providers.apple.engine as engine

    monkeypatch.setattr(engine, "decode_check", lambda *a, **k: None)
    order: list = []
    staged = tmp_path / "staged.m4a"
    staged.write_bytes(b"original-bytes")
    provider = _Provider(_alac_info(str(staged)))
    stub = _apple_stub(tmp_path / "lib", provider)

    def _spy_verify(path, **kwargs):
        order.append(("verify", str(path)))
        # Record only: the bytes are a fixture, verification itself is
        # pinned by the engine's own tests and the real-ffmpeg runs above.
        return None

    def _spy_extract(path, **kwargs):
        order.append(("extract", str(path)))
        work = tmp_path / "flac-work"
        work.mkdir(exist_ok=True)
        out = work / "converted.flac"
        # Real bytes: tagging runs on the placed file after this.
        _tone(out, codec="flac")
        return out, str(work)

    stub._apple_verify_staged = _spy_verify
    stub._apple_extract_flac = _spy_extract

    delivered = _deliver(stub, provider)

    assert [step for step, _ in order] == ["verify", "extract"]
    assert order[0][1] == str(staged)
    assert order[1][1] == str(staged)
    assert delivered["path"].endswith(".flac")


def test_stream_info_matrix_pins_all_four_cells():
    alac = StreamInfo(urls=[], file_extension=".flac", codecs="alac", requires_flac_extraction=True)
    assert (alac.file_extension, alac.requires_flac_extraction) == (".flac", True)

    aac = StreamInfo(urls=[], file_extension=".m4a", codecs="mp4a.40.2", requires_flac_extraction=False)
    assert (aac.file_extension, aac.requires_flac_extraction) == (".m4a", False)

    atmos = StreamInfo(urls=[], file_extension=".m4a", codecs="ec-3", requires_flac_extraction=False)
    assert (atmos.file_extension, atmos.requires_flac_extraction) == (".m4a", False)

    tidal_flac = StreamInfo(urls=["https://seg/1"], file_extension=".flac", codecs="flac")
    assert tidal_flac.file_extension == ".flac"
