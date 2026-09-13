"""The Chooser one-click audio default (issue #66).

Replaces the retired Download-Dolby-Atmos toggle one for one: "stereo", or
"both" for stereo + Atmos side by side. Atmos-alone has no Settings spelling
and stays per-click only. The toggle's stored value migrates (on = both);
the old key leaves settings.json on the next save.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from waves.config import _migrate_settings
from waves.constants import DefaultAudio, default_audio_is_both
from waves.model.cfg import Settings as ModelSettings
from waves.waves_ui.backend import WavesBridge

pytestmark = pytest.mark.usefixtures("isolated_settings_migrations")


def _migrated(raw_json: str) -> ModelSettings:
    data = ModelSettings.from_json(raw_json)
    _migrate_settings(data)
    return data


def _isolated() -> ModelSettings:
    data = ModelSettings()
    data.replay_gain_default_migrated = True
    data.api_rate_limit_wired_migrated = True
    data.lyrics_art_per_provider_migrated = True
    data.format_playlist_folder_migrated = True
    data.format_provider_segment_migrated = True
    return data


def test_toggle_on_becomes_both_and_off_stays_stereo():
    assert _migrated('{"download_dolby_atmos": true}').default_audio_type == "both"

    data = _isolated()
    data.download_dolby_atmos = False
    assert _migrate_settings(data) is True
    assert data.default_audio_type == "stereo"
    assert data.download_dolby_atmos is None


def test_absent_toggle_is_a_noop():
    data = _isolated()
    assert _migrate_settings(data) is False
    assert data.default_audio_type == "stereo"


def test_old_key_leaves_the_file_on_save():
    data = _migrated('{"download_dolby_atmos": true, "skip_existing": true}')
    assert "download_dolby_atmos" not in data.to_json()
    assert data.default_audio_type == "both"


def test_shipped_default_is_stereo():
    assert ModelSettings().default_audio_type == "stereo"


def test_both_means_both_and_everything_else_means_stereo():
    assert default_audio_is_both("both") is True
    assert default_audio_is_both(DefaultAudio.BOTH) is True
    assert default_audio_is_both("stereo") is False
    assert default_audio_is_both("") is False
    assert default_audio_is_both(None) is False
    assert default_audio_is_both("atmos") is False
    assert default_audio_is_both(True) is False


def _stub(**over):
    base = {"default_audio_type": "stereo"}
    base.update(over)
    stub = SimpleNamespace(settings=SimpleNamespace(data=SimpleNamespace(**base)))
    stub._chooser_default_audio = WavesBridge._chooser_default_audio.__get__(stub)
    stub._default_wants_both = WavesBridge._default_wants_both.__get__(stub)
    return stub


def test_chooser_default_follows_the_setting():
    assert _stub(default_audio_type="both")._chooser_default_audio() == "both"
    assert _stub(default_audio_type="stereo")._chooser_default_audio() == "stereo"
    assert _stub(default_audio_type="garbage")._chooser_default_audio() == "stereo"


def test_plain_clicks_consult_the_single_source():
    assert _stub(default_audio_type="both")._default_wants_both() is True
    assert _stub(default_audio_type="stereo")._default_wants_both() is False
    bare = SimpleNamespace()
    bare._default_wants_both = WavesBridge._default_wants_both.__get__(bare)
    assert bare._default_wants_both() is False


def test_save_defaults_writes_the_dropdown_word():
    staged: dict = {}
    stub = SimpleNamespace(applySettings=staged.update)
    stub.saveChooserDefaults = WavesBridge.saveChooserDefaults.__get__(stub)
    stub.saveChooserDefaults({"provider": "tidal", "tier": "", "audioType": "both"})
    assert staged == {"default_audio_type": "both"}
    staged.clear()
    stub.saveChooserDefaults({"provider": "tidal", "tier": "", "audioType": "stereo"})
    assert staged == {"default_audio_type": "stereo"}
    # Atmos-alone has no spelling: per-click only, never persisted.
    staged.clear()
    stub.saveChooserDefaults({"provider": "tidal", "tier": "", "audioType": "atmos"})
    assert staged == {}
