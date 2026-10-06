"""Providers paint as they answer: partial pages, own failure words, one cache write.

The search worker publishes one event per provider as its fetch completes.
The GUI folds the arrived groups into the unified display payload, keeps a
stale page's rows until a provider's fresh answer replaces them, and writes
the short-lived cache once, at settle, from the fresh groups only.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

from search.fakes import SearchStub, search_payloads

from waves.providers import Capability

_STALE = float("-inf")


def _track_row(row_id: str, **overrides) -> dict:
    row = {
        "id": row_id,
        "title": "Northern Grain",
        "artist": "Midnight Choir",
        "artist_id": "",
        "artists": [],
        "album": "Northern Grain",
        "album_id": "",
        "num": 1,
        "vol": 1,
        "art": "",
        "year": "2024",
        "date": "2024-01-01",
        "duration": "3:48",
        "duration_sec": 228,
        "quality": "LOSSLESS",
        "popularity": -1,
        "explicit": False,
        "added": "",
        "isrc": "USRC17607839",
    }
    row.update(overrides)
    return row


def _provider(name: str, search) -> SimpleNamespace:
    return SimpleNamespace(name=name, capabilities=frozenset({Capability.SEARCH}), search=search)


def _stub(providers: dict) -> SearchStub:
    stub = SearchStub()
    stub.providers = dict(providers)
    stub._provider_search_gates = {pid: (lambda: True) for pid in providers}
    return stub


def _group(provider: str, **buckets) -> dict:
    group = {"provider": provider}
    group.update(buckets)
    return group


def _tidal_group(albums=(), **buckets) -> dict:
    """A TIDAL group shaped like ``_search_group`` builds it: every declared
    bucket present, the pin and error keys included."""
    group = {
        "provider": "tidal",
        "artists": [],
        "albums": list(albums),
        "tracks": [],
        "videos": [],
        "playlists": [],
        "mixes": [],
        "top": None,
        "error": "",
    }
    group.update(buckets)
    return group


def _wait_for(condition, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.005)
    return condition()


def test_each_provider_paints_as_its_fetch_completes() -> None:
    stub = _stub(
        {
            "tidal": _provider("TIDAL", lambda needle: {"artists": [], "albums": [SimpleNamespace(id="al1")]}),
            "apple": _provider(
                "Apple Music",
                lambda needle: (
                    _wait_for(lambda: len(stub.searchResults.emits) >= 1),
                    {"artists": [], "albums": []},
                )[1],
            ),
        }
    )
    stub.search("one")

    emits = search_payloads(stub)
    assert len(emits) == 2
    first, second = emits
    assert "refresh" not in first
    assert [(s["provider"], s["state"]) for s in first["sources"]] == [("tidal", "ready"), ("apple", "loading")]
    assert [a["id"] for a in first["sections"]["albums"]] == ["al1"]
    assert second["refresh"] is True
    assert [(s["provider"], s["state"]) for s in second["sources"]] == [("tidal", "ready"), ("apple", "ready")]
    assert [a["id"] for a in second["sections"]["albums"]] == ["al1"]
    assert stub.busy == [True, False]
    assert stub.statuses[-1] == "1 results"
    # The cache holds provider groups (the storage shape), not the display payload.
    cached = stub._search_cache["tidal+apple:one"][1]
    assert [g["provider"] for g in cached["groups"]] == ["tidal", "apple"]
    assert "sections" not in cached and "sources" not in cached


def test_a_folded_equivalent_counts_once_and_exposes_both_sources() -> None:
    stub = _stub(
        {
            "tidal": _provider("TIDAL", lambda needle: {"tracks": [SimpleNamespace(id="t1")]}),
            "apple": _provider("Apple Music", lambda needle: {"tracks": [_track_row("apple:a1")]}),
        }
    )
    stub._track_dict = lambda track: _track_row(f"tidal:{track.id}")
    stub.search("one")

    last = search_payloads(stub)[-1]
    assert [row["id"] for row in last["sections"]["tracks"]] == ["tidal:t1"]
    assert last["sections"]["tracks"][0]["sources"] == [
        {"provider": "tidal", "id": "tidal:t1"},
        {"provider": "apple", "id": "apple:a1"},
    ]
    assert stub.statuses[-1] == "1 results"


def test_a_failed_source_keeps_healthy_rows_and_names_itself() -> None:
    def broken(needle):
        raise ValueError("catalog offline")

    stub = _stub(
        {
            "tidal": _provider("TIDAL", lambda needle: {"artists": [], "albums": [SimpleNamespace(id="al1")]}),
            "apple": _provider("Apple Music", broken),
        }
    )
    stub.search("one")

    last = search_payloads(stub)[-1]
    tidal, apple = last["sources"]
    assert (tidal["provider"], tidal["state"], tidal["error"]) == ("tidal", "ready", "")
    assert apple["state"] == "failed" and apple["error"] != ""
    assert [a["id"] for a in last["sections"]["albums"]] == ["al1"]
    assert stub.statuses[-1] == apple["error"]
    assert stub._search_cache == {}, "a failed source never enters the short cache"


def test_a_failed_source_on_a_stale_page_keeps_the_rows_it_had() -> None:
    stale = {"groups": [_tidal_group(albums=[{"id": "al1"}])]}
    stub = _stub({"tidal": _provider("TIDAL", lambda needle: (_ for _ in ()).throw(ValueError("offline")))})
    stub._search_cache["tidal:one"] = (_STALE, stale)
    stub.search("one")

    last = search_payloads(stub)[-1]
    assert [a["id"] for a in last["sections"]["albums"]] == ["al1"], "an empty or failed answer never blanks rows"
    assert last["sources"][0]["state"] == "failed" and last["sources"][0]["error"] != ""
    assert stub._search_cache["tidal:one"] == (_STALE, stale)


def test_a_confirmed_stale_page_is_left_alone_while_sources_refresh() -> None:
    fresh = {"groups": [_tidal_group(albums=[{"id": "al1"}])]}
    stub = _stub({"tidal": _provider("TIDAL", lambda needle: {"artists": [], "albums": [SimpleNamespace(id="al1")]})})
    stub._search_cache["tidal:one"] = (_STALE, fresh)
    stub.search("one")

    assert len(search_payloads(stub)) == 1, "the stale paint, nothing rebuilt"
    assert stub.statuses[-1] == "1 results"
    assert stub._search_cache["tidal:one"][0] > _STALE, "the window is fresh again"


def test_dropping_a_source_refolds_the_displayed_page() -> None:
    stub = _stub(
        {
            "tidal": _provider("TIDAL", lambda needle: {"artists": [], "albums": [SimpleNamespace(id="al1")]}),
            "apple": _provider("Apple Music", lambda needle: {"artists": [], "albums": [SimpleNamespace(id="al2")]}),
        }
    )
    stub.search("one")
    assert len(search_payloads(stub)) == 2

    stub.dropSearchSource("apple")
    last = search_payloads(stub)[-1]
    assert last["refresh"] is True
    assert [s["provider"] for s in last["sources"]] == ["tidal"]
    assert [a["id"] for a in last["sections"]["albums"]] == ["al1"]
