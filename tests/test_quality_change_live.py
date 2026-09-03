"""Issue #9: a saved audio-quality change must reach the tidal session live.

Streams are requested at the SESSION's audio quality (the Waves UI never
passes a per-download quality), and historically that was only written at
startup, so a settings change kept downloading at the old quality until the
app was restarted. applySettings must re-apply settings to the tidal session
whenever the audio quality changes -- through the provider's ``apply_quality``
(the seam, ticket #22), which writes the tier it maps the Waves rung to and
then runs the same settings_apply body.

Tested with the method-bound stub pattern (no display, no live bridge).
"""

from __future__ import annotations

from threading import Lock
from types import SimpleNamespace

from waves.waves_ui.backend import WavesBridge


class _Stub:
    """Bare object the real applySettings gets bound onto."""


def _signal():
    return SimpleNamespace(emit=lambda *a: None)


def _apply_stub():
    stub = _Stub()
    stub._waves_prefs = {}
    stub.settings = SimpleNamespace(
        data=SimpleNamespace(tidal_quality_audio="HIGH", ffmpeg_source="system", downloads_concurrent_max=3),
        save=lambda: None,
    )
    stub._ffmpeg_flag_prefs = {}
    # applySettings does its ffmpeg restores and its write under this lock, the
    # same one _save_settings holds, so a worker save cannot slip its borrowed
    # path into the write. A stub that drives applySettings needs the real thing.
    stub._settings_save_lock = Lock()
    # The real bridge hands the disk write to a background writer; the stub
    # runs it inline through its own settings.save seam.
    stub._submit_settings_write = lambda: stub.settings.save()
    stub._restore_ffmpeg_flags = lambda: None
    stub._restore_ffmpeg_path = lambda: None
    stub._ffmpeg_source_label = lambda: "system"
    stub._waves_pref_bool = lambda key: False
    stub.ownershipChanged = _signal()
    stub.targetTierChanged = _signal()  # the DEFAULT mark in a badge's quality menu (issue #36)
    stub.editionMergeChanged = _signal()
    stub.ffmpegStatusChanged = _signal()
    stub.skipExistingChanged = _signal()
    stub.dl_pool = SimpleNamespace(setMaxThreadCount=lambda n: None)
    stub._logged_in = False
    stub._set_status = lambda text: None
    # The quality re-apply rides the provider (ticket #22). The fake records
    # the (tier, audio type) it was asked for, then does what the real
    # provider's apply_quality does: write the mapped tier and run
    # settings_apply against the stub's own settings object.
    calls = []

    def fake_apply_quality(tier, audio_type):
        calls.append((str(tier), str(audio_type)))
        stub.settings.data.tidal_quality_audio = str(tier.value)

    stub.providers = {"tidal": SimpleNamespace(apply_quality=fake_apply_quality)}
    stub._apply_quality_calls = calls
    stub._reapply_quality = WavesBridge._reapply_quality.__get__(stub, _Stub)
    stub._reapply_provider_quality = WavesBridge._reapply_provider_quality.__get__(stub, _Stub)
    return stub


def _apply(stub, values):
    WavesBridge.applySettings.__get__(stub, type(stub))(values)


def test_tidal_quality_change_reapplies_session_settings():
    stub = _apply_stub()
    _apply(stub, {"tidal_quality_audio": "HI_RES_LOSSLESS"})
    assert stub._apply_quality_calls == [("HI_RES_LOSSLESS", "stereo")], (
        "quality change never reached the provider's apply_quality"
    )
    assert stub.settings.data.tidal_quality_audio == "HI_RES_LOSSLESS"


def test_unrelated_save_leaves_session_untouched():
    stub = _apply_stub()
    _apply(stub, {"skip_existing": True})
    assert not stub._apply_quality_calls
