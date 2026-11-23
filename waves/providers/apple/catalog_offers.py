"""Apple catalog traits are advertising, never a guessed rendition ceiling."""

from __future__ import annotations

from time import time
from typing import TYPE_CHECKING

from waves.constants import QualityTier
from waves.metadata.catalog_identity import CatalogIdentity
from waves.providers.apple.catalog_identity import request_resource
from waves.providers.catalog_offers import AvailabilityEvidence, DeliveryFacts, OfferConstraints

if TYPE_CHECKING:
    from waves.providers.apple.provider import AppleProvider


def probe(provider: AppleProvider, identity: CatalogIdentity, ask: OfferConstraints) -> AvailabilityEvidence:
    raw_id = identity.media_id.split(":", 1)[1]
    response = provider._run(request_resource(provider, identity.kind, raw_id))
    resources = response.get("data") or []
    if len(resources) != 1 or str(resources[0].get("id")) != raw_id:
        raise ValueError("Selected Apple availability item changed")  # noqa: TRY003
    attrs = resources[0].get("attributes") or {}
    traits = attrs.get("audioTraits") or []
    advertised = []
    if "lossless" in traits:
        advertised.append(DeliveryFacts(tier=QualityTier.LOSSLESS, audio_type="stereo"))
    if "hi-res-lossless" in traits:
        advertised.append(DeliveryFacts(tier=QualityTier.HI_RES_LOSSLESS, audio_type="stereo"))
    if "atmos" in traits:
        advertised.append(DeliveryFacts(audio_type="atmos"))
    now = time()
    # The current engine has no independent bounded manifest seam. Calling
    # resolve_stream here would download/decrypt media. Leave that evidence
    # unknown until a qualified metadata-only engine probe supplies it.
    return AvailabilityEvidence(
        advertised=tuple(advertised),
        observed_at=now,
        expires_at=now + 60,
        explanations=("Catalog traits are advertised; exact rendition availability is unknown.",),
    )
