"""Dual Version rows share one media id in the rollups and the force set.

Two hazards, both about the first finisher acting alone:

1. Bulk rollup: artist/folder groups credit ``media_id`` done on the first
   row's terminal state, so a bulk action reports completion while the
   sibling Version still runs — and the group is deleted, so the sibling's
   later failure has nowhere to go. A terminal bump settles its groups
   only when no sibling row (or held replay) for the media is outstanding.
2. Redownload force: the first row's success discards the media-ID-scoped
   override while dispatch reads it per row, so the sibling builds
   unforced and an existing Version is skipped. The override survives
   until no sibling row remains.

Both pinned here by driving dual rows (two qids, one media id) through a
bound-stub bridge: group hold then settle for each group kind, failure
reach after a hold, held-replay outstanding, and the force release rule
with its hook delegation.
"""

from __future__ import annotations

from threading import Lock

from waves.desktop.backend import WavesBridge


class _Signal:
    def __init__(self):
        self.emits: list = []

    def emit(self, *args) -> None:
        self.emits.append(args)


class _Stub:
    """Enough bridge for the rollup bumps and the force release: the queue,
    the group maps with their locks, the override sets, and signal recorders."""

    def __init__(self):
        self._queue: list = []
        self._queue_lock = Lock()
        self._pending_downloads: list = []
        self._pending_lock = Lock()
        self._artist_groups: dict = {}
        self._folder_groups: dict = {}
        self._artist_lock = Lock()
        self._folder_lock = Lock()
        self._scan_gen = 0
        self._redownload_overrides: set = set()
        self._library_claim_overrides: set = set()
        self.downloadState = _Signal()
        self.downloadProgress = _Signal()
        self.folderRemaining = _Signal()


def _bind_all(stub):
    """Bind the bump family: _bump_download_groups reaches its two kinds
    through self, so the twins ride along."""
    for name in (
        "_bump_download_groups",
        "_bump_artist_group",
        "_bump_folder_group",
        "_media_work_outstanding",
        "_release_redownload_override",
    ):
        setattr(stub, name, getattr(WavesBridge, name).__get__(stub, type(stub)))


def _rows(*statuses):
    """Dual rows for one media id: qid 1 stereo, qid 2 atmos."""
    return [
        {"qid": 1, "media_id": "m1", "status": statuses[0], "audioType": "stereo"},
        {"qid": 2, "media_id": "m1", "status": statuses[1], "audioType": "atmos"},
    ]


def _grouped(stub):
    _bind_all(stub)
    stub._artist_groups = {"a1": {"keys": {"m1"}, "done": set(), "failed": set(), "prog": {}}}
    stub._folder_groups = {
        "f1": {"keys": {"m1"}, "done": set(), "failed": set(), "prog": {}, "weights": {"m1": 1}, "total": 1}
    }


def _bump(stub, state, pct=100.0):
    stub._bump_download_groups("m1", pct, state)


# --------------------------------------------------------------------------- #
# Bulk rollup: the first finisher holds settlement while its sibling is live.
# --------------------------------------------------------------------------- #
def test_first_finisher_holds_both_groups_while_the_sibling_runs():
    stub = _Stub()
    stub._queue = _rows("done", "queued")
    _grouped(stub)

    _bump(stub, "done")

    assert "a1" in stub._artist_groups and "f1" in stub._folder_groups
    assert ("a1", "done") not in stub.downloadState.emits
    assert ("f1", "done") not in stub.downloadState.emits
    assert stub._artist_groups["a1"]["prog"] == {"m1": 100.0}


def test_last_finisher_settles_both_groups_done():
    stub = _Stub()
    stub._queue = _rows("done", "running")
    _grouped(stub)
    _bump(stub, "done")
    assert "a1" in stub._artist_groups, "held while the sibling runs"

    stub._queue = _rows("done", "done")
    _bump(stub, "done")

    assert "a1" not in stub._artist_groups and "f1" not in stub._folder_groups
    assert ("a1", "done") in stub.downloadState.emits
    assert ("f1", "done") in stub.downloadState.emits


def test_sibling_failure_after_a_hold_fails_the_groups():
    """The held first finish must not swallow the sibling's later failure:
    the failure reaches the group result."""
    stub = _Stub()
    stub._queue = _rows("done", "running")
    _grouped(stub)
    _bump(stub, "done")
    assert ("a1", "failed") not in stub.downloadState.emits

    stub._queue = _rows("done", "failed")
    _bump(stub, "failed")

    assert ("a1", "failed") in stub.downloadState.emits
    assert ("f1", "failed") in stub.downloadState.emits


def test_held_replay_counts_as_outstanding_work():
    """A sibling held for recovery has no row: its stashed replay still
    holds settlement, and the replay's own bump settles."""
    stub = _Stub()
    stub._queue = []
    stub._pending_downloads = [("m1", lambda: None)]
    _grouped(stub)

    _bump(stub, "done")

    assert "a1" in stub._artist_groups and "f1" in stub._folder_groups

    stub._pending_downloads = []
    _bump(stub, "done")

    assert "a1" not in stub._artist_groups and "f1" not in stub._folder_groups
    assert ("a1", "done") in stub.downloadState.emits


def test_solo_member_settles_as_before():
    stub = _Stub()
    stub._queue = [{"qid": 1, "media_id": "m1", "status": "done"}]
    _grouped(stub)

    _bump(stub, "done")

    assert "a1" not in stub._artist_groups and "f1" not in stub._folder_groups
    assert ("a1", "done") in stub.downloadState.emits


# --------------------------------------------------------------------------- #
# Redownload force: the override survives until no sibling row remains.
# --------------------------------------------------------------------------- #
def _release(stub, media_id="m1", qid=1):
    _bind_all(stub)
    return stub._release_redownload_override(media_id, qid)


def test_force_survives_while_a_sibling_row_is_live():
    stub = _Stub()
    stub._queue = _rows("done", "queued")
    stub._redownload_overrides = {"m1"}
    stub._library_claim_overrides = {"m1"}

    _release(stub, "m1", 1)

    assert stub._redownload_overrides == {"m1"}
    assert stub._library_claim_overrides == {"m1"}


def test_force_drops_once_no_sibling_row_remains():
    stub = _Stub()
    stub._queue = _rows("done", "done")
    stub._redownload_overrides = {"m1"}
    stub._library_claim_overrides = {"m1"}

    _release(stub, "m1", 2)

    assert stub._redownload_overrides == set()
    assert stub._library_claim_overrides == set()


def test_held_replay_keeps_the_force_for_its_return():
    stub = _Stub()
    stub._queue = []
    stub._pending_downloads = [("m1", lambda: None)]
    stub._redownload_overrides = {"m1"}

    _release(stub, "m1", 1)

    assert stub._redownload_overrides == {"m1"}, "the replay re-reads the force when it builds"


def test_media_hook_delegates_to_the_same_rule():
    """The Apple runner's media_work_outstanding hook answers the backend
    rule, so both pipelines share one definition of outstanding."""
    stub = _Stub()
    _bind_all(stub)
    stub._queue = _rows("done", "queued")
    hooks = WavesBridge._apple_job_hooks.__get__(stub, type(stub))()

    assert hooks.media_work_outstanding("m1", 1) is True

    stub._queue = _rows("done", "done")
    assert hooks.media_work_outstanding("m1", 2) is False
