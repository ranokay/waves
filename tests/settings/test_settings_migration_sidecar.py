"""One-time settings migrations survive a downgrade and a re-upgrade.

The in-file markers are fields an older release does not know, and that
release rewrites settings.json from its own model on every launch, so a
downgrade strips them. The sidecar beside settings.json is what keeps a step
applied across the round trip; the tests below drive the real
``_migrate_settings`` over a simulated downgraded config and pin every user
choice it must not touch. Each assertion is a setting the user owns.

Tests that need the sidecar seeded write it into the per-test path the
``isolated_settings_migrations`` fixture installs.
"""

from __future__ import annotations

import json

import pytest

from waves.config import (
    _MIGRATION_STEPS,
    _completed_migrations,
    _migrate_settings,
    _remember_migrations,
)
from waves.model.cfg import Settings as ModelSettings

pytestmark = pytest.mark.usefixtures("isolated_settings_migrations")


def _seed_sidecar(tmp_path, steps) -> None:
    (tmp_path / "settings-migrations.json").write_text(json.dumps({"completed": list(steps)}), encoding="utf-8")


def _downgraded_config() -> ModelSettings:
    """A config as an older release leaves it: markers stripped, carriers back."""
    data = ModelSettings()
    data.metadata_replay_gain = False  # the user turned it back off
    data.replay_gain_default_migrated = False  # the marker the downgrade dropped
    data.api_rate_limit_batch_size = 50
    data.api_rate_limit_delay_sec = 60.0  # a tuned pace above the plausible max
    data.api_rate_limit_wired_migrated = False
    data.lyrics_art_per_provider_migrated = False
    data.lyrics_embed = False  # a stale shared value
    data.apple_lyrics_embed = True  # the user's per-provider choice
    data.default_audio_type = "stereo"  # the user's choice
    data.download_dolby_atmos = True  # the retired carrier, re-serialized
    return data


def test_a_seeded_sidecar_keeps_every_user_choice(tmp_path):
    _seed_sidecar(tmp_path, _MIGRATION_STEPS)
    data = _downgraded_config()

    changed = _migrate_settings(data)

    # The re-serialized carrier is dropped, and nothing else moves.
    assert changed is True
    assert data.download_dolby_atmos is None
    assert data.default_audio_type == "stereo"
    # The replay gain the user turned off stays off.
    assert data.metadata_replay_gain is False
    # The tuned pace above the plausible max stays.
    assert data.api_rate_limit_delay_sec == 60.0
    # The per-provider mirror keeps the user's choice, not the shared value.
    assert data.apple_lyrics_embed is True
    assert _completed_migrations() == set(_MIGRATION_STEPS)


def test_a_reappearing_quality_carrier_is_folded_and_dropped(tmp_path):
    # The carrier is never serialized by this model, so its presence means an
    # older release wrote the file last: its value is the newest expression of
    # the setting, and it is folded once even when the sidecar has run before.
    _seed_sidecar(tmp_path, _MIGRATION_STEPS)
    data = ModelSettings()
    data.tidal_quality_audio = "HI_RES_LOSSLESS"
    data.quality_audio = "LOW_320K"

    _migrate_settings(data)

    assert data.tidal_quality_audio == "HIGH"
    assert data.quality_audio is None


def test_a_first_run_applies_the_steps_and_records_them(tmp_path):
    data = ModelSettings()
    data.api_rate_limit_batch_size = 3
    data.api_rate_limit_delay_sec = 60.0
    data.download_dolby_atmos = True

    changed = _migrate_settings(data)

    assert changed is True
    assert data.metadata_replay_gain is True
    assert data.api_rate_limit_delay_sec == ModelSettings().api_rate_limit_delay_sec
    assert data.api_rate_limit_batch_size == 3
    assert data.default_audio_type == "both"
    assert _completed_migrations() == set(_MIGRATION_STEPS)


def test_in_file_markers_seed_the_sidecar_without_replaying(tmp_path):
    data = ModelSettings()
    data.metadata_replay_gain = False
    data.replay_gain_default_migrated = True
    data.api_rate_limit_delay_sec = 60.0
    data.api_rate_limit_wired_migrated = True
    data.apple_lyrics_embed = True
    data.lyrics_art_per_provider_migrated = True
    data.format_playlist_folder_migrated = True
    data.format_provider_segment_migrated = True

    changed = _migrate_settings(data)

    assert changed is False
    assert data.metadata_replay_gain is False
    assert data.api_rate_limit_delay_sec == 60.0
    assert data.apple_lyrics_embed is True
    assert _completed_migrations() == set(_MIGRATION_STEPS)


def test_a_partial_sidecar_runs_only_the_unrecorded_step(tmp_path):
    _seed_sidecar(tmp_path, [step for step in _MIGRATION_STEPS if step != "replay_gain_default"])
    data = ModelSettings()
    data.metadata_replay_gain = False
    data.replay_gain_default_migrated = False  # stripped by the downgrade
    data.apple_lyrics_embed = True
    data.lyrics_art_per_provider_migrated = False

    _migrate_settings(data)

    assert data.metadata_replay_gain is True  # its step was not recorded
    assert data.apple_lyrics_embed is True  # its step was, so it did not replay
    assert _completed_migrations() == set(_MIGRATION_STEPS)


def test_a_corrupt_sidecar_is_replaced_not_trusted(tmp_path):
    (tmp_path / "settings-migrations.json").write_text("{not json", encoding="utf-8")
    data = ModelSettings()

    _migrate_settings(data)

    assert _completed_migrations() == set(_MIGRATION_STEPS)


def test_step_names_from_a_newer_build_are_carried_through(tmp_path):
    _seed_sidecar(
        tmp_path,
        [step for step in _MIGRATION_STEPS if step != "replay_gain_default"] + ["future_step"],
    )
    data = ModelSettings()

    _migrate_settings(data)

    recorded = _completed_migrations()
    assert recorded == set(_MIGRATION_STEPS) | {"future_step"}


def test_record_off_leaves_the_sidecar_alone(tmp_path):
    # The production caller migrates with record=False, saves, and only then
    # records: a save that never landed must not mark the steps done.
    given = [step for step in _MIGRATION_STEPS if step != "replay_gain_default"]
    _seed_sidecar(tmp_path, given)
    data = ModelSettings()

    _migrate_settings(data, record=False)

    assert _completed_migrations() == set(given), "record=False wrote the sidecar"
    _remember_migrations(_completed_migrations())
    assert _completed_migrations() == set(_MIGRATION_STEPS)
