"""Provider revocation isolates accounts, cached results and login attempts."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
from threading import Event, Lock, RLock, Thread, current_thread
from types import SimpleNamespace

import pytest

from waves.desktop.providers.lifecycle import (
    ProviderContexts,
    clear_provider_caches,
    provider_contexts,
    scan_current,
    scan_generation,
)
from waves.providers.base import Capability


def test_revocation_and_login_cancel_have_distinct_scopes():
    contexts = ProviderContexts()
    tidal = contexts.capture("tidal")
    apple = contexts.capture("apple")
    login = contexts.start_login("tidal")

    contexts.cancel_login("tidal")

    assert not contexts.current(login)
    assert contexts.current(tidal)
    assert contexts.current(apple)
    replacement = contexts.start_login("tidal")
    contexts.revoke("tidal")
    assert not contexts.current(tidal)
    assert not contexts.current(replacement)
    assert contexts.current(apple)
    assert contexts.capture("tidal").epoch == tidal.epoch + 1


def test_new_attempt_supersedes_old_without_invalidating_catalog_work():
    contexts = ProviderContexts()
    catalog = contexts.capture("third")
    first = contexts.start_login("third")
    second = contexts.start_login("third")
    effects = []

    assert not contexts.commit(first, lambda: effects.append("old login"))
    assert contexts.commit(second, lambda: effects.append("new login"))
    assert contexts.commit(catalog, lambda: effects.append("catalog"))
    assert effects == ["new login", "catalog"]


def test_commit_rejects_revoked_result_and_allows_nested_context_reads():
    contexts = ProviderContexts()
    token = contexts.capture("apple")
    effects = []
    assert contexts.commit(token, lambda: effects.append(contexts.current(token)))
    contexts.revoke("apple")
    assert not contexts.commit(token, lambda: effects.append("stale"))
    assert effects == [True]
    with pytest.raises(FrozenInstanceError):
        token.epoch = 99


def test_callback_exception_releases_the_context_lock():
    contexts = ProviderContexts()
    token = contexts.capture("apple")

    def fail():
        raise ValueError("bad result")

    with pytest.raises(ValueError, match="bad result"):
        contexts.commit(token, fail)
    contexts.revoke("apple")
    assert not contexts.current(token)


def test_revoke_cannot_enter_between_validity_check_and_commit():
    # Observe an actual contended acquisition, rather than infer a race from
    # elapsed time. Waiting is only the test's deterministic interleaving.
    contexts = ProviderContexts()
    token = contexts.capture("apple")
    callback_entered = Event()
    release_callback = Event()
    revoke_blocked = Event()
    lock = RLock()
    effects = []
    errors = []

    class ObservedLock:
        def __enter__(self):
            if current_thread().name == "revoker" and not lock.acquire(blocking=False):
                revoke_blocked.set()
                lock.acquire()
            elif current_thread().name != "revoker":
                lock.acquire()
            return self

        def __exit__(self, *_exc):
            lock.release()

    contexts._lock = ObservedLock()

    def callback():
        callback_entered.set()
        if not release_callback.wait(2):
            errors.append("callback was never released")
        effects.append("committed")

    def revoke():
        contexts.revoke("apple")
        effects.append("revoked")

    committer = Thread(target=lambda: contexts.commit(token, callback))
    revoker = Thread(target=revoke, name="revoker")
    committer.start()
    try:
        assert callback_entered.wait(2)
        revoker.start()
        assert revoke_blocked.wait(2)
    finally:
        release_callback.set()
        committer.join(2)
        if revoker.ident is not None:
            revoker.join(2)
    assert not committer.is_alive() and not revoker.is_alive()
    assert not errors
    assert effects == ["committed", "revoked"]
    assert not contexts.current(token)


def test_partial_host_gets_one_shared_context_authority():
    bridge = SimpleNamespace()
    seen = []
    threads = [Thread(target=lambda: seen.append(provider_contexts(bridge))) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(2)
        assert not thread.is_alive()
    assert len(seen) == 4
    assert all(contexts is seen[0] for contexts in seen)
    assert provider_contexts(bridge) is seen[0]


def test_scan_tokens_combine_global_stop_and_provider_revocation():
    bridge = SimpleNamespace(_scan_gen=0)
    tidal = scan_generation(bridge)
    apple = scan_generation(bridge, "apple")
    assert scan_current(bridge, tidal) and scan_current(bridge, apple)
    assert scan_current(bridge, 0)

    provider_contexts(bridge).revoke("tidal")

    assert not scan_current(bridge, tidal)
    assert scan_current(bridge, apple)
    assert scan_current(bridge, 0), "legacy ints retain their global-only meaning"
    fresh = scan_generation(bridge)
    bridge._scan_gen += 1
    assert not scan_current(bridge, fresh)
    assert not scan_current(bridge, apple)
    assert not scan_current(bridge, 0)


_IDS = {"tidal": {"991", "tidal:992"}, "apple": {"apple:993"}, "third": {"third:994"}}
_MEDIA_MAPS = (
    "_artist_cache",
    "_artist_reval_ts",
    "_artist_pop_cache",
    "_album_tracks_cache",
    "_edition_tracks_cache",
)
_SHELF_MAPS = ("_lib_cache", "_lib_sort", "_lib_gen", "_lib_reval_ts")


def _cache_bridge(tmp_path):
    ids = set().union(*_IDS.values())
    sources = set(_IDS)
    shelves = {(source, "albums") for source in sources}
    pages = {f"item:album:{mid}" for mid in ids}
    pages.update({"root", "pages/browse", "pl:p1", "pl:third:p1"})
    bridge = SimpleNamespace(
        # The registry drives which provider owns what; only TIDAL declares
        # Browse here, so clearing it also retires the combined landing.
        providers={
            "tidal": SimpleNamespace(capabilities=frozenset({Capability.BROWSE})),
            "apple": SimpleNamespace(capabilities=frozenset()),
            "third": SimpleNamespace(capabilities=frozenset()),
        },
        _objs={"album": dict.fromkeys(ids, "catalog object"), "track": dict.fromkeys(ids, "track object")},
        _objs_lock=Lock(),
        _evict_lock=Lock(),
        _prefetch_lock=Lock(),
        _media_lists_lock=Lock(),
        _queue_lock=Lock(),
        _page_cache_lock=Lock(),
        _browse_root_cache={"title": "TIDAL browse"},
        _browse_reval_ts=9.0,
        _browse_pages=dict.fromkeys(pages, "page"),
        _browse_loading=pages.copy(),
        _item_fetch_ts=dict.fromkeys(pages, 5.0),
        _category_pl={"pages/category": "TIDAL category", "third:category": "third category"},
        _fav_ids={"albums": "TIDAL favorites", "third:albums": "third favorites"},
        _lib_loading=shelves.copy(),
        _home_cache=dict.fromkeys(sources, "home"),
        _home_reval_ts=dict.fromkeys(sources, 4.0),
        _home_loading=sources.copy(),
        _prefetch_key="item:album:apple:993",
        _prefetch_claimed=True,
        _prefetch_unrecorded=pages.copy(),
        _album_tracks_inflight=dict.fromkeys(ids, True),
        _album_tracks_unrecorded=ids.copy(),
        _artist_loading=ids.copy(),
        _artist_prefetch="991",
        _artist_prefetch_claimed=True,
        _media_lists_cache=dict.fromkeys(sources, "lists"),
        _folder_tree=dict.fromkeys(sources, "tree"),
        _tree_warm_waiting=[(lambda: None, "held", source) for source in sorted(sources)],
        _tree_warm_inflight=sources.copy(),
        _refetch_inflight={("album", mid) for mid in ids},
        _chooser_refetch_pins={("album", mid): ("LOSSLESS", "stereo") for mid in ids},
        _merge_scanned=ids.copy(),
        _merge_plans={},
        _merge_plans_unbound={},
        _queue=[{"qid": qid, "media_id": mid} for qid, mid in enumerate(sorted(ids), 1)],
        _jobs=SimpleNamespace(
            objs=dict.fromkeys(range(1, 5), "job object"),
            aborts={1: "abort"},
            signals={1: "relay"},
            dls={1: "download"},
            tracks={1: "detail"},
        ),
        _search_cache={f"{source}:needle": (2.0, {"groups": [{"provider": source}]}) for source in sources},
        _page_cache_path=str(tmp_path / "page_cache.json"),
        _search_cache_path=str(tmp_path / "search_cache.json"),
        _search_gen=5,
        _browse_gen=6,
        _lib_epoch=7,
        _scan_gen=8,
        _ownership="local ownership",
        _library_files_gen={"all": 10},
        _library_files_loading={"all": (10,)},
        _own_cache={"991": "file evidence"},
        _paused=True,
    )
    for name in _MEDIA_MAPS:
        setattr(bridge, name, dict.fromkeys(ids, "value"))
    for name in _SHELF_MAPS:
        setattr(bridge, name, dict.fromkeys(shelves, "value"))
    for mid in ids:
        bridge._merge_plans[mid] = [
            SimpleNamespace(src=SimpleNamespace(id=mid), track_num=1, volume_num=1, identity_id=mid)
        ]
    for path in (tmp_path / "page_cache.json", tmp_path / "search_cache.json"):
        path.write_text("{}", encoding="utf-8")
    return bridge


@pytest.mark.parametrize("provider_id", ["tidal", "apple", "third"])
def test_cache_cleanup_preserves_other_providers_and_local_evidence(tmp_path, provider_id):
    bridge = _cache_bridge(tmp_path)
    own = _IDS[provider_id]
    remaining = set().union(*_IDS.values()) - own
    queue = bridge._queue.copy()

    clear_provider_caches(bridge, provider_id)

    for bucket in bridge._objs.values():
        assert set(bucket) == remaining
    for name in (*_MEDIA_MAPS, "_album_tracks_inflight"):
        assert set(getattr(bridge, name)) == remaining
    for name in _SHELF_MAPS:
        assert set(getattr(bridge, name)) == {(source, "albums") for source in _IDS if source != provider_id}
    assert bridge._lib_loading == {(source, "albums") for source in _IDS if source != provider_id}
    for name in ("_home_cache", "_home_reval_ts", "_home_loading", "_media_lists_cache", "_folder_tree"):
        assert set(getattr(bridge, name)) == set(_IDS) - {provider_id}
    for name in ("_album_tracks_unrecorded", "_artist_loading", "_merge_scanned"):
        assert getattr(bridge, name) == remaining
    assert bridge._refetch_inflight == {("album", mid) for mid in remaining}
    assert set(bridge._chooser_refetch_pins) == {("album", mid) for mid in remaining}
    assert set(bridge._merge_plans) == remaining
    assert bridge._merge_plans_unbound == {mid: [(mid, 1, 1, mid)] for mid in own}
    assert bridge._queue == queue
    assert set(bridge._jobs.objs) == {row["qid"] for row in queue if row["media_id"] in remaining}
    assert bridge._jobs.aborts == {1: "abort"} and bridge._jobs.signals == {1: "relay"}
    assert bridge._jobs.dls == {1: "download"} and bridge._jobs.tracks == {1: "detail"}
    assert {entry[2] for entry in bridge._tree_warm_waiting} == set(_IDS) - {provider_id}
    assert bridge._tree_warm_inflight == set(_IDS) - {provider_id}
    assert set(bridge._search_cache) == {f"{source}:needle" for source in _IDS if source != provider_id}
    assert bridge._ownership == "local ownership" and bridge._own_cache == {"991": "file evidence"}
    assert bridge._library_files_gen == {"all": 10} and bridge._library_files_loading == {"all": (10,)}
    assert (bridge._search_gen, bridge._browse_gen, bridge._lib_epoch, bridge._scan_gen) == (5, 6, 7, 8)
    assert bridge._paused
    assert not (tmp_path / "page_cache.json").exists() and not (tmp_path / "search_cache.json").exists()
    if provider_id == "tidal":
        assert bridge._browse_root_cache is None and bridge._browse_reval_ts == 0.0
        assert bridge._fav_ids == {"third:albums": "third favorites"}
        assert bridge._category_pl == {"third:category": "third category"}
        assert bridge._artist_prefetch is None and not bridge._artist_prefetch_claimed
    else:
        assert bridge._browse_root_cache == {"title": "TIDAL browse"}
        assert bridge._artist_prefetch == "991" and bridge._artist_prefetch_claimed
        assert bridge._fav_ids.get("albums") == "TIDAL favorites"
        assert bridge._category_pl.get("pages/category") == "TIDAL category"
    assert ("third:albums" in bridge._fav_ids) == (provider_id != "third")
    assert ("third:category" in bridge._category_pl) == (provider_id != "third")
    assert (bridge._prefetch_key is None) == (provider_id == "apple")
    for name in ("_browse_pages", "_browse_loading", "_item_fetch_ts", "_prefetch_unrecorded"):
        pages = set(getattr(bridge, name))
        assert {f"item:album:{mid}" for mid in remaining}.issubset(pages)
        assert not ({f"item:album:{mid}" for mid in own} & pages)
        assert ("root" in pages) == (provider_id != "tidal")
        assert ("pl:third:p1" in pages) == (provider_id != "third")


def test_a_browse_capable_provider_invalidates_the_combined_landing(tmp_path):
    """The landing is composed from every browse-capable provider's account:
    clearing any one of them retires it, not just TIDAL's."""
    bridge = _cache_bridge(tmp_path)
    bridge.providers["third"].capabilities = frozenset({Capability.BROWSE})

    clear_provider_caches(bridge, "third")

    assert bridge._browse_root_cache is None and bridge._browse_reval_ts == 0.0


def test_mixed_search_is_evicted_instead_of_served_as_complete(tmp_path):
    bridge = _cache_bridge(tmp_path)
    bridge._search_cache["tidal+apple:needle"] = (
        3.0,
        {"groups": [{"provider": "tidal"}, {"provider": "apple"}]},
    )
    apple_only = bridge._search_cache["apple:needle"]

    clear_provider_caches(bridge, "tidal")

    assert "tidal+apple:needle" not in bridge._search_cache
    assert bridge._search_cache["apple:needle"] is apple_only


def test_partial_bridge_cleanup_needs_no_qt_or_live_worker_state():
    bridge = SimpleNamespace(_objs={"album": {"991": "TIDAL", "apple:991": "Apple"}})
    clear_provider_caches(bridge, "tidal")
    assert bridge._objs == {"album": {"apple:991": "Apple"}}


def test_disk_invalidation_uses_the_snapshot_writer_lock(tmp_path, monkeypatch):
    bridge = _cache_bridge(tmp_path)
    unlink = Path.unlink
    invalidated = []

    def checked_unlink(path, *, missing_ok=False):
        acquired = bridge._page_cache_lock.acquire(blocking=False)
        if acquired:
            bridge._page_cache_lock.release()
        assert not acquired, "a saver could interleave with snapshot removal"
        invalidated.append(path.name)
        unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", checked_unlink)
    clear_provider_caches(bridge, "apple")
    assert invalidated == ["page_cache.json", "search_cache.json"]
