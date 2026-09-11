"""Chooser split button + popover (issue #35, spec section 7.2).

WHAT THIS FENCES OFF
--------------------
Every download control is a split button: the main face queues with the saved
Settings defaults, the chevron face (or right-click) opens the anchored
Chooser popover. The popover carries the provider segment (fixed on
collections), the provider's tiers with detail text, audio type
stereo/Atmos/both (collapsing to ATMOS ONLY on atmos-only tracks), lyrics/art
quick toggles, SET AS DEFAULTS (writes back to Settings) + DOWNLOAD. The
choice applies to that click only. With Apple disabled rows keep today's
single-face behavior.

HOW THIS STAYS FIXED
--------------------
Method-bound stubs, no display and no session: chooserTiers names the tiers
with spec detail text (Apple has no LOW); chooserDefaults answers provider /
providerFixed / tier / audioType / atmosOnly / toggles from Settings;
saveChooserDefaults stages tier + audio + toggles through applySettings and
refuses Apple LOW; downloadWithChooser pins tier + audio for that click only
without touching _quality_overrides, both queues two rows, atmos/stereo queue
one, and the defaults face (empty tier/audio) follows Settings.
"""

from __future__ import annotations

from threading import Lock
from types import SimpleNamespace

from waves.constants import CTX_APPLE, CTX_TIDAL
from waves.waves_ui import backend


class _Emit:
    def __init__(self) -> None:
        self.calls: list = []

    def emit(self, *args) -> None:
        self.calls.append(args)


def _bind(stub, *names) -> None:
    for name in names:
        setattr(stub, name, getattr(backend.WavesBridge, name).__get__(stub))


def _settings(**over):
    base = {
        "tidal_quality_audio": "HIGH",
        "apple_quality_audio": "LOSSLESS",
        "default_audio_type": "stereo",
        "apple_enabled": False,
        "lyrics_embed": False,
        "lyrics_file": False,
        "lyrics_ttml_file": False,
        "metadata_cover_embed": True,
        "cover_album_file": True,
        "format_track": "{tmpl}",
        "format_album": "{tmpl}",
        "format_playlist": "{tmpl}",
        "format_mix": "{tmpl}",
        "format_video": "{tmpl}",
        "format_atmos": "Dolby Atmos",
    }
    base.update(over)
    return SimpleNamespace(**base)


def _bridge(**over):
    b = SimpleNamespace()
    b._quality_overrides = {}
    b._objs = {"track": {}, "album": {}, "playlist": {}, "mix": {}, "video": {}}
    b._merge_plans = {}
    b.settings = SimpleNamespace(data=_settings(**over))
    b.qualityOverridesChanged = _Emit()
    b.qualityChoiceChanged = _Emit()
    b.ownershipChanged = _Emit()
    b.downloadState = _Emit()
    b.appleStatusChanged = _Emit()
    b.targetTierChanged = _Emit()
    b._queue_seq = 0
    b._queue = []
    b._queue_index = {}
    b._qdirty_added = []
    b._queue_lock = Lock()
    b._emit_queue = lambda: None
    b._logged_in = True
    b._download_gate = lambda: "ok"
    b._ffmpeg_gate_holds = lambda *a, **k: False
    b._library_bulk_skip_on = lambda: False
    b._stash_pending_download = lambda mid, fn: None
    b._job_tracks = {}
    b._job_objs = {}
    b._job_specs = {}
    b._pending_qids = []
    b._pump_queue = lambda: None
    b._queue_item = lambda qid: b._queue_index.get(qid)
    b._set_status = lambda msg: setattr(b, "_last_status", msg)
    b._last_status = ""
    b._playlist_template = lambda pid: "{tmpl}"
    b.providers = {CTX_TIDAL: SimpleNamespace(), CTX_APPLE: SimpleNamespace()}
    b._refetch_for_download = lambda bucket, mid: setattr(b, "_refetched", (bucket, mid))
    b._refetched = None
    b._chooser_refetch_pins = {}
    b._refetch_inflight = set()
    _bind(
        b,
        "_get_apple_enabled",
        "isAppleEnabled",
        "_chooser_provider_of",
        "_chooser_is_collection_kind",
        "_chooser_tier_entries",
        "chooserTiers",
        "chooserDefaultTier",
        "_chooser_default_tier_word",
        "_chooser_default_audio",
        "_chooser_atmos_only",
        "chooserDefaults",
        "saveChooserDefaults",
        "_chooser_normalize_audio",
        "_chooser_park_refetch",
        "_chooser_take_refetch",
        "_chooser_drop_refetch",
        "_chooser_ask_for",
        "_chooser_toggle_pins",
        "downloadWithChooser",
        "_chooser_confirm_status",
        "_download_apple_with_chooser",
        "_ask_quality_for",
        "_quality_override_key",
        "_queued_quality_value",
        "_target_tier",
        "_enqueue",
        "_download",
    )
    return b


def _track(tid="t1", album_id="a1"):
    return SimpleNamespace(
        id=tid,
        name="Song",
        version=None,
        album=SimpleNamespace(id=album_id, name="Album"),
        artist=SimpleNamespace(name="Artist"),
        artists=[SimpleNamespace(name="Artist")],
        audio_modes=["STEREO"],
    )


def _atmos_only_track(tid="tA"):
    t = _track(tid)
    t.audio_modes = ["DOLBY_ATMOS"]
    return t


def test_chooser_tiers_name_the_spec_detail_and_apple_has_no_low():
    b = _bridge()
    tidal = b.chooserTiers("tidal")
    assert [(e["word"], e["detail"]) for e in tidal] == [
        ("HI-RES", "FLAC 24-bit up to 192 kHz"),
        ("LOSSLESS", "FLAC 16-bit/44.1 kHz"),
        ("HIGH", "AAC 320"),
        ("LOW", "AAC 96"),
    ]
    apple = b.chooserTiers("apple")
    assert [(e["word"], e["detail"]) for e in apple] == [
        ("HI-RES", "ALAC 24/192"),
        ("LOSSLESS", "ALAC 16/44.1"),
        ("HIGH", "AAC 256"),
    ]
    assert "LOW" not in [e["word"] for e in apple]


def test_chooser_defaults_come_from_settings_per_provider():
    b = _bridge(tidal_quality_audio="HI_RES_LOSSLESS", apple_quality_audio="HIGH")
    assert b.chooserDefaultTier("tidal") == "HI-RES"
    assert b.chooserDefaultTier("apple") == "HIGH"
    d = b.chooserDefaults("t1", "track")
    assert d["provider"] == "tidal" and d["providerFixed"] is False
    assert d["tier"] == "HI-RES" and d["audioType"] == "stereo"
    assert d["atmosOnly"] is False and d["appleEnabled"] is False
    d_album = b.chooserDefaults("a1", "album")
    assert d_album["providerFixed"] is True
    d_apple = b.chooserDefaults("apple:456", "track")
    assert d_apple["provider"] == "apple" and d_apple["tier"] == "HIGH"
    assert [e["word"] for e in d_apple["tiers"]] == ["HI-RES", "LOSSLESS", "HIGH"]


def test_chooser_defaults_audio_follows_the_default_and_atmos_only_collapses(monkeypatch):
    b = _bridge(default_audio_type="both")
    assert b.chooserDefaults("t1", "track")["audioType"] == "both"
    b.settings.data.default_audio_type = "stereo"
    assert b.chooserDefaults("t1", "track")["audioType"] == "stereo"
    b._objs["track"]["tA"] = _atmos_only_track("tA")
    monkeypatch.setattr(backend, "_atmos_only", lambda obj: getattr(obj, "audio_modes", []) == ["DOLBY_ATMOS"])
    d = b.chooserDefaults("tA", "track")
    assert d["atmosOnly"] is True


def test_is_apple_enabled_gates_the_split_face():
    assert _bridge(apple_enabled=False).isAppleEnabled() is False
    assert _bridge(apple_enabled=True).isAppleEnabled() is True


def test_save_chooser_defaults_stages_through_apply_settings():
    b = _bridge()
    staged = {}
    b.applySettings = lambda vals: staged.update(vals)
    b.saveChooserDefaults({"provider": "tidal", "tier": "HI-RES", "audioType": "both"})
    assert staged["tidal_quality_audio"] == "HI_RES_LOSSLESS"
    assert staged["default_audio_type"] == "both"
    staged.clear()
    b.saveChooserDefaults({"provider": "apple", "tier": "LOSSLESS", "audioType": "stereo"})
    assert staged["apple_quality_audio"] == "LOSSLESS"
    assert staged["default_audio_type"] == "stereo"
    # Apple has no LOW rung: refused, nothing staged for quality.
    staged.clear()
    b.saveChooserDefaults({"provider": "apple", "tier": "LOW", "audioType": ""})
    assert "apple_quality_audio" not in staged
    # Quick toggles ride along under both spellings, staged onto the row's
    # own provider mirrors (issue #61).
    staged.clear()
    b.saveChooserDefaults({"provider": "tidal", "tier": "", "audioType": "", "lyricsEmbed": True, "coverFile": False})
    assert staged["tidal_lyrics_embed"] is True and staged["tidal_cover_album_file"] is False
    staged.clear()
    b.saveChooserDefaults({"provider": "apple", "tier": "", "audioType": "", "lyricsEmbed": True, "coverFile": False})
    assert staged["apple_lyrics_embed"] is True and staged["apple_cover_album_file"] is False
    # An explicit mirror wins over the shared spelling.
    staged.clear()
    b.saveChooserDefaults(
        {"provider": "tidal", "tier": "", "audioType": "", "lyricsEmbed": True, "tidal_lyrics_embed": False}
    )
    assert staged["tidal_lyrics_embed"] is False


def test_download_with_chooser_pins_that_click_only(monkeypatch):
    monkeypatch.setattr(backend, "_image", lambda obj, size: "")
    monkeypatch.setattr(backend, "_quality_label", lambda obj, provider=None: "HI-RES")
    monkeypatch.setattr(backend, "_primary_artist_name", lambda obj: "Artist")
    monkeypatch.setattr(backend, "_track_count", lambda obj: 1)
    monkeypatch.setattr(backend, "_offers_both", lambda obj: True)
    monkeypatch.setattr(backend, "_atmos_only", lambda obj: False)
    monkeypatch.setattr(backend, "_has_atmos", lambda obj: True)
    monkeypatch.setattr(backend, "name_builder_title", lambda obj: "Song")
    b = _bridge(tidal_quality_audio="HIGH")
    b._objs["track"]["t1"] = _track("t1")
    b.downloadWithChooser("t1", "track", "LOSSLESS", "stereo")
    row = b._queue[-1]
    assert (row["askQuality"], row["quality"]) == ("LOSSLESS", "LOSSLESS")
    assert row["audioType"] == "stereo"
    assert b._quality_overrides == {}, "the Chooser choice was stored"
    assert "LOSSLESS" in str(getattr(b, "_last_status", ""))


def test_download_with_chooser_both_queues_two_rows_and_empty_follows_settings(monkeypatch):
    monkeypatch.setattr(backend, "_image", lambda obj, size: "")
    monkeypatch.setattr(backend, "_quality_label", lambda obj, provider=None: "HI-RES")
    monkeypatch.setattr(backend, "_primary_artist_name", lambda obj: "Artist")
    monkeypatch.setattr(backend, "_track_count", lambda obj: 1)
    monkeypatch.setattr(backend, "_offers_both", lambda obj: True)
    monkeypatch.setattr(backend, "_atmos_only", lambda obj: False)
    monkeypatch.setattr(backend, "_has_atmos", lambda obj: True)
    monkeypatch.setattr(backend, "name_builder_title", lambda obj: "Song")
    b = _bridge(tidal_quality_audio="HIGH")
    b._objs["track"]["t1"] = _track("t1")
    b.downloadWithChooser("t1", "track", "HIGH", "both")
    assert len(b._queue) == 2
    assert sorted([r["audioType"] for r in b._queue]) == ["atmos", "stereo"]
    b2 = _bridge(tidal_quality_audio="LOSSLESS")
    b2._objs["track"]["t1"] = _track("t1")
    # Empty tier/audio is the defaults face: exactly what Settings says.
    b2.downloadWithChooser("t1", "track", "", "")
    assert (b2._queue[-1]["askQuality"], b2._queue[-1]["quality"]) == ("LOSSLESS", "LOSSLESS")


def test_download_with_chooser_atmos_only_track_collapses(monkeypatch):
    monkeypatch.setattr(backend, "_image", lambda obj, size: "")
    monkeypatch.setattr(backend, "_quality_label", lambda obj, provider=None: "ATMOS")
    monkeypatch.setattr(backend, "_primary_artist_name", lambda obj: "Artist")
    monkeypatch.setattr(backend, "_track_count", lambda obj: 1)
    monkeypatch.setattr(backend, "_offers_both", lambda obj: False)
    monkeypatch.setattr(backend, "_atmos_only", lambda obj: True)
    monkeypatch.setattr(backend, "_has_atmos", lambda obj: True)
    monkeypatch.setattr(backend, "name_builder_title", lambda obj: "Song")
    b = _bridge()
    b._objs["track"]["tA"] = _atmos_only_track("tA")
    b.downloadWithChooser("tA", "track", "HI-RES", "stereo")
    assert len(b._queue) == 1


def test_download_with_chooser_apple_routes_with_pins(monkeypatch):
    seen = {}

    def fake_apple(type_media, row, crow, tmpl, coll, mid, chooser_ask=None, chooser_audio=None, **kw):
        seen["ask"] = chooser_ask
        seen["audio"] = chooser_audio
        seen["mid"] = mid

    b = _bridge(apple_enabled=True, apple_quality_audio="LOSSLESS")
    provider = SimpleNamespace(
        cached=lambda kind, mid: {"id": mid},
        row_for=lambda kind, raw: {"title": "Apple Song", "artist": "Artist", "art": ""},
    )
    b.providers[CTX_APPLE] = provider
    b._download_apple = fake_apple
    _bind(b, "_chooser_confirm_status")
    b.downloadWithChooser("apple:456", "track", "HI-RES", "both")
    assert seen["mid"] == "apple:456"
    assert seen["ask"] == ("HI_RES_LOSSLESS", "HI-RES")
    assert seen["audio"] == "both"


def test_download_with_chooser_parks_pins_across_a_refetch(monkeypatch):
    """A Chooser click on an evicted id replays with its pins, not Settings."""
    monkeypatch.setattr(backend, "_image", lambda obj, size: "")
    monkeypatch.setattr(backend, "_quality_label", lambda obj, provider=None: "HI-RES")
    monkeypatch.setattr(backend, "_primary_artist_name", lambda obj: "Artist")
    monkeypatch.setattr(backend, "_track_count", lambda obj: 1)
    monkeypatch.setattr(backend, "_offers_both", lambda obj: False)
    monkeypatch.setattr(backend, "_atmos_only", lambda obj: False)
    monkeypatch.setattr(backend, "_has_atmos", lambda obj: False)
    monkeypatch.setattr(backend, "name_builder_title", lambda obj: "Song")
    b = _bridge(tidal_quality_audio="HIGH")
    _bind(b, "_on_media_refetched")
    # Cold cache: the click parks instead of queueing.
    b.downloadWithChooser("t1", "track", "LOSSLESS", "stereo", {"lyrics_embed": True, "cover_album_file": False})
    assert b._queue == []
    assert b._chooser_refetch_pins[("track", "t1")] == (
        "track",
        "LOSSLESS",
        "stereo",
        {"lyrics_embed": True, "cover_album_file": False},
    )
    # The fetch lands: replay queues at the parked pins, not Settings.
    b._objs["track"]["t1"] = _track("t1")
    b._refetch_inflight.discard(("track", "t1"))
    b._on_media_refetched("track", "t1")
    assert (b._queue[-1]["askQuality"], b._queue[-1]["quality"]) == ("LOSSLESS", "LOSSLESS")
    assert b._queue[-1]["askToggles"] == {"lyrics_embed": True, "cover_album_file": False}
    assert b._job_specs[b._queue[-1]["qid"]].chooser_toggles == {"lyrics_embed": True, "cover_album_file": False}
    assert ("track", "t1") not in b._chooser_refetch_pins


def test_download_with_chooser_apple_parks_pins_across_a_refetch():
    b = _bridge(apple_enabled=True)
    provider = SimpleNamespace(cached=lambda kind, mid: None)
    b.providers[CTX_APPLE] = provider
    refetched = []
    b._refetch_apple_for_download = lambda bucket, mid: refetched.append((bucket, mid))
    _bind(b, "_download_apple_with_chooser")
    b.downloadWithChooser("apple:456", "track", "HI-RES", "both", {"lyrics_embed": True})
    assert refetched == [("track", "apple:456")]
    assert b._chooser_refetch_pins[("track", "apple:456")] == ("track", "HI-RES", "both", {"lyrics_embed": True})


def test_download_with_chooser_keeps_the_gate_message_when_nothing_queued(monkeypatch):
    """A held or blocked click keeps the gate's own status, never Queued."""
    monkeypatch.setattr(backend, "_image", lambda obj, size: "")
    monkeypatch.setattr(backend, "_quality_label", lambda obj, provider=None: "HI-RES")
    monkeypatch.setattr(backend, "_primary_artist_name", lambda obj: "Artist")
    monkeypatch.setattr(backend, "_track_count", lambda obj: 1)
    monkeypatch.setattr(backend, "_offers_both", lambda obj: False)
    monkeypatch.setattr(backend, "_atmos_only", lambda obj: False)
    monkeypatch.setattr(backend, "_has_atmos", lambda obj: False)
    monkeypatch.setattr(backend, "name_builder_title", lambda obj: "Song")
    b = _bridge()
    b._objs["track"]["t1"] = _track("t1")
    b._download_gate = lambda: "block"
    b._set_status("gate says pick a folder")
    b.downloadWithChooser("t1", "track", "LOSSLESS", "stereo")
    assert b._queue == []
    assert getattr(b, "_last_status", "") != ""
    assert "Queued" not in str(getattr(b, "_last_status", ""))
    assert b.downloadState.calls[-1] == ("t1", "")


def test_download_with_chooser_carries_toggles_into_the_job(monkeypatch):
    monkeypatch.setattr(backend, "_image", lambda obj, size: "")
    monkeypatch.setattr(backend, "_quality_label", lambda obj, provider=None: "HI-RES")
    monkeypatch.setattr(backend, "_primary_artist_name", lambda obj: "Artist")
    monkeypatch.setattr(backend, "_track_count", lambda obj: 1)
    monkeypatch.setattr(backend, "_offers_both", lambda obj: False)
    monkeypatch.setattr(backend, "_atmos_only", lambda obj: False)
    monkeypatch.setattr(backend, "_has_atmos", lambda obj: False)
    monkeypatch.setattr(backend, "name_builder_title", lambda obj: "Song")
    b = _bridge(tidal_quality_audio="HIGH")
    b._objs["track"]["t1"] = _track("t1")
    b.downloadWithChooser(
        "t1", "track", "HIGH", "stereo", {"lyrics_embed": True, "lyrics_file": False, "cover_album_file": False}
    )
    row = b._queue[-1]
    assert row["askToggles"] == {"lyrics_embed": True, "lyrics_file": False, "cover_album_file": False}
    assert b._job_specs[row["qid"]].chooser_toggles == row["askToggles"]
    assert b._chooser_toggle_pins({"lyrics_embed": True, "bogus": True}) == {"lyrics_embed": True}
    assert b._chooser_toggle_pins("nonsense") == {}


def test_chooser_toggle_pins_win_over_provider_settings_for_the_job():
    from waves.download import Download

    dl = Download.__new__(Download)
    dl.settings = SimpleNamespace(data=_settings(lyrics_embed=False, cover_album_file=True))
    dl.provider = SimpleNamespace(id=CTX_TIDAL)
    dl._chooser_toggles = {"lyrics_embed": True, "cover_album_file": False}

    assert dl._psetting("lyrics_embed", False) is True
    assert dl._psetting("cover_album_file", True) is False
    assert dl._psetting("lyrics_file", False) is False, "an unpinned option still reads Settings"

    dl._chooser_toggles = {}
    assert dl._psetting("lyrics_embed", False) is False


def test_a_second_click_differing_only_in_toggles_is_not_a_duplicate(monkeypatch):
    monkeypatch.setattr(backend, "_image", lambda obj, size: "")
    monkeypatch.setattr(backend, "_quality_label", lambda obj, provider=None: "HI-RES")
    monkeypatch.setattr(backend, "_primary_artist_name", lambda obj: "Artist")
    monkeypatch.setattr(backend, "_track_count", lambda obj: 1)
    monkeypatch.setattr(backend, "_offers_both", lambda obj: False)
    monkeypatch.setattr(backend, "_atmos_only", lambda obj: False)
    monkeypatch.setattr(backend, "_has_atmos", lambda obj: False)
    monkeypatch.setattr(backend, "name_builder_title", lambda obj: "Song")
    b = _bridge(tidal_quality_audio="HIGH")
    b._objs["track"]["t1"] = _track("t1")

    b.downloadWithChooser("t1", "track", "HIGH", "stereo", {"lyrics_embed": True})
    b.downloadWithChooser("t1", "track", "HIGH", "stereo", {"lyrics_embed": False})
    assert len(b._queue) == 2, "a different per-click ask keeps its own row"

    b.downloadWithChooser("t1", "track", "HIGH", "stereo", {"lyrics_embed": True})
    assert len(b._queue) == 2, "the identical ask is still a duplicate"


def test_retry_reenters_with_the_rows_toggle_pins():
    b = _bridge()
    _bind(b, "_start_retry")
    seen = {}
    b._download = lambda *a, **k: seen.update(k)
    item = {
        "type": "track",
        "name": "Song",
        "template": "{tmpl}",
        "collection": False,
        "media_id": "t1",
        "askQuality": "HIGH",
        "quality": "HIGH",
        "audioType": "",
        "askToggles": {"lyrics_embed": True},
    }

    b._start_retry(item, _track("t1"))

    assert seen.get("chooser_toggles") == {"lyrics_embed": True}
