"""Opt-in live account checks.

Run explicitly:

    WAVES_ACCOUNT_TESTS=1 uv run --locked --all-extras pytest -q -m account tests

Without the gate every account test is skipped at collection. With it, the
module's ``real_profile`` fixture points the config path at the app's real
profile for this module only; every other test keeps the throwaway home the
root conftest installed. These tests reach real services with the user's own
credentials and never belong to the default suite. No credential value, cookie
or signed URL is written down: assertions name codecs, sizes and state words,
and the evidence records only those.

Live states that cannot be scripted (account expiry, throttling, held
recovery, the TIDAL UI journey) are recorded as gaps with the condition each
one needs, not pretended as coverage.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import ORIGINAL_XDG_CONFIG_HOME

pytestmark = pytest.mark.account

# Xtal on Selected Ambient Works 85-92: short, and the track the earlier
# wrapper-tier evidence used, so both tiers can be compared on one song.
SONG_ID = "1668862649"


@pytest.fixture(scope="module")
def real_profile():
    """The app's real Settings, for this module only.

    The root conftest points ``XDG_CONFIG_HOME`` at a throwaway home for every
    test; here the original value (or the platform-native default when it was
    unset) is restored around the fixture, and the Settings singleton is reset
    so it really re-reads the profile. The variable is put back before any
    other module runs.
    """
    from waves import config
    from waves.config import SingletonMeta

    with pytest.MonkeyPatch.context() as mp:
        if ORIGINAL_XDG_CONFIG_HOME:
            mp.setenv("XDG_CONFIG_HOME", ORIGINAL_XDG_CONFIG_HOME)
        else:
            mp.delenv("XDG_CONFIG_HOME", raising=False)
        SingletonMeta._instances.pop(config.Settings, None)
        try:
            yield config.Settings()
        finally:
            SingletonMeta._instances.pop(config.Settings, None)


def _cookies_path(profile) -> str:
    return str(getattr(profile.data, "apple_cookies_path", "") or "").strip()


def _apple_provider(profile):
    from waves.paths import path_config_base
    from waves.providers.apple.provider import AppleProvider
    from waves.providers.apple.runtime import AppleRuntimeManager

    provider = AppleProvider(catalog=None)
    provider.cookies_path = _cookies_path(profile)
    provider.ffmpeg_path = shutil.which("ffmpeg") or ""
    provider.nm3u8dlre_path = str(AppleRuntimeManager(path_config_base()).binary_path)
    return provider


def _xtal_track() -> dict:
    return {"id": SONG_ID, "title": "Xtal", "artist": "Aphex Twin"}


def _staged(stream, *, min_bytes: int) -> bytes:
    """Read the staged bytes so the assertions rest on the file, not the dict."""
    path = Path(str(stream.local_file))
    assert path.is_file()
    data = path.read_bytes()
    assert len(data) >= min_bytes, f"staged file is {len(data)} bytes"
    return data


def _probe_codec(path: Path) -> tuple[str, int]:
    """The staged file's real codec and bit rate, from ffprobe."""
    ffprobe = shutil.which("ffprobe") or ""
    assert ffprobe, "no ffprobe on PATH"
    out = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_name,bit_rate",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    stream = json.loads(out.stdout)["streams"][0]
    return str(stream.get("codec_name") or ""), int(stream.get("bit_rate") or 0)


def test_the_real_profile_verifies_its_cookies_export(real_profile):
    from waves.providers.apple.runtime import verify_cookies_file

    path = _cookies_path(real_profile)
    assert path, "no Apple cookies export configured in the real profile"
    verdict = verify_cookies_file(path)
    assert verdict["ok"] is True
    assert verdict["has_token"] is True


def test_cookies_tier_fetches_aac_live(real_profile):
    """The cookies tier (AAC stereo, no runtime) end to end."""
    from waves.constants import QualityTier

    if not _cookies_path(real_profile):
        pytest.skip("no Apple cookies export configured in the real profile")
    provider = _apple_provider(real_profile)
    stream = provider.resolve_stream(_xtal_track(), QualityTier.HIGH, "stereo")
    path = Path(str(stream.local_file))
    try:
        _staged(stream, min_bytes=1_000_000)
        codec, bit_rate = _probe_codec(path)
        assert codec == "aac", f"cookies tier probe says {codec}"
        assert 200_000 <= bit_rate <= 340_000, f"cookies tier bit rate {bit_rate} is not AAC 256k"
        assert stream.delivered["probe"]["codec"] == "aac"
        assert stream.delivered["probe"]["sample_rate"] == "44100"
        assert stream.delivered["audio_type"] == "stereo"
    finally:
        provider.discard_delivery(str(path))


def test_wrapper_tier_fetches_alac_live(real_profile):
    """The managed wrapper tier (ALAC stereo) end to end.

    The tier is reachable only through the managed sidecar with the guest's
    real session volume, so the supervisor readies it first. Readiness is the
    precondition; a sidecar already up counts, which is what the app itself
    would accept. Skipped with the exact reason when the port, the container
    runtime or the image is unavailable.
    """
    from waves.constants import QualityTier
    from waves.paths import path_config_base
    from waves.providers.apple.runtime import WRAPPER_V2_IMAGE, AppleRuntimeManager, wrapper_url
    from waves.providers.apple.supervision import SidecarSupervisor, wrapper_data_host_dir

    app_dir = path_config_base()
    manager = AppleRuntimeManager(app_dir)
    port = manager.read_port()
    if port <= 0:
        pytest.skip("the wrapper port is not provisioned in the real profile")
    if shutil.which("docker") is None:
        pytest.skip("no container runtime on PATH")
    supervisor = SidecarSupervisor(manager=manager)
    if not supervisor.ensure_started(http_port=port, image=WRAPPER_V2_IMAGE, data_dir=wrapper_data_host_dir(app_dir)):
        pytest.skip("the wrapper sidecar would not come up")

    provider = _apple_provider(real_profile)
    provider.wrapper_url = wrapper_url(port)
    stream = provider.resolve_stream(_xtal_track(), QualityTier.LOSSLESS, "stereo")
    path = Path(str(stream.local_file))
    try:
        _staged(stream, min_bytes=5_000_000)
        codec, _bit_rate = _probe_codec(path)
        assert codec == "alac", f"wrapper tier probe says {codec}"
        assert stream.codecs == "alac"
        assert stream.delivered["audio_type"] == "stereo"
        assert int(stream.delivered["bit_depth"] or 0) >= 16
        assert int(stream.delivered["sample_rate"] or 0) >= 44100
    finally:
        provider.discard_delivery(str(path))


def test_tidal_session_resumes_and_searches_live(real_profile):
    """The saved TIDAL session resumes and answers a search.

    The J1-J3 UI journey (sign in from the card with Apple on, both providers
    reachable, sign out, reverse order, relaunch) needs the credential typed in
    a browser; it is recorded as manual evidence in the run notes. This test
    proves the resumable session half once a sign-in exists.
    """
    from waves.paths import path_file_token

    if not Path(path_file_token()).is_file():
        pytest.skip("no TIDAL token in the real profile; sign in through the app first")
    from waves.desktop.session import WavesTidal
    from waves.providers.tidal import TidalProvider

    provider = TidalProvider(WavesTidal(real_profile))
    if not provider.login_resume():
        pytest.skip("the saved TIDAL session did not resume; sign in again")
    account = provider.account_id()
    assert account, "a resumed session answers no account id"
    results = provider.search("Aphex Twin")
    assert any(results.get(bucket) for bucket in ("artists", "albums", "tracks")), "search answered nothing"
