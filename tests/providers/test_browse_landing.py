"""The provider Browse landing contract (issue #600).

The combined Browse landing is composed from provider-owned recipes: a
provider names its own pages and chip groups, the bridge fetches/renders
them, and the neutral default contributes nothing. TIDAL's recipe is its
current editorial composition kept behind the seam: Explore names the chip
groups and the New/Top quick links, those pages inline, For You follows,
and the personalized home feed lands last.
"""

from __future__ import annotations

from types import SimpleNamespace

from providers.fakes import BareProvider, StubProvider

from waves.providers.tidal import TidalProvider


def _page_links(title: str, links: list[tuple[str, str]]) -> object:
    from tidalapi.page import PageLinks

    cat = PageLinks.__new__(PageLinks)
    cat.title = title
    cat.items = [SimpleNamespace(title=t, api_path=p) for t, p in links]
    return cat


def _explore(*links: tuple[str, str], **groups: list[tuple[str, str]]) -> SimpleNamespace:
    cats = [_page_links(name, links) for name, links in groups.items()]
    return SimpleNamespace(categories=cats)


def _tidal_with_explore(explore) -> TidalProvider:
    provider = TidalProvider.__new__(TidalProvider)
    provider._tidal = SimpleNamespace()
    seen: list[tuple[str, str]] = []

    def browse_page(title: str, api_path: str):
        seen.append((title, api_path))
        assert api_path == "pages/explore", api_path
        return explore

    provider.browse_page = browse_page  # type: ignore[method-assign]
    provider.seen_explore = seen  # type: ignore[attr-defined]
    return provider


def test_the_neutral_default_contributes_no_landing() -> None:
    assert BareProvider().browse_landing() == {}
    assert StubProvider("x", "X").browse_landing() == {}


def test_tidal_landing_names_chips_pages_and_home() -> None:
    explore = _explore(
        Genres=[("Pop", "pages/genres/pop"), ("Rock", "pages/genres/rock")],
        **{"Moods & Activities": [("Chill", "pages/moods/chill")], "Decades": []},
        **{"": [("New", "pages/new"), ("Top", "pages/top")]},
    )
    provider = _tidal_with_explore(explore)
    landing = provider.browse_landing()
    assert provider.seen_explore == [("Explore", "pages/explore")]
    assert landing["chips"]["genres"] == [
        {"title": "Pop", "path": "pages/genres/pop"},
        {"title": "Rock", "path": "pages/genres/rock"},
    ]
    assert landing["chips"]["moods"] == [{"title": "Chill", "path": "pages/moods/chill"}]
    assert landing["chips"]["decades"] == []
    assert landing["pages"] == [
        {"title": "New", "path": "pages/new"},
        {"title": "Top", "path": "pages/top"},
        {"title": "For You", "path": "pages/for_you"},
    ]
    assert landing["home"] is True


def test_tidal_landing_ships_for_you_when_the_quick_links_are_missing() -> None:
    provider = _tidal_with_explore(_explore(Genres=[("Pop", "pages/genres/pop")]))
    landing = provider.browse_landing()
    assert landing["pages"] == [{"title": "For You", "path": "pages/for_you"}]
    assert landing["chips"]["genres"] == [{"title": "Pop", "path": "pages/genres/pop"}]


def _artist(aid: str, name: str = "") -> object:
    import tidalapi

    obj = tidalapi.Artist.__new__(tidalapi.Artist)
    obj.id = aid
    obj.name = name or aid
    obj.image = lambda dimension=320: f"https://img/{aid}/{dimension}"
    return obj


def _track(tid: str, album) -> object:
    import tidalapi

    obj = tidalapi.Track.__new__(tidalapi.Track)
    obj.id = tid
    obj.album = album
    obj.image = lambda dimension=320: f"https://img/{tid}/{dimension}"
    return obj


def test_tidal_link_art_sample_round_robins_distinct_covers() -> None:
    # One cover per identity, one per row per pass: an artist portrait leads
    # its row over a track's copy of the same art, and the second row's
    # portrait joins before the repeat pass.
    a1 = _artist("ar1")
    page = SimpleNamespace(
        categories=[
            SimpleNamespace(items=[a1, _track("t1", a1)]),
            SimpleNamespace(items=[_artist("ar2")]),
        ]
    )
    provider = TidalProvider.__new__(TidalProvider)
    assert provider.link_art_sample(page, want=3) == [
        "https://img/ar1/320",
        "https://img/ar2/320",
        "https://img/t1/320",
    ]


def test_tidal_link_art_sample_has_nothing_for_a_page_without_covers() -> None:
    provider = TidalProvider.__new__(TidalProvider)
    assert provider.link_art_sample(SimpleNamespace(categories=[])) == []


def test_a_failed_explore_read_fails_the_whole_recipe() -> None:
    provider = TidalProvider.__new__(TidalProvider)
    provider._tidal = SimpleNamespace()

    def browse_page(title: str, api_path: str):
        raise RuntimeError("explore is down")

    provider.browse_page = browse_page  # type: ignore[method-assign]
    try:
        provider.browse_landing()
    except RuntimeError:
        return
    raise AssertionError("a failed Explore read must fail TIDAL's contribution")
