"""Lazy selected-context offers with bounded, request-scoped evidence caching.

Workers return guarded snapshots. Consumers revalidate at queued publication;
no selection, recovery, replacement or media diagnostic happens here.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from threading import RLock
from time import time

from waves.desktop.bridge_surfaces import provider_readiness
from waves.desktop.providers.catalog_identity import CatalogSelection, resolve_selected
from waves.desktop.providers.lifecycle import provider_contexts
from waves.ids import namespaced_id, provider_of_id
from waves.metadata.catalog_identity import CatalogIdentity, CatalogResolution, MatchEvidence, MatchState
from waves.providers.base import AccountState, Capability, Provider, ProviderReadiness, ReadinessState
from waves.providers.catalog_offers import (
    AvailabilityEvidence,
    CatalogOffer,
    EvidenceState,
    OfferConstraints,
    OfferPresence,
    requested_audio,
    satisfies,
)

logger = logging.getLogger(__name__)
MAX_CACHE_ENTRIES = 256


@dataclass(frozen=True)
class _CacheKey:
    request_id: str
    identity: CatalogIdentity
    ask: OfferConstraints
    stamp: tuple[str, ...]


class OfferEvidenceCache:
    """Bounded observations; only the same request/context/constraints may reuse."""

    def __init__(self, *, clock: Callable[[], float] = time) -> None:
        self._lock = RLock()
        self._clock = clock
        self._entries: OrderedDict[_CacheKey, AvailabilityEvidence] = OrderedDict()

    def get(self, key: _CacheKey) -> AvailabilityEvidence | None:
        with self._lock:
            evidence = self._entries.get(key)
            if evidence is None:
                return None
            if evidence.effective_state(self._clock()) == EvidenceState.STALE:
                self._entries.pop(key)
                return None
            self._entries.move_to_end(key)
            return evidence

    def put(self, key: _CacheKey, evidence: AvailabilityEvidence) -> None:
        with self._lock:
            self._entries[key] = evidence
            self._entries.move_to_end(key)
            while len(self._entries) > MAX_CACHE_ENTRIES:
                self._entries.popitem(last=False)


@dataclass(frozen=True)
class OfferSnapshot:
    selection: CatalogSelection
    offers: tuple[CatalogOffer, ...]
    # Guards contain private context stamps, never included in presentation.
    guards: tuple[Callable[[], bool], ...] = field(repr=False, compare=False)

    def validated(self) -> tuple[CatalogOffer, ...]:
        """Call on the receiving thread, including after a queued GUI hop."""
        return tuple(
            offer
            if guard()
            else replace(
                offer,
                readiness="unknown",
                match=CatalogResolution(offer.match.origin_id, MatchState.UNRESOLVED),
                evidence=AvailabilityEvidence(
                    state=EvidenceState.STALE, explanations=("Context changed; check availability again.",)
                ),
                presence=OfferPresence(),
                explanations=(),
            )
            for offer, guard in zip(self.offers, self.guards, strict=True)
        )

    def presentation(self) -> list[dict]:
        return [offer.presentation() for offer in self.validated()]


def _stamp(provider: Provider) -> tuple[str, ...] | None:
    try:
        return (*provider.availability_context(), repr(provider.capabilities), repr(provider.audio_types))
    except Exception:
        logger.debug("Offer context unavailable", exc_info=True)
        return None


def _live(bridge, provider: Provider) -> ProviderReadiness:
    try:
        return provider_readiness(bridge, provider)
    except Exception:
        return ProviderReadiness(None, AccountState.UNKNOWN, ())


def collect_offers(
    bridge,
    selections: tuple[CatalogSelection, ...],
    *,
    provider_ids: tuple[str, ...],
    ask: OfferConstraints,
    request_id: str,
    current: Callable[[], bool],
    trigger: str = "chooser",
    cache: OfferEvidenceCache | None = None,
    presence: Callable[[CatalogIdentity], OfferPresence] | None = None,
) -> tuple[OfferSnapshot, ...]:
    """Probe only on Chooser or enabled automatic-choice demand, never search.

    Lookup bounds come from the identity coordinator (64 entries/8 providers).
    Only resolved high-confidence or current-request confirmed candidates are
    probed. Presence is optional authoritative evidence, never inferred from a
    match. Media/decrypt diagnostics are outside this metadata-only seam.
    """
    if trigger not in ("chooser", "auto") or (
        trigger == "auto" and not bridge.settings.data.download_policies.choose_best_provider
    ):
        raise ValueError("Offer probing requires Chooser or opt-in routing demand")  # noqa: TRY003
    contexts = provider_contexts(bridge)
    pids = tuple(dict.fromkeys((*provider_ids, *(provider_of_id(item.media_id) for item in selections))))
    providers = {pid: bridge.providers[pid] for pid in pids if pid in bridge.providers}
    tokens = {pid: contexts.capture(pid) for pid in providers}
    stamps = {pid: _stamp(provider) for pid, provider in providers.items()}
    matches = resolve_selected(bridge, selections, provider_ids=provider_ids, current=current)
    cache = cache or OfferEvidenceCache()
    snapshots = []
    for result in matches:
        origin_pid = provider_of_id(result.selection.media_id)
        policy = bridge.settings.data.download_policies.effective(origin_pid).matching

        def valid(pid: str, *, origin_pid=origin_pid, policy=policy) -> bool:
            try:
                origin_provider = providers.get(origin_pid)
                provider = providers.get(pid)
                return (
                    current()
                    and (trigger != "auto" or bridge.settings.data.download_policies.choose_best_provider)
                    and origin_provider is not None
                    and provider is not None
                    and contexts.current(tokens[origin_pid])
                    and contexts.current(tokens[pid])
                    and stamps[origin_pid] is not None
                    and _stamp(origin_provider) == stamps[origin_pid]
                    and stamps[pid] is not None
                    and _stamp(provider) == stamps[pid]
                    and bridge.settings.data.download_policies.effective(origin_pid).matching == policy
                )
            except Exception:
                return False

        origin_id = namespaced_id(result.selection.media_id)
        resolutions = {item.provider_id: item.resolution for item in result.offers}
        if result.origin is not None:
            resolutions[origin_pid] = CatalogResolution(
                origin_id,
                MatchState.HIGH_CONFIDENCE,
                candidates=(MatchEvidence(result.origin),),
                explanations=("Original catalog item.",),
                observed_at=time(),
            )
        offers, guards = [], []
        for pid in dict.fromkeys((*provider_ids, origin_pid)):
            provider = providers.get(pid)
            resolution = resolutions.get(
                pid,
                CatalogResolution(
                    origin_id,
                    MatchState.UNRESOLVED,
                    explanations=result.explanations or ("Identity unresolved or catalog access needs setup.",),
                ),
            )
            identity = _selected_identity(resolution)
            # Bind this entry's origin/policy into a guard before moving to the
            # next selection; queued consumers must retain the original guard.
            guard = lambda pid=pid, valid=valid: valid(pid)
            stamp = stamps.get(pid)
            offer = _collect_one(
                pid,
                provider,
                resolution,
                identity,
                ask,
                request_id,
                (*stamp, repr(tokens[pid]), repr(tokens.get(origin_pid)), repr(stamps.get(origin_pid)), policy)
                if stamp is not None
                else None,
                guard,
                bridge,
                cache,
                presence,
                result.selection.kind,
            )
            offers.append(offer)
            guards.append(guard)
        snapshots.append(OfferSnapshot(result.selection, tuple(offers), tuple(guards)))
    return tuple(snapshots)


def _selected_identity(resolution: CatalogResolution) -> CatalogIdentity | None:
    if resolution.state == MatchState.USER_CONFIRMED:
        return next(
            (item.identity for item in resolution.candidates if item.identity.media_id == resolution.confirmed_id), None
        )
    if resolution.automatic_eligible and len(resolution.candidates) == 1:
        return resolution.candidates[0].identity
    return None


def _collect_one(
    pid, provider, resolution, identity, ask, request_id, stamp, guard, bridge, cache, presence, kind
) -> CatalogOffer:
    state, action = ReadinessState.UNSUPPORTED, ""
    evidence = AvailabilityEvidence()
    local = OfferPresence()
    if provider is not None:
        observations, readinesses = [], []
        for family in (ask,) if kind == "video" else requested_audio(ask):
            observation = AvailabilityEvidence()
            try:
                live = _live(bridge, provider)
                readiness = (
                    provider.offer_readiness(identity, family, live)
                    if identity is not None
                    else live.for_operation(Capability.DOWNLOAD)
                )
                readinesses.append(readiness)
                if identity is not None and readiness.state == ReadinessState.READY and guard() and stamp is not None:
                    key = _CacheKey(request_id, identity, family, stamp)
                    observation = _cached_probe(provider, key, guard, cache)
            except Exception:
                logger.debug("Provider availability probe failed", exc_info=True)
                observation = AvailabilityEvidence(
                    state=EvidenceState.FAILED, explanations=("Provider availability check failed; try again.",)
                )
            observations.append(observation)
        if readinesses:
            readiness = next((item for item in readinesses if item.state != ReadinessState.READY), readinesses[0])
            state, action = readiness.state, readiness.action
        evidence = _combined_evidence(tuple(observations))
    if identity is not None and guard() and presence is not None:
        try:
            local = presence(identity)
        except Exception:
            logger.debug("Offer ownership/presence unavailable", exc_info=True)
    explanation = ()
    if state != ReadinessState.READY:
        explanation = (
            "Requested format is unsupported."
            if state == ReadinessState.UNSUPPORTED
            else "Provider delivery needs setup or account action.",
        )
    elif evidence.state == EvidenceState.AVAILABLE and not all(
        any(satisfies(fact, family, video=kind == "video") for fact in evidence.probed)
        for family in ((ask,) if kind == "video" else requested_audio(ask))
    ):
        explanation = ("Probed delivery does not establish the selected constraints.",)
    return CatalogOffer(
        pid,
        identity.media_id if identity else "",
        kind,
        resolution,
        ask,
        evidence,
        tuple(sorted(str(value) for value in provider.capabilities)) if provider else (),
        str(state),
        action,
        local,
        explanation,
    )


def _combined_evidence(observations: tuple[AvailabilityEvidence, ...]) -> AvailabilityEvidence:
    if len(observations) == 1:
        return observations[0]
    states = {item.state for item in observations}
    return AvailabilityEvidence(
        advertised=tuple(fact for item in observations for fact in item.advertised),
        probed=tuple(fact for item in observations for fact in item.probed),
        state=EvidenceState.AVAILABLE
        if states == {EvidenceState.AVAILABLE}
        else EvidenceState.FAILED
        if EvidenceState.FAILED in states
        else EvidenceState.UNKNOWN,
        observed_at=max(item.observed_at for item in observations),
        expires_at=min((item.expires_at for item in observations if item.expires_at), default=0),
        explanations=tuple(word for item in observations for word in item.explanations),
    )


def _cached_probe(
    provider: Provider, key: _CacheKey, guard: Callable[[], bool], cache: OfferEvidenceCache
) -> AvailabilityEvidence:
    evidence = cache.get(key)
    if evidence is not None:
        return evidence
    with provider.catalog_context():
        evidence = provider.probe_availability(key.identity, key.ask)
    if guard():
        # Cap lifetime even for adapters omitting expiry. Failed/partial
        # checking observations are retried on the next explicit demand.
        evidence = replace(evidence, expires_at=min(evidence.expires_at or time() + 60, time() + 60))
        if evidence.state not in (EvidenceState.FAILED, EvidenceState.CHECKING, EvidenceState.STALE):
            cache.put(key, evidence)
    return evidence
