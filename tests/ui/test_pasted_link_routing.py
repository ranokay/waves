"""A pasted catalog link routes to open_url; a search that mentions a host does not.

The search field decides with the link's HOST, never a substring: a query
containing "tidal.com" is still a query, and a lookalike host is not a
provider's catalog. Covers the pure helper the slot calls; the QML paste
flow itself is pinned by test_search_paste_autosearch.py.
"""

from __future__ import annotations

import pytest

from waves.desktop.backend import _pasted_media_link


@pytest.mark.parametrize(
    "needle",
    [
        "https://tidal.com/browse/album/12345",
        "https://listen.tidal.com/album/12345",
        "tidal.com/browse/track/1",
        "listen.tidal.com/album/12345",
        "https://music.apple.com/us/album/x/12345",
        "music.apple.com/us/album/x/12345",
    ],
)
def test_a_catalog_link_is_recognised(needle):
    assert _pasted_media_link(needle) is True


@pytest.mark.parametrize(
    "needle",
    [
        "my tidal.com playlist",
        "the music.apple.com era",
        "tidal.com.evil.example/album/12345",
        "not-tidal.com/album/1",
        "evilapple.com/album/1",
        "example.com/album/1",
        "monolink amniotic",
        "https://example.com/?tidal.com/album/1",
    ],
)
def test_a_query_that_merely_mentions_a_host_is_not_a_link(needle):
    assert _pasted_media_link(needle) is False
