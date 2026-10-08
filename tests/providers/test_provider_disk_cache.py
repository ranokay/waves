"""Provider snapshots preserve attribution and cannot publish revoked work."""

from __future__ import annotations

import copy
import json
import os
import stat
from _thread import LockType
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, Lock, Thread

import pytest
from support.bridge_stub import BridgeStub

from waves.desktop.providers import cache
from waves.desktop.providers.lifecycle import ProviderContexts


@dataclass
class _Host(BridgeStub):
    _page_cache_path: Path
    _search_cache_path: Path
    _provider_contexts: ProviderContexts = field(default_factory=ProviderContexts)
    _page_cache_lock: LockType = field(default_factory=Lock)


@pytest.fixture
def host(tmp_path):
    return _Host(tmp_path / "pages.json", tmp_path / "searches.json")


def _payloads():
    accounts = {"tidal": "opaque-one", "apple": "opaque-two", "paper": ""}
    data = {
        "accounts": accounts,
        "browse_root": {"title": "TIDAL feed"},
        "browse_pages": {
            "root": {"title": "Root"},
            "cat:FEATURED": {"title": "Featured"},
            "pl:42": {"title": "Legacy playlist"},
            "pl:paper:42": {"title": "Paper playlist"},
            "item:album:apple:42": {"title": "Apple album"},
            "item:album:paper:42": {"title": "Paper album"},
        },
        "artists": {"42": {"name": "TIDAL"}, "apple:42": {"name": "Apple"}, "paper:42": {"name": "Paper"}},
        "library": {"tidal:albums": {"items": [{"id": "42"}], "offset": 40, "more": True}},
        "home": {"tidal": [{"title": "For you"}], "apple": [{"title": "Apple"}], "paper": [{"title": "Paper"}]},
    }
    searches = {
        "accounts": accounts,
        "searches": {
            "tidal:one": {"groups": [{"provider": "tidal"}]},
            "apple:one": {"groups": [{"provider": "apple"}]},
            "paper:one": {"groups": [{"provider": "paper"}]},
            "tidal+paper:one": {"groups": [{"provider": "tidal"}, {"provider": "paper"}]},
            "legacy-query": {"groups": [{"provider": "paper"}]},
        },
    }
    return data, searches


def test_save_preserves_scoped_stamps_and_existing_page_search_layout(host, monkeypatch):
    data, searches = _payloads()
    tokens = [host._provider_contexts.capture(pid) for pid in ("tidal", "apple", "paper")]
    names = []
    mkstemp = cache.tempfile.mkstemp

    def record_stage(**kwargs):
        fd, name = mkstemp(**kwargs)
        names.append(name)
        if os.name == "posix":
            assert stat.S_IMODE(Path(name).stat().st_mode) == 0o600
        return fd, name

    monkeypatch.setattr(cache.tempfile, "mkstemp", record_stage)
    assert cache.save_snapshot(host, data, searches, tokens)
    assert cache.save_snapshot(host, data, searches, tokens)
    assert len(set(names)) == 4, "each file in every save stages through a private name"
    assert cache.read_snapshot(host._page_cache_path) == {**data, "version": 8}
    assert cache.read_snapshot(host._search_cache_path) == {**searches, "version": 8}
    assert "version" not in data and "version" not in searches
    assert not list(host._page_cache_path.parent.glob("*.tmp"))


@pytest.mark.parametrize("revoked", ["tidal", "paper"])
def test_revocation_during_fsync_cannot_recreate_removed_snapshot(host, monkeypatch, revoked):
    data, searches = _payloads()
    tokens = [host._provider_contexts.capture(pid) for pid in ("tidal", "paper")]
    assert cache.save_snapshot(host, data, searches, tokens)
    staged = Event()
    release = Event()
    results = []
    errors = []
    fsync = cache.os.fsync

    def hold_first_fsync(fd):
        fsync(fd)
        if not staged.is_set():
            staged.set()
            if not release.wait(2):
                raise RuntimeError("staging was never released")

    def save():
        try:
            results.append(cache.save_snapshot(host, data, searches, tokens))
        except Exception as exc:
            errors.append(exc)

    monkeypatch.setattr(cache.os, "fsync", hold_first_fsync)
    worker = Thread(target=save)
    worker.start()
    try:
        assert staged.wait(2)
        # Staging must not hold either lock: sign-out and cache removal can
        # finish while the disk is slow, rather than wait on the fsync.
        acquired = host._provider_contexts._lock.acquire(blocking=False)
        assert acquired
        host._provider_contexts._lock.release()
        acquired = host._page_cache_lock.acquire(blocking=False)
        assert acquired
        host._page_cache_lock.release()
        host._provider_contexts.revoke(revoked)
        with host._page_cache_lock:
            host._page_cache_path.unlink()
            host._search_cache_path.unlink()
    finally:
        release.set()
        worker.join(2)
    assert not worker.is_alive() and not errors
    assert results == [False]
    assert not host._page_cache_path.exists() and not host._search_cache_path.exists()
    assert not list(host._page_cache_path.parent.glob("*.tmp"))


def test_only_final_replaces_hold_context_and_writer_locks(host, monkeypatch):
    data, searches = _payloads()
    tokens = [host._provider_contexts.capture(pid) for pid in ("tidal", "paper")]
    replace = cache.os.replace
    observations = []

    def observed_replace(source, destination):
        def probe():
            context_free = host._provider_contexts._lock.acquire(blocking=False)
            if context_free:
                host._provider_contexts._lock.release()
            writer_free = host._page_cache_lock.acquire(blocking=False)
            if writer_free:
                host._page_cache_lock.release()
            observations.append((context_free, writer_free))

        observer = Thread(target=probe)
        observer.start()
        observer.join(2)
        assert not observer.is_alive()
        replace(source, destination)

    monkeypatch.setattr(cache.os, "replace", observed_replace)
    assert cache.save_snapshot(host, data, searches, tokens)
    assert observations == [(False, False), (False, False)]


def test_second_stage_failure_preserves_previous_files_and_cleans_private_files(host, monkeypatch):
    data, searches = _payloads()
    tokens = [host._provider_contexts.capture("tidal")]
    assert cache.save_snapshot(host, data, searches, tokens)
    previous = [path.read_bytes() for path in (host._page_cache_path, host._search_cache_path)]
    calls = 0
    fsync = cache.os.fsync

    def fail_second(fd):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("disk unavailable")
        fsync(fd)

    monkeypatch.setattr(cache.os, "fsync", fail_second)
    data["browse_root"] = {"title": "Fresh feed"}
    assert not cache.save_snapshot(host, data, searches, tokens)
    assert [path.read_bytes() for path in (host._page_cache_path, host._search_cache_path)] == previous
    assert not list(host._page_cache_path.parent.glob("*.tmp"))


def test_invalid_payload_or_missing_epoch_never_publishes(host):
    data, searches = _payloads()
    assert not cache.save_snapshot(host, data, searches, [])
    data["artists"] = data  # an unsafe snapshot assembled while caches mutate
    assert not cache.save_snapshot(host, data, searches, [host._provider_contexts.capture("tidal")])
    assert not host._page_cache_path.exists() and not host._search_cache_path.exists()
    assert not list(host._page_cache_path.parent.glob("*.tmp"))


@pytest.mark.parametrize("contents", ["{", "[]", '{"version":7,"user":"old","library":{}}'])
def test_invalid_or_legacy_mixed_snapshot_is_not_trusted(tmp_path, contents):
    path = tmp_path / "pages.json"
    path.write_text(contents, encoding="utf-8")
    assert cache.read_snapshot(path) == {}
    assert cache.read_snapshot(tmp_path / "absent.json") == {}


@pytest.mark.parametrize(
    ("provider_id", "pages", "artists", "searches"),
    [
        (
            "tidal",
            {"pl:paper:42", "item:album:apple:42", "item:album:paper:42"},
            {"apple:42", "paper:42"},
            {"apple:one", "paper:one", "legacy-query"},
        ),
        (
            "apple",
            {"root", "cat:FEATURED", "pl:42", "pl:paper:42", "item:album:paper:42"},
            {"42", "paper:42"},
            {"tidal:one", "paper:one", "tidal+paper:one", "legacy-query"},
        ),
        (
            "paper",
            {"root", "cat:FEATURED", "pl:42", "item:album:apple:42"},
            {"42", "apple:42"},
            {"tidal:one", "apple:one"},
        ),
    ],
)
def test_prune_removes_own_fields_and_mixed_searches_preserving_independent_sources(
    provider_id, pages, artists, searches
):
    data, search_data = _payloads()
    data.update(search_data)
    for pid in ("apple", "paper"):
        data["library"][f"{pid}:albums"] = {"items": [{"id": f"{pid}:42"}], "offset": 40, "more": False}
    previous = copy.deepcopy(data)

    pruned = cache.remove_provider(data, provider_id)

    assert data == previous, "pruning is pure, including nested cache containers"
    assert set(pruned["browse_pages"]) == pages
    assert set(pruned["artists"]) == artists
    assert set(pruned["searches"]) == searches
    assert set(pruned["accounts"]) == {"tidal", "apple", "paper"} - {provider_id}
    assert set(pruned["home"]) == {"tidal", "apple", "paper"} - {provider_id}
    assert set(pruned["library"]) == {f"{pid}:albums" for pid in {"tidal", "apple", "paper"} - {provider_id}}
    assert pruned["browse_root"] == (None if provider_id == "tidal" else previous["browse_root"])
    assert json.loads(json.dumps(pruned)) == pruned


def test_overlapping_provider_prunes_block_warmup_and_preserve_an_unrelated_account(host):
    from types import SimpleNamespace

    from waves.desktop.backend import WavesBridge

    class DeferredPool:
        def __init__(self):
            self.workers = []

        def start(self, worker):
            self.workers.append(worker)

    host.providers = {
        pid: SimpleNamespace(account_id=lambda account=pid: account) for pid in ("tidal", "apple", "paper")
    }
    host.threadpool = DeferredPool()
    host._cache_disk_revoked = {}
    host._browse_root_cache = None
    host._browse_pages = {}
    host._artist_cache = {}
    host._lib_cache = {}
    host._home_cache = {}
    host._search_cache = {}
    data, searches = _payloads()
    accounts = WavesBridge._cache_accounts(host)
    data["accounts"] = searches["accounts"] = accounts
    assert cache.save_snapshot(host, data, searches, [host._provider_contexts.capture(pid) for pid in host.providers])

    for pid in ("tidal", "apple"):
        host._provider_contexts.revoke(pid)
        host._cache_disk_revoked[pid] = host._provider_contexts.capture(pid)
        WavesBridge._schedule_provider_cache_clear(host, pid)
    WavesBridge._load_page_cache(host)
    WavesBridge._load_search_cache(host)
    assert host._browse_root_cache is None
    assert host._artist_cache == {"paper:42": {"name": "Paper"}}
    assert set(host._search_cache) == {"paper:one", "legacy-query"}

    host.threadpool.workers[0].fn()
    assert set(host._cache_disk_revoked) == {"tidal", "apple"}, "the earlier worker captured a revoked token"
    host.threadpool.workers[1].fn()
    assert host._cache_disk_revoked == {}
    assert cache.read_snapshot(host._page_cache_path)["accounts"] == {"paper": accounts["paper"]}
    assert cache.read_snapshot(host._page_cache_path)["artists"] == {"paper:42": {"name": "Paper"}}
    assert set(cache.read_snapshot(host._search_cache_path)["searches"]) == {"paper:one", "legacy-query"}


def test_factory_reset_during_staging_cannot_recreate_its_caches(host, monkeypatch):
    data, searches = _payloads()
    fsync = cache.os.fsync

    def reset_while_staging(fd):
        fsync(fd)
        host._factory_reset = True

    monkeypatch.setattr(cache.os, "fsync", reset_while_staging)
    assert not cache.save_snapshot(host, data, searches, [host._provider_contexts.capture("tidal")])
    assert not host._page_cache_path.exists() and not host._search_cache_path.exists()
