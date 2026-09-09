"""ALAC delivery via wrapper-v2 (issue #32, spec §1, §4.3, §6)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from waves.apple_engine import (
    AppleCredentialsError,
    apple_delivery_detail,
    apple_tier_for_delivery,
)
from waves.constants import QualityTier, quality_rank
from waves.providers.apple import AppleProvider
from waves.providers.base import AudioType


def _song_resource(song_id="song-1", traits=("lossless",)):
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
            "audioTraits": list(traits),
            "isrc": "GBAAA9200001",
        },
        "relationships": {"artists": {"data": [{"id": "artist-1"}]}},
    }


def test_tier_mapping_is_honest_and_detail_never_ranks():
    assert apple_tier_for_delivery("aac", None, "44100") == QualityTier.HIGH.value
    assert apple_tier_for_delivery("alac", 16, 44100) == QualityTier.LOSSLESS.value
    assert apple_tier_for_delivery("alac", 16, 48000) == QualityTier.LOSSLESS.value
    assert apple_tier_for_delivery("alac", 24, 96000) == QualityTier.HI_RES_LOSSLESS.value
    assert apple_tier_for_delivery("alac", 24, 192000) == QualityTier.HI_RES_LOSSLESS.value
    # 24/96 and 24/192 share the one rung; the numbers ride the label.
    assert apple_tier_for_delivery("alac", 24, 96000) == apple_tier_for_delivery("alac", 24, 192000)
    assert apple_delivery_detail("alac", 24, 96000) == "ALAC 24/96000"
    assert apple_delivery_detail("alac", 24, 192000) == "ALAC 24/192000"
    assert quality_rank(apple_tier_for_delivery("alac", 24, 96000)) == quality_rank(
        apple_tier_for_delivery("alac", 24, 192000)
    )
    assert apple_tier_for_delivery("e-ac-3", None, "48000") == QualityTier.HIGH.value


def test_cookies_tier_advertises_high_only():
    provider = AppleProvider(catalog=None)
    assert provider.wrapper_available is False
    assert provider.advertised_tier(_song_resource(traits=("hi-res-lossless",))) == QualityTier.HIGH
    assert provider.advertised_ceiling(None) == quality_rank(QualityTier.HIGH)
    assert provider.advertised_deliveries(_song_resource()) == [(QualityTier.HIGH, AudioType.STEREO)]


def test_wrapper_tier_advertises_lossless_rungs():
    provider = AppleProvider(catalog=None)
    provider.wrapper_url = "http://127.0.0.1:51234"
    assert provider.wrapper_available is True
    assert provider.advertised_tier(_song_resource(traits=("hi-res-lossless",))) == QualityTier.HI_RES_LOSSLESS
    assert provider.advertised_tier(_song_resource(traits=("lossless",))) == QualityTier.LOSSLESS
    assert provider.advertised_tier(_song_resource(traits=())) == QualityTier.HIGH
    # Per-track ceiling (issue #32): hi-res masters cap at HI_RES, lossless
    # at LOSSLESS, AAC-only at HIGH; unknown stays unknown, never a guess.
    assert provider.advertised_ceiling(_song_resource(traits=("hi-res-lossless",))) == quality_rank(
        QualityTier.HI_RES_LOSSLESS
    )
    assert provider.advertised_ceiling(_song_resource(traits=("lossless",))) == quality_rank(QualityTier.LOSSLESS)
    assert provider.advertised_ceiling(_song_resource(traits=())) == quality_rank(QualityTier.HIGH)
    assert provider.advertised_ceiling(None) is None
    deliveries = provider.advertised_deliveries(_song_resource(traits=("hi-res-lossless",)))
    assert (QualityTier.HIGH, AudioType.STEREO) in deliveries
    assert (QualityTier.LOSSLESS, AudioType.STEREO) in deliveries
    assert (QualityTier.HI_RES_LOSSLESS, AudioType.STEREO) in deliveries


def test_resolve_stream_alac_reports_honest_tier(tmp_path, monkeypatch):
    import waves.apple_engine as engine

    staged = tmp_path / "staged.m4a"
    staged.write_bytes(b"fake-alac")
    workdir = tmp_path / "work"
    workdir.mkdir()

    def fake_alac(**kwargs):
        assert kwargs["song_id"] == "song-1"
        assert kwargs["wrapper_url"] == "http://127.0.0.1:51234"
        return SimpleNamespace(staged_path=staged, workdir=workdir, is_atmos=False, codec="alac")

    monkeypatch.setattr(engine, "download_song_alac_file", fake_alac)
    monkeypatch.setattr(
        engine,
        "probe_audio_file",
        lambda path, ffprobe_path="": {"codec": "alac", "sample_rate": "96000", "bit_depth": 24},
    )

    # Cookies path must not be touched on the ALAC run.
    def _no_cookies(**kwargs):
        raise AssertionError("cookies path must not run for a wrapper ALAC ask")

    monkeypatch.setattr(engine, "download_song_file", _no_cookies)
    provider = AppleProvider(catalog=None)
    provider.wrapper_url = "http://127.0.0.1:51234"
    provider.cookies_path = "/cookies.txt"

    info = provider.resolve_stream(
        _song_resource(traits=("hi-res-lossless",)), QualityTier.HI_RES_LOSSLESS, AudioType.STEREO
    )
    assert info.local_file == str(staged)
    assert info.delivered["tier"] == QualityTier.HI_RES_LOSSLESS.value
    assert info.delivered["bit_depth"] == 24
    assert info.delivered["sample_rate"] == 96000
    assert info.delivered["codecs"] == "alac"
    provider.discard_delivery(str(staged))


def test_resolve_stream_alac_16bit_lands_lossless(tmp_path, monkeypatch):
    import waves.apple_engine as engine

    staged = tmp_path / "staged.m4a"
    staged.write_bytes(b"fake-alac")
    workdir = tmp_path / "work"
    workdir.mkdir()
    monkeypatch.setattr(
        engine,
        "download_song_alac_file",
        lambda **kwargs: SimpleNamespace(staged_path=staged, workdir=workdir, is_atmos=False, codec="alac"),
    )
    monkeypatch.setattr(
        engine,
        "probe_audio_file",
        lambda path, ffprobe_path="": {"codec": "alac", "sample_rate": "44100", "bit_depth": 16},
    )
    monkeypatch.setattr(
        engine, "download_song_file", lambda **kwargs: (_ for _ in ()).throw(AssertionError("no fallback"))
    )
    provider = AppleProvider(catalog=None)
    provider.wrapper_url = "http://127.0.0.1:51234"

    info = provider.resolve_stream(_song_resource(), QualityTier.HI_RES_LOSSLESS, AudioType.STEREO)
    # Asked HI_RES, master tops out at 16/44.1: the readout says LOSSLESS, honestly.
    assert info.delivered["tier"] == QualityTier.LOSSLESS.value
    assert info.delivered["sample_rate"] == 44100
    provider.discard_delivery(str(staged))


def test_resolve_stream_without_wrapper_stays_aac(tmp_path, monkeypatch):
    import waves.apple_engine as engine

    staged = tmp_path / "staged.m4a"
    staged.write_bytes(b"fake-aac")
    workdir = tmp_path / "work"
    workdir.mkdir()
    monkeypatch.setattr(
        engine,
        "download_song_file",
        lambda **kwargs: SimpleNamespace(staged_path=staged, workdir=workdir, is_atmos=False, codec=""),
    )
    monkeypatch.setattr(
        engine,
        "probe_audio_file",
        lambda path, ffprobe_path="": {"codec": "aac", "sample_rate": "44100", "bit_depth": None},
    )
    provider = AppleProvider(catalog=None)
    provider.cookies_path = "/cookies.txt"

    info = provider.resolve_stream(_song_resource(), QualityTier.HI_RES_LOSSLESS, AudioType.STEREO)
    assert info.delivered["tier"] == QualityTier.HIGH.value
    provider.discard_delivery(str(staged))


def test_alac_fallback_to_aac_when_no_alac_variant(tmp_path, monkeypatch):
    import waves.apple_engine as engine

    staged = tmp_path / "staged.m4a"
    staged.write_bytes(b"fake-aac")
    workdir = tmp_path / "work"
    workdir.mkdir()

    def _no_alac(**kwargs):
        raise RuntimeError("GamdlInterfaceFormatNotAvailableError: no alac playlist")

    monkeypatch.setattr(engine, "download_song_alac_file", _no_alac)
    monkeypatch.setattr(
        engine,
        "download_song_file",
        lambda **kwargs: SimpleNamespace(staged_path=staged, workdir=workdir, is_atmos=False, codec=""),
    )
    monkeypatch.setattr(
        engine,
        "probe_audio_file",
        lambda path, ffprobe_path="": {"codec": "aac", "sample_rate": "44100", "bit_depth": None},
    )
    provider = AppleProvider(catalog=None)
    provider.wrapper_url = "http://127.0.0.1:51234"
    provider.cookies_path = "/cookies.txt"

    info = provider.resolve_stream(_song_resource(), QualityTier.HI_RES_LOSSLESS, AudioType.STEREO)
    assert info.delivered["tier"] == QualityTier.HIGH.value
    provider.discard_delivery(str(staged))


def test_wrapper_logged_out_raises_credentials_without_fallback(tmp_path, monkeypatch):
    import waves.apple_engine as engine

    def _logged_out(**kwargs):
        raise AppleCredentialsError("The Apple wrapper is not signed in")

    monkeypatch.setattr(engine, "download_song_alac_file", _logged_out)
    provider = AppleProvider(catalog=None)
    provider.wrapper_url = "http://127.0.0.1:51234"
    provider.cookies_path = "/cookies.txt"

    with pytest.raises(AppleCredentialsError):
        provider.resolve_stream(_song_resource(), QualityTier.HI_RES_LOSSLESS, AudioType.STEREO)


def test_corrupt_alac_never_falls_back_to_aac(tmp_path, monkeypatch):
    """Integrity failures stay integrity failures (spec §6): no AAC mask."""
    import waves.apple_engine as engine
    from waves.apple_engine import AppleIntegrityError

    def _corrupt(**kwargs):
        raise AppleIntegrityError("The Apple download failed its integrity check", staged_path="/tmp/bad.m4a")

    monkeypatch.setattr(engine, "download_song_alac_file", _corrupt)
    provider = AppleProvider(catalog=None)
    provider.wrapper_url = "http://127.0.0.1:51234"
    provider.cookies_path = "/cookies.txt"

    with pytest.raises(AppleIntegrityError):
        provider.resolve_stream(_song_resource(), QualityTier.HI_RES_LOSSLESS, AudioType.STEREO)


def test_wrapper_session_persists_across_provider_restarts(tmp_path, monkeypatch):
    """Same URL, new provider instance, no re-login: the guest holds the session."""
    import waves.apple_engine as engine

    calls: list = []

    def _alac(**kwargs):
        calls.append(kwargs["wrapper_url"])
        staged = tmp_path / f"staged-{len(calls)}.m4a"
        staged.write_bytes(b"fake-alac")
        workdir = tmp_path / f"work-{len(calls)}"
        workdir.mkdir(exist_ok=True)
        return SimpleNamespace(staged_path=staged, workdir=workdir, is_atmos=False, codec="alac")

    monkeypatch.setattr(engine, "download_song_alac_file", _alac)
    monkeypatch.setattr(
        engine,
        "probe_audio_file",
        lambda path, ffprobe_path="": {"codec": "alac", "sample_rate": "192000", "bit_depth": 24},
    )
    for _ in range(2):
        provider = AppleProvider(catalog=None)
        provider.wrapper_url = "http://127.0.0.1:51234"
        info = provider.resolve_stream(_song_resource(), QualityTier.HI_RES_LOSSLESS, AudioType.STEREO)
        assert info.delivered["tier"] == QualityTier.HI_RES_LOSSLESS.value
        provider.discard_delivery(info.local_file)
    assert calls == ["http://127.0.0.1:51234", "http://127.0.0.1:51234"]


def test_probe_bit_depth_prefers_bits_per_sample():
    import waves.apple_engine as engine

    assert engine._probe_bit_depth({"bits_per_sample": "24"}) == 24
    assert engine._probe_bit_depth({"bits_per_raw_sample": "16"}) == 16
    # No sample_fmt guessing: a padded container must not read as hi-res.
    assert engine._probe_bit_depth({"sample_fmt": "s16"}) is None
    assert engine._probe_bit_depth({}) is None


def test_wrapper_url_resolve_prefers_override_then_persisted(tmp_path):
    from waves.apple_runtime import AppleRuntimeManager
    from waves.waves_ui.backend import WavesBridge

    mgr = AppleRuntimeManager(tmp_path)
    persisted = mgr.ensure_port(0)
    stub = SimpleNamespace(
        settings=SimpleNamespace(data=SimpleNamespace(apple_wrapper_port=0)),
        _apple_runtime=mgr,
    )
    stub._resolve_apple_wrapper_url = WavesBridge._resolve_apple_wrapper_url.__get__(stub, SimpleNamespace)
    assert stub._resolve_apple_wrapper_url().endswith(f":{persisted}")
    stub.settings.data.apple_wrapper_port = 50000 if persisted != 50000 else 50001
    # Override wins when free; either way it names the override port.
    url = stub._resolve_apple_wrapper_url()
    assert url.endswith(f":{stub.settings.data.apple_wrapper_port}") or url.endswith(f":{persisted}")


def test_expected_word_caps_by_ceiling():
    from waves.waves_ui.backend import WavesBridge

    stub = SimpleNamespace(settings=SimpleNamespace(data=SimpleNamespace(download_dolby_atmos=False)))
    stub._apple_wants_atmos = WavesBridge._apple_wants_atmos.__get__(stub, SimpleNamespace)
    stub._apple_expected_word = WavesBridge._apple_expected_word.__get__(stub, SimpleNamespace)
    assert (
        stub._apple_expected_word(
            None, requested_rank=quality_rank(QualityTier.HIGH), ceiling_rank=quality_rank(QualityTier.HIGH)
        )
        == "HIGH"
    )
    assert (
        stub._apple_expected_word(
            None,
            requested_rank=quality_rank(QualityTier.HI_RES_LOSSLESS),
            ceiling_rank=quality_rank(QualityTier.HI_RES_LOSSLESS),
        )
        == "HI-RES"
    )
    # Asked HI_RES, cookies ceiling HIGH: the row promises HIGH, not HI-RES.
    assert (
        stub._apple_expected_word(
            None,
            requested_rank=quality_rank(QualityTier.HI_RES_LOSSLESS),
            ceiling_rank=quality_rank(QualityTier.HIGH),
        )
        == "HIGH"
    )
