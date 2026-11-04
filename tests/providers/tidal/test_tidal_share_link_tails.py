"""TIDAL share links name the same item whatever tail the share sheet adds.

A pasted link can arrive with a trailing ``/u``, a trailing slash, a query, a
fragment, or any combination. Both the id and the kind read from one
normalized path, so they cannot disagree about the tail. A foreign host and
malformed input report no kind; bare ids keep working. The provider's
``open_url`` is driven too: it is the caller that turns the pair into a
lookup.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from tidalapi.session import Session

from waves.constants import MediaType
from waves.providers import TidalProvider
from waves.providers.tidal_client import get_tidal_media_id, get_tidal_media_type

# Every form TIDAL's share sheet and a browser address bar produce for the
# same track. The query and fragment pair deliberately contains slashes.
TRACK_SHARE_LINKS = [
    "https://tidal.com/browse/track/123/u",
    "https://tidal.com/browse/track/123/",
    "https://tidal.com/track/123?u",
    "https://tidal.com/browse/track/123?utm=x#top",
    "https://tidal.com/browse/track/123/u/",
    "https://tidal.com/browse/track/123?share=a/b#c/d",
    "tidal.com/browse/track/123/u",
    "listen.tidal.com/browse/track/123/u",
]


@pytest.mark.parametrize("url", TRACK_SHARE_LINKS)
def test_share_link_tails_still_name_the_track(url):
    assert get_tidal_media_type(url) == MediaType.TRACK
    assert get_tidal_media_id(url) == "123"


def test_a_bare_id_is_an_id_not_a_link():
    assert get_tidal_media_id("123") == "123"
    assert get_tidal_media_type("123") is False


def test_a_bare_u_is_kept_as_an_id():
    assert get_tidal_media_id("u") == "u"


def test_a_u_is_only_a_tail_after_a_media_id():
    # Without an id in front, "u" is the link's own id, never a suffix to drop.
    assert get_tidal_media_id("https://tidal.com/browse/track/u") == "u"
    assert get_tidal_media_type("https://tidal.com/browse/track/u") == MediaType.TRACK


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/track/123",
        "https://tidal.com.evil.example/track/123",
        "not-tidal.com/track/123",
        "https://[bad",
    ],
)
def test_a_foreign_or_malformed_url_reports_no_kind(url):
    assert get_tidal_media_type(url) is False


def test_malformed_input_does_not_raise_from_the_id_reader():
    assert get_tidal_media_id("https://[bad") == ""


@pytest.mark.parametrize(
    ("url", "media_id", "kind"),
    [
        ("https://tidal.com/browse/album/42", "42", MediaType.ALBUM),
        ("https://tidal.com/browse/album/42/u", "42", MediaType.ALBUM),
        ("https://tidal.com/browse/album/42/?utm=x#top", "42", MediaType.ALBUM),
        ("https://tidal.com/browse/video/7", "7", MediaType.VIDEO),
        ("https://tidal.com/browse/video/7/u/", "7", MediaType.VIDEO),
        ("https://tidal.com/browse/playlist/pl-1", "pl-1", MediaType.PLAYLIST),
        ("https://tidal.com/browse/playlist/pl-1/?u", "pl-1", MediaType.PLAYLIST),
        ("https://tidal.com/browse/mix/mx-1", "mx-1", MediaType.MIX),
        ("https://tidal.com/browse/mix/mx-1#top", "mx-1", MediaType.MIX),
        ("https://tidal.com/browse/artist/9", "9", MediaType.ARTIST),
        ("https://tidal.com/browse/artist/9/u", "9", MediaType.ARTIST),
    ],
)
def test_every_supported_kind_survives_the_share_tail(url, media_id, kind):
    assert get_tidal_media_type(url) == kind
    assert get_tidal_media_id(url) == media_id


def _provider() -> tuple[TidalProvider, SimpleNamespace]:
    tidal = SimpleNamespace(session=Mock(spec=Session))
    return TidalProvider(tidal), tidal


@pytest.mark.parametrize("url", TRACK_SHARE_LINKS)
def test_open_url_resolves_every_shared_track_tail(url):
    provider, tidal = _provider()
    track = Mock(name="track")
    tidal.session.track.return_value = track

    assert provider.open_url(url) is track
    tidal.session.track.assert_called_once_with("123", with_album=True)


def test_open_url_refuses_a_foreign_or_lookalike_host():
    provider, tidal = _provider()
    assert provider.open_url("https://example.com/track/123") is None
    assert provider.open_url("https://tidal.com.evil.example/track/123") is None
    tidal.session.track.assert_not_called()
