"""Selected-context catalog resolution for bridge workers.

This coordinator returns snapshots; it does not publish, route downloads, or
cache evidence. Consumers must retain their selection guard through queued GUI
publication. Each provider's outcome survives an unrelated provider's failure.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from waves.desktop.bridge_surfaces import provider_readiness
from waves.desktop.providers.lifecycle import ProviderToken, provider_contexts
from waves.ids import namespaced_id, provider_of_id
from waves.metadata.catalog_identity import (
    MAX_ENTRIES,
    CatalogIdentity,
    CatalogLookup,
    CatalogResolution,
    MatchState,
    resolve_candidates,
)
from waves.providers.base import Capability, Provider, ReadinessState

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CatalogSelection:
    kind: str
    media_id: str


@dataclass(frozen=True)
class ProviderMatch:
    provider_id: str
    resolution: CatalogResolution


@dataclass(frozen=True)
class SelectedMatches:
    selection: CatalogSelection
    offers: tuple[ProviderMatch, ...] = ()
    explanations: tuple[str, ...] = ()


def resolve_selected(
    bridge,
    selections: tuple[CatalogSelection, ...],
    *,
    provider_ids: tuple[str, ...],
    current: Callable[[], bool],
) -> tuple[SelectedMatches, ...]:
    """Resolve explicit entries/providers on a worker, preserving order/repeats.

    Matching strictness comes from the existing persisted origin policy. No
    selection beyond this bounded request is scanned. ``current`` is the
    consumer's selection/request-constraint generation guard.
    """
    if len(selections) > MAX_ENTRIES or len(provider_ids) > 8:
        message = "Catalog resolution exceeded the selected-context bound"
        raise ValueError(message)
    contexts = provider_contexts(bridge)
    providers = bridge.providers
    selected_ids = tuple(dict.fromkeys((*provider_ids, *(provider_of_id(item.media_id) for item in selections))))
    selected_providers = {pid: providers[pid] for pid in selected_ids if pid in providers}
    tokens = {pid: contexts.capture(pid) for pid in selected_providers}
    policies = {pid: bridge.settings.data.download_policies.effective(pid).matching for pid in selected_providers}
    stamps = {pid: _stamp(provider) for pid, provider in selected_providers.items()}
    results = tuple(
        _resolve_entry(bridge, selection, provider_ids, current, tokens, policies, stamps) for selection in selections
    )
    return tuple(_validate_entry(bridge, result, current, tokens, policies, stamps) for result in results)


def _ready(bridge, provider: Provider, kind: str) -> bool:
    try:
        return (
            kind in provider.identity_kinds
            and provider_readiness(bridge, provider).for_operation(Capability.CATALOG).state == ReadinessState.READY
        )
    except Exception:
        logger.debug("Provider identity readiness failed", exc_info=True)
        return False


def _stamp(provider: Provider) -> tuple[str, ...] | None:
    try:
        return provider.catalog_identity_context()
    except Exception:
        logger.debug("Provider identity context failed", exc_info=True)
        return None


def _lookup(provider: Provider, origin: CatalogIdentity) -> CatalogLookup:
    try:
        with provider.catalog_context():
            lookup = provider.catalog_candidates(origin)
        if all(provider_of_id(item.media_id) == provider.id for item in lookup.candidates):
            return lookup
    except Exception:
        logger.debug("Provider catalog identity lookup failed", exc_info=True)
    return CatalogLookup(complete=False, explanations=("Provider catalog lookup failed.",))


def _resolve_entry(
    bridge,
    selection: CatalogSelection,
    provider_ids: tuple[str, ...],
    current: Callable[[], bool],
    tokens: dict[str, ProviderToken],
    policies: dict[str, str],
    stamps: dict[str, tuple[str, ...] | None],
) -> SelectedMatches:
    contexts = provider_contexts(bridge)
    providers = bridge.providers

    origin_id = namespaced_id(selection.media_id)
    origin_provider = providers.get(provider_of_id(origin_id))
    if not current() or origin_provider is None or not _ready(bridge, origin_provider, selection.kind):
        return SelectedMatches(selection, explanations=("Origin is unavailable or this media kind is unsupported.",))
    origin_token = tokens[origin_provider.id]
    if not contexts.current(origin_token) or stamps[origin_provider.id] is None:
        return SelectedMatches(selection, explanations=("Origin context changed; resolve again.",))
    policy = policies[origin_provider.id]
    try:
        with origin_provider.catalog_context():
            origin = origin_provider.catalog_identity(selection.kind, origin_id.split(":", 1)[1])
    except Exception:
        return SelectedMatches(selection, explanations=("Origin catalog lookup failed.",))
    if origin.media_id != origin_id or origin.kind != selection.kind:
        return SelectedMatches(selection, explanations=("Origin catalog identity changed.",))
    offers: list[ProviderMatch] = []
    for pid in dict.fromkeys(provider_ids):
        provider = providers.get(pid)
        if provider is None or pid == origin_provider.id or not _ready(bridge, provider, selection.kind):
            continue
        token = tokens[pid]
        if not current() or not contexts.current(origin_token) or not contexts.current(token):
            continue
        lookup = (
            _lookup(provider, origin)
            if stamps[pid] is not None
            else CatalogLookup(complete=False, explanations=("Provider catalog context is unavailable.",))
        )
        resolution = resolve_candidates(origin, lookup, policy)
        offers.append(ProviderMatch(pid, resolution))
    return SelectedMatches(selection, tuple(offers))


def _validate_entry(
    bridge,
    result: SelectedMatches,
    current: Callable[[], bool],
    tokens: dict[str, ProviderToken],
    policies: dict[str, str],
    stamps: dict[str, tuple[str, ...] | None],
) -> SelectedMatches:
    contexts = provider_contexts(bridge)
    providers = bridge.providers
    selection = result.selection
    origin_id = namespaced_id(selection.media_id)
    origin_provider = providers.get(provider_of_id(origin_id))
    if origin_provider is None:
        return result
    origin_token = tokens[origin_provider.id]
    policy = policies[origin_provider.id]
    offers = result.offers
    # No cache: a stale snapshot is discarded in full, including otherwise
    # consistent candidates, rather than retaining confirmable old facts.
    valid = current() and contexts.current(origin_token) and _ready(bridge, origin_provider, selection.kind)
    valid = valid and bridge.settings.data.download_policies.effective(origin_provider.id).matching == policy
    valid = valid and stamps[origin_provider.id] is not None and _stamp(origin_provider) == stamps[origin_provider.id]
    if not valid:
        return SelectedMatches(selection, explanations=("Selected catalog context changed; resolve again.",))
    checked = tuple(
        offer
        if contexts.current(tokens[offer.provider_id])
        and _ready(bridge, providers[offer.provider_id], selection.kind)
        and stamps[offer.provider_id] is not None
        and _stamp(providers[offer.provider_id]) == stamps[offer.provider_id]
        else ProviderMatch(
            offer.provider_id,
            CatalogResolution(
                origin_id, MatchState.UNRESOLVED, explanations=("Provider context changed; resolve again.",)
            ),
        )
        for offer in offers
    )
    return SelectedMatches(selection, checked, result.explanations)
