"""The Chooser captures an opt-in upgrade only when it is demonstrated.

With upgrade_provider off the duplicate policy decides. With it on, a matched
cross-provider offer captures a plan only for a Waves-owned unchanged origin
whose recorded facts the probed delivery strictly beats; otherwise the manual
choice still proceeds, with a visible note and no plan.
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from support.bridge_stub import BridgeStub

from waves.constants import QualityTier
from waves.desktop.backend import WavesBridge
from waves.desktop.providers.catalog_identity import CatalogSelection
from waves.desktop.providers.catalog_offers import OfferSnapshot
from waves.metadata.catalog_identity import CatalogIdentity, CatalogResolution, MatchState
from waves.metadata.digest import audio_digest
from waves.model.cfg import Settings
from waves.providers.catalog_offers import (
    AvailabilityEvidence,
    CatalogOffer,
    DeliveryFacts,
    EvidenceState,
    OfferConstraints,
)


def _origin() -> CatalogIdentity:
    return CatalogIdentity(
        media_id="tidal:1",
        kind="track",
        title="Song",
        artist="Artist",
        identifier="USSM1000001",
        duration_ms=200000,
        explicit=False,
        version=None,
        release_title="Album",
        release_artist="Artist",
        release_date="2020-01-01",
        track_number=1,
        disc_number=1,
        track_count=1,
    )


def _offer(facts=(), state=MatchState.HIGH_CONFIDENCE, pid="apple") -> CatalogOffer:
    return CatalogOffer(
        pid,
        f"{pid}:2",
        "track",
        CatalogResolution("tidal:1", state),
        OfferConstraints(tier=QualityTier.LOSSLESS, audio_type="stereo"),
        evidence=AvailabilityEvidence(state=EvidenceState.AVAILABLE, probed=tuple(facts)),
        readiness="ready",
    )


def _host(offer, *, origin=None, record=None, upgrade=True, path=None):
    snapshot = OfferSnapshot(CatalogSelection("track", "tidal:1"), (offer,), (lambda: True,), origin)
    data = Settings()
    data.download_policies.upgrade_provider = upgrade
    b = BridgeStub(
        _catalog_offer_generation=7,
        _catalog_offer_snapshot=(7, snapshot),
        calls=[],
        statuses=[],
        settings=SimpleNamespace(data=data),
        _ownership=SimpleNamespace(ownership_of=lambda *_a, **_k: record),
    )
    b._set_status = b.statuses.append
    b._chooser_ask_for = lambda pid, tier: (tier, tier) if tier in ("HIGH", "LOSSLESS", "") else None
    b._chooser_normalize_audio = lambda audio, pid: audio if audio in ("stereo", "both", "") else None
    b.downloadWithChooser = lambda *args: b.calls.append(args)
    b._current_chooser_offer = WavesBridge._current_chooser_offer.__get__(b)
    b._upgrade_plan_for = WavesBridge._upgrade_plan_for.__get__(b)
    b._on_catalog_upgrade_ready = WavesBridge._on_catalog_upgrade_ready.__get__(b)

    class _SyncPool:
        def start(self, worker):
            worker.run()

    b.threadpool = _SyncPool()
    b._catalogUpgradeReady = SimpleNamespace(emit=lambda payload: b._on_catalog_upgrade_ready(payload))
    return b


def test_the_plan_is_captured_only_for_an_owned_unchanged_origin(tmp_path):
    origin_file = tmp_path / "Song.ogg"
    origin_file.write_bytes(b"old audio")
    record = {
        "path": str(origin_file),
        "quality_tier": "LOSSLESS",
        "quality_rank": 2,
        "audio_type": "stereo",
        "codecs": "flac",
        "bit_depth": 16,
        "sample_rate": 44100,
        "audio_digest": audio_digest(origin_file),
    }
    b = _host(
        _offer(
            (
                DeliveryFacts(
                    tier=QualityTier.HI_RES_LOSSLESS,
                    audio_type="stereo",
                    codec="alac",
                    bit_depth=24,
                    sample_rate=96000,
                ),
            )
        ),
        origin=_origin(),
        record=record,
    )

    assert WavesBridge.downloadCatalogOffer(b, 7, "apple", "LOSSLESS", "stereo", {})

    pins = b.calls[0][4]
    assert pins["upgrade"]["origin_id"] == "tidal:1"
    assert pins["upgrade"]["origin_path"] == str(origin_file)
    assert pins["upgrade"]["origin_digest"] == record["audio_digest"]
    assert pins["origin_facts"]["album_title"] == "Album"


def test_a_manual_choice_still_proceeds_when_no_improvement_is_demonstrated(tmp_path):
    origin_file = tmp_path / "Song.ogg"
    origin_file.write_bytes(b"old audio")
    record = {
        "path": str(origin_file),
        "quality_tier": "HI_RES_LOSSLESS",
        "quality_rank": 3,
        "audio_type": "stereo",
        "codecs": "flac",
        "bit_depth": 24,
        "sample_rate": 96000,
        "audio_digest": audio_digest(origin_file),
    }
    b = _host(
        _offer(
            (
                DeliveryFacts(
                    tier=QualityTier.LOSSLESS,
                    audio_type="stereo",
                    codec="alac",
                    bit_depth=16,
                    sample_rate=44100,
                ),
            )
        ),
        origin=_origin(),
        record=record,
    )

    assert WavesBridge.downloadCatalogOffer(b, 7, "apple", "LOSSLESS", "stereo", {})

    assert "upgrade" not in b.calls[0][4]
    assert "No upgrade applied" in b.statuses[-1]


def test_an_unproven_digest_never_authorizes_an_upgrade(tmp_path):
    origin_file = tmp_path / "Song.ogg"
    origin_file.write_bytes(b"old audio")
    record = {
        "path": str(origin_file),
        "quality_tier": "LOSSLESS",
        "quality_rank": 2,
        "audio_type": "stereo",
        "codecs": "flac",
        "bit_depth": 16,
        "sample_rate": 44100,
        "audio_digest": "stale-digest",
    }
    b = _host(
        _offer(
            (
                DeliveryFacts(
                    tier=QualityTier.HI_RES_LOSSLESS,
                    audio_type="stereo",
                    codec="alac",
                    bit_depth=24,
                    sample_rate=96000,
                ),
            )
        ),
        origin=_origin(),
        record=record,
    )

    assert WavesBridge.downloadCatalogOffer(b, 7, "apple", "LOSSLESS", "stereo", {})

    assert "upgrade" not in b.calls[0][4]


def test_the_gui_slot_does_not_hash_or_stat(tmp_path, monkeypatch):
    from waves.desktop import backend

    origin_file = tmp_path / "Song.ogg"
    origin_file.write_bytes(b"old audio")
    record = {
        "path": str(origin_file),
        "quality_tier": "LOSSLESS",
        "quality_rank": 2,
        "audio_type": "stereo",
        "codecs": "flac",
        "bit_depth": 16,
        "sample_rate": 44100,
        "audio_digest": audio_digest(origin_file),
    }
    b = _host(
        _offer(
            (
                DeliveryFacts(
                    tier=QualityTier.HI_RES_LOSSLESS,
                    audio_type="stereo",
                    codec="alac",
                    bit_depth=24,
                    sample_rate=96000,
                ),
            )
        ),
        origin=_origin(),
        record=record,
    )

    class _RecordingPool:
        def __init__(self):
            self.workers = []

        def start(self, worker):
            self.workers.append(worker)

    b.threadpool = _RecordingPool()
    called: list = []
    b._ownership.ownership_of = lambda *_a, **_k: called.append("stat") or record
    monkeypatch.setattr(backend, "digest_matches", lambda *_a, **_k: called.append("hash") or True)

    assert WavesBridge.downloadCatalogOffer(b, 7, "apple", "LOSSLESS", "stereo", {})

    assert called == [], "the GUI slot must not stat the store or hash the audio"
    b.threadpool.workers[0].run()
    assert "stat" in called and "hash" in called


def test_both_audio_type_captures_no_upgrade_plan(tmp_path):
    origin_file = tmp_path / "Song.ogg"
    origin_file.write_bytes(b"old audio")
    record = {
        "path": str(origin_file),
        "quality_tier": "LOSSLESS",
        "quality_rank": 2,
        "audio_type": "stereo",
        "codecs": "flac",
        "bit_depth": 16,
        "sample_rate": 44100,
        "audio_digest": audio_digest(origin_file),
    }
    item = replace(
        _offer(
            (
                DeliveryFacts(
                    tier=QualityTier.HI_RES_LOSSLESS,
                    audio_type="stereo",
                    codec="alac",
                    bit_depth=24,
                    sample_rate=96000,
                ),
            )
        ),
        selected=OfferConstraints(tier=QualityTier.LOSSLESS, audio_type="both"),
    )
    b = _host(item, origin=_origin(), record=record)

    assert WavesBridge.downloadCatalogOffer(b, 7, "apple", "LOSSLESS", "both", {})

    assert "upgrade" not in b.calls[0][4]
    assert "No upgrade applied" in b.statuses[-1]


def test_an_empty_audio_type_resolves_the_recorded_version(tmp_path):
    origin_file = tmp_path / "Song.ogg"
    origin_file.write_bytes(b"old audio")
    record = {
        "path": str(origin_file),
        "quality_tier": "LOSSLESS",
        "quality_rank": 2,
        "audio_type": "stereo",
        "codecs": "flac",
        "bit_depth": 16,
        "sample_rate": 44100,
        "audio_digest": audio_digest(origin_file),
    }
    item = replace(
        _offer(
            (
                DeliveryFacts(
                    tier=QualityTier.HI_RES_LOSSLESS,
                    audio_type="stereo",
                    codec="alac",
                    bit_depth=24,
                    sample_rate=96000,
                ),
            )
        ),
        selected=OfferConstraints(tier=QualityTier.LOSSLESS, audio_type=""),
    )
    b = _host(item, origin=_origin(), record=record)

    assert WavesBridge.downloadCatalogOffer(b, 7, "apple", "LOSSLESS", "", {})

    assert b.calls[0][4]["upgrade"]["audio_type"] == "stereo"


def test_the_real_chooser_chain_captures_provenance_and_upgrade(tmp_path):
    from waves.desktop import backend as backend_module
    from waves.model.cfg import Settings

    origin_file = tmp_path / "Song.ogg"
    origin_file.write_bytes(b"old audio")
    record = {
        "path": str(origin_file),
        "quality_tier": "LOSSLESS",
        "quality_rank": 2,
        "audio_type": "stereo",
        "codecs": "flac",
        "bit_depth": 16,
        "sample_rate": 44100,
        "audio_digest": audio_digest(origin_file),
    }
    item = _offer(
        (
            DeliveryFacts(
                tier=QualityTier.HI_RES_LOSSLESS,
                audio_type="stereo",
                codec="alac",
                bit_depth=24,
                sample_rate=96000,
            ),
        )
    )
    snapshot = OfferSnapshot(CatalogSelection("track", "tidal:1"), (item,), (lambda: True,), _origin())
    data = Settings()
    data.download_policies.upgrade_provider = True
    b = BridgeStub(
        _catalog_offer_generation=7,
        _catalog_offer_snapshot=(7, snapshot),
        settings=SimpleNamespace(data=data),
        _ownership=SimpleNamespace(ownership_of=lambda *_a, **_k: record),
        _objs={"track": {"apple:2": SimpleNamespace(id="2", name="Song", full_name="Song")}},
        _queue=[],
    )
    b._set_status = lambda _text: None
    b._chooser_toggle_pins = WavesBridge._chooser_toggle_pins.__get__(b)
    b._chooser_provider_of = lambda _mid: "apple"
    b._chooser_ask_for = lambda _pid, tier: (tier, tier) if tier in ("LOSSLESS", "") else None
    b._chooser_normalize_audio = lambda audio, _pid: audio if audio in ("stereo", "both", "") else None
    b._download_click = lambda *_a, **_k: False
    b._waves_pref_bool = lambda _key: False
    b._library_bulk_skip_on = lambda: True
    b._playlist_template = lambda _mid: "{track_title}"
    b._chooser_confirm_status = lambda *_a: None
    b._current_chooser_offer = WavesBridge._current_chooser_offer.__get__(b)
    b._upgrade_plan_for = WavesBridge._upgrade_plan_for.__get__(b)
    b._on_catalog_upgrade_ready = WavesBridge._on_catalog_upgrade_ready.__get__(b)
    b.downloadWithChooser = WavesBridge.downloadWithChooser.__get__(b)
    b.captured = None

    class _SyncPool:
        def start(self, worker):
            worker.run()

    b.threadpool = _SyncPool()
    b._catalogUpgradeReady = SimpleNamespace(emit=lambda payload: b._on_catalog_upgrade_ready(payload))

    def capture_download(obj, kind, name, template, collection, media_id, **kwargs):
        b.captured = backend_module._capture_request(
            b,
            "apple",
            kind,
            media_id,
            kwargs["chooser_ask"][0],
            kwargs["chooser_audio"],
            kwargs["chooser_toggles"],
        )
        return True

    b._download = capture_download

    assert WavesBridge.downloadCatalogOffer(b, 7, "apple", "LOSSLESS", "stereo", {})

    intent = b.captured
    assert intent is not None
    assert intent.origin_facts()["album_title"] == "Album"
    assert intent.origin_consistent is True
    assert intent.upgrade_json
    # The provenance/upgrade values are not boolean queue toggles.
    asset_pins = backend_module._chooser_asset_pins(
        {"origin_facts": {"x": 1}, "upgrade": {"x": 1}, "lyrics_embed": True}
    )
    assert asset_pins == {"lyrics_embed": True}


def test_a_same_provider_offer_captures_no_origin_overlay(tmp_path):
    from waves.desktop import backend as backend_module
    from waves.model.cfg import Settings

    item = _offer(
        (
            DeliveryFacts(
                tier=QualityTier.LOSSLESS,
                audio_type="stereo",
                codec="flac",
                bit_depth=16,
                sample_rate=44100,
            ),
        ),
        pid="tidal",
    )
    snapshot = OfferSnapshot(CatalogSelection("track", "tidal:1"), (item,), (lambda: True,), _origin())
    b = BridgeStub(
        _catalog_offer_generation=7,
        _catalog_offer_snapshot=(7, snapshot),
        settings=SimpleNamespace(data=Settings()),
        _ownership=SimpleNamespace(ownership_of=lambda *_a, **_k: None),
        _objs={"track": {"tidal:1": SimpleNamespace(id="1", name="Song", full_name="Song")}},
    )
    b.statuses = []
    b._set_status = b.statuses.append
    b._chooser_toggle_pins = WavesBridge._chooser_toggle_pins.__get__(b)
    b._chooser_provider_of = lambda _mid: "tidal"
    b._chooser_ask_for = lambda _pid, tier: (tier, tier) if tier in ("LOSSLESS", "") else None
    b._chooser_normalize_audio = lambda audio, _pid: audio if audio in ("stereo", "") else None
    b._download_click = lambda *_a, **_k: False
    b._waves_pref_bool = lambda _key: False
    b._library_bulk_skip_on = lambda: True
    b._playlist_template = lambda _mid: "{track_title}"
    b._chooser_confirm_status = lambda *_a: None
    b._current_chooser_offer = WavesBridge._current_chooser_offer.__get__(b)
    b._upgrade_plan_for = WavesBridge._upgrade_plan_for.__get__(b)
    b._on_catalog_upgrade_ready = WavesBridge._on_catalog_upgrade_ready.__get__(b)
    b.downloadWithChooser = WavesBridge.downloadWithChooser.__get__(b)
    b.captured = None

    def capture_download(obj, kind, name, template, collection, media_id, **kwargs):
        b.captured = backend_module._capture_request(
            b,
            "tidal",
            kind,
            media_id,
            kwargs["chooser_ask"][0],
            kwargs["chooser_audio"],
            kwargs["chooser_toggles"],
        )
        return True

    b._download = capture_download
    assert b._current_chooser_offer(7, "tidal") is not None

    ok = WavesBridge.downloadCatalogOffer(b, 7, "tidal", "LOSSLESS", "stereo", {})
    assert ok, b.statuses

    intent = b.captured
    assert intent is not None
    assert intent.origin_facts() == {}
    assert intent.upgrade_json == ""
