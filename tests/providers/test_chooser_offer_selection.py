from dataclasses import replace
from types import SimpleNamespace

from waves.constants import QualityTier
from waves.desktop.backend import WavesBridge
from waves.desktop.providers.catalog_identity import CatalogSelection
from waves.desktop.providers.catalog_offers import OfferSnapshot
from waves.metadata.catalog_identity import CatalogResolution, MatchState
from waves.model.cfg import Settings
from waves.model.download_policy import capture_intent
from waves.providers.catalog_offers import AvailabilityEvidence, CatalogOffer, EvidenceState, OfferConstraints


def host(offer, guard=lambda: True):
    snapshot = OfferSnapshot(CatalogSelection("track", "1"), (offer,), (guard,))
    b = SimpleNamespace(_catalog_offer_generation=7, _catalog_offer_snapshot=(7, snapshot), calls=[], statuses=[])
    b._set_status = b.statuses.append
    b._chooser_ask_for = lambda pid, tier: (tier, tier) if tier in ("HIGH", "LOSSLESS", "") else None
    b._chooser_normalize_audio = lambda audio, pid: audio if audio in ("stereo", "") else None
    b.downloadWithChooser = lambda *args: b.calls.append(args)
    b._current_chooser_offer = WavesBridge._current_chooser_offer.__get__(b)
    return b


def offer(pid="apple", state=MatchState.HIGH_CONFIDENCE):
    return CatalogOffer(
        pid, pid + ":2", "track", CatalogResolution("tidal:1", state), OfferConstraints(), readiness="ready"
    )


def test_dispatch_keeps_origin_and_provider_engine_pins_separate():
    b = host(offer())
    assert WavesBridge.downloadCatalogOffer(
        b, 7, "apple", "LOSSLESS", "stereo", {"provider_pin": "apple", "engine": "auto"}
    )
    assert b.calls == [
        (
            "apple:2",
            "track",
            "LOSSLESS",
            "stereo",
            {"provider_pin": "apple", "engine": "auto", "origin_media_id": "tidal:1"},
        )
    ]


def test_dispatch_preserves_legacy_source_key():
    b = host(offer("tidal"))
    assert WavesBridge.downloadCatalogOffer(b, 7, "tidal", "HIGH", "stereo", {})
    assert b.calls[0][0] == "1"


def test_new_request_and_revoked_context_cannot_dispatch_old_evidence():
    valid = True
    b = host(offer(), lambda: valid)
    valid = False
    assert not WavesBridge.downloadCatalogOffer(b, 7, "apple", "HIGH", "stereo", {})
    b._catalog_offer_generation = 8
    assert not WavesBridge.downloadCatalogOffer(b, 8, "apple", "HIGH", "stereo", {})
    assert not b.calls


def test_ambiguous_and_expired_offers_cannot_dispatch():
    for item in (
        offer(state=MatchState.AMBIGUOUS),
        replace(offer(), evidence=AvailabilityEvidence(state=EvidenceState.STALE)),
    ):
        b = host(item)
        assert not WavesBridge.downloadCatalogOffer(b, 7, "apple", "HIGH", "stereo", {})
        assert not b.calls


def test_unknown_exact_rendition_does_not_invent_unavailability():
    b = host(offer())
    assert WavesBridge.downloadCatalogOffer(b, 7, "apple", "HIGH", "stereo", {})


def test_fallback_consents_relax_only_the_selected_dimension():
    data = Settings()
    data.download_policies.choose_best_provider = True
    data.download_policies.recover_provider = True
    for provider_allowed, engine_allowed in ((False, True), (True, False)):
        intent = capture_intent(
            data,
            "apple",
            "track",
            "apple:2",
            tier=str(QualityTier.LOSSLESS),
            audio_type="stereo",
            toggles={},
            provider_pin="apple",
            engine_pin="gamdl",
            allow_provider_fallback=provider_allowed,
            allow_engine_fallback=engine_allowed,
        )
        assert intent.choose_best_provider is provider_allowed
        assert intent.recover_provider is provider_allowed
        assert intent.same_provider_fallback is engine_allowed
