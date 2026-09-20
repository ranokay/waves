"""The degraded verdict is measured against the quality the run ASKED for.

A delivery that matched the ask is not degraded, a delivery under it still is,
and a fetch with no ask recorded never is.
"""

from __future__ import annotations

from threading import Lock
from types import SimpleNamespace

from waves.desktop.backend import WavesBridge


def _bind(stub, name):
    return getattr(WavesBridge, name).__get__(stub, type(stub))


class _Stub:
    pass


def _ownership_stub():
    s = _Stub()
    s.recorded: list = []

    class _Store:
        def record(self, *a, **kw):
            s.recorded.append(kw)
            return 1

    s._ownership = _Store()
    s.settings = SimpleNamespace(data=SimpleNamespace(symlink_to_track=False))
    s._own_cache = {}
    s._own_cache_lock = Lock()
    s._evict_own_cache_locked = lambda *a, **k: None
    s._announce_ownership = lambda *a, **k: None
    s._note_download_base_ok = lambda *a, **k: None
    s._record_ownership = _bind(s, "_record_ownership")
    return s


def _record(stub, *, tier: str, requested: int, ceiling: int) -> dict:
    stub._ownership_event = None
    stub._record_ownership(
        {
            "id": "101",
            "path": "/music/Artist/Album/01 Song.flac",
            "quality": {"tier": tier, "requested_rank": requested, "ceiling_rank": ceiling},
        }
    )
    return stub.recorded[-1]


def test_a_delivery_that_matched_the_ask_is_not_a_degraded_attempt():
    """At LOSSLESS on a HI_RES release, TIDAL delivering LOSSLESS is TIDAL
    obeying, not TIDAL falling short."""
    s = _ownership_stub()

    assert _record(s, tier="LOSSLESS", requested=2, ceiling=3)["degraded"] is False


def test_a_delivery_under_the_ask_is_still_a_degraded_attempt():
    """Asked for HI_RES, served HIGH: the degraded verdict must still bite."""
    s = _ownership_stub()

    assert _record(s, tier="HIGH", requested=3, ceiling=3)["degraded"] is True


def test_a_delivery_with_no_ask_recorded_is_never_degraded():
    """An Atmos fetch carries no requested_rank (-1). Reading -1 as a rank the
    delivery fell short of would have counted every one of them."""
    s = _ownership_stub()

    assert _record(s, tier="LOSSLESS", requested=-1, ceiling=3)["degraded"] is False


def test_the_recorded_ask_is_the_one_the_degraded_verdict_used():
    """The verdict and the stored requested_rank must come from one read, or a
    later reader draws a different conclusion from the same row."""
    s = _ownership_stub()
    row = _record(s, tier="LOSSLESS", requested=2, ceiling=3)

    assert row["requested_rank"] == 2
    assert row["ceiling_rank"] == 3
