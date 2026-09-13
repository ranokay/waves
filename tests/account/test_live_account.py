"""Opt-in live account checks (item 22 of the audit remediation).

Run explicitly:

    WAVES_ACCOUNT_TESTS=1 .venv/bin/python -m pytest -q tests/account -m account

The gate does two things: account-marked tests are skipped without it, and
with it the root conftest leaves ``XDG_CONFIG_HOME`` alone, so the app's real
profile is the subject. These tests reach real services with the user's own
credentials and are never part of the default suite. No credential value,
cookie or signed URL is recorded anywhere; assertions name codecs, sizes and
state words only.

The TIDAL re-login (J1-J3) and the expiry/throttle/held-recovery states are
manual/live conditions rather than scripted ones: the suite reports them as
skips with the exact gap until they can be observed.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

pytestmark = pytest.mark.account

# The short Apple track the audit's live runs used (Xtal).
SONG_ID = "1668862649"


@pytest.fixture(scope="module")
def profile():
    from waves.config import Settings

    return Settings()


def _cookies_path(profile) -> str:
    return str(getattr(profile.data, "apple_cookies_path", "") or "").strip()


def _apple_provider(profile):
    from waves.helper.path import path_config_base
    from waves.providers.apple.provider import AppleProvider
    from waves.providers.apple.runtime import AppleRuntimeManager

    provider = AppleProvider(catalog=None)
    provider.cookies_path = _cookies_path(profile)
    provider.ffmpeg_path = shutil.which("ffmpeg") or ""
    provider.nm3u8dlre_path = str(AppleRuntimeManager(path_config_base()).binary_path)
    return provider


def _track() -> dict:
    return {"id": SONG_ID, "title": "Xtal", "artist": "Aphex Twin"}


def test_the_real_profile_verifies_its_cookies_export(profile):
    from waves.providers.apple.runtime import verify_cookies_file

    path = _cookies_path(profile)
    assert path, "no Apple cookies export configured in the real profile"
    verdict = verify_cookies_file(path)
    assert verdict["ok"] is True
    assert verdict["has_token"] is True


def test_cookies_tier_fetches_aac_live(profile):
    """The cookies tier (AAC 256 stereo, no runtime) end to end."""
    from waves.constants import QualityTier

    if not _cookies_path(profile):
        pytest.skip("no Apple cookies export configured in the real profile")
    provider = _apple_provider(profile)
    stream = provider.resolve_stream(_track(), QualityTier.HIGH, "stereo")
    staged = Path(str(stream.local_file))
    try:
        assert staged.is_file()
        assert staged.stat().st_size > 1_000_000, f"staged file is {staged.stat().st_size} bytes"
        assert stream.codecs == "mp4a.40.2", f"cookies tier delivered {stream.codecs}"
        assert stream.delivered["audio_type"] == "stereo"
        assert stream.delivered["tier"] == QualityTier.HIGH.value
    finally:
        provider.discard_delivery(str(staged))


def test_wrapper_tier_fetches_alac_live(profile):
    """The managed wrapper tier (ALAC stereo) end to end.

    The sidecar is started through the same supervisor the app uses; the
    guest's session volume is the real one. Skipped with the exact reason
    when the port, the container runtime or the image is unavailable.
    """
    from waves.constants import QualityTier
    from waves.helper.path import path_config_base
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

    provider = _apple_provider(profile)
    provider.wrapper_url = wrapper_url(port)
    stream = provider.resolve_stream(_track(), QualityTier.LOSSLESS, "stereo")
    staged = Path(str(stream.local_file))
    try:
        assert staged.is_file()
        assert staged.stat().st_size > 5_000_000, f"staged file is {staged.stat().st_size} bytes"
        assert stream.codecs == "alac", f"wrapper tier delivered {stream.codecs}"
        assert stream.delivered["audio_type"] == "stereo"
        assert int(stream.delivered["bit_depth"] or 0) >= 16
        assert int(stream.delivered["sample_rate"] or 0) >= 44100
    finally:
        provider.discard_delivery(str(staged))


def test_tidal_session_resumes_and_searches_live(profile):
    """The saved TIDAL session resumes and answers a search.

    The J1-J3 UI journey (sign in from the card with Apple on, both providers
    reachable, sign out, reverse order, relaunch) needs the credential typed in
    a browser and is recorded as manual evidence; this test proves the
    resumable session half once a sign-in exists.
    """
    from waves.helper.path import path_file_token

    if not Path(path_file_token()).is_file():
        pytest.skip("no TIDAL token in the real profile; sign in through the app first")
    from waves.providers.tidal import TidalProvider
    from waves.waves_ui.session import WavesTidal

    provider = TidalProvider(WavesTidal(profile))
    if not provider.login_resume():
        pytest.skip("the saved TIDAL session did not resume; sign in again")
    account = provider.account_id()
    assert account, "a resumed session answers no account id"
    results = provider.search("Aphex Twin")
    assert any(results.get(bucket) for bucket in ("artists", "albums", "tracks")), "search answered nothing"
