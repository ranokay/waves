"""The Chooser captures an opt-in upgrade only when it is demonstrated.

With upgrade_provider off the duplicate policy decides. With it on, a matched
cross-provider offer captures a plan only for a Waves-owned unchanged origin
whose recorded facts the probed delivery strictly beats; otherwise the manual
choice still proceeds, with a visible note and no plan.
"""

from __future__ import annotations

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


def _offer(facts=(), state=MatchState.HIGH_CONFIDENCE) -> CatalogOffer:
    return CatalogOffer(
        "apple",
        "apple:2",
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
    b._chooser_normalize_audio = lambda audio, pid: audio if audio in ("stereo", "") else None
    b.downloadWithChooser = lambda *args: b.calls.append(args)
    b._current_chooser_offer = WavesBridge._current_chooser_offer.__get__(b)
    b._upgrade_plan_for = WavesBridge._upgrade_plan_for.__get__(b)
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
