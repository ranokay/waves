"""Immutable item evidence and conservative comparison, independent of SDKs/Qt.

Advertising is never availability; a selected requirement is never delivered
media. Missing technical facts remain None and cannot establish improvement.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from enum import StrEnum
from math import isfinite
from time import time

from waves.constants import TIER_RANK, QualityTier
from waves.metadata.catalog_identity import CatalogResolution


class EvidenceState(StrEnum):
    UNKNOWN = "unknown"
    CHECKING = "checking"
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    STALE = "stale"
    FAILED = "failed"


@dataclass(frozen=True)
class DeliveryFacts:
    tier: QualityTier | None = None
    audio_type: str = ""
    codec: str = ""
    profile: str = ""
    sample_rate: int | None = None
    bit_depth: int | None = None
    bitrate: int | None = None
    width: int | None = None
    height: int | None = None
    hdr: bool | None = None
    frame_rate: float | None = None

    def __post_init__(self) -> None:
        for name in ("sample_rate", "bit_depth", "bitrate", "width", "height"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                object.__setattr__(self, name, None)
        if self.frame_rate is not None and (
            isinstance(self.frame_rate, bool) or not isfinite(self.frame_rate) or self.frame_rate <= 0
        ):
            object.__setattr__(self, "frame_rate", None)
        codec, profile = {
            "mp4a.40.2": ("aac", "lc"),
            "mp4a.40.5": ("aac", "he"),
            "mp4a.40.29": ("aac", "he-v2"),
            "ec-3": ("eac3", ""),
        }.get(self.codec.lower(), (self.codec.lower(), self.profile.lower()))
        object.__setattr__(self, "codec", codec)
        object.__setattr__(self, "profile", profile)


@dataclass(frozen=True)
class OfferConstraints:
    tier: QualityTier = QualityTier.HIGH
    audio_type: str = "stereo"
    quality_strategy: str = "best_available"
    required_codec: str = ""
    minimum_sample_rate: int = 0
    minimum_bit_depth: int = 0
    minimum_bitrate: int = 0
    video_height: int = 0
    video_codec: str = ""
    video_hdr: str = "sdr"
    video_max_fps: int = 0
    engine_pin: str = ""
    provider_pin: str = ""


def requested_audio(ask: OfferConstraints) -> tuple[OfferConstraints, ...]:
    """Dual-download keeps a stereo requirement plus a separate Atmos copy.

    Lossless resolution/codec constraints apply to stereo; Atmos is its own
    delivery family, rather than a lossless rendition of the same mix.
    """
    if ask.audio_type != "both":
        return (ask,)
    return (
        replace(ask, audio_type="stereo"),
        replace(
            ask,
            audio_type="atmos",
            tier=QualityTier.HIGH,
            required_codec="",
            minimum_sample_rate=0,
            minimum_bit_depth=0,
            minimum_bitrate=0,
        ),
    )


@dataclass(frozen=True)
class AvailabilityEvidence:
    advertised: tuple[DeliveryFacts, ...] = ()
    probed: tuple[DeliveryFacts, ...] = ()
    state: EvidenceState = EvidenceState.UNKNOWN
    observed_at: float = field(default_factory=time)
    # A short-lived observation, not a delivery guarantee.
    expires_at: float = 0
    explanations: tuple[str, ...] = ()

    def effective_state(self, now: float | None = None) -> EvidenceState:
        return (
            EvidenceState.STALE
            if self.expires_at and (time() if now is None else now) >= self.expires_at
            else self.state
        )


@dataclass(frozen=True)
class OfferPresence:
    # Equivalent local presence is not ownership of this provider's item.
    owned: bool | None = None
    library_present: bool | None = None
    delivered: tuple[DeliveryFacts, ...] = ()


@dataclass(frozen=True)
class CatalogOffer:
    provider_id: str
    media_id: str
    kind: str
    match: CatalogResolution
    selected: OfferConstraints
    evidence: AvailabilityEvidence = field(default_factory=AvailabilityEvidence)
    capabilities: tuple[str, ...] = ()
    readiness: str = "unknown"
    action: str = ""
    presence: OfferPresence = field(default_factory=OfferPresence)
    explanations: tuple[str, ...] = ()

    @property
    def is_origin(self) -> bool:
        return self.media_id == self.match.origin_id

    def comparable_facts(self, now: float | None = None) -> tuple[DeliveryFacts, ...]:
        if (
            self.readiness != "ready"
            or (self.selected.provider_pin and self.selected.provider_pin != self.provider_id)
            or not (self.is_origin or self.match.automatic_eligible)
            or self.evidence.effective_state(now) != EvidenceState.AVAILABLE
        ):
            return ()
        return tuple(
            fact
            for fact in self.evidence.probed
            if any(satisfies(fact, ask, video=self.kind == "video") for ask in requested_audio(self.selected))
        )

    def presentation(self, now: float | None = None) -> dict:
        """Only neutral scalars/collections cross the desktop boundary."""
        return {
            "provider_id": self.provider_id,
            "media_id": self.media_id,
            "origin_id": self.match.origin_id,
            "kind": self.kind,
            "match_state": str(self.match.state),
            "automatic_eligible": self.match.automatic_eligible,
            "capabilities": list(self.capabilities),
            "readiness": self.readiness,
            "action": self.action,
            "advertised": [asdict(fact) for fact in self.evidence.advertised],
            "probed": [asdict(fact) for fact in self.evidence.probed],
            "selected": asdict(self.selected),
            "delivered": [asdict(fact) for fact in self.presence.delivered],
            "owned": self.presence.owned,
            "library_present": self.presence.library_present,
            "evidence_state": str(self.evidence.effective_state(now)),
            "summary": self.summary(now),
            "observed_at": self.evidence.observed_at,
            "expires_at": self.evidence.expires_at,
            "explanations": [*self.match.explanations, *self.evidence.explanations, *self.explanations],
        }

    def summary(self, now: float | None = None) -> str:
        if self.selected.audio_type == "both":
            return "; ".join(
                f"{ask.audio_type.title()}: {replace(self, selected=ask).summary(now)}"
                for ask in requested_audio(self.selected)
            )
        if self.readiness != "ready":
            return (
                "Requested format unsupported"
                if self.readiness == "unsupported"
                else "Delivery needs setup or account action"
            )
        if not self.media_id:
            return "Identity unresolved; availability unknown"
        state = self.evidence.effective_state(now)
        if state != EvidenceState.AVAILABLE:
            return {
                EvidenceState.STALE: "Availability stale; check again",
                EvidenceState.CHECKING: "Checking availability",
                EvidenceState.FAILED: "Availability check failed; try again",
                EvidenceState.UNAVAILABLE: "Requested delivery unavailable",
            }.get(state, "Exact availability unknown")
        facts = tuple(
            fact for fact in self.evidence.probed if satisfies(fact, self.selected, video=self.kind == "video")
        )
        if not facts:
            return "Manifest does not establish selected constraints"
        fact = facts[0]
        details = [fact.codec.upper()] if fact.codec else []
        if fact.bit_depth is not None:
            details.append(f"{fact.bit_depth} bit")
        if fact.sample_rate is not None:
            details.append(f"{fact.sample_rate / 1000:g} kHz")
        if fact.height is not None:
            details.append(f"{fact.height}p")
        return "Manifest: " + (", ".join(details) or "available; technical detail unknown")


def satisfies(fact: DeliveryFacts, ask: OfferConstraints, *, video: bool = False) -> bool:
    """Filter known constraints before comparing. Unknown required facts fail."""
    if video:
        return (
            fact.height is not None
            and fact.height >= ask.video_height
            and (not ask.video_codec or fact.codec == ask.video_codec)
            and (ask.video_hdr == "any" or fact.hdr is (ask.video_hdr == "hdr"))
            and (not ask.video_max_fps or (fact.frame_rate is not None and fact.frame_rate <= ask.video_max_fps))
        )
    if fact.audio_type != ask.audio_type or (ask.required_codec and fact.codec != ask.required_codec):
        return False
    for value, minimum in (
        (fact.sample_rate, ask.minimum_sample_rate),
        (fact.bit_depth, ask.minimum_bit_depth),
        (fact.bitrate, ask.minimum_bitrate),
    ):
        if minimum and (value is None or value < minimum):
            return False
    if fact.tier is None:
        return False
    # Best available may accept a lower lossless resolution visibly. It never
    # authorizes a lossless-to-lossy or audio-type change.
    if TIER_RANK[fact.tier] < TIER_RANK[QualityTier.LOSSLESS] <= TIER_RANK[ask.tier]:
        return False
    return ask.quality_strategy != "minimum_required" or TIER_RANK[fact.tier] >= TIER_RANK[ask.tier]


def compare_quality(left: DeliveryFacts, right: DeliveryFacts, *, video: bool = False) -> int | None:
    """1/0/-1 for comparable facts; None means improvement is unproven."""
    if video:
        a, b = (left.height, left.width), (right.height, right.width)
    elif left.audio_type != right.audio_type:
        return None
    elif left.codec in ("flac", "alac") and right.codec in ("flac", "alac"):
        a, b = (left.bit_depth, left.sample_rate), (right.bit_depth, right.sample_rate)
    elif left.codec and left.codec == right.codec and left.profile and left.profile == right.profile:
        a, b = (left.bitrate,), (right.bitrate,)
    else:
        return None
    if any(value is None for value in (*a, *b)):
        return None
    known_a = tuple(value for value in a if value is not None)
    known_b = tuple(value for value in b if value is not None)
    return (known_a > known_b) - (known_a < known_b)


@dataclass(frozen=True)
class OfferChoice:
    media_id: str
    provider_id: str
    explanations: tuple[str, ...]


def choose_offer(
    offers: tuple[CatalogOffer, ...],
    *,
    origin_id: str,
    provider_priority: tuple[str, ...] = (),
    now: float | None = None,
) -> OfferChoice:
    """Rank only demonstrated comparable improvements; unknown retains origin.

    This returns a suggestion, without routing, replacement or fallback consent.
    Explicit provider/engine pins remain constraints, owned by the caller.
    """
    origin = next((offer for offer in offers if offer.media_id == origin_id), None)
    origin_provider = origin_id.split(":", 1)[0]
    if origin is None:
        return OfferChoice(origin_id, origin_provider, ("Origin evidence is unknown; retain origin.",))
    chosen = origin
    best = _best_facts(origin, now)
    if best is None:
        return OfferChoice(origin_id, origin_provider, ("Origin availability is unknown; improvement is unproven.",))
    priority = {pid: index for index, pid in enumerate(provider_priority)}
    for offer in offers:
        fact = _best_facts(offer, now)
        if fact is None or offer.selected != origin.selected or offer.kind != origin.kind:
            continue
        comparisons = tuple(
            compare_quality(left, right, video=offer.kind == "video") for left, right in zip(fact, best, strict=True)
        )
        # Every requested family must be comparable and non-degrading. A
        # better stereo copy cannot conceal a worse/unknown Atmos copy.
        if any(value is None or value < 0 for value in comparisons):
            continue
        comparison = 1 if any(value == 1 for value in comparisons) else 0
        if comparison == 1 or (
            comparison == 0
            and priority.get(offer.provider_id, len(priority)) < priority.get(chosen.provider_id, len(priority))
        ):
            chosen, best = offer, fact
    reason = (
        "Demonstrated comparable quality and provider preference."
        if chosen != origin
        else "No demonstrated improvement or preferred comparable tie; retain origin."
    )
    return OfferChoice(chosen.media_id, chosen.provider_id, (reason,))


def _best_facts(offer: CatalogOffer, now: float | None) -> tuple[DeliveryFacts, ...] | None:
    facts = offer.comparable_facts(now)
    best_families = []
    for ask in requested_audio(offer.selected):
        family = tuple(fact for fact in facts if satisfies(fact, ask, video=offer.kind == "video"))
        if not family:
            return None
        best = family[0]
        for fact in family[1:]:
            comparison = compare_quality(fact, best, video=offer.kind == "video")
            if comparison is None:
                # Different profiles cannot form one automatic maximum.
                return None
            if comparison > 0:
                best = fact
        best_families.append(best)
    return tuple(best_families)
