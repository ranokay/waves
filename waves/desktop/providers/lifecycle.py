"""Provider context revocation and the bridge's explicitly owned caches.

Worker results commit through ProviderContexts. A callback holds a short
lock: it may update memory or queue a GUI result, never fetch, fsync or wait.
The bridge revokes before stopping work and clearing caches; this module
does not abort jobs, change session state or close a worker's live resources.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, MutableMapping
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Protocol

from waves.ids import DEFAULT_PROVIDER, provider_of_id
from waves.providers.base import Capability

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ProviderToken:
    provider_id: str
    epoch: int
    attempt: int | None = None


@dataclass(slots=True)
class _Context:
    epoch: int = 0
    attempt: int = 0


class ProviderContexts:
    """One authority for provider epochs and cancellable login attempts."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._contexts: dict[str, _Context] = {}

    def capture(self, provider_id: str) -> ProviderToken:
        with self._lock:
            state = self._contexts.setdefault(provider_id, _Context())
            return ProviderToken(provider_id, state.epoch)

    def start_login(self, provider_id: str) -> ProviderToken:
        with self._lock:
            state = self._contexts.setdefault(provider_id, _Context())
            state.attempt += 1
            return ProviderToken(provider_id, state.epoch, state.attempt)

    def cancel_login(self, provider_id: str) -> None:
        with self._lock:
            self._contexts.setdefault(provider_id, _Context()).attempt += 1

    def revoke(self, provider_id: str) -> None:
        with self._lock:
            state = self._contexts.setdefault(provider_id, _Context())
            state.epoch += 1
            state.attempt += 1

    def current(self, token: ProviderToken) -> bool:
        with self._lock:
            state = self._contexts.get(token.provider_id)
            return (
                state is not None
                and state.epoch == token.epoch
                and (token.attempt is None or state.attempt == token.attempt)
            )

    def commit(self, token: ProviderToken, callback: Callable[[], None]) -> bool:
        """Commit a short in-memory result atomically with its validity check."""
        with self._lock:
            if not self.current(token):
                return False
            callback()
            return True


class _ContextHost(Protocol):
    _provider_contexts: ProviderContexts
    _scan_gen: int


_host_lock = RLock()


def provider_contexts(bridge: _ContextHost) -> ProviderContexts:
    """Real bridges initialize eagerly; partial stubs initialize once here."""
    with _host_lock:
        contexts = getattr(bridge, "_provider_contexts", None)
        if not isinstance(contexts, ProviderContexts):
            contexts = ProviderContexts()
            bridge._provider_contexts = contexts
        return contexts


@dataclass(frozen=True, slots=True)
class ScanToken:
    global_generation: int
    provider: ProviderToken


def scan_generation(bridge: _ContextHost, provider_id: str = DEFAULT_PROVIDER) -> ScanToken:
    """Capture STOP ALL and this provider's context for an asynchronous scan."""
    return ScanToken(getattr(bridge, "_scan_gen", 0), provider_contexts(bridge).capture(provider_id))


def scan_current(bridge: _ContextHost, token: ScanToken | int) -> bool:
    """Legacy integer callers check STOP ALL only; new callers carry both."""
    generation = getattr(bridge, "_scan_gen", 0)
    if isinstance(token, int):
        return token == generation
    return token.global_generation == generation and provider_contexts(bridge).current(token.provider)


def _drop_keys[K, V](cache: MutableMapping[K, V], owns: Callable[[K], bool]) -> None:
    for key in list(cache):
        if owns(key):
            cache.pop(key, None)


def _drop_members[K](cache: set[K], owns: Callable[[K], bool]) -> None:
    cache.difference_update(key for key in list(cache) if owns(key))


def page_provider(key: str) -> str:
    """The provider a page-cache key belongs to.

    Item page keys wrap media ids (``item:<kind>:<id>``); playlists-grid
    keys are ``pl:<provider>:<path>`` and editorial page keys
    ``browse:<provider>:<path>``. A legacy bare editorial path (an upgraded
    nav snapshot or disk cache) reads as TIDAL, and ``cat:``/``root`` keys
    are TIDAL's own rollup/landing slots.
    """
    if key.startswith("item:"):
        return provider_of_id(key.partition(":")[2].partition(":")[2])
    if key.startswith(("pl:", "browse:")):
        # ``pl:<provider>:<path>`` / ``browse:<provider>:<path>`` carry their
        # owner; a legacy bare editorial path reads as TIDAL (provider_of_id's
        # bare-value rule), so pre-upgrade caches and nav snapshots keep
        # resolving.
        return provider_of_id(key.partition(":")[2])
    if key.startswith("fav:"):
        source, separator, _kind = key.partition(":")[2].partition(":")
        return source if separator else DEFAULT_PROVIDER
    if key.startswith("cat:"):
        # ``cat:<provider>:<path>``; a legacy bare path reads as TIDAL.
        return provider_of_id(key.partition(":")[2])
    if key == "root":
        return DEFAULT_PROVIDER
    return provider_of_id(key)


def _clear_page_memory(
    bridge,
    provider_id: str,
    owns_media: Callable[[str], bool],
    owns_page: Callable[[str], bool],
    owns_shelf: Callable[[tuple[str, str]], bool],
) -> None:
    with getattr(bridge, "_evict_lock", None) or nullcontext():
        for name in ("_lib_cache", "_lib_sort", "_lib_gen", "_lib_reval_ts"):
            _drop_keys(getattr(bridge, name, {}), owns_shelf)
        _drop_members(getattr(bridge, "_lib_loading", set()), owns_shelf)
        for name in ("_home_cache", "_home_reval_ts"):
            getattr(bridge, name, {}).pop(provider_id, None)
        getattr(bridge, "_home_loading", set()).discard(provider_id)
        for name in (
            "_artist_cache",
            "_artist_reval_ts",
            "_artist_pop_cache",
            "_album_tracks_cache",
            "_edition_tracks_cache",
        ):
            _drop_keys(getattr(bridge, name, {}), owns_media)
        _drop_keys(getattr(bridge, "_browse_pages", {}), owns_page)
        _drop_members(getattr(bridge, "_browse_loading", set()), owns_page)
        _drop_keys(getattr(bridge, "_item_fetch_ts", {}), owns_page)
        _drop_keys(getattr(bridge, "_category_pl", {}), owns_page)
        _drop_keys(getattr(bridge, "_fav_ids", {}), owns_media)
        _clear_search_cache(bridge, provider_id)
        # The combined landing is composed from every browse-capable
        # provider's account, so any one of them changing (sign-out, relogin,
        # disable) invalidates it, not just TIDAL's. Its in-flight guard is
        # released too: "root" is attributed to the default provider by
        # page_provider, so the owns_page sweep above would leave it set and
        # a stale worker's early return would strand the landing's load
        # slot for the rest of the session.
        provider = (getattr(bridge, "providers", None) or {}).get(provider_id)
        capabilities = getattr(provider, "capabilities", frozenset()) if provider is not None else frozenset()
        if Capability.BROWSE in capabilities:
            bridge._browse_root_cache = None
            bridge._browse_reval_ts = 0.0
            _drop_members(getattr(bridge, "_browse_loading", set()), lambda key: key == "root")


def _clear_search_cache(bridge, provider_id: str) -> None:
    search_cache = getattr(bridge, "_search_cache", {})
    for key, (_stamp, payload) in list(search_cache.items()):
        if provider_id in key.partition(":")[0].split("+") or any(
            isinstance(group, dict) and group.get("provider") == provider_id for group in payload.get("groups") or []
        ):
            search_cache.pop(key, None)


def _clear_prefetches(bridge, owns_media: Callable[[str], bool], owns_page: Callable[[str], bool]) -> None:
    with getattr(bridge, "_prefetch_lock", None) or nullcontext():
        if owns_page(getattr(bridge, "_prefetch_key", None) or ""):
            bridge._prefetch_key = None
            bridge._prefetch_claimed = False
        _drop_members(getattr(bridge, "_prefetch_unrecorded", set()), owns_page)
        _drop_keys(getattr(bridge, "_album_tracks_inflight", {}), owns_media)
        _drop_keys(getattr(bridge, "_album_tracks_tokens", {}), owns_media)
        _drop_members(getattr(bridge, "_album_tracks_unrecorded", set()), owns_media)
        _drop_members(getattr(bridge, "_artist_loading", set()), owns_media)
        if owns_media(getattr(bridge, "_artist_prefetch", None) or ""):
            bridge._artist_prefetch = None
            bridge._artist_prefetch_claimed = False


def _unbind_provider_jobs(bridge, owns_media: Callable[[str], bool]) -> None:
    _drop_members(getattr(bridge, "_merge_scanned", set()), owns_media)
    plans = getattr(bridge, "_merge_plans", {})
    unbound = getattr(bridge, "_merge_plans_unbound", None)
    for mid, plan in list(plans.items()):
        if owns_media(mid):
            if unbound is not None:
                unbound[mid] = [
                    (str(getattr(entry.src, "id", "") or ""), entry.track_num, entry.volume_num, entry.identity_id)
                    for entry in plan
                ]
            plans.pop(mid, None)
    with getattr(bridge, "_queue_lock", None) or nullcontext():
        own_qids = {row["qid"] for row in getattr(bridge, "_queue", []) if owns_media(row.get("media_id", ""))}
    jobs = getattr(bridge, "_jobs", None)
    if jobs is not None:
        _drop_keys(jobs.objs, lambda qid: qid in own_qids)


def _invalidate_disk_caches(bridge) -> None:
    with getattr(bridge, "_page_cache_lock", None) or nullcontext():
        for name in ("_page_cache_path", "_search_cache_path"):
            path = getattr(bridge, name, None)
            if isinstance(path, (str, Path)) and path:
                try:
                    Path(path).unlink(missing_ok=True)
                except OSError:
                    logger.debug("Could not invalidate provider disk cache", exc_info=True)


def clear_provider_caches(bridge, provider_id: str, *, invalidate_disk: bool = True) -> None:
    """Clear one provider's bridge caches after its context was revoked.

    Called on the GUI thread. Existing cache locks protect their writers;
    active workers must also commit through their captured context. Mixed
    search entries are evicted, because their keys promise a complete enabled
    provider set. Unrelated-only entries survive. Legacy mixed disk snapshots
    are disposable and invalidated under the saver lock; the integration owns
    guarded saves/loads and per-provider snapshot account/context stamps.

    Queue rows, paused state, aborts, relays, downloads, plain job detail and
    local Library/Ownership evidence remain with their existing owners.
    """
    if not provider_id:
        return

    def owns_media(key: str) -> bool:
        return provider_of_id(key) == provider_id

    def owns_page(key: str) -> bool:
        return page_provider(key) == provider_id

    def owns_shelf(key: tuple[str, str]) -> bool:
        return key[0] == provider_id

    def owns_refetch(key: tuple[str, str]) -> bool:
        return owns_media(key[1])

    with getattr(bridge, "_objs_lock", None) or nullcontext():
        for bucket in getattr(bridge, "_objs", {}).values():
            _drop_keys(bucket, owns_media)

    _clear_page_memory(bridge, provider_id, owns_media, owns_page, owns_shelf)
    _clear_prefetches(bridge, owns_media, owns_page)
    with getattr(bridge, "_media_lists_lock", None) or nullcontext():
        getattr(bridge, "_media_lists_cache", {}).pop(provider_id, None)
        getattr(bridge, "_folder_tree", {}).pop(provider_id, None)
    if hasattr(bridge, "_tree_warm_waiting"):
        bridge._tree_warm_waiting = [entry for entry in bridge._tree_warm_waiting if entry[2] != provider_id]
    getattr(bridge, "_tree_warm_inflight", set()).discard(provider_id)
    _drop_members(getattr(bridge, "_refetch_inflight", set()), owns_refetch)
    _drop_keys(getattr(bridge, "_chooser_refetch_pins", {}), owns_refetch)
    _unbind_provider_jobs(bridge, owns_media)
    if invalidate_disk:
        _invalidate_disk_caches(bridge)
