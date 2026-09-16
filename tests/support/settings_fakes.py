"""Settings-schema stand-ins shared by the settings and provider tests.

``schema_stub`` builds the minimal bridge state ``WavesBridge.settingsSchema``
reads: fresh defaults (never the machine's own config), the given Apple
switch and TIDAL session state, and the ffmpeg probes. ``prefs_stub`` is the
waves-prefs half on its own.
"""

from __future__ import annotations

from types import SimpleNamespace

from waves.constants import CTX_APPLE, CTX_TIDAL
from waves.model.cfg import HelpSettings
from waves.model.cfg import Settings as ModelSettings
from waves.providers.apple.provider import AppleProvider
from waves.providers.tidal import TidalProvider
from waves.waves_ui.backend import WavesBridge


class _Stub:
    """Bare object the real methods get bound onto."""


def _bind(stub, name):
    return getattr(WavesBridge, name).__get__(stub, type(stub))


def prefs_stub():
    stub = _Stub()
    stub._default_waves_prefs = _bind(stub, "_default_waves_prefs")
    stub._waves_prefs = stub._default_waves_prefs()
    stub._waves_pref_bool = _bind(stub, "_waves_pref_bool")
    return stub


def schema_stub(apple_enabled: bool = False, logged_in: bool = False):
    """A bridge stub with just enough state for settingsSchema(): a fresh
    defaults-only config, the given Apple switch and TIDAL session state, and
    the provider registry the schema composes its cards from (the real
    descriptors, not test copies)."""

    class _Cfg:
        data = ModelSettings()
        help = HelpSettings()

    stub = prefs_stub()
    stub.settings = _Cfg()
    stub.settings.data.apple_enabled = apple_enabled
    stub._help = HelpSettings()
    stub._help_for = _bind(stub, "_help_for")
    stub._ffmpeg_flag_prefs = {}
    stub.ffmpegState = lambda: {"status": "none", "source": "none", "path": ""}
    stub._user_ffmpeg_path = lambda: ""
    stub._ffmpeg_detected_path = lambda: ""
    stub._logged_in = logged_in
    stub.providers = {
        CTX_TIDAL: SimpleNamespace(id=CTX_TIDAL, descriptor=TidalProvider.descriptor, is_logged_in=logged_in),
        CTX_APPLE: SimpleNamespace(id=CTX_APPLE, descriptor=AppleProvider.descriptor, is_logged_in=False),
    }
    return stub
