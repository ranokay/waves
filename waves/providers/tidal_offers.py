"""One TIDAL item/manifest read. No media URLs, bytes or SDK defaults escape."""

from __future__ import annotations

import base64
import json
import xml.etree.ElementTree as ET
from dataclasses import replace
from time import time
from typing import TYPE_CHECKING

from waves.constants import QualityTier, tier_from_word
from waves.metadata.catalog_identity import CatalogIdentity
from waves.providers.catalog_offers import AvailabilityEvidence, DeliveryFacts, EvidenceState, OfferConstraints

if TYPE_CHECKING:
    from tidalapi import Session

MAX_MANIFEST_BYTES = 512 * 1024


def positive(value) -> int | None:
    """Accept actual integral API facts, without convenient SDK defaults."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def manifest_facts(raw: dict) -> tuple[DeliveryFacts, ...]:
    """Read a bounded BTS/MPD manifest; unknown fields stay unknown."""
    encoded = raw.get("manifest")
    if not isinstance(encoded, str) or len(encoded) > MAX_MANIFEST_BYTES * 2:
        return ()
    try:
        data = base64.b64decode(encoded, validate=True)
        if len(data) > MAX_MANIFEST_BYTES:
            return ()
        mime = str(raw.get("manifestMimeType") or "")
        common = DeliveryFacts(
            tier=tier_from_word(raw.get("audioQuality")),
            audio_type={"STEREO": "stereo", "DOLBY_ATMOS": "atmos"}.get(raw.get("audioMode"), ""),
            bit_depth=positive(raw.get("bitDepth")),
            sample_rate=positive(raw.get("sampleRate")),
        )
        if "dash+xml" in mime:
            return _dash_facts(data, common)
        if "bts" in mime:
            manifest = json.loads(data)
            if not isinstance(manifest, dict):
                return ()
            if manifest.get("encryptionType") not in (None, "NONE"):
                return ()
            return (replace(common, codec=str(manifest.get("codecs") or "")),) if manifest.get("urls") else ()
    except (ValueError, TypeError, ET.ParseError):
        return ()
    return ()


def probe(session: Session, identity: CatalogIdentity, ask: OfferConstraints) -> AvailabilityEvidence:
    raw_id = identity.media_id.split(":", 1)[1]
    resource = "albums" if identity.kind == "album" else "tracks" if identity.kind == "track" else "videos"
    raw = session.request.request("GET", f"{resource}/{raw_id}").json()
    if str(raw.get("id")) != raw_id:
        raise ValueError("Selected TIDAL availability item changed")  # noqa: TRY003
    advertised = ()
    tier = tier_from_word(raw.get("audioQuality"))
    if tier is not None:
        advertised = (DeliveryFacts(tier=tier),)
    now = time()
    if identity.kind != "track":
        return AvailabilityEvidence(
            advertised=advertised,
            observed_at=now,
            expires_at=now + 60,
            explanations=("Collection/video item availability needs separate rendition evidence.",),
        )
    # One authenticated metadata request, with per-call quality. It does not
    # change the live session's quality or fetch the manifest's media URLs.
    tier = ask.tier
    if ask.audio_type == "atmos":
        tier = QualityTier.HIGH
    elif ask.quality_strategy == "best_available":
        tier = (
            QualityTier.HI_RES_LOSSLESS
            if ask.tier in (QualityTier.LOSSLESS, QualityTier.HI_RES_LOSSLESS)
            else QualityTier.HIGH
        )
    payload = session.request.request(
        "GET",
        f"tracks/{raw_id}/playbackinfopostpaywall",
        params={
            "playbackmode": "STREAM",
            "audioquality": str(tier),
            "assetpresentation": "FULL",
        },
    ).json()
    facts = manifest_facts(payload)
    return AvailabilityEvidence(
        advertised,
        facts,
        EvidenceState.AVAILABLE if facts else EvidenceState.UNKNOWN,
        now,
        now + 60,
        () if facts else ("Manifest availability is unknown.",),
    )


def _dash_facts(data: bytes, common: DeliveryFacts) -> tuple[DeliveryFacts, ...]:
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        return ()
    root = ET.fromstring(data)  # noqa: S314 -- bounded authenticated manifest; DTD/entity declarations rejected
    if any(item.tag.rsplit("}", 1)[-1] == "ContentProtection" for item in root.iter()):
        return ()
    facts = []
    for adaptation in root.iter():
        if adaptation.tag.rsplit("}", 1)[-1] != "AdaptationSet":
            continue
        for rep in adaptation:
            if rep.tag.rsplit("}", 1)[-1] != "Representation":
                continue
            codec = rep.get("codecs") or adaptation.get("codecs") or ""
            rate = rep.get("audioSamplingRate") or adaptation.get("audioSamplingRate")
            bandwidth = rep.get("bandwidth")
            facts.append(
                replace(
                    common,
                    sample_rate=_attribute_int(rate, common.sample_rate),
                    codec=codec,
                    bitrate=_attribute_int(bandwidth),
                )
            )
            if len(facts) >= 16:
                return tuple(facts)
    return tuple(facts)


def _attribute_int(value: str | None, fallback: int | None = None) -> int | None:
    if value is None:
        return fallback
    try:
        return positive(int(value))
    except ValueError:
        return None
