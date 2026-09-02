"""The Provider seam's TIDAL side, pinned to the old paths it delegates to.

Ticket #19 (expand half of the seam's expand-contract): ``waves/providers/``
exists, nothing is routed yet, and the app behaves exactly as before. These
tests are the anti-drift mechanism for the period where a fact exists in two
places (the provider's translation and the backend mirror it must not drift
from): each one pins the provider's answer to an independent source of truth --
the helper call shapes, the backend's tier-word / ceiling / delivered-quality /
image normalizers, the engine's refusal decision, and the ownership store's
rank scale.
"""

from __future__ import annotations

import types
from threading import Lock
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from tidalapi import Track
from tidalapi.media import AudioMode, MediaMetadataTags, Quality
from tidalapi.mix import Mix
from tidalapi.session import Session

from waves.constants import MediaType
from waves.ownership import QUALITY_RANK
from waves.providers import (
    AudioType,
    Capability,
    Provider,
    QualityTier,
    StreamInfo,
    TidalProvider,
    quality_rank,
    tier_from_tidal,
)


class _FakeTidal:
    """The config-layer Tidal the provider wraps, with the real quality body.

    ``settings_apply`` is the real config.py body bound onto the stand-in, so a
    quality application is asserted against what the engine would actually
    write, not against a recording of a mock.
    """

    from waves.config import Tidal as _Tidal

    settings_apply = _Tidal.settings_apply

    def __init__(self):
        self.session = Mock(spec=Session)
        self.is_atmos_session = False
        self.settings = Mock()
        self.settings.data = Mock()
        self.settings.data.quality_audio = Quality.low_320k


def _provider(**kwargs) -> tuple[TidalProvider, _FakeTidal]:
    tidal = _FakeTidal()
    return TidalProvider(tidal, **kwargs), tidal


def _http_error(status: int, body: dict) -> Exception:
    from requests import HTTPError

    response = Mock()
    response.status_code = status
    response.json.return_value = body
    error = HTTPError(response=response)
    return error


def _patch_tidal_page(monkeypatch, page, parser=None):
    """Stand in for the module's tidalapi page classes; returns the Page and
    PageCategoryV2 stand-ins so a test can assert the construction shape."""
    page_cls = Mock(name="Page", return_value=page)
    parser_cls = Mock(name="PageCategoryV2", return_value=parser) if parser is not None else Mock(name="PageCategoryV2")
    monkeypatch.setattr("waves.providers.tidal.tidal_page", SimpleNamespace(Page=page_cls, PageCategoryV2=parser_cls))
    return page_cls, parser_cls


class _BareProvider(Provider):
    """A provider implementing the whole fused interface, with no bodies."""

    id = "x"
    name = "X"
    capabilities = frozenset()

    def login_begin(self): ...
    def login_complete(self, payload): ...
    def logout(self): ...
    @property
    def is_logged_in(self): ...
    def apply_quality(self, tier, audio_type): ...
    def search(self, needle): ...
    def open_url(self, url): ...
    def get_object(self, kind, raw_id): ...
    def collection_items(self, obj, include_videos=True): ...
    def user_collections(self): ...
    def favorites_page(self, kind, offset, limit, order=None): ...
    def favorite_ids(self, kind): ...
    def advertised_tier(self, obj): ...
    def advertised_deliveries(self, obj): ...
    def advertised_ceiling(self, obj): ...
    def resolve_stream(self, track, tier, audio_type): ...
    def fetch_lyrics(self, track): ...
    def cover_url(self, obj, dimension): ...
    def track_facts(self, track): ...
    def classify_refusal(self, exc): ...
    def login_resume(self): ...
    def account_id(self): ...
    def credential_facts(self): ...
    def reset_session(self): ...
    def folder_tree(self, root_folders=None): ...
    def search_tracks(self, needle, limit=10): ...
    def browse_page(self, title, api_path): ...
    def browse_home(self): ...
    def browse_window(self, title, data_path, mod_type, offset, limit=50):
        ...

        # ---------------------------------------------------------------- the seam

    def test_login_begin_rebuilds_a_torn_down_session(self):
        # The engine's logout deletes the session object outright; a fresh
        # PKCE login rebuilds one instead of failing (the self-heal the
        # bridge's login slot used to carry, now where the session lives).
        provider, tidal = _provider()
        tidal.session = None
        built = []
        provider.reset_session = lambda: built.append(True)  # type: ignore[method-assign]

        provider.login_begin()

        assert built == [True], "a torn-down session must be rebuilt before the flow starts"

    def test_login_begin_keeps_a_live_session(self):
        provider, _ = _provider()
        rebuilds = []
        provider.reset_session = lambda: rebuilds.append(True)  # type: ignore[method-assign]

        provider.login_begin()

        assert rebuilds == []


class TestTheSeam:
    def test_tidal_provider_is_a_provider(self):
        provider, _ = _provider()
        assert isinstance(provider, Provider)
        assert provider.id == "tidal"
        assert provider.name == "TIDAL"

    def test_tidal_capabilities(self):
        provider, _ = _provider()
        assert provider.capabilities == frozenset(Capability)

    def test_base_module_stays_import_light(self):
        # The neutral types must import without tidalapi (or Qt), so a
        # provider-free caller (and the Apple side later) can use them freely.
        import waves.providers.base as base

        assert "tidalapi" not in vars(base)


# ------------------------------------------------------- session / auth


class TestSession:
    def test_login_begin_returns_the_pkce_url(self):
        provider, tidal = _provider()
        tidal.session.pkce_login_url.return_value = "https://login.tidal.com/authorize?x=1"
        assert provider.login_begin() == "https://login.tidal.com/authorize?x=1"

    def test_login_complete_exchanges_the_token_and_finalizes(self):
        provider, tidal = _provider()
        tidal.session.pkce_get_auth_token.return_value = {"code": "t"}
        tidal.login_finalize = Mock(return_value=True)

        assert provider.login_complete("https://tidal.com/login?code=q") is True
        tidal.session.pkce_get_auth_token.assert_called_once_with("https://tidal.com/login?code=q")
        tidal.session.process_auth_token.assert_called_once_with({"code": "t"}, is_pkce_token=True)
        tidal.login_finalize.assert_called_once_with()

    def test_login_complete_propagates_a_failed_finalize(self):
        provider, tidal = _provider()
        tidal.session.pkce_get_auth_token.return_value = {}
        tidal.login_finalize = Mock(return_value=False)
        assert provider.login_complete("https://tidal.com/login?code=q") is False

    def test_is_logged_in_reads_the_session(self):
        provider, tidal = _provider()
        tidal.session.check_login.return_value = True
        assert provider.is_logged_in is True
        tidal.session.check_login.return_value = False
        assert provider.is_logged_in is False

    def test_logout_delegates_to_the_config_body(self):
        provider, tidal = _provider()
        tidal.logout = Mock(return_value=True)
        provider.logout()
        tidal.logout.assert_called_once_with()

    def test_apply_quality_writes_the_mapped_tier_through_settings_apply(self):
        # The real settings_apply body runs: the session gets the tidalapi
        # quality the Waves tier maps to, plus the video quality it always sets.
        provider, tidal = _provider()
        provider.apply_quality(QualityTier.HIGH, AudioType.STEREO)
        assert tidal.settings.data.quality_audio == Quality.low_320k
        assert tidal.session.audio_quality == Quality.low_320k
        assert tidal.session.video_quality is not None

    def test_apply_quality_maps_every_rung(self):
        provider, tidal = _provider()
        expected = {
            QualityTier.LOW: Quality.low_96k,
            QualityTier.HIGH: Quality.low_320k,
            QualityTier.LOSSLESS: Quality.high_lossless,
            QualityTier.HI_RES_LOSSLESS: Quality.hi_res_lossless,
        }
        for tier, quality in expected.items():
            provider.apply_quality(tier, AudioType.STEREO)
            assert tidal.session.audio_quality == quality

    def test_apply_quality_respects_the_atmos_session_guard(self):
        # settings_apply holds the stereo tier off the session while the Atmos
        # swap owns it -- the provider inherits that guard by delegating.
        provider, tidal = _provider()
        tidal.is_atmos_session = True
        provider.apply_quality(QualityTier.HI_RES_LOSSLESS, AudioType.ATMOS)
        assert tidal.session.audio_quality != Quality.hi_res_lossless

    def test_apply_quality_carries_audio_type_without_touching_the_swap(self):
        # The Atmos session swap is a per-stream, tollbooth-protected engine
        # concern (fenced): applying a quality never engages it.
        provider, tidal = _provider()
        tidal.switch_to_atmos_session = Mock()
        provider.apply_quality(QualityTier.LOSSLESS, AudioType.ATMOS)
        tidal.switch_to_atmos_session.assert_not_called()


# ------------------------------------------------------------- catalog


class TestCatalog:
    def test_search_is_one_page_of_the_real_pager(self):
        # The GUI keeps a bounded head of each list, so the search rides one
        # 300-row page (the backend's own shape): exactly one session call.
        provider, tidal = _provider()
        page = {"tracks": [Mock(name="t1"), Mock(name="t2")], "top_hit": None}
        tidal.session.search.return_value = page

        result = provider.search("aphex twin")

        tidal.session.search.assert_called_once()
        _, kwargs = tidal.session.search.call_args
        assert kwargs.get("limit") == 300 and kwargs.get("offset") == 0
        assert result["tracks"] == page["tracks"]
        assert result["top_hit"] is None

    def test_open_url_resolves_like_the_helper_chain(self):
        provider, tidal = _provider()
        album = Mock(name="album")
        tidal.session.album.return_value = album

        resolved = provider.open_url("https://tidal.com/browse/album/123?u")

        assert resolved is album
        tidal.session.album.assert_called_once_with("123")

    def test_open_url_returns_none_for_an_unknown_grammar(self):
        provider, _ = _provider()
        assert provider.open_url("https://example.com/nothing/here") is None

    def test_advertised_tier_answers_none_for_a_missing_quality_not_low(self):
        # Empty tags and no audio_quality: the fold turns garbage into the
        # ladder's bottom rung, but a MISSING quality must stay unknown -- a
        # row labelled LOW is a claim the catalog never made.
        provider, _ = _provider()
        obj = Mock(spec=["media_metadata_tags", "audio_quality"])
        obj.media_metadata_tags = []
        obj.audio_quality = None
        assert provider.advertised_tier(obj) is None

    def test_collection_items_serializes_a_mix_parse(self):
        # A mix's lazy items() parses through the SHARED session.page parser;
        # the read holds the provider's browse lock, a browse parse can't
        # corrupt it mid-flight. Non-mix collections page typed endpoints and
        # stay lock-free.
        provider, _ = _provider()
        held = []
        provider._browse_lock = type(
            "_Recording",
            (),
            {
                "__enter__": staticmethod(lambda: held.append("enter")),
                "__exit__": staticmethod(lambda *a: held.append("exit")),
            },
        )()
        mix = Mix.__new__(Mix)
        mix_items = [Mock(name="t")]
        mix.items = lambda: mix_items

        class _ArtistLike:
            # A real bound-method shape: the paginator reads __func__.
            def __init__(self):
                self.albums: list = []

            def get_albums(self, limit=100, offset=0):
                return self.albums

            def get_ep_singles(self, limit=100, offset=0):
                return []

        artist = _ArtistLike()

        assert provider.collection_items(mix) == mix_items
        assert provider.collection_items(artist) == []
        assert held == ["enter", "exit"], "only the mix parse takes the lock"

    def test_open_url_returns_none_when_the_lookup_fails(self):
        provider, tidal = _provider()
        tidal.session.track.side_effect = RuntimeError("gone")
        assert provider.open_url("https://tidal.com/browse/track/9") is None

    def test_get_object_resolves_every_kind(self):
        provider, tidal = _provider()
        provider.get_object(MediaType.TRACK, "7")
        tidal.session.track.assert_called_once_with("7", with_album=True)
        provider.get_object(MediaType.ALBUM, "8")
        tidal.session.album.assert_called_once_with("8")
        provider.get_object(MediaType.VIDEO, "9")
        tidal.session.video.assert_called_once_with("9")
        provider.get_object(MediaType.PLAYLIST, "10")
        tidal.session.playlist.assert_called_once_with("10")
        provider.get_object(MediaType.MIX, "11")
        tidal.session.mix.assert_called_once_with("11")
        provider.get_object(MediaType.ARTIST, "12")
        tidal.session.artist.assert_called_once_with("12")

    def test_collection_items_of_an_album(self):
        provider, _ = _provider()
        from tidalapi import Album

        album = Mock(spec=Album)
        tracks = [Mock(name="t")]
        # The pager pages until a call comes back empty, and probes
        # ``__func__`` to special-case one favorites pager: the fake item
        # fetcher must be a real bound method, like the engine's are.
        album.tracks = types.MethodType(lambda self, limit, offset: list(tracks) if offset == 0 else [], album)

        assert provider.collection_items(album, include_videos=False) == tracks

    def test_collection_items_of_a_mix_filters_videos(self):
        provider, _ = _provider()
        from tidalapi import Mix

        mix = Mock(spec=Mix)
        from tidalapi import Track, Video

        track, video = Mock(spec=Track), Mock(spec=Video)
        mix.items.return_value = [track, video]

        items = provider.collection_items(mix, include_videos=False)
        assert items == [track]

    def test_collection_items_of_an_artist(self):
        provider, _ = _provider()
        from tidalapi.artist import Artist

        artist = Mock(spec=Artist)
        album1 = Mock(name="album1")
        album1.name = "album1"
        artist.get_albums = types.MethodType(lambda self, limit, offset: [album1] if offset == 0 else [], artist)
        artist.get_ep_singles = types.MethodType(lambda self, limit, offset: [], artist)

        items = provider.collection_items(artist)
        assert [a.name for a in items] == ["album1"]

    def test_user_collections_returns_playlists_and_mixes(self):
        provider, tidal = _provider()
        playlist, folder, mix = Mock(name="pl"), Mock(name="folder"), Mock(name="mix")
        favorites = tidal.session.user.favorites
        favorites.playlists_paginated.return_value = [playlist]
        favorites.playlist_folders.side_effect = lambda limit, offset, parent_folder_id: [folder] if offset == 0 else []
        category = Mock()
        category.items = [mix]
        tidal.session.mixes.return_value.categories = [category]

        result = provider.user_collections()

        assert result == {"playlists": [folder, playlist], "mixes": [mix]}


class TestFavoritesPages:
    """The My Tidal favorites windows and the favorite-id sets, read through
    the provider once the bridge routes (ticket #20). The order mapping moves
    here from the bridge's ``_lib_order_kwargs``; these tests pin the same
    verdicts that file pinned, against the same tidalapi enums."""

    def test_favorites_page_maps_the_neutral_order_per_category(self):
        from tidalapi.types import AlbumOrder, ArtistOrder, ItemOrder, OrderDirection, VideoOrder

        provider, _ = _provider()
        favorites_by_kind = {}
        for kind in ("albums", "artists", "tracks", "videos"):
            favorites = Mock()
            method = getattr(favorites, kind)
            method.return_value = []
            getattr(favorites, f"get_{kind}_count").return_value = 0
            favorites_by_kind[kind] = favorites

        def page(kind, order):
            provider._tidal.session.user.favorites = favorites_by_kind[kind]
            provider.favorites_page(kind, 0, 10, order)
            _, kwargs = getattr(favorites_by_kind[kind], kind).call_args
            return kwargs["order"], kwargs["order_direction"]

        assert page("albums", ("date", "desc")) == (AlbumOrder.DateAdded, OrderDirection.Descending)
        assert page("albums", ("release", "asc")) == (AlbumOrder.ReleaseDate, OrderDirection.Ascending)
        assert page("tracks", ("name", "asc")) == (ItemOrder.Name, OrderDirection.Ascending)
        assert page("tracks", ("artist", "desc")) == (ItemOrder.Artist, OrderDirection.Descending)
        assert page("artists", ("name", "asc")) == (ArtistOrder.Name, OrderDirection.Ascending)
        assert page("videos", ("date", "desc")) == (VideoOrder.DateAdded, OrderDirection.Descending)

    def test_favorites_page_without_a_spec_asks_no_order(self):
        # No order spec -> the API's raw default, exactly as the bridge's
        # empty kwargs did.
        provider, _ = _provider()
        favorites = Mock()
        favorites.albums.return_value = []
        favorites.get_albums_count.return_value = 0
        provider._tidal.session.user.favorites = favorites

        provider.favorites_page("albums", 0, 10, None)

        _, kwargs = favorites.albums.call_args
        assert "order" not in kwargs and "order_direction" not in kwargs

    def test_favorites_page_unsupported_order_key_asks_no_order(self):
        # An order key a category doesn't offer -> no kwargs, API default.
        provider, _ = _provider()
        favorites = Mock()
        favorites.albums.return_value = []
        favorites.get_albums_count.return_value = 0
        provider._tidal.session.user.favorites = favorites

        provider.favorites_page("albums", 0, 10, ("nonsense", "desc"))

        _, kwargs = favorites.albums.call_args
        assert "order" not in kwargs and "order_direction" not in kwargs

    def test_favorites_page_more_comes_from_the_total_count(self):
        # A limit-N window can return FEWER than N rows (tidalapi drops
        # unavailable items), so "more" must come from the count.
        provider, _ = _provider()
        favorites = Mock()
        favorites.tracks.return_value = [Mock(), Mock()]
        favorites.get_tracks_count.return_value = 5
        provider._tidal.session.user.favorites = favorites

        _rows, more = provider.favorites_page("tracks", 0, 3)

        assert more is True  # 0 + 3 < 5
        _, kwargs = favorites.tracks.call_args
        assert kwargs["limit"] == 3 and kwargs["offset"] == 0

    def test_favorites_page_without_a_count_pages_until_a_short_window(self):
        provider, _ = _provider()
        favorites = Mock()
        favorites.tracks.return_value = [Mock(), Mock()]
        favorites.get_tracks_count.side_effect = RuntimeError("no count")
        provider._tidal.session.user.favorites = favorites

        rows, more = provider.favorites_page("tracks", 0, 3)

        assert len(rows) == 2
        assert more is True  # a full-looking window (len > 0) may continue

    def test_favorites_page_survives_older_tidalapi(self):
        # Older tidalapi: drop the order kwargs, then the limit/offset kwargs,
        # then slice the one unpaged call -- the bridge's ladder, verbatim.
        provider, _ = _provider()
        rows = [Mock(name=f"t{i}") for i in range(4)]

        class _OldFavorites:
            def tracks(self, *args, **kwargs):
                if kwargs:
                    raise TypeError("unexpected keyword argument")
                return rows

            def get_tracks_count(self):
                raise TypeError("no counts either")

        provider._tidal.session.user.favorites = _OldFavorites()

        got, more = provider.favorites_page("tracks", 2, 3, ("date", "desc"))

        assert got == rows[2:5]
        assert more is True  # len(raw) > 0

    def test_favorite_ids_pages_to_the_total_count(self):
        provider, _ = _provider()
        albums = [Mock(id=str(i)) for i in range(3)]
        favorites = Mock()
        favorites.albums.side_effect = lambda limit, offset: albums[offset : offset + limit]
        favorites.get_albums_count.return_value = 3
        provider._tidal.session.user.favorites = favorites

        ids = provider.favorite_ids("albums")

        assert ids == {"0", "1", "2"}
        # The last window (offset 100) is never fetched: the count said done.
        assert favorites.albums.call_count == 1

    def test_favorite_ids_empty_batch_guards_a_lying_count(self):
        provider, _ = _provider()
        favorites = Mock()
        favorites.tracks.return_value = []  # count lies that more exist
        favorites.get_tracks_count.return_value = 500
        provider._tidal.session.user.favorites = favorites

        assert provider.favorite_ids("tracks") == set()

    def test_favorite_ids_without_a_count_stops_on_a_short_window(self):
        provider, _ = _provider()
        first = [Mock(id=str(i)) for i in range(100)]
        favorites = Mock()
        favorites.tracks.side_effect = lambda limit, offset: [] if offset else first
        favorites.get_tracks_count.side_effect = RuntimeError("no count")
        provider._tidal.session.user.favorites = favorites

        ids = provider.favorite_ids("tracks")

        assert len(ids) == 100

    def test_favorite_ids_survives_older_tidalapi(self):
        # One unpaged call, sliced by nothing: the ids still come out.
        provider, _ = _provider()

        class _OldFavorites:
            def albums(self, *args, **kwargs):
                if kwargs:
                    raise TypeError("unexpected keyword argument")
                return [Mock(id="7")]

            def get_albums_count(self):
                raise TypeError("no counts")

        provider._tidal.session.user.favorites = _OldFavorites()

        assert provider.favorite_ids("albums") == {"7"}

    def test_favorite_ids_carry_the_partial_set_when_pagination_fails(self):
        # Two windows land, then the network dies: the failure carries the
        # ids already collected, so the bridge can serve what was gathered
        # (the old path's exact rule) instead of blanking the badges.
        from waves.providers.base import FavoritesUnavailable

        provider, _ = _provider()
        first = [Mock(id=str(i)) for i in range(100)]
        favorites = Mock()
        favorites.tracks.side_effect = lambda limit, offset: RuntimeError("network died") if offset else first
        favorites.get_tracks_count.return_value = 500
        provider._tidal.session.user.favorites = favorites

        with pytest.raises(FavoritesUnavailable) as excinfo:
            provider.favorite_ids("tracks")

        assert len(excinfo.value.ids) == 100

    def test_favorite_ids_let_failures_propagate(self):
        # The bridge keeps its serve-stale semantics; the provider must raise,
        # not swallow a partial set as fresh (the old path's rule). A session
        # missing entirely fails before any window, so nothing partial exists.
        provider, _ = _provider()
        provider._tidal.session.user.favorites = None
        with pytest.raises(AttributeError):
            provider.favorite_ids("albums")


# ------------------------------------------------------------- quality


class TestQuality:
    def test_tier_rank_matches_the_ownership_store_scale(self):
        # Two spellings of one scale is the drift the seam analysis warned
        # about: pin them together.
        for tier in QualityTier:
            assert quality_rank(tier) == QUALITY_RANK[tier.value]

    def test_tier_from_tidal_aligns_with_the_backend_tier_words(self):
        # The backend folds a delivered tier into the one word the UI shows;
        # the Waves rung must fold the same way or a row's badge lies.
        from waves.waves_ui.backend import _tier_word

        word_by_tier = {
            QualityTier.LOW: "LOW",
            QualityTier.HIGH: "HIGH",
            QualityTier.LOSSLESS: "LOSSLESS",
            QualityTier.HI_RES_LOSSLESS: "HI-RES",
        }
        for quality in Quality:
            tier = tier_from_tidal(quality)
            assert word_by_tier[tier] == _tier_word(quality.value), quality

    def test_advertised_tier_reads_the_metadata_tags(self):
        provider, _ = _provider()
        from tidalapi import Track

        hires = Mock(spec=Track)
        hires.media_metadata_tags = [MediaMetadataTags.hi_res_lossless]
        assert provider.advertised_tier(hires) is QualityTier.HI_RES_LOSSLESS

        lossless = Mock(spec=Track)
        lossless.media_metadata_tags = [MediaMetadataTags.lossless]
        assert provider.advertised_tier(lossless) is QualityTier.LOSSLESS

    def test_advertised_tier_falls_back_to_audio_quality(self):
        provider, _ = _provider()
        from tidalapi import Track

        track = Mock(spec=Track)
        track.media_metadata_tags = []
        track.audio_quality = Quality.low_320k
        assert provider.advertised_tier(track) is QualityTier.HIGH

    def test_advertised_tier_matches_the_helper_verdict(self):
        from waves.helper.tidal import quality_audio_highest

        provider, _ = _provider()
        from tidalapi import Track

        for tags, audio_quality in [
            ([MediaMetadataTags.hi_res_lossless], Quality.low_320k),
            ([MediaMetadataTags.lossless], Quality.low_320k),
            ([], Quality.low_320k),
            ([], Quality.low_96k),
        ]:
            track = Mock(spec=Track)
            track.media_metadata_tags = tags
            track.audio_quality = audio_quality
            assert provider.advertised_tier(track) is tier_from_tidal(quality_audio_highest(track))

    def test_advertised_ceiling_matches_the_backend_gate_input(self):
        # The backend's upgrade gate caps on exactly this answer; the numbers
        # must be the ownership store's ranks, not a new scale.
        from waves.waves_ui.backend import _advertised_ceiling

        provider, _ = _provider()
        from tidalapi import Track

        for tags in (
            [MediaMetadataTags.hi_res_lossless],
            [MediaMetadataTags.lossless],
            ["LOSSY"],  # a below-the-line tag, spelled however it arrives
            [],
        ):
            track = Mock(spec=Track)
            track.media_metadata_tags = tags
            assert provider.advertised_ceiling(track) == _advertised_ceiling(track)

    def test_advertised_deliveries_stereo(self):
        provider, _ = _provider()
        from tidalapi import Track

        track = Mock(spec=Track)
        track.media_metadata_tags = [MediaMetadataTags.lossless]
        track.audio_quality = Quality.low_320k
        track.audio_modes = [AudioMode.stereo]

        assert provider.advertised_deliveries(track) == [(QualityTier.LOSSLESS, AudioType.STEREO)]

    def test_advertised_deliveries_with_atmos(self):
        provider, _ = _provider()
        from tidalapi import Track

        track = Mock(spec=Track)
        track.media_metadata_tags = [MediaMetadataTags.lossless]
        track.audio_quality = Quality.low_320k
        track.audio_modes = [AudioMode.stereo, AudioMode.dolby_atmos]

        deliveries = provider.advertised_deliveries(track)
        assert (QualityTier.LOSSLESS, AudioType.STEREO) in deliveries
        assert (QualityTier.HIGH, AudioType.ATMOS) in deliveries

    def test_advertised_deliveries_atmos_only(self):
        provider, _ = _provider()
        from tidalapi import Track

        track = Mock(spec=Track)
        track.media_metadata_tags = []
        track.audio_quality = Quality.low_320k
        track.audio_modes = [AudioMode.dolby_atmos]

        assert provider.advertised_deliveries(track) == [(QualityTier.HIGH, AudioType.ATMOS)]

    def test_advertised_deliveries_omit_what_the_catalog_does_not_state(self):
        # An unknown tier advertises nothing: inventing a floor rung for an
        # unparseable object would be a product decision the spec never made.
        provider, _ = _provider()
        from tidalapi import Track

        broken = Mock(spec=Track)
        broken.media_metadata_tags = None  # the tier lookup cannot answer
        broken.audio_modes = []
        assert provider.advertised_deliveries(broken) == []

        broken_atmos = Mock(spec=Track)
        broken_atmos.media_metadata_tags = None
        broken_atmos.audio_modes = [AudioMode.dolby_atmos]
        assert provider.advertised_deliveries(broken_atmos) == [(QualityTier.HIGH, AudioType.ATMOS)]


# ---------------------------------------------------- per-track delivery


class TestDelivery:
    def _track_stream_info(self, stream=None, manifest=None):
        from waves.model.downloader import TrackStreamInfo

        return TrackStreamInfo(
            stream_manifest=manifest,
            file_extension=".flac",
            requires_flac_extraction=True,
            media_stream=stream,
        )

    def test_resolve_stream_needs_a_registered_engine(self):
        provider, _ = _provider()
        with pytest.raises(RuntimeError, match="resolver"):
            provider.resolve_stream(Mock(), QualityTier.LOSSLESS, AudioType.STEREO)

    def test_resolve_stream_translates_the_engine_answer(self):
        # The engine's resolver answers in the engine's shape until the
        # pipeline routes; the provider's job is the neutral translation.
        stream = Mock()
        stream.audio_quality = Quality.high_lossless
        stream.audio_mode = AudioMode.stereo
        stream.bit_depth = 16
        stream.sample_rate = 44100
        manifest = Mock()
        manifest.get_urls.return_value = ["https://seg/1", "https://seg/2"]
        manifest.codecs = "flac"
        info = self._track_stream_info(stream=stream, manifest=manifest)
        track = Mock(name="track")
        resolver = Mock(return_value=info)
        provider, _ = _provider(stream_resolver=resolver)

        resolved = provider.resolve_stream(track, QualityTier.LOSSLESS, AudioType.STEREO)

        resolver.assert_called_once_with(track, QualityTier.LOSSLESS, AudioType.STEREO)
        assert isinstance(resolved, StreamInfo)
        assert resolved.file_extension == ".flac"
        assert resolved.requires_flac_extraction is True
        assert resolved.urls == ["https://seg/1", "https://seg/2"]
        assert resolved.codecs == "flac"
        assert resolved.delivered["tier"] == "LOSSLESS"
        assert resolved.delivered["bit_depth"] == 16

    def test_translation_delivered_snapshot_carries_the_backend_facts(self):
        # One fact, two spellings, until the contract ticket deletes the
        # backend copy: the neutral snapshot carries the same measured facts
        # in the seam's vocabulary (audio_type where the backend snapshot
        # says audio_mode) -- pin the translation, not the spelling.
        from waves.waves_ui.backend import _stream_quality

        provider, _ = _provider()
        stream = Mock()
        stream.audio_quality = Quality.hi_res_lossless
        stream.audio_mode = AudioMode.dolby_atmos
        stream.bit_depth = 24
        stream.sample_rate = 192000
        manifest = Mock()
        manifest.codecs = "eac3"
        info = self._track_stream_info(stream=stream, manifest=manifest)

        resolved = provider._as_stream_info(info)
        backend_snapshot = _stream_quality(info)

        assert resolved.delivered["tier"] == backend_snapshot["tier"]
        assert resolved.delivered["bit_depth"] == backend_snapshot["bit_depth"]
        assert resolved.delivered["sample_rate"] == backend_snapshot["sample_rate"]
        assert resolved.delivered["codecs"] == backend_snapshot["codecs"]
        assert resolved.delivered["audio_type"] == str(AudioType.ATMOS)
        assert backend_snapshot["audio_mode"] == "DOLBY_ATMOS"

    def test_delivered_audio_type_is_stereo_for_a_stereo_stream(self):
        provider, _ = _provider()
        stream = Mock()
        stream.audio_quality = Quality.high_lossless
        stream.audio_mode = AudioMode.stereo
        stream.bit_depth = 16
        stream.sample_rate = 44100
        manifest = Mock()
        manifest.codecs = "flac"
        info = self._track_stream_info(stream=stream, manifest=manifest)

        resolved = provider._as_stream_info(info)
        assert resolved.delivered["audio_type"] == str(AudioType.STEREO)
        assert resolved.delivered["tier"] == "LOSSLESS"

    def test_fetch_lyrics_prefers_synced_and_plain_pair(self):
        provider, _ = _provider()
        track = Mock()
        track.lyrics.return_value = Mock(subtitles="[00:01] la", text="la")

        assert provider.fetch_lyrics(track) == ("[00:01] la", "la")

    def test_fetch_lyrics_survives_a_missing_lyrics_call(self):
        provider, _ = _provider()
        track = Mock()
        track.lyrics.side_effect = RuntimeError("no lyrics")
        assert provider.fetch_lyrics(track) == ("", "")

    def test_cover_url_asks_the_engine_object(self):
        provider, _ = _provider()
        from tidalapi import Album

        album = Mock(spec=Album)
        album.image.return_value = "https://cover/320.jpg"
        assert provider.cover_url(album, 320) == "https://cover/320.jpg"

    def test_cover_url_matches_the_backend_best_effort_image(self):
        from waves.waves_ui.backend import _image

        provider, _ = _provider()
        from tidalapi import Album, Track

        plain = Mock(spec=Album)
        plain.image.side_effect = RuntimeError("640 not served")
        assert provider.cover_url(plain, 640) == _image(plain, 640)

        # A track carries no image of its own: the album answers, exactly as
        # the backend's best-effort image helper resolves it.
        wrapped = Mock(spec=Track)
        album = Mock(spec=Album)
        album.image.return_value = "https://cover/via-track.jpg"
        wrapped.album = album
        assert provider.cover_url(wrapped, 320) == _image(wrapped, 320) == "https://cover/via-track.jpg"

        bare = object()
        assert provider.cover_url(bare, 320) == _image(bare, 320)

    def test_track_facts_carries_the_fact_schema(self):
        # The fields the tag writer reads, under stable names, so the engine
        # can consume facts instead of reaching into the catalog object.
        import datetime

        provider, _ = _provider()
        from tidalapi import Album, Track

        album = Mock(spec=Album)
        album.available_release_date = datetime.date(2024, 3, 1)
        album.release_date = datetime.date(2024, 3, 5)
        album.num_tracks = 10
        album.num_volumes = 2
        album.upc = "00602547595134"
        album.type = "ALBUM"
        album.name = "Selected Ambient Works"
        artist = Mock()
        artist.id = "100"
        artist.name = "Aphex Twin"
        artist.roles = None  # a role-less credit counts as main (the helper's guard)
        track = Mock(spec=Track)
        track.id = "1"
        track.copyright = "1992"
        track.isrc = "GBAHT9200001"
        track.explicit = False
        track.bpm = 0
        track.key = None
        track.key_scale = None
        track.share_url = "https://tidal.com/browse/track/1"
        track.volume_num = 1
        track.track_num = 3
        track.artists = [artist]
        album.artists = [artist]
        track.album = album

        facts = provider.track_facts(track)

        assert facts["item_id"] == "tidal:1"  # the seam's namespaced spelling (§4.2)
        assert facts["artist_ids"] == ["tidal:100"]
        assert facts["album_artist_ids"] == ["tidal:100"]
        assert facts["artists"] == [("tidal:100", "Aphex Twin")]
        assert facts["copyright"] == "1992"
        assert facts["isrc"] == "GBAHT9200001"
        assert facts["explicit"] is False
        assert facts["bpm"] == 0
        assert facts["share_url"] == "https://tidal.com/browse/track/1"
        assert facts["volume_num"] == 1
        assert facts["track_num"] == 3
        assert facts["release_date"] == "2024-03-01"
        assert facts["release_type"] == "album"
        assert facts["album_artist_ids"] == ["tidal:100"]
        album_facts = facts["album"]
        assert album_facts["name"] == "Selected Ambient Works"
        assert album_facts["num_tracks"] == 10
        assert album_facts["num_volumes"] == 2
        assert album_facts["upc"] == "00602547595134"

    def test_track_facts_keep_an_id_less_credit_on_the_artists_tag(self):
        # The old tag pull wrote EVERY credited artist's name while the id
        # list filtered separately; the fact schema must not shrink a credit
        # whose id never arrived -- the pair just carries an empty identity.
        provider, _ = _provider()
        from tidalapi import Track

        credited, id_less = Mock(), Mock()
        credited.id = "100"
        credited.name = "Aphex Twin"
        id_less.id = None
        id_less.name = "DJ Anonymous"
        track = Mock(spec=Track)
        track.artists = [credited, id_less]
        track.album = None  # keep the album-artist helpers out of this pin

        facts = provider.track_facts(track)

        assert facts["artists"] == [("tidal:100", "Aphex Twin"), ("", "DJ Anonymous")]
        assert facts["artist_ids"] == ["tidal:100"]  # the id list filters separately

    def test_track_facts_survives_a_track_without_an_album(self):
        # Playlist pages carry album-less tracks; the fact pull must answer,
        # not raise (the tag writer guards the same way).
        provider, _ = _provider()
        from tidalapi import Track

        track = Mock(spec=Track)
        track.album = None
        track.copyright = ""
        track.isrc = ""
        track.explicit = False
        track.bpm = None
        track.key = None
        track.key_scale = None
        track.share_url = ""
        track.volume_num = None
        track.track_num = 1
        track.artists = []

        facts = provider.track_facts(track)

        assert facts["release_date"] == ""
        assert facts["release_type"] == ""
        assert facts["album"]["name"] == ""
        assert facts["item_id"] == ""  # unknown stays unknown, never "tidal:"

    def test_preview_hook_stays_unwired_for_tidal(self):
        # TIDAL previews ride the engine's own HLS pipeline; the hook is the
        # second provider's plug-in point.
        provider, _ = _provider()
        assert provider.preview_url(Mock()) is None


# ------------------------------------------------- session lifecycle (contract)


class TestSessionLifecycleContract:
    """The session work the GUI used to do by reaching the session directly
    (ticket #22): resume from stored credentials, the account id, the
    credential facts the redactor is taught, and the post-logout rebuild."""

    def test_login_resume_delegates_to_the_cached_token_login(self):
        provider, tidal = _provider()
        tidal.login_token = Mock(return_value=True)
        assert provider.login_resume() is True
        tidal.login_token.assert_called_once_with()

    def test_account_id_reads_the_session_user(self):
        provider, tidal = _provider()
        tidal.session.user.id = 4242
        assert provider.account_id() == "4242"

    def test_account_id_answers_empty_when_there_is_no_user(self):
        provider, tidal = _provider()
        tidal.session.user = None
        assert provider.account_id() == ""

    def test_credential_facts_carry_the_secrets_the_redactor_registers(self):
        provider, tidal = _provider()
        tidal.session.access_token = "tok"  # noqa: S105 - a canned test value
        tidal.session.refresh_token = "ref"  # noqa: S105 - a canned test value
        tidal.session.session_id = "sid"
        tidal.session.user = Mock()
        tidal.session.user.id = 7
        tidal.session.user.username = "me@example.com"

        facts = provider.credential_facts()

        assert facts == {
            "access_token": "tok",
            "refresh_token": "ref",
            "session_id": "sid",
            "account_id": "7",
            "username": "me@example.com",
        }

    def test_credential_facts_survive_a_missing_user(self):
        provider, tidal = _provider()
        tidal.session.user = None
        facts = provider.credential_facts()
        assert facts["account_id"] == "" and facts["username"] == ""

    def test_reset_session_rebuilds_and_rehardens(self, monkeypatch):
        # Sign-out in a long-lived GUI cannot leave a deleted session (the
        # engine's CLI assumption): the provider rebuilds a clean one, mirrors
        # the constructor's captured client pairs, and re-applies the quality.
        import tidalapi

        provider, tidal = _provider()
        hardened: list = []
        monkeypatch.setattr("waves.providers.tidal.harden_api_session", lambda session: hardened.append(session))
        tidal.original_client_id = None
        tidal.original_client_secret = None
        tidal.original_client_id_pkce = None
        tidal.original_client_secret_pkce = None
        tidal.is_atmos_session = True  # a stale Atmos flag must not survive

        provider.reset_session()

        assert isinstance(tidal.session, tidalapi.Session)
        assert hardened == [tidal.session]
        assert tidal.original_client_id == tidal.session.config.client_id
        assert tidal.original_client_secret == tidal.session.config.client_secret
        assert tidal.original_client_id_pkce == tidal.session.config.client_id_pkce
        assert tidal.original_client_secret_pkce == tidal.session.config.client_secret_pkce
        assert tidal.is_atmos_session is False
        assert tidal.session.audio_quality == tidal.settings.data.quality_audio  # re-applied


# ------------------------------------------------------- catalog (contract)


class TestCatalogContract:
    """The reads the bridge still made against the session/helper directly
    before the contract pass: the folder walk, the small track search, and
    the editorial (Browse) reads."""

    def test_search_tracks_is_a_lightweight_track_only_search(self):
        provider, tidal = _provider()
        track = Mock(name="track")
        tidal.session.search.return_value = {"tracks": [track]}

        result = provider.search_tracks("artist song", limit=10)

        assert result == [track]
        _, kwargs = tidal.session.search.call_args
        assert kwargs.get("models") == [Track]
        assert kwargs.get("limit") == 10

    def test_search_tracks_answers_empty_when_the_bucket_is_missing(self):
        provider, tidal = _provider()
        tidal.session.search.return_value = {}
        assert provider.search_tracks("x", limit=5) == []

    def test_folder_tree_walks_the_helper_body(self, monkeypatch):
        from waves.helper.folders import FolderTree

        provider, tidal = _provider()
        roots = [Mock(name="root folder")]
        seen: dict = {}
        monkeypatch.setattr(
            "waves.providers.tidal.walk_playlist_tree",
            lambda session, root_folders=None: seen.update(session=session, root_folders=root_folders) or FolderTree(),
        )

        tree = provider.folder_tree(root_folders=roots)

        assert isinstance(tree, FolderTree)
        assert seen["session"] is tidal.session
        assert seen["root_folders"] is roots

    def test_browse_page_reads_the_editorial_path_and_degrades_to_the_stock_parse(self, monkeypatch):
        provider, tidal = _provider()
        page = Mock(name="page")
        page.request.request.return_value.json.return_value = {"title": "Whatever"}  # no "rows": V2 shape
        page_cls, _ = _patch_tidal_page(monkeypatch, page)

        result = provider.browse_page("Explore", "pages/explore")

        page_cls.assert_called_once_with(tidal.session, "Explore")
        page.request.request.assert_called_once_with("GET", "pages/explore", params={"deviceType": "BROWSER"})
        assert result is page.parse.return_value
        page.parse.assert_called_once_with({"title": "Whatever"})

    def test_browse_page_parses_rows_and_stashes_the_paging_handle(self, monkeypatch):
        provider, _ = _provider()
        cat = Mock(name="category")
        page = Mock(name="page")
        page.request.request.return_value.json.return_value = {
            "title": "Explore",
            "rows": [
                {
                    "modules": [
                        {
                            "type": "pagedList",
                            "pagedList": {"dataApiPath": "pages/data/x", "totalNumberOfItems": 7, "items": [1, 2]},
                        }
                    ]
                }
            ],
        }
        page.page_category.parse.return_value = cat
        _patch_tidal_page(monkeypatch, page)

        result = provider.browse_page("Explore", "pages/explore")

        assert result is page  # the parsed page comes back for the bridge to render
        assert result.title == "Explore"  # the payload's own title wins
        assert result.categories == [cat]
        assert cat._waves_pl == {
            "data": "pages/data/x",
            "total": 7,
            "n": 2,
            "modType": "pagedList",
        }

    def test_browse_page_drops_an_unparseable_module_and_keeps_the_rest(self, monkeypatch):
        provider, _ = _provider()
        good = Mock(name="good")
        page = Mock(name="page")
        page.request.request.return_value.json.return_value = {
            "title": "",
            "rows": [{"modules": [{"type": "bad"}]}, {"modules": [{"type": "good"}]}],
        }
        page.page_category.parse.side_effect = [RuntimeError("unknown module"), good]
        _patch_tidal_page(monkeypatch, page)

        result = provider.browse_page("Explore", "pages/explore")

        assert result.categories == [good]

    def test_browse_home_reads_the_v2_feed(self, monkeypatch):
        provider, tidal = _provider()
        ok = Mock(name="ok")
        parser = Mock(name="parser")
        parser.parse_item.side_effect = [ok, RuntimeError("bad module")]
        request = Mock(name="request")
        request.request.return_value.json.return_value = {"items": [{"id": 1}, {"id": "bad"}]}
        tidal.session.request = request
        tidal.session.config = Mock()
        tidal.session.config.api_v2_location = "https://api.tidal.com/v2"
        tidal.session.locale = "en_US"
        page = Mock(name="page")
        _patch_tidal_page(monkeypatch, page, parser)

        result = provider.browse_home()

        request.request.assert_called_once_with(
            "GET",
            "home/feed/static",
            base_url="https://api.tidal.com/v2",
            params={"deviceType": "BROWSER", "locale": "en_US", "platform": "WEB"},
        )
        parser.parse_item.assert_called_with({"id": "bad"})  # every item was offered
        assert result.categories == [ok]  # the bad module was dropped, the feed lives

    def test_browse_window_reads_one_paged_window(self, monkeypatch):
        provider, _ = _provider()
        cat = Mock(name="category")
        page = Mock(name="page")
        page.request.request.return_value.json.return_value = {"items": [{"a": 1}, {"b": 2}], "totalNumberOfItems": 9}
        page.page_category.parse.return_value = cat
        _patch_tidal_page(monkeypatch, page)

        window = provider.browse_window("Genre", "pages/data/x", "pagedList", offset=50)

        page.request.request.assert_called_once_with(
            "GET",
            "pages/data/x",
            params={"deviceType": "BROWSER", "locale": "en_US", "offset": 50, "limit": 50},
        )
        page.page_category.parse.assert_called_once_with(
            {"type": "pagedList", "title": "Genre", "pagedList": {"items": [{"a": 1}, {"b": 2}]}}
        )
        assert window.category is cat
        assert window.n == 2  # the RAW page length, the paging arithmetic's input
        assert window.total == 9


# ------------------------------------------------------- preview (contract)


class TestPreviewContract:
    """Full-track preview resolution: the session dance (stream lock, normal
    session, LOW pin, restore) is TIDAL machinery and moved behind the seam
    with it."""

    @staticmethod
    def _manifest(*, encrypted=False, is_bts=False, urls=None, hls="hls-master"):
        manifest = Mock(name="manifest")
        manifest.is_encrypted = encrypted
        manifest.get_urls.return_value = urls or ["seg-1"]
        manifest.get_hls.return_value = hls
        return manifest

    def _resolved(self, *, encrypted=False, is_bts=False, hls="hls-master"):
        provider, tidal = _provider()
        tidal.restore_normal_session = Mock(return_value=True)
        tidal.stream_lock = Lock()
        manifest = self._manifest(encrypted=encrypted, is_bts=is_bts, hls=hls)
        stream = Mock(name="stream")
        stream.is_bts = is_bts
        stream.get_stream_manifest.return_value = manifest
        track = Mock(name="track")
        track.get_stream.return_value = stream
        return provider, tidal, track

    def test_a_bts_stream_resolves_to_its_single_file(self):
        provider, _tidal, track = self._resolved(is_bts=True)

        info = provider.resolve_preview(track)

        assert info.single_file is True
        assert info.urls == ["seg-1"]
        assert info.encrypted is False
        track.get_stream.assert_called_once_with()

    def test_an_hls_stream_resolves_to_its_master_url(self):
        provider, _, track = self._resolved(is_bts=False)

        info = provider.resolve_preview(track)

        assert info.single_file is False
        assert info.hls_url == "hls-master"

    def test_the_session_is_left_at_the_configured_quality(self):
        # The resolve pins LOW for its own fetch and restores the configured
        # tier in finally -- the guarantee the bridge's comment documents.
        provider, tidal, track = self._resolved()
        tidal.settings.data.quality_audio = Quality.high_lossless

        provider.resolve_preview(track)

        assert tidal.session.audio_quality == Quality.high_lossless

    def test_the_fetch_rides_the_low_tier(self):
        provider, tidal, track = self._resolved()
        seen = []
        track.get_stream.side_effect = lambda: (
            seen.append(tidal.session.audio_quality) or Mock(get_stream_manifest=lambda: self._manifest())
        )
        provider.resolve_preview(track)
        assert seen == [Quality.low_96k]

    def test_a_failed_session_restore_answers_unresolvable(self):
        provider, tidal, track = self._resolved()
        tidal.restore_normal_session = Mock(return_value=False)

        info = provider.resolve_preview(track)

        assert info.urls == [] and info.encrypted is False
        track.get_stream.assert_not_called()

    def test_an_encrypted_stream_is_marked_not_served(self):
        provider, _, track = self._resolved(encrypted=True)

        info = provider.resolve_preview(track)

        assert info.encrypted is True
        assert info.urls == []

    def test_the_default_provider_hook_answers_unresolvable(self):
        # The optional hook's inherited default: a provider without session
        # machinery answers "could not resolve", never a crash.
        info = _BareProvider().resolve_preview(Mock())
        assert info.urls == [] and info.hls_url == ""


# ------------------------------------------------------------- refusals


class TestRefusals:
    def test_asset_refusal_is_final(self):
        provider, _ = _provider()
        error = _http_error(401, {"userMessage": "Asset is not ready for playback", "subStatus": 4005})
        refusal = provider.classify_refusal(error)
        assert refusal.kind.value == "unavailable"
        assert "Asset is not ready" in refusal.message

    def test_gone_stream_kinds_are_final(self):
        from tidalapi.exceptions import AssetNotAvailable, ObjectNotFound, StreamNotAvailable

        provider, _ = _provider()
        for exc in (StreamNotAvailable(), ObjectNotFound(), AssetNotAvailable()):
            assert provider.classify_refusal(exc).kind.value == "unavailable"

    def test_auth_family_is_a_failure_not_a_refusal(self):
        # "Your session, not the content" (subStatus 11000-11999): the engine
        # refuses to call this gone, and so must the provider.
        provider, _ = _provider()
        error = _http_error(401, {"userMessage": "Invalid token", "subStatus": 11002})
        assert provider.classify_refusal(error).kind.value == "failure"

    def test_expired_token_is_a_failure(self):
        provider, _ = _provider()
        error = _http_error(401, {"userMessage": "The token has expired."})
        assert provider.classify_refusal(error).kind.value == "failure"

    def test_throttling_is_its_own_class(self):
        from tidalapi.exceptions import TooManyRequests

        provider, _ = _provider()
        assert provider.classify_refusal(TooManyRequests()).kind.value == "throttled"

    def test_everything_else_is_a_failure(self):
        provider, _ = _provider()
        assert provider.classify_refusal(_http_error(500, {})).kind.value == "failure"
        assert provider.classify_refusal(ValueError("nope")).kind.value == "failure"

    def test_classification_agrees_with_the_engine_decision(self):
        # The engine marks a stream-info fetch unavailable under exactly one
        # condition; the provider's classifier must not disagree with it.
        from requests import HTTPError
        from tidalapi.exceptions import AssetNotAvailable, ObjectNotFound, StreamNotAvailable, TooManyRequests

        from waves.download import _tidal_refuses_asset

        provider, _ = _provider()
        cases: list[Exception] = [
            StreamNotAvailable(),
            ObjectNotFound(),
            AssetNotAvailable(),
            TooManyRequests(),
            ValueError("network died"),
            _http_error(401, {"userMessage": "Asset is not ready for playback", "subStatus": 4005}),
            _http_error(403, {"userMessage": "Asset is not ready for playback"}),
            _http_error(401, {"userMessage": "Invalid token", "subStatus": 11002}),
            _http_error(401, {"userMessage": "The token has expired."}),
            _http_error(500, {}),
        ]
        for exc in cases:
            refusal = provider.classify_refusal(exc)
            engine_refused = isinstance(exc, StreamNotAvailable | ObjectNotFound | AssetNotAvailable) or (
                isinstance(exc, HTTPError) and _tidal_refuses_asset(exc) is not None
            )
            if engine_refused:
                assert refusal.kind.value == "unavailable", exc
            elif isinstance(exc, TooManyRequests):
                assert refusal.kind.value == "throttled", exc
            else:
                assert refusal.kind.value == "failure", exc
