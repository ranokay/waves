"""The combined Browse landing: provider-owned sections, one surface (#600).

The landing is assembled from every ready browse provider's own recipe:
sections keep registry order, each row and chip link carries its owner so
every drill-down routes back to the provider that served it, a provider
whose reads fail loses only its own rows, and a provider that declares no
Browse (or is signed out) contributes nothing at all.
"""

from __future__ import annotations

from types import SimpleNamespace

from browse.fakes import LandingProvider

from waves.desktop.backend import WavesBridge
from waves.providers.base import Capability


def _page(rows):
    return SimpleNamespace(rows=rows)


def _card(kind: str, cid: str) -> dict:
    return {"kind": kind, "id": cid}


def _row(title: str, ids, kind: str = "cards", **extra) -> dict:
    return {
        "rowKind": kind,
        "title": title,
        "items": [_card("track" if kind == "tracks" else "album", i) for i in ids],
        "more": "",
        **extra,
    }


def _bridge(providers) -> WavesBridge:
    b = WavesBridge.__new__(WavesBridge)
    b.providers = dict(providers)
    b._tracked_sessions = set()
    b._provider_readiness_probes = {}
    return b


def test_the_combined_landing_keeps_registry_order_and_stamps_owners() -> None:
    tidal = LandingProvider(
        "tidal",
        "TIDAL",
        landing={
            "chips": {"genres": [{"title": "Pop", "path": "pages/genres/pop"}], "moods": [], "decades": []},
            "pages": [{"title": "For You", "path": "pages/for_you"}],
            "home": False,
        },
        pages={"pages/for_you": _page([_row("Fresh for you", "a1")])},
    )
    stub = LandingProvider(
        "stub",
        "Stub",
        landing={"pages": [{"title": "Stub shelf", "path": "pages/stub"}], "home": False},
        pages={"pages/stub": _page([_row("Stub picks", "s1")])},
    )
    payload = _bridge({"tidal": tidal, "stub": stub})._browse_root()
    assert payload["error"] is False
    assert [s["title"] for s in payload["sections"]] == ["Fresh for you", "Stub picks"]
    assert [s["provider_id"] for s in payload["sections"]] == ["tidal", "stub"]
    assert payload["genres"] == [{"title": "Pop", "path": "pages/genres/pop", "provider_id": "tidal"}]
    assert payload["moods"] == [] and payload["decades"] == []
    assert payload["sources"] == [
        {"provider_id": "tidal", "name": "TIDAL"},
        {"provider_id": "stub", "name": "Stub"},
    ]


def test_one_provider_failing_loses_only_its_own_rows() -> None:
    broken = LandingProvider("broken", "Broken", landing=RuntimeError("landing is down"))
    stub = LandingProvider(
        "stub",
        "Stub",
        landing={"pages": [{"title": "Stub shelf", "path": "pages/stub"}], "home": False},
        pages={"pages/stub": _page([_row("Stub picks", "s1")])},
    )
    payload = _bridge({"broken": broken, "stub": stub})._browse_root()
    assert payload["error"] is False
    assert [s["provider_id"] for s in payload["sections"]] == ["stub"]
    assert [s["provider_id"] for s in payload["sources"]] == ["stub"]


def test_a_failing_page_inside_a_working_landing_keeps_the_other_pages() -> None:
    tidal = LandingProvider(
        "tidal",
        "TIDAL",
        landing={
            "pages": [
                {"title": "Dead", "path": "pages/dead"},
                {"title": "Alive", "path": "pages/alive"},
            ],
            "home": False,
        },
        pages={"pages/dead": RuntimeError("page is down"), "pages/alive": _page([_row("Alive shelf", "a1")])},
    )
    payload = _bridge({"tidal": tidal})._browse_root()
    assert payload["error"] is False
    assert [s["title"] for s in payload["sections"]] == ["Alive shelf"]


def test_a_recipe_whose_every_declared_read_failed_is_a_failed_landing() -> None:
    # The recipe ran, but every page it declared raised: the provider
    # contributed nothing and must not count as a success that hides the
    # failure behind an empty, error-free landing.
    stub = LandingProvider(
        "stub",
        "Stub",
        landing={"pages": [{"title": "Dead", "path": "pages/dead"}], "home": False},
        pages={"pages/dead": RuntimeError("page is down")},
    )
    payload = _bridge({"stub": stub})._browse_root()
    assert payload["error"] is True
    assert payload["sections"] == []


def test_the_landing_is_an_error_only_when_every_attempted_provider_failed() -> None:
    a = LandingProvider("a", "A", landing=RuntimeError("a is down"))
    b = LandingProvider("b", "B", landing=RuntimeError("b is down"))
    payload = _bridge({"a": a, "b": b})._browse_root()
    assert payload["error"] is True
    assert payload["sections"] == []
    assert payload["sources"] == []


def test_incapable_and_signed_out_providers_contribute_nothing() -> None:
    no_browse = LandingProvider(
        "catalog_only",
        "Catalog only",
        landing={"pages": [{"title": "X", "path": "pages/x"}], "home": False},
        pages={"pages/x": _page([_row("X shelf", "x1")])},
        capabilities=frozenset({Capability.CATALOG}),
    )
    signed_out = LandingProvider(
        "signed_out",
        "Signed out",
        landing={"pages": [{"title": "Y", "path": "pages/y"}], "home": False},
        pages={"pages/y": _page([_row("Y shelf", "y1")])},
        logged_in=False,
    )
    payload = _bridge({"catalog_only": no_browse, "signed_out": signed_out})._browse_root()
    assert payload["sections"] == []
    assert payload["sources"] == []
    # Nothing was attempted: an empty landing is not an error (the pane's
    # sign-in CTA owns that state).
    assert payload["error"] is False


def test_home_rows_land_last_deduped_by_title_and_stripped_of_paging() -> None:
    tidal = LandingProvider(
        "tidal",
        "TIDAL",
        landing={"pages": [{"title": "Essentials to explore", "path": "pages/for_you"}], "home": True},
        pages={"pages/for_you": _page([_row("Essentials to explore", "p1")])},
        home=_page(
            [
                _row("essentials to EXPLORE", "p2"),
                _row("Popular playlists", "p3", data="pages/data/9", total=40, offset=12, modType="PLAYLIST_LIST"),
            ]
        ),
    )
    payload = _bridge({"tidal": tidal})._browse_root()
    titles = [s["title"] for s in payload["sections"]]
    assert titles == ["Essentials to explore", "Popular playlists"]
    home_row = payload["sections"][1]
    assert home_row["more"] == ""
    for key in ("data", "total", "offset", "modType"):
        assert key not in home_row


def test_recipe_page_paths_validate_like_drill_downs() -> None:
    # A recipe path may never steer a request off the provider's own API:
    # the landing fetch goes through the same path validation as a click.
    stub = LandingProvider(
        "stub",
        "Stub",
        landing={
            "pages": [
                {"title": "Evil", "path": "https://evil.test/pages/x"},
                {"title": "Fine", "path": "pages/fine"},
            ],
            "home": False,
        },
        pages={
            "https://evil.test/pages/x": _page([_row("Evil shelf", "e1")]),
            "pages/fine": _page([_row("Fine shelf", "f1")]),
        },
    )
    payload = _bridge({"stub": stub})._browse_root()
    assert [s["title"] for s in payload["sections"]] == ["Fine shelf"]
    assert ("browse_page", "Evil", "https://evil.test/pages/x") not in stub.calls


def test_containment_dedupe_stays_within_one_providers_rows() -> None:
    big = [f"a{n}" for n in range(25)]
    tidal = LandingProvider(
        "tidal",
        "TIDAL",
        landing={"pages": [{"title": "Tidal", "path": "pages/t"}], "home": False},
        pages={
            "pages/t": _page(
                [
                    _row("New releases for you", big, data="path/x", total=40, offset=25, modType="ALBUM_LIST"),
                    _row("Suggested new albums", big[5:15]),
                ]
            )
        },
    )
    # The stub's row holds items the TIDAL row also carries; a global dedupe
    # would drop the second provider's shelf, per-provider keeps it.
    stub = LandingProvider(
        "stub",
        "Stub",
        landing={"pages": [{"title": "Stub", "path": "pages/s"}], "home": False},
        pages={"pages/s": _page([_row("Stub picks", big)])},
    )
    payload = _bridge({"tidal": tidal, "stub": stub})._browse_root()
    assert [s["title"] for s in payload["sections"]] == ["New releases for you", "Stub picks"]
    assert [s["provider_id"] for s in payload["sections"]] == ["tidal", "stub"]
