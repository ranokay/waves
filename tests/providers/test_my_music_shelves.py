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
from waves.waves_ui.backend import WavesBridge

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


def test_no_favourites_provider_means_no_empty_state():
    # A registry that could never fill the pane has nothing to say: no dead
    # call to action stands over shelves no provider would ever load. A
    # FAVORITES provider whose status kind is not a session cannot fill
    # shelves either (see _provider_can_fill_shelves), so it gets no state.
    from waves.providers import StatusKind

    apple = StubProvider("apple", "Apple Music", capabilities=frozenset({Capability.SEARCH}))
    assert backend._my_music_empty(stub_bridge({"apple": apple})) == {}
    assert backend._my_music_empty(stub_bridge({})) == {}
    setup_only = StubProvider(
        "fake",
        "Fake Music",
        capabilities=frozenset({Capability.FAVORITES}),
        status_kind=StatusKind.SETUP,
        logged_in=False,
    )
    assert backend._my_music_empty(stub_bridge({"fake": setup_only})) == {}


def test_the_pane_count_agrees_with_the_favourites_the_badges_read():
    """The pane's count is the count the badge path reads (issue #259, AC4).

    Search's library-scoped views and the badges ask for the user's favourites
    through the bridge's own ``_favorite_ids`` (the provider's id sweep); the
    pane pages the same set through ``_library_page``/``favorites_page``. Both
    halves are driven through the bridge over ONE provider fixture, so this
    pins the real invariant the criterion is about: two different readers of
    one favourites set agree -- the paged windows advance by the page size and
    the short-window verdict adds up to exactly the id sweep, no window
    skipped or counted twice, and both read the same provider.
    """
    albums = [f"al{i}" for i in range(7)]

    class _Provider:
        capabilities = frozenset({Capability.FAVORITES})
        is_logged_in = True

        def __init__(self):
            self.calls: list = []

        def descriptor(self):
            from waves.providers import ProviderDescriptor, StatusKind

            return ProviderDescriptor(id="tidal", name="TIDAL", status_kind=StatusKind.SESSION)

        def favorites_page(self, kind, offset, limit, order=None):
            self.calls.append(("favorites_page", offset, limit))
            # tidalapi's shape: a window can come back short (unavailable
            # items dropped inside it) while "more" comes from the total.
            window = albums[offset : offset + limit]
            return list(window), offset + limit < len(albums)

        def favorite_ids(self, kind):
            self.calls.append(("favorite_ids", kind))
            return set(albums)

        def row_for(self, kind, item):
            return {"id": item}

    provider = _Provider()
    bridge = SimpleNamespace(providers={"tidal": provider}, _lib_sort={}, _fav_ids={})

    # The badge path: what the library-scoped artist views and the badges read.
    badge_ids = WavesBridge._favorite_ids(bridge, "albums")

    # The pane's path: the same source's favourites, paged to exhaustion.
    rows: list = []
    offset, more = 0, True
    while more:
        page, more = backend.WavesBridge._library_page(bridge, "tidal", "albums", offset, 3)
        rows.extend(page)
        offset += 3

    assert [r["id"] for r in rows] == albums, "the pane's windows must cover the favourites set exactly"
    assert len(rows) == len(badge_ids), "the pane's count is the badge path's count"
    assert next(c[0] for c in provider.calls) == "favorite_ids"
    assert all(c[0] == "favorites_page" for c in provider.calls[1:]), "both readers go to the source's provider"


class _Signal:
    """Records ``emit`` calls so a test can assert what QML would have seen."""

    def __init__(self):
        self.emits: list = []

    def emit(self, *args):
        self.emits.append(args)


def test_two_sources_loading_their_shelves_in_one_turn_both_land():  # noqa: C901 (one straight harness)
    """One source's load must not cancel another's (issue #259).

    Opening My Music loads the primary source's shelf and every other source's
    in the same turn. A single global load generation meant the first load's
    worker found the counter moved and silently dropped its page: that group's
    pane stayed blank with no emit and no retry. The generations are per shelf
    page now, so both land.
    """
    rows = {"tidal": [{"id": "t1"}], "fake": [{"id": "f1"}]}

    class _Provider:
        capabilities = frozenset({Capability.FAVORITES})
        is_logged_in = True

        def __init__(self, provider_id):
            self.id = provider_id

        def descriptor(self):
            from waves.providers import ProviderDescriptor, StatusKind

            return ProviderDescriptor(id=self.id, name=self.id, status_kind=StatusKind.SESSION)

        def favorites_page(self, kind, offset, limit, order=None):
            return list(rows[self.id]), False

        def row_for(self, kind, item):
            return dict(item)

    class _HeldPool:
        def __init__(self):
            self.workers: list = []

        def start(self, worker):
            self.workers.append(worker)

    class _Bridge:
        _lib_generation = WavesBridge._lib_generation
        _lib_start = WavesBridge._lib_start
        loadLibrary = WavesBridge.loadLibrary
        _lib_status = WavesBridge._lib_status
        _lib_count = staticmethod(WavesBridge._lib_count)

        def __init__(self):
            self._logged_in = True
            self.providers = {sid: _Provider(sid) for sid in ("tidal", "fake")}
            self._lib_cache: dict = {}
            self._lib_loading: set = set()
            self._lib_sort: dict = {}
            self._lib_reval_ts: dict = {}
            self._lib_epoch = 0
            self._lib_gen: dict = {}
            self.threadpool = _HeldPool()
            self.libraryLoaded = _Signal()
            self.statuses: list = []

        def _set_busy(self, on):
            pass

        def _set_status(self, text):
            self.statuses.append(text)

        def _save_page_cache(self):
            pass

        def _library_page(self, source, category, offset, limit, order_override=None):
            # The page build itself is exercised by the seam tests; here the
            # point is the two workers both landing.
            return list(rows[source]), False

    stub = _Bridge()
    stub.loadLibrary("tidal", "albums")
    stub.loadLibrary("fake", "albums")  # the second load used to cancel the first

    # The second load's worker lands first, then the first's (the order that
    # exposed the drop).
    stub.threadpool.workers[1].run()
    stub.threadpool.workers[0].run()

    assert stub.libraryLoaded.emits == [
        ("fake", "albums", [{"id": "f1"}], False),
        ("tidal", "albums", [{"id": "t1"}], False),
    ]
    assert stub._lib_cache[("tidal", "albums")]["items"] == [{"id": "t1"}]
    assert stub._lib_cache[("fake", "albums")]["items"] == [{"id": "f1"}]


def test_the_sources_are_bridge_data_not_qml_copy():
    # The pane renders the bridge's list -- the group label, the strip's
    # categories and the empty state's words are all data -- so a provider's
    # own name reaches the UI without a QML edit.
    qml = MAIN_QML.read_text(encoding="utf-8")

    assert "Saved from" not in qml
    assert "waves.myMusicSources()" in qml
    assert "waves.myMusicEmpty()" in qml
