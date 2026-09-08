"""Apple download seam: tier words, Atmos choice, facts, refusals, resolve."""

from __future__ import annotations

import shutil
from types import SimpleNamespace

import pytest

from waves.apple_engine import AppleCredentialsError
from waves.constants import QualityTier, quality_rank
from waves.providers.apple import AppleProvider
from waves.providers.base import AudioType, RefusalKind


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
            "contentRating": "explicit",
        },
        "relationships": {"artists": {"data": [{"id": "artist-1"}]}},
    }


def test_cookies_tier_advertises_high_with_optional_atmos():
    provider = AppleProvider(catalog=None)

    assert provider.advertised_tier({}) == QualityTier.HIGH
    assert provider.advertised_deliveries(_song_resource(atmos=False)) == [(QualityTier.HIGH, AudioType.STEREO)]
    assert provider.advertised_deliveries(_song_resource(atmos=True)) == [
        (QualityTier.HIGH, AudioType.STEREO),
        (QualityTier.HIGH, AudioType.ATMOS),
    ]
    assert provider.advertised_ceiling({}) == quality_rank(QualityTier.HIGH)


def test_atmos_is_instead_of_stereo_with_stereo_fallback():
    provider = AppleProvider(catalog=None)

    assert provider._delivery_atmos(_song_resource(atmos=True), AudioType.ATMOS) is True
    assert provider._delivery_atmos(_song_resource(atmos=False), AudioType.ATMOS) is False
    assert provider._delivery_atmos(_song_resource(atmos=True), AudioType.STEREO) is False
    assert provider._delivery_atmos(_song_resource(atmos=True), None) is False


def test_track_facts_follow_the_seam_schema_namespaced():
    provider = AppleProvider(catalog=None)

    facts = provider.track_facts(_song_resource())

    assert facts["item_id"] == "apple:song-1"
    assert facts["artist_ids"] == ["apple:artist-1"]
    assert facts["artists"] == [("apple:artist-1", "Aphex Twin")]
    assert facts["isrc"] == "GBAAA9200001"
    assert facts["explicit"] is True
    assert facts["track_num"] == 1 and facts["volume_num"] == 1
    assert facts["album"]["name"] == "Selected Ambient Works 85-92"


def test_track_facts_name_only_the_first_of_several_credits():
    provider = AppleProvider(catalog=None)
    resource = _song_resource()
    resource["relationships"] = {"artists": {"data": [{"id": "artist-1"}, {"id": "artist-2"}]}}

    facts = provider.track_facts(resource)

    assert facts["artist_ids"] == ["apple:artist-1", "apple:artist-2"]
    assert facts["artists"] == [("apple:artist-1", "Aphex Twin"), ("apple:artist-2", "")]


def test_classify_refusal_sorts_credentials_throttle_and_gone():
    provider = AppleProvider(catalog=None)

    creds = provider.classify_refusal(AppleCredentialsError("need cookies"))
    assert creds.kind is RefusalKind.FAILURE and "cookies" in creds.message

    throttled = provider.classify_refusal(RuntimeError("HTTP 429 too many requests"))
    assert throttled.kind is RefusalKind.THROTTLED

    gone = provider.classify_refusal(RuntimeError("song 404 not found"))
    assert gone.kind is RefusalKind.UNAVAILABLE

    other = provider.classify_refusal(RuntimeError("boom"))
    assert other.kind is RefusalKind.FAILURE


def test_resolve_stream_delivers_a_staged_file_and_releases_it(tmp_path, monkeypatch):
    import waves.apple_engine as engine

    staged = tmp_path / "staged.m4a"
    staged.write_bytes(b"fake-audio")
    workdir = tmp_path / "work"
    workdir.mkdir()

    def fake_download_song_file(**kwargs):
        assert kwargs["song_id"] == "song-1"
        assert kwargs["atmos"] is False
        assert kwargs["cookies_path"] == "/cookies.txt"
        return SimpleNamespace(staged_path=staged, workdir=workdir, is_atmos=False, codec="")

    monkeypatch.setattr(engine, "download_song_file", fake_download_song_file)
    monkeypatch.setattr(engine, "cleanup_delivery", lambda delivery: workdir.rmdir())
    provider = AppleProvider(catalog=None)
    provider.cookies_path = "/cookies.txt"

    info = provider.resolve_stream(_song_resource(), QualityTier.HI_RES_LOSSLESS, AudioType.STEREO)

    assert info.local_file == str(staged)
    assert info.urls == [] and info.single_file is True and info.file_extension == ".m4a"
    assert info.delivered["tier"] == QualityTier.HIGH.value
    assert info.delivered["audio_type"] == str(AudioType.STEREO)
    assert str(staged) in provider._staged
    provider.discard_delivery(str(staged))
    assert str(staged) not in provider._staged
    assert not workdir.exists()


def test_resolve_stream_without_cookies_raises_before_touching_gamdl():
    provider = AppleProvider(catalog=None)
    provider.cookies_path = ""

    with pytest.raises(AppleCredentialsError):
        provider.resolve_stream(_song_resource(), QualityTier.HIGH, AudioType.STEREO)


def test_missing_binaries_name_the_settings_field(tmp_path, monkeypatch):
    import waves.apple_engine as engine

    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape\n")
    monkeypatch.setattr(engine.shutil, "which", lambda name: None)

    with pytest.raises(engine.AppleDownloadError, match="N_m3u8DL-RE"):
        engine.download_song_file(song_id="song-1", atmos=False, cookies_path=str(cookies))


def test_ffprobe_prefers_the_ffmpeg_sibling(tmp_path, monkeypatch):
    import waves.apple_engine as engine

    ffmpeg = tmp_path / "bin" / "ffmpeg"
    ffmpeg.parent.mkdir()
    ffmpeg.write_bytes(b"x")
    sibling = tmp_path / "bin" / "ffprobe"
    sibling.write_bytes(b"x")
    monkeypatch.setattr(engine.shutil, "which", lambda name: None)

    assert engine.ffprobe_for(str(ffmpeg)) == str(sibling)
    assert engine.ffprobe_for(str(tmp_path / "nowhere" / "ffmpeg")) == ""


needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def _ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    assert path is not None  # guarded by needs_ffmpeg
    return path


@needs_ffmpeg
def test_decode_check_accepts_clean_audio_and_rejects_garbage(tmp_path):
    import subprocess

    import waves.apple_engine as engine

    good = tmp_path / "good.m4a"
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
            str(good),
        ],
        check=True,
    )
    engine.decode_check(good)

    bad = tmp_path / "bad.m4a"
    bad.write_bytes(b"not audio at all, just text padding " * 100)
    with pytest.raises(engine.AppleDownloadError):
        engine.decode_check(bad)
