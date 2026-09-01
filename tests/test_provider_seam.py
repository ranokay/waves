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
from unittest.mock import Mock

import pytest
from tidalapi.media import AudioMode, MediaMetadataTags, Quality
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


# ---------------------------------------------------------------- the seam


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
        favorites.playlist_folders.side_effect = lambda limit, offset, parent_folder_id: (
            [folder] if offset == 0 else []
        )
        category = Mock()
        category.items = [mix]
        tidal.session.mixes.return_value.categories = [category]

        result = provider.user_collections()

        assert result == {"playlists": [folder, playlist], "mixes": [mix]}


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
