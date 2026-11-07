"""The QML toggle map cannot inject bridge-owned pins into a catalog download."""

from dataclasses import replace
from types import MethodType

from support.bridge_stub import BridgeStub

from waves.constants import QualityTier
from waves.desktop.backend import WavesBridge
from waves.desktop.providers.catalog_identity import CatalogSelection
from waves.desktop.providers.catalog_offers import OfferSnapshot
from waves.metadata.catalog_identity import CatalogResolution, MatchState
from waves.providers.catalog_offers import (
    AvailabilityEvidence,
    CatalogOffer,
    DeliveryFacts,
    EvidenceState,
    OfferConstraints,
)


def _host():
    offer = replace(
        CatalogOffer(
            "apple",
            "apple:2",
            "track",
            CatalogResolution("tidal:1", MatchState.HIGH_CONFIDENCE),
            OfferConstraints(),
            readiness="ready",
        ),
        evidence=AvailabilityEvidence(
            state=EvidenceState.AVAILABLE,
            probed=(DeliveryFacts(tier=QualityTier.HIGH, audio_type="stereo", codec="aac"),),
        ),
    )
    snapshot = OfferSnapshot(CatalogSelection("track", "1"), (offer,), (lambda: True,))
    b = BridgeStub(_catalog_offer_generation=7, _catalog_offer_snapshot=(7, snapshot), calls=[], statuses=[])
    b._set_status = b.statuses.append
    b._chooser_ask_for = lambda pid, tier: (tier, tier) if tier in ("HIGH", "") else None
    b._chooser_normalize_audio = lambda audio, pid: audio if audio in ("stereo", "") else None
    b.downloadWithChooser = lambda *args: b.calls.append(args)
    b._current_chooser_offer = MethodType(WavesBridge._current_chooser_offer, b)
    return b


def test_a_toggle_map_cannot_inject_an_upgrade_plan_or_origin_facts():
    b = _host()

    assert WavesBridge.downloadCatalogOffer(
        b, 7, "apple", "HIGH", "stereo", {"upgrade": {"forged": True}, "origin_facts": {"album": "x"}}
    )

    pins = b.calls[0][4]
    assert "upgrade" not in pins
    assert "origin_facts" not in pins
