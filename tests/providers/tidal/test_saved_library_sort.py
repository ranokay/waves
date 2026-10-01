"""TIDAL saved-shelf ordering."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from waves.desktop.backend import WavesBridge

# ----- My Tidal sort -> tidalapi order enums -------------------------------
# The enum mapping lives in TidalProvider with the favorites reads;
# its verdicts are pinned in tests/providers/test_provider_seam.py. Here:
# the bridge's default-sort policy, still date-desc, as delivered through
# the seam.

try:
    from tidalapi.types import OrderDirection as _OrderDirection
except Exception:  # pragma: no cover - depends on installed tidalapi version
    _OrderDirection = None


@pytest.mark.skipif(_OrderDirection is None, reason="tidalapi has no ordered favourites")
def test_library_page_default_sort_is_date_desc():
    # A category with no explicit sort must still ASK tidalapi for date-added
    # descending. tidalapi's raw default is not date-added, so leaving it unset
    # made a tab's default "Recently added" show the wrong order and disagree
    # with the Home previews (which force date-desc).
    from tidalapi.types import AlbumOrder, OrderDirection

    from waves.providers.tidal import TidalProvider

    b = WavesBridge.__new__(WavesBridge)
    b._lib_sort = {}
    favorites = MagicMock()
    favorites.albums.return_value = []
    favorites.get_albums_count.return_value = 0
    b.tidal = MagicMock()
    b.tidal.session.user.favorites = favorites
    b.providers = {"tidal": TidalProvider(b.tidal)}

    rows, more = WavesBridge._library_page(b, "tidal", "albums", 0, 10)

    assert rows == [] and more is False
    _, kwargs = favorites.albums.call_args
    assert kwargs["order"] is AlbumOrder.DateAdded
    assert kwargs["order_direction"] is OrderDirection.Descending
