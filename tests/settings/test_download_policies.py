"""Shared policy inheritance and queued intent survive edits and retries."""

import json
from dataclasses import FrozenInstanceError, replace
from threading import Event

import pytest
from providers.apple.test_apple_engine_routing import FakeEngine, audio
from settings.fakes import schema_stub

from waves.constants import QualityTier, QualityVideo
from waves.desktop.backend import WavesBridge
from waves.model.cfg import Settings
from waves.model.download_policy import apply_policy_edit, capture_intent, decode_policies
from waves.providers.apple.engines import EngineFacts, EnginePolicy, EngineRouter, EngineRouteUnavailable


def capture(data, **changes):
    return capture_intent(
        data, "apple", "album", "apple:album-1", tier="LOSSLESS", audio_type=None, toggles={}, **changes
    )


def test_provider_overrides_inherit_and_can_return_to_shared_rules():
    data = Settings()
    data.download_policies = apply_policy_edit(
        data.download_policies, "download_policies.shared.required_codec", "alac"
    )
    data.download_policies = apply_policy_edit(
        data.download_policies, "download_policies.providers.tidal.required_codec", "flac"
    )
    assert data.download_policies.effective("apple").required_codec == "alac"
    assert data.download_policies.effective("tidal").required_codec == "flac"
    data.download_policies = apply_policy_edit(
        data.download_policies, "download_policies.providers.tidal.required_codec", "__inherit__"
    )
    assert data.download_policies.effective("tidal").required_codec == "alac"


def test_round_trip_preserves_legacy_values_and_tier_serialization():
    data = Settings(
        tidal_quality_audio="LOW",
        apple_quality_audio="LOSSLESS",
        default_audio_type="both",
        quality_video=QualityVideo.P1080,
        download_delay=False,
        api_rate_limit_batch_size=57,
        api_rate_limit_delay_sec=81.5,
        apple_pacing_batch_size=31,
        apple_pacing_delay_sec=47.5,
        tidal_lyrics_embed=True,
        apple_lyrics_embed=False,
        apple_cover_file_format="png",
    )
    data.download_policies = apply_policy_edit(
        data.download_policies, "download_policies.providers.apple.matching", "release"
    )
    restored = Settings.from_json(data.to_json())
    assert restored == data
    assert json.loads(data.to_json())["tidal_quality_audio"] == "LOW"
    assert restored.download_policies.effective("apple").matching == "release"


def test_old_config_gains_policies_without_rewriting_existing_preferences():
    data = Settings.from_json(
        json.dumps({"tidal_quality_audio": "HIGH", "quality_video": "1080", "apple_pacing_delay_sec": 73.5})
    )
    assert data.tidal_quality_audio == "HIGH"
    assert data.quality_video == QualityVideo.P1080
    assert data.apple_pacing_delay_sec == 73.5
    intent = capture(data)
    assert intent.policy.metadata_source == intent.policy.organization_source == "origin"
    assert not any(
        (intent.choose_best_provider, intent.recover_provider, intent.upgrade_provider, intent.enrich_provider)
    )
    assert intent.same_provider_fallback


def test_corrupt_policy_values_recover_independently_and_bounds_are_enforced():
    policies = decode_policies(
        {
            "shared": {"required_codec": "invented", "matching": "release", "video_max_fps": 10000},
            "providers": {"apple": {"require_extras": True, "quality_strategy": None}},
            "provider_priority": " APPLE, tidal, apple ",
            "engine_priority": {"apple": "gamdl, next"},
            "attempt_limit": 999,
            "retry_delay_sec": -50,
            "request_timeout_sec": 999,
            "choose_best_provider": "true",
            "recover_provider": True,
        }
    )
    assert policies.effective("apple").required_codec == ""
    assert policies.effective("apple").matching == "release"
    assert policies.effective("apple").require_extras
    assert policies.shared.video_max_fps == 240
    assert policies.provider_priority == ("apple", "tidal")
    assert policies.engines("apple") == ("gamdl", "next")
    assert (policies.attempt_limit, policies.retry_delay_sec, policies.request_timeout_sec) == (5, 0, 120)
    assert not policies.choose_best_provider and policies.recover_provider


def test_cross_provider_permissions_are_independent_and_provider_pins_require_relaxation():
    data = Settings()
    data.download_policies.recover_provider = True
    pinned = capture(data, provider_pin="apple")
    relaxed = capture(data, provider_pin="apple", allow_fallback=True)
    assert not pinned.recover_provider and relaxed.recover_provider
    assert not relaxed.choose_best_provider and not relaxed.upgrade_provider and not relaxed.enrich_provider
    engine_pin = capture(data, engine_pin="gamdl")
    assert not engine_pin.same_provider_fallback
    assert capture(data, engine_pin="gamdl", allow_fallback=True).same_provider_fallback
    data.download_policies.same_provider_fallback = False
    assert not capture(data, engine_pin="gamdl", allow_fallback=True).same_provider_fallback


def test_settings_edits_do_not_change_captured_assets_metadata_paths_or_pacing():
    data = Settings(apple_lyrics_embed=True, apple_pacing_delay_sec=47.5, format_track="Original/{track_title}")
    data.download_policies.engine_priority["apple"] = ("first", "second")
    old = capture(data, clean_album_artist=True)
    data.apple_lyrics_embed = False
    data.apple_pacing_delay_sec = 0
    data.format_track = "New/{track_title}"
    data.download_policies.shared = replace(data.download_policies.shared, matching="release")
    data.download_policies.engine_priority["apple"] = ("second",)
    new = capture(data)
    saved = old.settings_data()
    assert saved.apple_lyrics_embed and saved.apple_pacing_delay_sec == 47.5
    assert saved.format_track == "Original/{track_title}"
    assert old.policy.matching == "recording" and new.policy.matching == "release"
    assert old.engine_priority == ("first", "second") and new.engine_priority == ("second",)
    assert old.clean_album_artist
    saved.apple_pacing_delay_sec = 999
    assert old.settings_data().apple_pacing_delay_sec == 47.5
    with pytest.raises(FrozenInstanceError):
        old.policy.matching = "release"


def test_chooser_assets_and_audio_pin_the_request_without_storing_a_default():
    data = Settings(default_audio_type="both", apple_lyrics_embed=False)
    old = capture_intent(
        data, "apple", "track", "apple:1", tier="HIGH", audio_type="atmos", toggles={"lyrics_embed": True}
    )
    assert old.settings_data().apple_quality_audio == QualityTier.HIGH.value
    assert old.settings_data().apple_lyrics_embed and old.policy.audio_type == "atmos"
    assert data.default_audio_type == "both" and not data.apple_lyrics_embed


def test_snapshot_does_not_retain_setup_credentials_or_network_origins():
    data = Settings(
        apple_cookies_path="/private/account.cookies", network_mount_origins={"/private/music": "smb://private"}
    )
    intent = capture(data)
    assert "account.cookies" not in intent.settings_json and "smb://" not in intent.settings_json
    assert intent.settings_data().apple_cookies_path == ""


def test_auto_uses_current_readiness_under_captured_preferences_and_constraints():
    data = Settings()
    data.download_policies.engine_priority["apple"] = ("first", "second")
    data.download_policies.shared = replace(data.download_policies.shared, required_codec="alac")
    intent = capture(data)
    first, second = FakeEngine("first", codecs=("alac",)), FakeEngine("second", codecs=("alac",))
    router = EngineRouter((first, second))
    request = audio(required_codec=intent.policy.required_codec, abort=Event())
    policy = EnginePolicy(intent.engine_priority, intent.engine_pin, intent.same_provider_fallback)
    assert router.select(request, policy, EngineFacts()) is first
    first.ready = False
    assert router.select(request, policy, EngineFacts()) is second
    second.descriptor = replace(
        second.descriptor, requirements=(replace(second.descriptor.requirements[0], codecs=("aac",)),)
    )
    with pytest.raises(EngineRouteUnavailable):
        router.select(request, policy, EngineFacts())


def test_explicit_engine_pin_is_only_relaxed_by_the_jobs_allow_fallback():
    first, second = FakeEngine("first", ready=False), FakeEngine("second")
    router = EngineRouter((first, second))
    with pytest.raises(EngineRouteUnavailable):
        router.select(audio(), EnginePolicy(("second",), "first"), EngineFacts())
    assert router.select(audio(), EnginePolicy(("second",), "first", True), EngineFacts()) is second


def test_schema_uses_one_staged_store_and_keeps_video_and_pacing_owners():
    bridge = schema_stub()
    before = bridge.settings.data.to_json()
    sections = WavesBridge.settingsSchema(bridge)
    assert bridge.settings.data.to_json() == before
    downloads = next(s for s in sections if s["id"] == "downloads")
    advanced = next(s for s in sections if s["id"] == "advanced")
    providers = next(s for s in sections if s["id"] == "providers")["providers"]
    assert {"quality_video", "video_download", "video_convert_mp4"} <= {f["key"] for f in downloads["fields"]}
    assert {"apple_pacing_delay_sec", "api_rate_limit_delay_sec", "download_delay"} <= {
        f["key"] for f in advanced["fields"]
    }
    assert any(f["key"] == "download_policies.providers.apple.matching" for p in providers for f in p["fields"])
    keys = [f["key"] for s in sections for f in s["fields"]] + [f["key"] for p in providers for f in p["fields"]]
    assert len(keys) == len(set(keys))


def test_real_enqueue_and_retry_keep_original_single_audio_row_and_full_intent(monkeypatch):
    from settings.test_quality_override import _bridge, _track

    from waves.desktop import backend

    monkeypatch.setattr(backend, "_image", lambda obj, size: "")
    monkeypatch.setattr(backend, "_quality_label", lambda obj, provider=None: "HI-RES")
    bridge = _bridge()
    bridge.settings.data = Settings(tidal_quality_audio="LOSSLESS", tidal_lyrics_embed=True)
    bridge._waves_pref_bool = lambda key: True
    obj = _track()
    assert bridge._download(obj, "track", "Song", "Original/{track_title}", False, "t1")
    original = bridge._queue[-1]
    original["status"] = "failed"
    intent = bridge._jobs.intents[original["qid"]]
    bridge.settings.data.default_audio_type = "both"
    bridge.settings.data.tidal_lyrics_embed = False
    bridge.settings.data.download_policies.shared = replace(
        bridge.settings.data.download_policies.shared, matching="release"
    )
    bridge._merge_plans = {}
    assert WavesBridge._start_retry(bridge, original, obj)
    retried = bridge._queue[-1]
    assert len(bridge._queue) == 2
    assert retried["audioType"] == original["audioType"] == ""
    assert bridge._jobs.intents[retried["qid"]] is intent
    assert bridge._jobs.specs[retried["qid"]].intent.settings_data().tidal_lyrics_embed
    assert retried["askLibrarySkip"]
    assert bridge._download(obj, "track", "Song", "New/{track_title}", False, "t1")
    assert bridge._jobs.intents[bridge._queue[-1]["qid"]].policy.matching == "release"


def test_dispatch_builds_engine_from_snapshot_and_keeps_credentials_live(monkeypatch):
    from types import SimpleNamespace

    from waves.desktop import backend

    data = Settings(download_base_path="original", tidal_lyrics_embed=True, api_rate_limit_delay_sec=42)
    intent = capture_intent(
        data, "tidal", "track", "t1", tier="LOSSLESS", audio_type=None, toggles={}, clean_album_artist=True
    )
    data.download_base_path = "new"
    data.tidal_lyrics_embed = False
    data.api_rate_limit_delay_sec = 0
    data.path_binary_ffmpeg = "current-tool"
    calls = {}

    def build(**kwargs):
        calls.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(backend, "_TrackedDownload", build)
    bridge = SimpleNamespace(
        settings=SimpleNamespace(data=data),
        _resolve_ffmpeg=lambda: None,
        _event_abort=Event(),
        _event_run=Event(),
        tidal=SimpleNamespace(),
        providers={"tidal": SimpleNamespace()},
        _ownership=SimpleNamespace(ownership_of=None, stamp_ceiling=None),
        _target_quality_rank=lambda tier: 2,
        _warn_if_ffmpeg_missing=lambda dl: None,
    )
    signals = SimpleNamespace(item=None, item_name=None, list_item=None, list_name=None)
    WavesBridge._build_download(bridge, signals, pinned_quality=QualityTier.LOSSLESS, request_intent=intent)
    assert calls["path_base"] == "original"
    assert calls["settings_data"].tidal_lyrics_embed and calls["settings_data"].api_rate_limit_delay_sec == 42
    assert calls["settings_data"].path_binary_ffmpeg == "current-tool"
    assert calls["album_artist_tag_clean"]()


def test_changed_destination_probes_original_folder_and_never_updates_new_default():
    from types import SimpleNamespace

    from waves.desktop.backend import DownloadIncomplete

    data = Settings(download_base_path="original")
    intent = capture(data)
    data.download_base_path = "new"
    paths = []

    def probe(**kwargs):
        paths.append(kwargs["path_override"])
        return "ok", "original"

    proven = []
    bridge = SimpleNamespace(
        settings=SimpleNamespace(data=data), _probe_download_base=probe, _note_download_base_ok=proven.append
    )
    assert WavesBridge._request_reachability(bridge, intent, lambda: None)
    assert paths == proven == ["original"] and data.download_base_path == "new"
    bridge._probe_download_base = lambda **kwargs: ("dead", "original")
    with pytest.raises(DownloadIncomplete, match="original download folder"):
        WavesBridge._request_reachability(bridge, intent, lambda: None)


def test_atmos_retry_keeps_placement_after_the_folder_format_changes(monkeypatch):
    from settings.test_quality_override import _bridge, _track

    from waves.desktop import backend

    monkeypatch.setattr(backend, "_image", lambda obj, size: "")
    monkeypatch.setattr(backend, "_quality_label", lambda obj, provider=None: "HI-RES")
    monkeypatch.setattr(backend, "_has_atmos", lambda obj: True)
    monkeypatch.setattr(backend, "_atmos_only", lambda obj: False)
    bridge = _bridge()
    bridge.settings.data = Settings(default_audio_type="stereo", format_atmos="Original Atmos")
    bridge._chooser_normalize_audio = lambda audio, provider: audio
    obj = _track()
    base = "{artist_name}/{track_title}"
    assert bridge._download(obj, "track", "Song", base, False, "t1", chooser_audio="atmos")
    original = bridge._queue[-1]
    original["status"] = "failed"
    bridge.settings.data.format_atmos = "Changed Atmos"
    bridge._merge_plans = {}
    assert WavesBridge._start_retry(bridge, original, obj)
    retried = bridge._queue[-1]
    assert retried["template"] == original["template"] == "{artist_name}/Original Atmos/{track_title}"
    assert bridge._jobs.specs[retried["qid"]].base_template == base


def test_apple_enqueue_dispatch_and_retry_preserve_rules_but_use_current_setup(tmp_path):
    from downloads.test_apple_job_runner import _album_row, _entry_stub

    from waves.providers.apple.provider import AppleProvider

    provider = AppleProvider()
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape\n")
    bridge = _entry_stub(tmp_path / "lib", provider, cookies)
    bridge.settings.data = Settings(
        apple_enabled=True,
        apple_cookies_path=str(cookies),
        apple_quality_audio="HIGH",
        apple_lyrics_embed=True,
        apple_pacing_delay_sec=47,
    )
    bridge.settings.data.download_policies.engine_priority["apple"] = ("gamdl", "future")
    bridge.settings.data.download_policies.operation_priority["apple"] = {"artwork": ("future", "gamdl")}
    bridge._download_apple = lambda *args, **kwargs: WavesBridge._download_apple(bridge, *args, **kwargs)
    args = ("album", _album_row(), _album_row(), "{artist_name}/{track_title}", True, "apple:album-1")
    assert bridge._download_apple(*args, chooser_toggles={"engine": "gamdl", "allow_fallback": True})
    original = bridge._queue[-1]
    intent = bridge._jobs.intents[original["qid"]]
    bridge.settings.data.apple_lyrics_embed = False
    bridge.settings.data.apple_pacing_delay_sec = 0
    bridge.settings.data.default_audio_type = "both"
    bridge.settings.data.apple_cookies_path = "current.cookies"
    bridge.settings.data.download_policies.engine_priority["apple"] = ("future",)
    hooks = bridge._apple_job_hooks(intent)
    assert hooks.apple_setting("lyrics_embed")
    assert hooks.settings().data.apple_pacing_delay_sec == 47
    assert hooks.settings().data.apple_cookies_path == "current.cookies"
    original["status"] = "failed"
    assert provider.downloads.serve_retry(original, _album_row())
    retried = bridge._queue[-1]
    assert len(bridge._queue) == 2 and retried["audioType"] == ""
    assert bridge._jobs.intents[retried["qid"]] is intent
    assert bridge._jobs.specs[retried["qid"]].engine_policy == EnginePolicy(("gamdl", "future"), "gamdl", True)
    assert intent.operation_priority == (("artwork", ("future", "gamdl")),)


def test_apple_retry_held_for_ffmpeg_setup_keeps_the_original_request(tmp_path):
    from downloads.test_apple_job_runner import _album_row, _entry_stub

    from waves.providers.apple.provider import AppleProvider

    provider = AppleProvider()
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape\n")
    bridge = _entry_stub(tmp_path / "lib", provider, cookies)
    bridge.settings.data = Settings(apple_enabled=True, apple_cookies_path=str(cookies))
    bridge._download_apple = lambda *args, **kwargs: WavesBridge._download_apple(bridge, *args, **kwargs)
    args = ("album", _album_row(), _album_row(), "{artist_name}/{track_title}", True, "apple:album-1")
    assert bridge._download_apple(*args)
    original = bridge._queue[-1]
    intent = bridge._jobs.intents[original["qid"]]
    original["status"] = "failed"
    held = []
    bridge._ffmpeg_gate_holds = lambda mid, replay: held.append(replay) or True
    assert not provider.downloads.serve_retry(original, _album_row())
    bridge.settings.data.download_policies.shared = replace(
        bridge.settings.data.download_policies.shared, matching="release"
    )
    bridge._ffmpeg_gate_holds = lambda *args: False
    assert held.pop()()
    assert bridge._jobs.intents[bridge._queue[-1]["qid"]] is intent
