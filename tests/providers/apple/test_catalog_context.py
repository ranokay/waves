"""Old Apple catalog workers can return rows without repopulating a new cache."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from contextlib import nullcontext
from threading import Event, Lock, Thread

import pytest

from waves.providers.apple import AppleProvider


def _resource(kind: str, raw_id: str, name: str) -> dict:
    return {
        "id": raw_id,
        "type": {"artist": "artists", "album": "albums", "track": "songs", "playlist": "playlists"}[kind],
        "attributes": {"name": name, "artistName": "Fixture artist"},
        "relationships": {"tracks": {"data": []}},
    }


class _Catalog:
    """SDK boundary double whose old response can finish after a new response."""

    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()
        self.lock = Lock()
        self.block_kind = ""
        self.calls: list[tuple[str, str]] = []
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1

    def _fetch(self, kind: str, raw_id: str) -> dict:
        with self.lock:
            self.calls.append((kind, raw_id))
            block = kind == self.block_kind and len(self.calls) == 1
        if block:
            self.started.set()
            assert self.release.wait(5), "test must release the old SDK response"
        return {"data": [_resource(kind, raw_id, "Old" if block else "Current")]}

    async def get_album(self, raw_id: str) -> dict:
        return self._fetch("album", raw_id)

    async def get_artist(self, raw_id: str) -> dict:
        return self._fetch("artist", raw_id)

    async def get_playlist(self, raw_id: str) -> dict:
        return self._fetch("playlist", raw_id)

    async def get_song(self, raw_id: str) -> dict:
        return self._fetch("track", raw_id)

    async def get_search_results(self, term: str, types: str) -> dict:
        if term == "old":
            self.started.set()
            assert self.release.wait(5), "test must release the old search response"
        return {
            "results": {
                bucket: {"data": [_resource(kind, "same", term)]}
                for kind, bucket in (
                    ("artist", "artists"),
                    ("album", "albums"),
                    ("track", "songs"),
                    ("playlist", "playlists"),
                )
            }
        }


class _ConcurrentProvider(AppleProvider):
    def _run(self, awaitable: Coroutine[None, None, dict]) -> dict:
        # Isolate the SDK request boundary from the production shared-loop
        # serialization so the old/new completion order is deterministic.
        return asyncio.run(awaitable)


def _start(work: Callable[[], None]) -> tuple[Thread, list[BaseException]]:
    errors: list[BaseException] = []

    def run() -> None:
        try:
            work()
        except BaseException as exc:
            errors.append(exc)

    worker = Thread(target=run)
    worker.start()
    return worker, errors


def _finish(worker: Thread, errors: list[BaseException], release: Event) -> None:
    release.set()
    worker.join(5)
    assert not worker.is_alive()
    assert errors == []


def test_blocked_search_cannot_replace_new_objects_or_remove_complete_markers():
    catalog = _Catalog()
    provider = _ConcurrentProvider(catalog=catalog)
    results: list[dict] = []
    worker, errors = _start(lambda: results.append(provider.search("old")))
    current: dict[str, dict] = {}
    try:
        assert catalog.started.wait(5)
        provider.invalidate_catalog_context()
        for kind in ("artist", "album", "track", "playlist"):
            current[kind] = provider.get_object(kind, "same")
    finally:
        _finish(worker, errors, catalog.release)
    assert results[0]["albums"][0]["title"] == "old"
    for kind, item in current.items():
        assert provider.cached(kind, "same") is item
        assert (kind, "same") in provider._complete
    calls = list(catalog.calls)
    assert provider.get_object("album", "same") is current["album"]
    assert catalog.calls == calls


@pytest.mark.parametrize("kind", ["artist", "album", "track", "playlist"])
@pytest.mark.parametrize("dispatch_scope", [False, True])
def test_blocked_get_object_cannot_replace_new_same_id_completion(kind, dispatch_scope):
    catalog = _Catalog()
    catalog.block_kind = kind
    provider = _ConcurrentProvider(catalog=catalog)
    old_results: list[dict] = []
    context = provider.catalog_context() if dispatch_scope else nullcontext()

    def old_work() -> None:
        with context:
            old = provider.get_object(kind, "same")
            old_results.append(old)
            if dispatch_scope:
                provider.row_for(kind, old)

    worker, errors = _start(old_work)
    try:
        assert catalog.started.wait(5)
        provider.invalidate_catalog_context()
        current = provider.get_object(kind, "same")
    finally:
        _finish(worker, errors, catalog.release)
    assert old_results[0]["attributes"]["name"] == "Old"
    assert current["attributes"]["name"] == "Current"
    assert provider.cached(kind, "apple:same") is current
    assert (kind, "same") in provider._complete
    assert provider.get_object(kind, "same") is current
    assert len(catalog.calls) == 2


def test_context_captures_at_dispatch_before_worker_enters_and_restores_thread_state():
    catalog = _Catalog()
    provider = _ConcurrentProvider(catalog=catalog)
    old_context = provider.catalog_context()
    provider.invalidate_catalog_context()
    results: list[dict] = []

    def delayed_work() -> None:
        with old_context:
            stale = provider.get_object("album", "stale-only")
            results.append(provider.row_for("album", stale))
        provider.row_for("album", _resource("album", "fresh", "Fresh"))

    worker, errors = _start(delayed_work)
    worker.join(5)
    assert not worker.is_alive()
    assert errors == []
    assert results[0]["title"] == "Current"
    assert provider.cached("album", "stale-only") is None
    assert ("album", "stale-only") not in provider._complete
    assert provider.cached("album", "fresh")["attributes"]["name"] == "Fresh"


def test_nested_context_preserves_outer_epoch_and_exception_restores_it():
    provider = AppleProvider(catalog=_Catalog())
    old_context = provider.catalog_context()
    provider.invalidate_catalog_context()
    newer_context = provider.catalog_context()
    current = _resource("album", "same", "Current")
    provider.row_for("album", current)
    with pytest.raises(RuntimeError), old_context, newer_context:
        provider.row_for("album", _resource("album", "same", "Old"))
        raise RuntimeError("fixture operation failed")
    assert provider.cached("album", "same") is current
    provider.row_for("album", _resource("album", "after", "After"))
    assert provider.cached("album", "after") is not None


def test_collection_self_scope_keeps_later_refetches_in_original_epoch():
    catalog = _Catalog()
    catalog.block_kind = "track"
    provider = _ConcurrentProvider(catalog=catalog)
    collection = _resource("album", "collection", "Collection")
    collection["relationships"]["tracks"]["data"] = [{"id": "same"}, {"id": "later"}]
    results: list[list[dict]] = []
    worker, errors = _start(lambda: results.append(provider.collection_items(collection)))
    try:
        assert catalog.started.wait(5)
        provider.invalidate_catalog_context()
        current = provider.get_object("track", "same")
    finally:
        _finish(worker, errors, catalog.release)
    assert [row["id"] for row in results[0]] == ["apple:same", "apple:later"]
    assert provider.cached("track", "same") is current
    assert provider.cached("track", "later") is None
    assert ("track", "same") in provider._complete
    assert ("track", "later") not in provider._complete


def test_artist_page_self_scope_keeps_all_rows_in_original_epoch(monkeypatch):
    provider = _ConcurrentProvider(catalog=_Catalog())
    artist = _resource("artist", "artist", "Artist")
    artist["relationships"]["albums"] = {
        "data": [_resource("album", "same", "Old"), _resource("album", "later", "Later")]
    }
    started, release = Event(), Event()
    album_row = provider._album_row

    def blocked_row(item: dict, artist_ids: dict[str, str]) -> dict:
        if item["id"] == "same":
            started.set()
            assert release.wait(5), "test must release the old page builder"
        return album_row(item, artist_ids)

    monkeypatch.setattr(provider, "_album_row", blocked_row)
    results: list[dict] = []
    worker, errors = _start(lambda: results.append(provider.artist_page(artist)))
    try:
        assert started.wait(5)
        provider.invalidate_catalog_context()
        current = provider.get_object("album", "same")
    finally:
        _finish(worker, errors, release)
    assert [row["title"] for row in results[0]["albums"]] == ["Old", "Later"]
    assert provider.cached("album", "same") is current
    assert ("album", "same") in provider._complete
    assert provider.cached("album", "later") is None


def test_collection_rows_returns_existing_complete_rows_without_second_translation():
    provider = AppleProvider(catalog=_Catalog())
    collection = _resource("album", "collection", "Collection")
    collection["relationships"]["tracks"]["data"] = [_resource("track", "song", "Song")]
    rows = provider.collection_rows(collection, include_videos=False)
    assert rows == provider.collection_items(collection, include_videos=False)
    assert rows[0]["title"] == "Song"
    assert rows[0]["id"] == "apple:song"
    assert "attributes" not in rows[0]
    assert set(collection) == {"id", "type", "attributes", "relationships"}
    assert set(collection["relationships"]["tracks"]["data"][0]) == {"id", "type", "attributes", "relationships"}


def test_invalidation_leaves_shared_catalog_loop_fetch_and_public_setup_fields_intact():
    catalog = _Catalog()
    provider = AppleProvider(catalog=catalog)
    loop = asyncio.new_event_loop()
    provider._loop = loop
    provider.cookies_path = "fixture-cookies"
    provider.nm3u8dlre_path = "fixture-downloader"
    provider.ffmpeg_path = "fixture-ffmpeg"
    provider.wrapper_url = "http://127.0.0.1:49153"
    provider.wrapper_logged_in = True
    provider._fetch_scoped = True
    fetch_stack = _Catalog()
    provider._fetch_stack = fetch_stack
    provider._staged["fixture-path"] = fetch_stack
    provider.row_for("album", _resource("album", "same", "Cached"))
    try:
        provider.invalidate_catalog_context()
        assert provider._objects == {"artist": {}, "album": {}, "track": {}, "playlist": {}}
        assert provider._complete == set()
        assert provider._catalog is catalog
        assert catalog.close_calls == 0
        assert provider._loop is loop
        assert not loop.is_closed()
        assert provider._fetch_scoped is True
        assert provider._fetch_stack is fetch_stack
        assert provider._staged["fixture-path"] is fetch_stack
        assert fetch_stack.close_calls == 0
        assert provider.cookies_path == "fixture-cookies"
        assert provider.nm3u8dlre_path == "fixture-downloader"
        assert provider.ffmpeg_path == "fixture-ffmpeg"
        assert provider.wrapper_url == "http://127.0.0.1:49153"
        assert provider.wrapper_logged_in is True
    finally:
        loop.close()
