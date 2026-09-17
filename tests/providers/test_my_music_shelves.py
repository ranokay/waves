"""My Music's saved-shelf sources: labels, categories and the empty state.

Issue #221's source-label rule: the shelves a provider contributes are
labelled by their source only when more than one provider contributes them.
Issue #259 makes the pane render those sources generically: every source
carries its own shelf categories (capability-driven, ADR 0008), a lone source
renders exactly as it did before -- no label -- and a second provider that
declares FAVORITES contributes its own group from its descriptor and its live
session alone.

The data half of the third-provider paper test lives here: a provider that is
not TIDAL contributes a saved section from its descriptor and its live
session alone, its category strip comes from its capabilities, and the empty
state's words are bridge data, never QML copy.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from support.provider_fakes import StubProvider, stub_bridge

from waves.providers import Capability
from waves.waves_ui import backend

REPO_ROOT = Path(__file__).resolve().parents[2]
MAIN_QML = REPO_ROOT / "waves" / "waves_ui" / "qml" / "Main.qml"

# TIDAL's strip, exactly as the pane has always rendered it.
_TIDAL_CATEGORIES = ["home", "albums", "tracks", "artists", "playlists", "mixes", "videos"]


def _shelf_provider(provider_id, name, *, logged_in=True, capabilities=None):
    """A provider whose saved shelves My Music can render.

    The neutral descriptor is a session-kind one, so the readiness read is
    the provider's own ``is_logged_in`` unless the bridge tracks it.
    """
    return StubProvider(
        provider_id,
        name,
        capabilities=frozenset({Capability.FAVORITES}) if capabilities is None else capabilities,
        logged_in=logged_in,
    )


def test_a_lone_saved_shelf_source_carries_no_label():
    # One provider contributes: the pane's rows are that provider, so the
    # label stays "" and the pane renders exactly as it did (issue #221).
    sources = backend._saved_shelf_sources(stub_bridge({"tidal": _shelf_provider("tidal", "TIDAL")}))

    assert sources == [{"id": "tidal", "name": "TIDAL", "label": ""}]


def test_a_second_saved_shelf_source_qualifies_every_label():
    # The paper test: a provider that is not TIDAL contributes a second saved
    # section from its descriptor and its session alone -- the labels become
    # source-qualified together, with no QML edit.
    sources = backend._saved_shelf_sources(
        stub_bridge(
            {
                "tidal": _shelf_provider("tidal", "TIDAL"),
                "fake": _shelf_provider("fake", "Fake Music"),
            }
        )
    )

    assert [s["id"] for s in sources] == ["tidal", "fake"]
    assert [s["label"] for s in sources] == ["Saved from TIDAL", "Saved from Fake Music"]


def test_a_provider_that_cannot_fill_shelves_is_not_a_source():
    # A provider with no favourites capability and a signed-out provider
    # cannot fill saved shelves, so neither contributes a section.
    no_capability = _shelf_provider("apple", "Apple Music", capabilities=frozenset({Capability.SEARCH}))
    signed_out = _shelf_provider("tidal", "TIDAL", logged_in=False)
    assert backend._saved_shelf_sources(stub_bridge({"tidal": signed_out, "apple": no_capability})) == []

    # A tracked session answers from the bridge's flag (the one the login
    # flow and every catalog read move together), not the provider's.
    tracked = _shelf_provider("tidal", "TIDAL", logged_in=True)
    assert backend._saved_shelf_sources(stub_bridge({"tidal": tracked}, tracked=frozenset({"tidal"}))) == []
    sourced = backend._saved_shelf_sources(
        stub_bridge({"tidal": tracked}, logged_in=True, tracked=frozenset({"tidal"}))
    )
    assert [s["id"] for s in sourced] == ["tidal"]


def test_a_source_carries_the_categories_its_provider_can_fill():
    # TIDAL declares everything: the pane's seven strips, in the order it has
    # always rendered them and with the strip's own capitalisation.
    tidal = StubProvider("tidal", "TIDAL", capabilities=frozenset(Capability), logged_in=True)

    sourced = backend._my_music_sources(stub_bridge({"tidal": tidal}))

    assert [c["id"] for c in sourced[0]["categories"]] == _TIDAL_CATEGORIES
    assert [c["label"] for c in sourced[0]["categories"]][:3] == ["Home", "Albums", "Tracks"]


def test_the_categories_are_capability_driven():
    # A favourites-only source gets the favourites shelves and nothing else:
    # no empty Mixes/Videos tab (ADR 0008). A provider that later declares
    # one of these grows its strip with no QML edit.
    fake = StubProvider("fake", "Fake Music", capabilities=frozenset({Capability.FAVORITES}), logged_in=True)
    sourced = backend._my_music_sources(stub_bridge({"fake": fake}))
    assert [c["id"] for c in sourced[0]["categories"]] == ["home", "albums", "tracks", "artists"]

    videoed = StubProvider(
        "fake", "Fake Music", capabilities=frozenset({Capability.FAVORITES, Capability.VIDEOS}), logged_in=True
    )
    assert [c["id"] for c in backend._my_music_sources(stub_bridge({"fake": videoed}))[0]["categories"]] == [
        "home",
        "albums",
        "tracks",
        "artists",
        "videos",
    ]

    # A provider with no FAVORITES is not a source at all: no shelves exist
    # for it to fill.
    browsing = StubProvider("fake", "Fake Music", capabilities=frozenset({Capability.BROWSE}), logged_in=True)
    assert backend._my_music_sources(stub_bridge({"fake": browsing})) == []


def test_a_third_provider_adds_its_own_group_with_no_surface_edit():
    # The paper test at the data half: the sources list grows a group whose
    # identity, label and categories all come from the fake provider's
    # descriptor and capabilities.
    tidal = StubProvider("tidal", "TIDAL", capabilities=frozenset(Capability), logged_in=True)
    fake = StubProvider("fake", "Fake Music", capabilities=frozenset({Capability.FAVORITES}), logged_in=True)

    sourced = backend._my_music_sources(stub_bridge({"tidal": tidal, "fake": fake}))

    assert [s["id"] for s in sourced] == ["tidal", "fake"]
    assert [s["label"] for s in sourced] == ["Saved from TIDAL", "Saved from Fake Music"]
    assert [c["id"] for c in sourced[1]["categories"]] == ["home", "albums", "tracks", "artists"]


def test_the_signed_out_empty_state_names_the_provider_that_could_fill_it():
    # The #220 state, now bridge data: TIDAL's own words, its own sign-in
    # action, and the detail line listing exactly the shelves it would fill.
    tidal = StubProvider("tidal", "TIDAL", capabilities=frozenset(Capability), logged_in=False)

    empty = backend._my_music_empty(stub_bridge({"tidal": tidal}))

    assert empty["provider"] == "tidal" and empty["action"] == "signin"
    assert empty["message"] == "My Music is your TIDAL library"
    assert empty["detail"] == "Sign in to see your albums, tracks, artists, playlists, mixes and videos."
    assert empty["action_label"] == "Sign in to TIDAL"


def test_the_empty_state_follows_the_provider_and_its_categories():
    # A second provider's state is its own: the message names it, the action
    # is its session verb, and the shelves in the sentence are the ones its
    # capabilities declare.
    fake = StubProvider(
        "fake", "Fake Music", capabilities=frozenset({Capability.FAVORITES, Capability.VIDEOS}), logged_in=False
    )

    empty = backend._my_music_empty(stub_bridge({"fake": fake}))

    assert empty["message"] == "My Music is your Fake Music library"
    assert empty["action_label"] == "Sign in to Fake Music"
    assert empty["detail"] == "Sign in to see your albums, tracks, artists and videos."


def test_a_signed_in_source_leaves_no_empty_state():
    tidal = _shelf_provider("tidal", "TIDAL", logged_in=True)

    assert backend._my_music_empty(stub_bridge({"tidal": tidal})) == {}


def test_a_setup_provider_that_could_fill_shelves_offers_its_setup_action():
    # Nothing here signs in (a setup-kind provider's path is its own wizard),
    # so the click the state offers is that provider's own setup verb.
    from waves.providers import StatusKind

    fake = StubProvider(
        "fake",
        "Fake Music",
        capabilities=frozenset({Capability.FAVORITES}),
        status_kind=StatusKind.SETUP,
        logged_in=False,
    )

    empty = backend._my_music_empty(stub_bridge({"fake": fake}))

    assert empty["provider"] == "fake" and empty["action"] == "setup"
    assert empty["action_label"] == "Set up Fake Music"


def test_no_favourites_provider_means_no_empty_state():
    # A registry that could never fill the pane has nothing to say: no dead
    # call to action stands over shelves no provider would ever load.
    apple = StubProvider("apple", "Apple Music", capabilities=frozenset({Capability.SEARCH}))
    assert backend._my_music_empty(stub_bridge({"apple": apple})) == {}
    assert backend._my_music_empty(stub_bridge({})) == {}


def test_the_pane_count_agrees_with_the_favourites_the_badges_read():
    """The pane's rows ARE the favourites set the badge path reads.

    Search's library-scoped views and badges ask for the user's favourites
    through ``Provider.favorite_ids``; the pane pages the same set through
    ``favorites_page``. Paging the pane to exhaustion must accumulate exactly
    that set -- no window skipped, none counted twice -- so a row the badge
    marks is a row the pane shows and the status count is its size.
    """
    albums = [f"al{i}" for i in range(7)]

    class _Provider:
        capabilities = frozenset({Capability.FAVORITES})
        is_logged_in = True

        def descriptor(self):
            from waves.providers import ProviderDescriptor, StatusKind

            return ProviderDescriptor(id="fake", name="Fake Music", status_kind=StatusKind.SESSION)

        def favorites_page(self, kind, offset, limit, order=None):
            window = albums[offset : offset + limit]
            return list(window), offset + limit < len(albums)

        def favorite_ids(self, kind):
            return set(albums)

        def row_for(self, kind, item):
            return {"id": item}

    provider = _Provider()
    bridge = SimpleNamespace(providers={"fake": provider}, _lib_sort={})
    rows: list = []
    offset, more = 0, True
    while more:
        page, more = backend.WavesBridge._library_page(bridge, "fake", "albums", offset, 3)
        rows.extend(page)
        offset += 3

    assert [r["id"] for r in rows] == albums, "the pane's windows must cover the favourites set exactly"
    assert len(rows) == len(_Provider().favorite_ids("albums")), "the pane's count is the badge's count"


def test_the_sources_are_bridge_data_not_qml_copy():
    # The pane renders the bridge's list -- the group label, the strip's
    # categories and the empty state's words are all data -- so a provider's
    # own name reaches the UI without a QML edit.
    qml = MAIN_QML.read_text(encoding="utf-8")

    assert "Saved from" not in qml
    assert "waves.myMusicSources()" in qml
    assert "waves.myMusicEmpty()" in qml
