"""Sign-out clears the spinner a superseded search worker latches, a rollup
whose failed member later lands ends green while a real failure stays red, and
withdrawing a row releases both of the marks it registered.
"""

from __future__ import annotations

from threading import Lock
from types import SimpleNamespace

from conftest import _Signal

from waves.desktop.backend import WavesBridge
from waves.providers import Capability


class _InlinePool:
    @staticmethod
    def start(worker, priority: int = 0):
        worker.fn()


# --------------------------------------------------------------------------- #
# sign-out during a search must not leave the spinner turning
# --------------------------------------------------------------------------- #
class _SearchStub:
    """The real search slot on the attributes it reads, nothing more."""

    search = WavesBridge.search
    _search_total = staticmethod(WavesBridge._search_total)
    _SEARCH_TTL = 60.0

    def __init__(self):
        self.threadpool = _InlinePool()
        self.statuses: list[str] = []
        self.busy: list[bool] = []
        self._logged_in = True
        self._search_gen = 0
        self._search_cache: dict = {}
        self._objs: dict = {"album": {}, "track": {}, "artist": {}}
        self._objs_lock = Lock()
        self.tidal = SimpleNamespace(session=object())
        # The fetch rides the Provider seam; the fake supersedes itself
        # mid-fetch.
        self.providers = {
            "tidal": SimpleNamespace(capabilities=frozenset({Capability.SEARCH}), search=self._superseded_search)
        }
        self.searchResults = _Signal()
        self.artistMetaLoaded = _Signal()

    def _superseded_search(self, needle):
        self._search_gen += 1  # what logout does to an in-flight search
        return {}

    def _set_status(self, text):
        self.statuses.append(text)

    def _set_busy(self, on):
        self.busy.append(bool(on))


def test_a_superseded_search_worker_cannot_clear_busy_itself():
    """The shape the sign-out fix has to answer for.

    Every generation-gated return in the search worker is a BARE return, and
    each of them sits above the _set_busy(False) at the end of work(). So a
    worker whose generation was bumped out from under it leaves busy exactly
    as it found it: whoever bumps the generation owns clearing the flag.
    """
    stub = _SearchStub()

    stub.search("anything")

    assert stub.busy == [True], "the worker returned without ever clearing what it set"


def _logout_stub(tmp_path):
    """A stub carrying every attribute logout touches, and nothing else."""
    stub = SimpleNamespace()
    stub.logout = WavesBridge.logout.__get__(stub, type(stub))
    stub.busy: list[bool] = []
    stub.statuses: list[str] = []
    stub.stopped = []
    stub.stopAll = lambda: stub.stopped.append(True)
    stub.tidal = SimpleNamespace(logout=lambda: None)
    stub._reset_tidal_session = lambda: None
    stub._set_logged_in = lambda value: None
    stub._set_busy = lambda on: stub.busy.append(bool(on))
    stub._set_status = lambda text: stub.statuses.append(text)
    for name in (
        "_lib_cache",
        "_lib_loading",
        "_lib_sort",
        "_fav_ids",
        "_browse_pages",
        "_browse_loading",
        "_category_pl",
        "_prefetch_unrecorded",
        "_album_tracks_inflight",
        "_album_tracks_unrecorded",
        "_item_fetch_ts",
        "_artist_cache",
        "_artist_loading",
        "_album_tracks_cache",
        "_edition_tracks_cache",
        "_lib_reval_ts",
        "_search_cache",
        "_artist_pop_cache",
    ):
        setattr(stub, name, {})
    stub._pending_lock = Lock()
    stub._prefetch_lock = Lock()
    stub._objs_lock = Lock()
    stub._pending_downloads = []
    stub._lib_epoch = 0
    stub._lib_gen = {}
    stub._browse_root_cache = None
    stub._browse_gen = 0
    stub._browse_reval_ts = 0.0
    stub._prefetch_key = None
    stub._prefetch_claimed = False
    stub._home_cache = {}
    stub._home_loading = set()
    stub._home_reval_ts = {}
    stub._media_lists_cache = {}
    stub._folder_tree = {}
    stub._tree_warm_waiting = []
    stub._search_gen = 0
    stub._objs = {"album": {}, "track": {}, "artist": {}, "playlist": {}, "video": {}, "mix": {}}
    stub._page_cache_path = str(tmp_path / "page_cache.json")
    return stub


def test_signing_out_clears_the_spinner_it_orphans(tmp_path):
    """logout bumps _search_gen (and _browse_gen), which is what strands the
    in-flight worker above its own _set_busy(False). Nothing else clears the
    flag, so the sign-out has to, or the spinner turns for the rest of the
    session and every later status reads as if something were still loading."""
    stub = _logout_stub(tmp_path)

    stub.logout()

    assert stub.busy and stub.busy[-1] is False, "sign-out left busy latched"
    assert stub.statuses[-1] == "Signed out"
    assert stub._search_gen == 1, "this is the bump that orphans the worker"


# --------------------------------------------------------------------------- #
# a member that failed and then landed is not a failure
# --------------------------------------------------------------------------- #
class _FolderBumpStub:
    _bump_folder_group = WavesBridge._bump_folder_group

    def __init__(self, group: dict):
        self._folder_groups = {"fold1": group}
        self._folder_lock = Lock()
        self._scan_gen = 0
        self.downloadProgress = _Signal()
        self.downloadState = _Signal()
        self.folderRemaining = _Signal()


class _ArtistBumpStub:
    _bump_artist_group = WavesBridge._bump_artist_group

    def __init__(self, group: dict):
        self._artist_groups = {"art1": group}
        self._artist_lock = Lock()
        self._scan_gen = 0
        self.downloadProgress = _Signal()
        self.downloadState = _Signal()


def _group(keys, weighted: bool):
    grp = {"keys": set(keys), "done": set(), "failed": set(), "prog": {}}
    if weighted:
        grp["weights"] = dict.fromkeys(keys, 1)
        grp["total"] = len(keys)
    return grp


def test_a_folder_rollup_that_recovers_ends_green():
    """A held-and-recovered playlist fails once (the folder went away) and then
    succeeds on the replay. The group's verdict is bool(grp["failed"]), so an
    add-only credit leaves the whole folder button red over a run in which
    every playlist is on disk."""
    stub = _FolderBumpStub(_group(("p1", "p2"), weighted=True))

    stub._bump_folder_group("p1", None, "failed")  # the share dropped out
    stub._bump_folder_group("p1", 100.0, "done")  # the replay landed it
    stub._bump_folder_group("p2", 100.0, "done")

    assert stub.downloadState.emits[-1] == ("fold1", "done"), stub.downloadState.emits
    assert ("fold1", 100.0) in stub.downloadProgress.emits


def test_a_discography_rollup_that_recovers_ends_green():
    stub = _ArtistBumpStub(_group(("al1", "al2"), weighted=False))

    stub._bump_artist_group("al1", None, "failed")
    stub._bump_artist_group("al1", 100.0, "done")
    stub._bump_artist_group("al2", 100.0, "done")

    assert stub.downloadState.emits[-1] == ("art1", "done"), stub.downloadState.emits


def test_a_member_that_really_failed_still_ends_red():
    """The other direction, or the guard would just hide every failure: an
    album that never came back keeps the discography red."""
    stub = _ArtistBumpStub(_group(("al1", "al2"), weighted=False))

    stub._bump_artist_group("al1", None, "failed")
    stub._bump_artist_group("al2", 100.0, "done")

    assert stub.downloadState.emits[-1] == ("art1", "failed")


# --------------------------------------------------------------------------- #
# a released row takes both of its marks with it
# --------------------------------------------------------------------------- #
class _RemoveStub:
    _remove_rows_where = WavesBridge._remove_rows_where
    _reindex_queue = WavesBridge._reindex_queue

    def __init__(self, rows):
        self._queue = list(rows)
        self._queue_lock = Lock()
        self._qdirty_removed: list[int] = []
        self._redownload_overrides: set[str] = set()
        self._library_claim_overrides: set[str] = set()
        # The third mark a withdrawn row gives up, alongside the two above.
        self._merge_plans: dict = {}
        # The held-download stash the withdrawal reads to tell a hold from a
        # give-up: all three marks above survive a withdrawal that is really a
        # hold. Nothing is held in these tests, so every mark is released.
        self._pending_downloads: list = []
        self._pending_lock = Lock()


def _row(qid: int, media_id: str, status: str = "queued"):
    return {"qid": qid, "media_id": media_id, "status": status, "idx": 0}


def test_withdrawing_a_row_releases_both_marks_it_registered():
    """registerRedownload marks the force AND the library-claim override, and
    downloadAlbumAnyway marks the second on its own. Releasing only the first
    leaves the album exempt from the library scan's bulk tag-claim gate for the
    rest of the session: the next click from anywhere downloads tracks the
    gate should have skipped, with nothing on screen to say why."""
    stub = _RemoveStub([_row(1, "al1")])
    stub._redownload_overrides.add("al1")
    stub._library_claim_overrides.add("al1")

    assert stub._remove_rows_where(lambda it: it["qid"] == 1) == [1]

    assert stub._redownload_overrides == set()
    assert stub._library_claim_overrides == set(), "the claim override outlived its row"


def test_a_retry_keeps_both_marks():
    """A RETRY re-queues the item before its old row is dropped, so a live row
    still holds both marks: closing the other half must not break it."""
    stub = _RemoveStub([_row(1, "al1", "failed"), _row(2, "al1", "queued")])
    stub._redownload_overrides.add("al1")
    stub._library_claim_overrides.add("al1")

    stub._remove_rows_where(lambda it: it["qid"] == 1)

    assert stub._redownload_overrides == {"al1"}
    assert stub._library_claim_overrides == {"al1"}
