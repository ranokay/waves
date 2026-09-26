"""Signing out ends the downloads first, on the session that started them.

Every job is handed to the download pool at the moment it is queued, and the
signed-in check sits at that moment, never inside the running job. Signing
out must therefore abort the queue itself, not wait for the account to reject
items one at a time: a backlog left running fails one item at a time, for as
long as the queue is, which is exactly what someone switching to a second
account is trying to escape.

The stop is the STOP button's own, so nothing is lost: the rows stay, marked
stopped, and RETRY ALL picks them up on whichever account signs in next (the
Stopped section). What this pins is the order. The session object is
destroyed a few lines later, so the aborts have to be set before it goes.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from waves.desktop.backend import WavesBridge


def _bridge(tmp_path) -> MagicMock:
    """A stand-in holding only what ``logout`` reaches for.

    MagicMock answers the rest, so the test says nothing about the cache
    clearing around it and keeps working when that list changes.
    """
    bridge = MagicMock()
    bridge._objs = {"album": {}, "track": {}}
    bridge._page_cache_path = str(tmp_path / "pages.json")
    bridge._jobs.objs = {}
    bridge._merge_scanned = set()
    bridge._merge_plans = {}
    bridge._merge_plans_unbound = {}
    return bridge


def _order(bridge: MagicMock) -> list[str]:
    return [name for name, _args, _kwargs in bridge.mock_calls]


def test_signing_out_stops_the_downloads(tmp_path):
    bridge = _bridge(tmp_path)

    WavesBridge.logout(bridge)

    assert bridge.stopAll.called, "the queue was left running on the account being signed out of"


def test_the_stop_comes_before_the_session_is_torn_down(tmp_path):
    bridge = _bridge(tmp_path)

    WavesBridge.logout(bridge)
    order = _order(bridge)

    logout_calls = [i for i, name in enumerate(order) if name.endswith(".logout")]
    assert logout_calls, "the sign-out must tear the session down through the provider"
    assert all(order.index("stopAll") < i for i in logout_calls), "the aborts must be set while the session lives"
    assert order.index("stopAll") < order.index("_set_logged_in")


def test_signing_out_still_says_so(tmp_path):
    # The stop sets its own status; the sign-out's is the one that must stand.
    bridge = _bridge(tmp_path)

    WavesBridge.logout(bridge)

    assert bridge._set_status.call_args.args == ("Signed out",)


def test_signing_out_drops_the_queues_kept_objects_and_the_scan_marks(tmp_path):
    """RETRY downloads from the row's kept object, and a best-of-both scan is
    remembered per album: both are bound to the account being signed out
    of, so the next account must re-fetch by id and re-scan."""
    bridge = _bridge(tmp_path)
    bridge._jobs.objs = {"7": object()}
    bridge._merge_scanned = {"7"}

    WavesBridge.logout(bridge)

    assert bridge._jobs.objs == {}, "a RETRY on the next account would download under the old token"
    assert bridge._merge_scanned == set()
    assert bridge._unbind_merge_plans.called, "the plans still hold the dead session's Track objects"


def test_signing_out_unbinds_merge_plans_to_catalog_ids(tmp_path):
    """A best-of-both plan's Track objects die with the session; the ids
    survive so a RETRY on the next account rebinds through its own session
    instead of downloading under the old token."""
    bridge = _bridge(tmp_path)
    entry = SimpleNamespace(src=SimpleNamespace(id="123"), track_num=1, volume_num=1, identity_id="123")
    bridge._merge_plans = {"7": [entry]}
    bridge._merge_plans_unbound = {}

    WavesBridge._unbind_merge_plans(bridge)

    assert bridge._merge_plans == {}
    assert bridge._merge_plans_unbound["7"] == [("123", 1, 1, "123")]
