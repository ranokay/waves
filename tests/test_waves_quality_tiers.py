"""Issue #24: the Waves quality enum and per-provider quality settings.

The four-rung ladder (LOW < HIGH < LOSSLESS < HI_RES_LOSSLESS) is Waves' own
vocabulary (``waves.constants.QualityTier``); tidalapi's ``Quality`` is engine
codec vocabulary the TIDAL engine maps onto the ladder at its own boundary.
The parse points a pinned quality string goes through -- queue pinning, the
ownership rank scale, session quality apply -- run the Waves enum, and the
``quality_audio`` setting is split into ``tidal_quality_audio`` /
``apple_quality_audio`` serialized as Waves tier strings, with one migration
carrying the old value over so nobody's settings reset.
"""

from __future__ import annotations

from threading import Lock
from types import SimpleNamespace

import pytest
from tidalapi.media import Quality

from waves.config import tidal_quality_for_tier
from waves.constants import TIER_RANK, QualityTier, quality_rank, tier_from_word
from waves.model.cfg import Settings as ModelSettings
from waves.model.cfg import Settings as _Model  # the migration subject
from waves.ownership import quality_rank as ownership_quality_rank
from waves.waves_ui.backend import WavesBridge, _enum_options

# ---- the ladder ----------------------------------------------------------------


def test_the_ladder_has_exactly_the_four_rungs_in_order():
    assert [t.value for t in QualityTier] == ["LOW", "HIGH", "LOSSLESS", "HI_RES_LOSSLESS"]
    # The ladder's "<" is its rank scale: what every comparison in the app
    # actually runs on.
    ranks = [quality_rank(t) for t in QualityTier]
    assert ranks == sorted(ranks)


def test_the_rank_scale_runs_the_enum_low_through_hi_res():
    assert quality_rank(QualityTier.LOW) == 0
    assert quality_rank(QualityTier.HIGH) == 1
    assert quality_rank(QualityTier.LOSSLESS) == 2
    assert quality_rank(QualityTier.HI_RES_LOSSLESS) == 3
    assert TIER_RANK == {"LOW": 0, "HIGH": 1, "LOSSLESS": 2, "HI_RES_LOSSLESS": 3}


def test_an_unknown_tier_ranks_below_every_real_rung():
    assert quality_rank("GARBAGE") == -1
    assert quality_rank(None) == -1
    assert quality_rank("") == -1


def test_ownership_scale_is_the_same_ladder():
    # One scale everywhere: what the ownership store ranks a delivered copy
    # with is what the bridge ranks a target with.
    for tier in QualityTier:
        assert ownership_quality_rank(tier) == quality_rank(tier)
    assert ownership_quality_rank("GARBAGE") == -1


# ---- the one fold --------------------------------------------------------------


@pytest.mark.parametrize(
    ("word", "tier"),
    [
        ("LOW", QualityTier.LOW),
        ("HIGH", QualityTier.HIGH),
        ("LOSSLESS", QualityTier.LOSSLESS),
        ("HI_RES_LOSSLESS", QualityTier.HI_RES_LOSSLESS),
        # UI words (the badge's spelling)
        ("HI-RES", QualityTier.HI_RES_LOSSLESS),
        # tidalapi value spellings (a legacy row's askQuality, a wire value)
        ("LOW_96K", QualityTier.LOW),
        ("LOW_320K", QualityTier.HIGH),
        # tidalapi member-name spellings
        ("low_320k", QualityTier.HIGH),
        ("hi_res_lossless", QualityTier.HI_RES_LOSSLESS),
        ("high_lossless", QualityTier.LOSSLESS),
    ],
)
def test_every_spelling_folds_onto_the_ladder(word, tier):
    assert tier_from_word(word) is tier


@pytest.mark.parametrize("word", ["", None, "DEFAULT", "GARBAGE", "   "])
def test_non_tier_words_fold_to_nothing(word):
    assert tier_from_word(word) is None


# ---- the settings split and its one migration -----------------------------------


def _migrated(raw_json: str) -> ModelSettings:
    data = _Model.from_json(raw_json)
    from waves.config import _migrate_settings

    _migrate_settings(data)
    return data


def test_an_existing_quality_value_lands_in_the_tidal_setting_with_identical_meaning():
    data = _migrated('{"quality_audio": "LOSSLESS", "skip_existing": true}')
    assert data.tidal_quality_audio == "LOSSLESS"


@pytest.mark.parametrize(
    ("legacy", "tier"),
    [
        ("LOW_96K", "LOW"),
        ("LOW_320K", "HIGH"),
        ("LOSSLESS", "LOSSLESS"),
        ("HI_RES_LOSSLESS", "HI_RES_LOSSLESS"),
        ("low_320k", "HIGH"),
    ],
)
def test_each_legacy_spelling_keeps_its_meaning(legacy, tier):
    assert _migrated(f'{{"quality_audio": "{legacy}"}}').tidal_quality_audio == tier


def test_the_migration_touches_no_other_setting():
    data = _migrated(
        '{"quality_audio": "HI_RES_LOSSLESS", "skip_existing": false, '
        '"download_base_path": "/music", "api_rate_limit_batch_size": 7, '
        '"lyrics_embed": true, "metadata_replay_gain": true, '
        '"replay_gain_default_migrated": true}'
    )
    assert data.skip_existing is False
    assert data.download_base_path == "/music"
    assert data.api_rate_limit_batch_size == 7
    assert data.lyrics_embed is True
    # Markers of earlier migrations the user already went through stand.
    assert data.replay_gain_default_migrated is True


def test_the_apple_setting_starts_at_its_own_default():
    data = _migrated('{"quality_audio": "LOW_320K"}')
    assert data.apple_quality_audio == "LOSSLESS"


def test_the_legacy_key_never_reaches_disk_again():
    import json

    data = _migrated('{"quality_audio": "LOSSLESS"}')
    assert "quality_audio" not in json.loads(data.to_json())


def test_a_config_without_the_legacy_key_migrates_to_nothing():
    data = _migrated('{"skip_existing": true, "tidal_quality_audio": "HI_RES_LOSSLESS"}')
    assert data.tidal_quality_audio == "HI_RES_LOSSLESS"


def test_a_corrupt_legacy_value_falls_back_to_the_tidal_default():
    assert _migrated('{"quality_audio": "ULTRA"}').tidal_quality_audio == ModelSettings().tidal_quality_audio


def test_the_stored_settings_are_tier_strings_by_default():
    fresh = ModelSettings()
    assert fresh.tidal_quality_audio == "HIGH"
    assert fresh.apple_quality_audio == "LOSSLESS"


# ---- session quality apply (the TIDAL mapping, engine boundary) ------------------


def test_the_engine_maps_each_rung_onto_its_tidal_codec():
    assert tidal_quality_for_tier(QualityTier.LOW) is Quality.low_96k
    assert tidal_quality_for_tier(QualityTier.HIGH) is Quality.low_320k
    assert tidal_quality_for_tier(QualityTier.LOSSLESS) is Quality.high_lossless
    assert tidal_quality_for_tier(QualityTier.HI_RES_LOSSLESS) is Quality.hi_res_lossless


# ---- parse points on the bridge -------------------------------------------------


def _bind(stub, *names):
    for name in names:
        setattr(stub, name, getattr(WavesBridge, name).__get__(stub))


def _bridge(tidal_quality="HIGH"):
    b = SimpleNamespace()
    b._quality_overrides = {}
    b._objs = {"track": {}, "album": {}}
    b.settings = SimpleNamespace(data=SimpleNamespace(tidal_quality_audio=tidal_quality))
    b._queue = []
    b._queue_index = {}
    b._queue_item = lambda qid: b._queue_index.get(qid)
    _bind(
        b,
        "_ask_quality_for",
        "_queued_quality_value",
        "_target_tier",
        "_target_quality_rank",
        "_max_quality_rank",
        "_job_quality",
    )
    return b


def test_a_row_s_quality_parses_through_the_waves_enum():
    b = _bridge()
    b._queue_index[1] = _row("LOSSLESS")
    assert b._job_quality(1) is QualityTier.LOSSLESS
    # A legacy spelling a pre-split row carries still folds.
    b._queue_index[1] = _row("LOW_320K")
    assert b._job_quality(1) is QualityTier.HIGH


def _row(ask_quality):
    return {"qid": 1, "askQuality": ask_quality, "quality": "HIGH"}


def test_an_unreadable_row_quality_pins_nothing():
    b = _bridge()
    b._queue_index[1] = _row("GARBAGE")
    assert b._job_quality(1) is None
    b._queue_index[1] = {"qid": 1}
    assert b._job_quality(1) is None


def test_the_settings_tier_reads_as_the_plain_tier_string():
    b = _bridge(tidal_quality="HI_RES_LOSSLESS")
    assert b._queued_quality_value() == "HI_RES_LOSSLESS"
    assert b._target_tier() == "HI-RES"


def test_the_target_rank_runs_the_enum_scale():
    b = _bridge(tidal_quality="LOSSLESS")
    assert b._target_quality_rank() == 2
    assert b._target_quality_rank(QualityTier.HI_RES_LOSSLESS) == 3
    assert b._target_quality_rank("HIGH") == 1


def test_an_ask_stores_the_tier_string_and_the_ui_word():
    b = _bridge(tidal_quality="LOW")
    b.setQualityOverride = WavesBridge.setQualityOverride.__get__(b)
    b.qualityOverridesChanged = SimpleNamespace(emit=lambda *a: None)
    b.qualityChoiceChanged = SimpleNamespace(emit=lambda *a: None)
    b.ownershipChanged = SimpleNamespace(emit=lambda *a: None)
    b._quality_choice_scope = lambda mid: [mid]
    b._quality_override_key = WavesBridge._quality_override_key.__get__(b)
    b.setQualityOverride("t1", "HI-RES")
    ask, word = b._ask_quality_for(SimpleNamespace(album=None), "track", "t1")
    assert ask == "HI_RES_LOSSLESS"
    assert word == "HI-RES"


def test_the_quality_cap_reads_the_tier_setting():
    b = _bridge(tidal_quality="HIGH")
    assert b._max_quality_rank() == 1


# ---- the settings page round-trip ------------------------------------------------


def test_the_tidal_choice_round_trips_tier_strings():
    options = _enum_options("tidal_quality_audio", QualityTier)
    assert [o["value"] for o in options] == ["LOW", "HIGH", "LOSSLESS", "HI_RES_LOSSLESS"]
    assert options[2]["label"]  # every option carries a human label


def test_the_apple_choice_exists_with_honest_labels():
    # The shared ladder drives the options; Apple's labels name its own
    # codecs and start at HIGH (Apple has no LOW rung), so LOW has no mapped
    # label and would fall back to the raw name.
    options = _enum_options("apple_quality_audio", QualityTier)
    assert [o["value"] for o in options] == ["LOW", "HIGH", "LOSSLESS", "HI_RES_LOSSLESS"]
    by_value = {o["value"]: o["label"] for o in options}
    assert by_value["HIGH"] == "High (AAC 256)"
    assert by_value["LOSSLESS"] == "Lossless (ALAC 16-bit)"
    assert by_value["HI_RES_LOSSLESS"] == "Max · Hi-Res (ALAC 24-bit)"
    assert by_value["LOW"] == "LOW"


# ---- per-provider side effects ----------------------------------------------------


class _Stub:
    """Bare object the real applySettings gets bound onto."""


def _signal():
    return SimpleNamespace(emit=lambda *a: None)


def _apply_stub(providers):
    stub = _Stub()
    stub._waves_prefs = {}
    stub.settings = SimpleNamespace(
        data=SimpleNamespace(
            tidal_quality_audio="HIGH",
            apple_quality_audio="LOSSLESS",
            quality_video="480",
            ffmpeg_source="system",
            downloads_concurrent_max=3,
        ),
        save=lambda: None,
    )
    stub._ffmpeg_flag_prefs = {}
    stub._settings_save_lock = Lock()
    stub._submit_settings_write = lambda: stub.settings.save()
    stub._restore_ffmpeg_flags = lambda: None
    stub._restore_ffmpeg_path = lambda: None
    stub._ffmpeg_source_label = lambda: "system"
    stub._waves_pref_bool = lambda key: False
    stub.ownershipChanged = _signal()
    stub.targetTierChanged = _signal()
    stub.editionMergeChanged = _signal()
    stub.ffmpegStatusChanged = _signal()
    stub.skipExistingChanged = _signal()
    stub.dl_pool = SimpleNamespace(setMaxThreadCount=lambda n: None)
    stub._logged_in = False
    stub._set_status = lambda text: None
    stub.providers = providers
    stub._reapply_quality = WavesBridge._reapply_quality.__get__(stub, _Stub)
    stub._reapply_provider_quality = WavesBridge._reapply_provider_quality.__get__(stub, _Stub)
    return stub


def _apply(stub, values):
    WavesBridge.applySettings.__get__(stub, type(stub))(values)


def _recording_provider():
    calls = []
    provider = SimpleNamespace(apply_quality=lambda tier, audio_type: calls.append((str(tier), str(audio_type))))
    return provider, calls


def test_a_tidal_quality_change_applies_to_the_tidal_provider():
    provider, calls = _recording_provider()
    stub = _apply_stub({"tidal": provider})
    _apply(stub, {"tidal_quality_audio": "HI_RES_LOSSLESS"})
    assert calls == [("HI_RES_LOSSLESS", "stereo")]
    assert stub.settings.data.tidal_quality_audio == "HI_RES_LOSSLESS"


def test_an_apple_quality_change_applies_to_the_apple_provider():
    apple, calls = _recording_provider()
    tidal, tidal_calls = _recording_provider()
    stub = _apply_stub({"tidal": tidal, "apple": apple})
    _apply(stub, {"apple_quality_audio": "HIGH"})
    assert calls == [("HIGH", "stereo")]
    assert tidal_calls == [], "a TIDAL setting change reached the Apple provider's seam"
    assert stub.settings.data.apple_quality_audio == "HIGH"


def test_the_apple_side_effect_is_skipped_without_an_apple_provider():
    tidal, tidal_calls = _recording_provider()
    stub = _apply_stub({"tidal": tidal})
    _apply(stub, {"apple_quality_audio": "HIGH"})
    assert tidal_calls == []
    assert stub.settings.data.apple_quality_audio == "HIGH"


def test_the_tidal_side_effect_carries_its_ownership_broadcast():
    provider, calls = _recording_provider()
    stub = _apply_stub({"tidal": provider})
    seen = []
    stub.ownershipChanged = SimpleNamespace(emit=lambda *a: seen.append(a))
    _apply(stub, {"tidal_quality_audio": "LOSSLESS"})
    assert calls and seen == [("",)], "the owned-copy refresh never ran"
