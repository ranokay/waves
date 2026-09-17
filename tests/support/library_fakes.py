"""Library-bridge stand-ins shared by the library scan tests.

``make_library_bridge`` binds the real WavesBridge scan methods onto a
minimal stand-in and opens a real per-root LibraryIndex, so the glue tests
exercise the per-root cache-file behaviour without mutagen or Qt.
"""

from __future__ import annotations

import os
import threading
from types import SimpleNamespace

from conftest import _InlinePool, _Signal

from waves.library_index import LibraryIndex, cache_file_for_root
from waves.waves_ui.backend import WavesBridge

_METHODS = (
    # Every emit the scan makes off the pool goes through this guard (a scan
    # can outlive the bridge on a quit), so the stub needs it to emit at all.
    "_emit_from_worker",
    "_rebuild_library_index",
    "_invalidate_library_index",
    "_library_scan_once",
    "_library_worker_scan",
    "_library_worker_probe",
    # Every publish swaps the index and the artist rollup derived from it
    # together, off the GUI thread; the slot keeps a lazy derive only for the
    # case where a publish lands between its two reads.
    "_publish_index",
    "_bump_library_stamp",
    "_artist_rollup",
    # The scan's index builder and the launch badge seed, extracted from
    # _rebuild_library_index so the seed can run at construction while the
    # sweep itself waits for the boot reveal; the rebuild's closures delegate
    # to them, so every scan in the library tests needs them bound.
    "_build_presence_indexes",
    "_sql_presence_indexes",
    "_dict_presence_indexes",
    "_seed_library_badges_job",
    "_seed_library_badges",
    "libraryAlbumPresence",
    "libraryTrackPresence",
    "artistLibraryPresence",
    # The three slots above route an unanswerable question through this one
    # guarded hop, which is a no-op unless the probe methods are bound too
    # (tests/library/test_library_probe_fallback.py binds them).
    "_library_probe_miss",
    "libraryIndexReady",
    "libraryStamp",
    "_library_root",
    # The Library section's file pages (ADR 0007, issue #222): the pane loads
    # them from the scan's own index, so the glue tests drive the real slots.
    "loadLibraryFiles",
    "loadMoreLibraryFiles",
    "_library_files_state",
    "_library_files_start",
    "_library_files_stale",
    "myMusicLibrary",
    "_waves_pref_bool",
    "rescanLibrary",
    "setWavesPref",
    "librarySource",
    "libraryDownloadFolder",
    "_library_bulk_skip_on",
    "downloadsInsideLibrary",
    "_path_inside_library",
    "_library_claims_album",
    "_library_claims_track",
    "_library_track_claim",
    # The MusicBrainz overlay rides inside the presence slot; the opt-in pref
    # defaults off in these stubs, so it answers pass-through (its own rules
    # are covered in tests/library/test_mb_overlay.py).
    "_mb_arbitrated",
    "_mb_arbiter_on",
    # The scan sizes its pools from this classifier's verdict; the real one
    # runs here (tmp_path is a local disk, so these glue tests scan at full
    # speed). Its own rules are covered in tests/library/test_library_watch_classify.py.
    "_library_root_is_local",
    "_library_root_locality",
    # The scan's TAIL: the watcher realignment and the coalescing read that
    # dispatches a trailing rebuild. Without them a dispatched scan dies on
    # an AttributeError in the Worker wrapper, leaving the coalescing untested.
    "_resolve_watch_set",
    # The share self-heal offers: both getattr-guard the backend machinery
    # they forward to, so on these stubs they are no-ops unless a test plants
    # a recorder.
    "_library_share_remount",
    "_library_share_alive",
    # Runs straight after every scan and returns 0 at once unless that scan
    # flagged a listing (see tests/library/test_smb_relist.py for its own guard).
    "_library_recover_untrusted",
)


class LibraryStub:
    pass


for _m in _METHODS:
    setattr(LibraryStub, _m, getattr(WavesBridge, _m))


def make_album_dir(base, rel, files):
    d = os.path.join(base, *rel.split("/"))
    os.makedirs(d, exist_ok=True)
    for name in files:
        open(os.path.join(d, name), "w").close()
    return d


def make_library_bridge(
    tmp_path,
    *,
    library_enabled=True,
    library_source="separate",
    library_folder="",
    download_base="",
    tagmap=None,
    path_tags=None,
    item_ids=None,
):
    # library_enabled defaults True HERE (the app's factory default is False)
    # because these are glue tests of an activated scan; the master-switch
    # gate itself has its own tests. ``tagmap`` answers per folder (the
    # album-level tests); ``path_tags`` answers per file and wins when given
    # (the per-track tests, whose files must differ).
    tagmap = tagmap or {}
    path_tags = path_tags or {}
    item_ids = item_ids or {}
    s = LibraryStub()
    s.threadpool = _InlinePool()
    s._waves_prefs = {
        "library_enabled": library_enabled,
        "library_source": library_source,
        "library_folder": library_folder,
        "library_bulk_skip": True,
    }
    s.settings = SimpleNamespace(data=SimpleNamespace(download_base_path=download_base), save=lambda: None)

    # The bridge's real _open_library_index resolves one cache file per root
    # (cache_file_for_root) and is re-invoked on a root change; mirror that
    # here with the test's fake tag readers kept across reopens, so the glue
    # tests exercise the per-root file behaviour without mutagen.
    def _reopen():
        return LibraryIndex(
            cache_file_for_root(str(tmp_path), s._library_root()),
            read_tags=(lambda p: path_tags.get(p)) if path_tags else (lambda p: tagmap.get(os.path.dirname(p))),
            read_item_id=lambda p: item_ids.get(p, ""),
        )

    s._open_library_index = _reopen
    s._library = _reopen()
    s._library_index = None
    s._library_track_index = None
    s._library_artist_index = {}
    s._library_artist_index_src = None
    s._presence_memo = {}
    s._presence_memo_src = None
    s._track_presence_memo = {}
    s._track_presence_memo_src = None
    s._library_index_building = False
    s._library_index_pending = False
    s._library_force_full_pending = False
    s._library_index_lock = threading.Lock()
    # The probe-by-name queue (bridge_library, "Probe by name"). Every
    # publish re-arms whatever a running scan made it defer, so the state
    # has to exist on every stub, not only the probe test's.
    s._library_scan_partial = False
    s._library_probe_memo = {}
    s._library_probe_inflight = set()
    s._library_probe_pending = {}
    s._library_probe_deferred = {}
    s._library_probe_draining = False
    s._library_probe_gate = threading.Lock()
    s._library_backfill_done = False
    s._library_scanning = None
    s._library_gen = 0
    s._library_scan_status = "unset"
    s._library_scan_progress = {}
    s._library_scan_read_t0 = 0.0
    # The Library section's file-page state (ADR 0007, issue #222).
    s._library_files_gen = {}
    s._library_files_loading = set()
    s.libraryPresenceChanged = _Signal()
    s.libraryScanStatusChanged = _Signal()
    s.librarySourceChanged = _Signal()
    s.libraryFilesLoaded = _Signal()
    s.libraryFilesMore = _Signal()
    # The change-of-source path tears down the file watcher and persists prefs;
    # both are Qt/disk side effects out of scope for this glue test, so stub them
    # to no-ops. _logged_in is False so nothing re-initialises Download.
    s._teardown_library_watch = lambda: None
    s._library_poll_in_flight = False
    s._save_waves_prefs = lambda: None
    s._save_settings = lambda: None
    s._logged_in = False
    # The scan tail asks the GUI thread to realign the file watcher via this
    # signal; in production it is connected to _sync_library_watch, here it is a
    # no-op recorder (the watcher is Qt-only and out of scope for this Qt-free glue
    # test, which is covered instead by test_library_watch_classify.py).
    s._librarySyncWatch = _Signal()
    return s


class ScandirStub:
    """A scandir stand-in: the entries are handed over as-is."""

    def __init__(self, entries):
        self._entries = entries

    def __enter__(self):
        return iter(self._entries)

    def __exit__(self, *a):
        return False


def fake_listing(monkeypatch, shape):
    """Replace os.scandir for the folders in ``shape`` ({dir: transform}) with
    the transform applied to the real entries; every other folder lists for
    real. A transform receives the real DirEntry list and returns the list the
    OS will be believed to have returned."""
    import waves.library_index as li

    real = os.scandir
    targets = {os.path.abspath(d): fn for d, fn in shape.items()}

    def fake(path=".", *a, **k):
        fn = targets.get(os.path.abspath(path))
        if fn is None:
            return real(path, *a, **k)
        with real(path, *a, **k) as it:
            entries = list(it)
        return ScandirStub(fn(entries))

    monkeypatch.setattr(li.os, "scandir", fake)
    return real
