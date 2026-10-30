"""The FLAC signature check's run state (Settings, Advanced).

A FLAC file whose header carries no audio signature fails ``flac -t`` and is
refused by strict players even though its audio is intact (see
:mod:`waves.flac_verify` for the format detail and the read/seal guarantees,
and :mod:`waves.library.flac_check` for the walk, verdict store, reports and
fix loop). This module is the composed run-state owner the bridge forwards
to: the scope the card selects, the progress and outcome a run posts, the
resume marker an unfinished fix leaves, and the report a run writes.

It is deliberately Qt-free. ``WavesBridge`` owns the slots and signals and
constructs this object with explicit callbacks: a worker dispatcher, a
GUI-thread post, a reveal, the ffmpeg path, the roots to walk, the prefs
mapping and the factory-reset state. Nothing here imports ``backend``.

Scope, chosen on the card and remembered as Waves prefs:

* ``flac_check_source == "waves"`` (the default): the Waves library, meaning
  the download folder plus the library folder when the library scan is on
  and configured (the same two folders the ownership badge may look at).
* ``flac_check_source == "folder"``: the one folder in ``flac_check_folder``,
  which only ever comes from the system folder dialog on the card.

Nothing else is ever walked, and a link that points outside the chosen
folders is skipped by the walk. A fix acts only on the rows of the last scan,
and only while the selection still names the folders that scan walked.

A fix that stops before it finishes (the app quit or crashed, or the user
cancelled) is remembered in the ``flac_check_resume`` pref, the scope key of
the folders it was writing in. RESUME on the card selects those folders
again, scans them, and fixes what the scan finds: a file the earlier fix
signed reads as signed, so the run picks up where the other left off. Never
started on its own: a fix that crashed the app would otherwise crash it again
on every launch.

Threading: the public methods run on the GUI thread and only move state
there. The work runs through ``start`` (the bridge's threadpool), posts
progress and its outcome through ``post`` (queued to the GUI thread), and
each run carries a generation stamp so a stale worker's events are dropped.
One run at a time: a slot called while one is running is a no-op.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sqlite3
import sys
import threading
import time
from collections.abc import Callable

from waves import flac_verify as fv
from waves import redaction
from waves.library import flac_check as core

logger = logging.getLogger("waves.flac")

# Progress events are rate-limited to one per this many seconds: a header
# scan reads thousands of files a second, and each event re-renders a card.
_PROGRESS_MIN_S = 0.25
# The time left is offered once a run has been going this long: before that
# the pace is one or two files, and one long track would skew it.
_ETA_MIN_S = 5.0
# Reports go under the config folder, next to the logs, never into a music
# folder (the factory wipe knows this folder).
REPORTS_DIR = "reports"

SOURCE_WAVES = "waves"
SOURCE_FOLDER = "folder"


def idle_state() -> dict:
    return {
        "phase": "idle",  # idle | scanning | fixing | done | cancelled | failed
        "running": False,
        "mode": "header",  # header | deep (what the last scan did)
        "last": "",  # scan | fix: which run the counts describe
        "files": 0,  # files worked through so far (a fix: candidates only)
        "total": 0,  # files the run works through; 0 while a scan is still walking the folders
        "found": 0,  # files the walk has found so far (a scan, before total is known)
        "eta": -1,  # seconds left at the pace so far; -1 while there is no pace to go by
        "counts": {},  # status -> count (waves.flac_verify statuses)
        "fixable": 0,  # files a fix would act on (UNSET rows of the last scan)
        "report": "",  # path of the last report written ("" = none)
        "roots": 0,  # folders walked
        "ffmpeg": False,  # a decoder was available when the run started
        "error": "",
        "scope": "",  # the folders the last scan walked, as a key (see _scope)
        # Folders (selected or below) the last scan could not open or list:
        # their files were not checked. A fix carries its scan's figure.
        "folders_unreadable": 0,
        # Files whose verdict an earlier scan had already found (unchanged
        # since, so not read again; see core.VerdictCache).
        "cached": 0,
    }


def _time_left(elapsed: float, done: float, total: float) -> int:
    """Seconds left at the pace so far, or -1 until there is a pace to go by."""
    if total <= 0 or done <= 0 or done >= total or elapsed < _ETA_MIN_S:
        return -1
    return round(elapsed * (total - done) / done)


def _scope_roots(key: str) -> list[str]:
    """The folders a scope key names (see FlacCheck._scope)."""
    source, _sep, rest = key.partition(":")
    if source == SOURCE_FOLDER:
        return [rest] if rest else []
    return [r for r in rest.split("\n") if r]


def _under_any(folder: str, parents: list[str]) -> bool:
    folder = os.path.normpath(folder)
    for parent in parents:
        parent = os.path.normpath(parent)
        if folder == parent or folder.startswith(parent.rstrip(os.sep) + os.sep):
            return True
    return False


def _unopened(chosen: bool, roots: int) -> str:
    """What the card says when none of the selected folders could be opened."""
    if chosen:
        return "The chosen folder could not be opened."
    if roots == 1:
        return "The Waves library folder could not be opened."
    return "The Waves library folders could not be opened."


class _Progress:
    """What a running scan or fix posts to the card: counts per status, the
    files worked through out of the total, and the time left. Rate-limited.

    The time left is the elapsed time scaled by the work still to do. A scan
    weighs every file the same; a fix weighs each by its size (``sizes``),
    since a long hi-res track takes many times what a short one does."""

    def __init__(self, post, total: int = 0, sizes: dict[str, int] | None = None) -> None:
        self._post = post
        self._sizes = sizes
        self._counts: dict[str, int] = {}
        self._seen = 0
        self._done = 0
        self._total = sum(sizes.values()) if sizes else total
        self._started = time.monotonic()
        self._last = 0.0

    def _due(self) -> bool:
        now = time.monotonic()
        if now - self._last < _PROGRESS_MIN_S:
            return False
        self._last = now
        return True

    def on_walk(self, found: int, done: bool) -> None:
        """The scan's walk: files found so far, then the total. The time left
        counts from the end of the walk, the first file read."""
        if done:
            self._total = found
            self._started = time.monotonic()
            self._post({"found": found, "total": found})
        elif self._due():
            self._post({"found": found})

    def on_row(self, verdict: core.Verdict) -> None:
        self._seen += 1
        self._counts[verdict.status] = self._counts.get(verdict.status, 0) + 1
        self._done += self._sizes.get(verdict.path, 0) if self._sizes else 1
        if verdict.status == fv.SEALED:
            logger.info("FLAC check: signature written: %s", redaction.content(os.path.basename(verdict.path)))
        elif verdict.status in (
            fv.MISMATCH,
            fv.LENGTH_DIFFERS,
            fv.WRITE_FAILED,
            fv.DECODE_FAILED,
        ):
            logger.warning(
                "FLAC check: %s: %s",
                core.STATUS_LABELS[verdict.status],
                redaction.content(os.path.basename(verdict.path)),
            )
        if self._due():
            eta = _time_left(time.monotonic() - self._started, self._done, self._total)
            self._post({"files": self._seen, "counts": dict(self._counts), "eta": eta})


class FlacCheck:
    """The FLAC check's state and work, driven by explicit callbacks.

    ``waves_roots`` returns the download folder and the library folder (the
    latter empty while the library scan is off). ``ffmpeg`` returns the
    decoder path ("" when none). ``start(fn, *args)`` dispatches a worker.
    ``post(gen, fields)`` hands state fields to the GUI thread. ``reveal``
    shows a path in the file manager. ``factory_reset`` reports the bridge's
    wipe latch. ``prefs`` is the live waves.json mapping and ``save_prefs``
    persists it.
    """

    def __init__(
        self,
        config_dir: str,
        *,
        waves_roots: Callable[[], list[str]],
        ffmpeg: Callable[[], str],
        post: Callable[[int, dict], None],
        start: Callable[..., None],
        reveal: Callable[[str], None],
        factory_reset: Callable[[], bool],
        prefs: dict,
        save_prefs: Callable[[], None],
    ) -> None:
        self._config_dir = config_dir
        self._waves_roots_cb = waves_roots
        self._ffmpeg_cb = ffmpeg
        self._post_cb = post
        self._start = start
        self._reveal = reveal
        self._factory_reset = factory_reset
        self._prefs = prefs
        self._save_prefs = save_prefs
        self._gen = 0
        self._cancel = threading.Event()
        # Clear while a scan holds the remembered verdicts open: a factory
        # reset waits on it so the wipe can take the file (Windows refuses
        # to delete a file that is open).
        self._cache_free = threading.Event()
        self._cache_free.set()
        self._rows: list[core.Verdict] = []
        self._unreadable: list[str] = []  # the folders the scan behind the rows could not read
        self._result: tuple[int, list[core.Verdict], list[str]] = (0, [], [])
        self._state = idle_state()
        self._resuming = False  # a RESUME's scan is on; its outcome starts the fix
        # The running fix inherits an unfinished fix's marker: finishing it
        # does not finish what the other left in a folder this one missed.
        self._keep_resume = False
        # The folders the scan behind the marker's fix could not read (that
        # fix never wrote there); None when the marker predates this launch.
        self._resume_unread: list[str] | None = None

    # ---- what the card reads ---------------------------------------------

    def state(self) -> dict:
        """The check's current state, a plain dict (see :func:`idle_state`),
        plus the fix RESUME would pick up: ``resume_source`` ("waves",
        "folder", or "" when there is none) and ``resume_folders``, and
        ``reports``: whether any report is on disk for VIEW REPORTS to show."""
        state = dict(self._state)
        state["reports"] = core.has_report(self._report_dir())
        state["counts"] = dict(state.get("counts") or {})
        target = self._resume_target()
        state["resume_source"] = target[0] if target else ""
        state["resume_folders"] = list(target[2]) if target else []
        return state

    # ---- the folders and the decoder -------------------------------------

    def _waves_roots(self) -> list[str]:
        """The Waves library: the download folder plus the library folder when
        one is configured and the library scan is on."""
        return core.effective_roots(self._waves_roots_cb())

    def _scope(self) -> tuple[str, str, list[str], str]:
        """What the card's selection names: (source, scope key, roots, error).
        The key names the folders exactly, so a scan's rows can be matched to
        the selection later; ``error`` is set (and roots empty) when there is
        nothing to walk. Nothing is stat'ed here (GUI thread)."""
        if self._prefs.get("flac_check_source") == SOURCE_FOLDER:
            folder = str(self._prefs.get("flac_check_folder") or "").strip()
            if not folder or not os.path.isabs(folder):
                return SOURCE_FOLDER, "", [], "Choose a folder first."
            return SOURCE_FOLDER, f"{SOURCE_FOLDER}:{folder}", [folder], ""
        roots = self._waves_roots()
        if not roots:
            return SOURCE_WAVES, "", [], "Set a download folder first."
        return SOURCE_WAVES, f"{SOURCE_WAVES}:" + "\n".join(roots), roots, ""

    def _resume_target(self) -> tuple[str, str, list[str]] | None:
        """The fix that stopped before it finished, as (source, chosen folder,
        folders), or None. A Waves library fix whose folders have moved since
        is not offered: a scan of the new folders is a new start, not a
        resume. Nothing is stat'ed here (GUI thread)."""
        marker = str(self._prefs.get("flac_check_resume") or "")
        source, _sep, rest = marker.partition(":")
        if source == SOURCE_FOLDER and os.path.isabs(rest):
            return SOURCE_FOLDER, rest, [rest]
        if source == SOURCE_WAVES:
            roots = self._waves_roots()
            if roots and marker == f"{SOURCE_WAVES}:" + "\n".join(roots):
                return SOURCE_WAVES, "", roots
        return None

    def _ffmpeg(self) -> str:
        with contextlib.suppress(Exception):
            return self._ffmpeg_cb() or ""
        return ""

    def _report_dir(self) -> str:
        return os.path.join(self._config_dir, REPORTS_DIR)

    def _cache_path(self) -> str:
        return os.path.join(self._config_dir, core.CACHE_NAME)

    # ---- the folder choice (remembered) ----------------------------------

    def sources(self) -> dict:
        """What the card's folder row shows: the selected source ("waves" or
        "folder"), the chosen folder, the scope key the selection names (the
        card compares it with state().scope), and the Waves library folders a
        "waves" scan would walk."""
        source, key, _roots, _error = self._scope()
        return {
            "source": source,
            "folder": str(self._prefs.get("flac_check_folder") or ""),
            "key": key,
            "waves": self._waves_roots(),
        }

    def _set_pref(self, key: str, value: str) -> bool:
        if self._prefs.get(key) == value:
            return False
        self._prefs[key] = value
        self._save_prefs()
        return True

    def set_source(self, source: str) -> bool:
        """Choose what the next scan walks: "waves" (the Waves library) or
        "folder" (the folder picked with Browse). Ignored while a run is on.
        Returns whether the choice moved."""
        if self._state.get("running") or source not in (SOURCE_WAVES, SOURCE_FOLDER):
            return False
        return self._set_pref("flac_check_source", source)

    def set_folder(self, folder: str) -> bool:
        """Remember the folder the system dialog returned and select it. Only
        an absolute path is taken; ignored while a run is on. Returns whether
        anything moved."""
        folder = (folder or "").strip()
        if self._state.get("running") or not folder or not os.path.isabs(folder):
            return False
        moved = self._set_pref("flac_check_folder", folder)
        return self._set_pref("flac_check_source", SOURCE_FOLDER) or moved

    # ---- the runs (GUI thread) -------------------------------------------

    def _begin(self, phase: str, **fields) -> int:
        """Stamp a new run, clear the cancel flag and publish its start."""
        self._gen += 1
        self._cancel.clear()
        self._state.update(idle_state() | {"phase": phase, "running": True} | fields)
        return self._gen

    def _fail(self, error: str) -> None:
        self._state.update({"phase": "failed", "running": False, "error": error})

    def scan(self, deep: bool = False, recheck: bool = False) -> None:
        """Walk the selected folders and read every FLAC header (``deep`` also
        decodes each file and compares). A file unchanged since an earlier
        scan takes that scan's verdict unless ``recheck`` asks for every file
        to be read again. Reads only; writes one CSV report under the config
        folder when done."""
        if self._state.get("running"):
            return
        source, key, roots, error = self._scope()
        if error:
            self._fail(error)
            return
        ffmpeg = self._ffmpeg()
        if deep and not ffmpeg:
            self._fail("A deep check needs FFmpeg (see the Processing section).")
            return
        gen = self._begin(
            "scanning", mode="deep" if deep else "header", roots=len(roots), ffmpeg=bool(ffmpeg), scope=key
        )
        self._rows = []
        self._unreadable = []
        logger.info(
            "FLAC check: %s scan of %d folder(s) started (%s%s)",
            "deep" if deep else "header",
            len(roots),
            "chosen folder" if source == SOURCE_FOLDER else "Waves library",
            ", every file read again" if recheck else "",
        )
        self._start(self._scan_job, gen, roots, ffmpeg, bool(deep), source == SOURCE_FOLDER, bool(recheck))

    def fix(self) -> None:
        """Write the signature into the files the last scan found without one.
        Each is re-read, decoded and checked again right before its 34 header
        bytes are written (see :func:`waves.flac_verify.seal_file`); nothing
        else in any file is touched, and a file with a signature is never
        rewritten."""
        if self._state.get("running"):
            return
        rows = list(self._rows)
        if not any(v.status == fv.UNSET for v in rows):
            return
        # The rows belong to the folders the last scan walked; once the card
        # names other folders, writing into those rows is not what the user
        # is looking at, so the fix waits for a scan of the selection. Said
        # on the card (the bridge emits after this slot): a folder changed
        # elsewhere in Settings while the card was open would otherwise leave
        # FIX offered and silently doing nothing.
        _source, key, _roots, _error = self._scope()
        scanned = self._state.get("scope") or ""
        if not key or key != scanned:
            logger.info("FLAC check: fix skipped, the folder selection changed since the scan")
            self._fail("The folders changed since the scan. Scan again first.")
            return
        ffmpeg = self._ffmpeg()
        if not ffmpeg:
            self._fail("Writing signatures needs FFmpeg (see the Processing section).")
            return
        candidates = sum(v.status == fv.UNSET for v in rows)
        unreadable = list(self._unreadable)
        # fixable stays the candidate count while the fix runs; the outcome
        # replaces it with what is left. total is what "Writing N of M" reads.
        gen = self._begin(
            "fixing",
            mode=self._state.get("mode", "header"),
            ffmpeg=True,
            fixable=candidates,
            total=candidates,
            scope=key,
            folders_unreadable=len(unreadable),
        )
        # Remembered until the fix finishes, so a quit or a crash part way
        # leaves RESUME on the card (cleared in _settled). An unfinished
        # fix's marker outlives this one when the scan missed folders that
        # fix could have written in (see _missed).
        prior = str(self._prefs.get("flac_check_resume") or "")
        self._keep_resume = prior == key
        if prior != key:
            self._resume_unread = list(unreadable)
        self._set_pref("flac_check_resume", key)
        logger.info("FLAC check: fix of %d file(s) started", candidates)
        self._start(self._fix_job, gen, rows, ffmpeg, candidates, unreadable)

    def resume(self) -> None:
        """Pick up the fix that stopped before it finished: select the folders
        it was writing in, scan them again, and fix what that scan finds (a
        file it already signed reads as signed). Nothing to resume, or a run
        on: a no-op."""
        if self._state.get("running"):
            return
        target = self._resume_target()
        if target is None:
            return
        source, folder, _roots = target
        if source == SOURCE_FOLDER:
            self._set_pref("flac_check_folder", folder)
        self._set_pref("flac_check_source", source)
        logger.info("FLAC check: resuming the last fix")
        self._resuming = True
        self.scan(False)
        if not self._state.get("running"):
            # The scan was refused (no folder): it said so, and nothing follows.
            self._resuming = False

    def cancel(self) -> None:
        """Stop the running scan or fix after the file it is on. A fix never
        leaves a file half-written: the header write is one 34-byte call."""
        if self._state.get("running"):
            self._cancel.set()

    def supersede(self) -> None:
        """(GUI thread, factory reset) Discard the running run's outcome and
        ask it to stop after the file it is on."""
        self._gen += 1
        self._cancel.set()

    def reveal_reports(self) -> None:
        """Show the reports folder in the file manager, at any time (a scan
        may be running); nothing when no report has been written yet. On
        macOS Finder selects the newest report in it; elsewhere the folder
        opens (handing a report itself over would open it in a spreadsheet)."""
        folder = self._report_dir()
        path = core.newest_report(folder)
        if path:
            self._reveal(path if sys.platform == "darwin" else folder)

    # ---- the workers (pool thread) ---------------------------------------

    def _post(self, gen: int, fields: dict) -> None:
        """Hand state fields to the GUI thread."""
        self._post_cb(gen, fields)

    def _alive(self, gen: int):
        return lambda: not self._cancel.is_set() and self._gen == gen

    def _progress(self, gen: int, total: int = 0, sizes: dict[str, int] | None = None) -> _Progress:
        """The run's progress poster (see _Progress)."""
        return _Progress(lambda fields: self._post(gen, fields), total, sizes)

    def _finish(
        self,
        gen: int,
        kind: str,
        rows: list[core.Verdict],
        cancelled: bool,
        files: int | None = None,
        unreadable: list[str] | None = None,
    ) -> None:
        """Write the report, park the rows for a fix, publish the outcome.
        ``files`` is what the run worked on (a fix: its candidates; a scan:
        every row), the number the card's note reports. ``unreadable`` is
        the folders the scan could not read (listed in the report)."""
        unreadable = list(unreadable or [])
        report = ""
        # No report once a factory reset is under way (it wipes the config
        # folder, and a report lists every file the run saw) or once a newer
        # run has taken over; the outcome is dropped at the event handler too.
        if self._factory_reset() or gen != self._gen:
            logger.info("FLAC check: %s outcome dropped, the run was superseded", kind)
        else:
            try:
                report = core.write_new_report(self._report_dir(), kind, rows, unreadable)
            except Exception:
                logger.exception("FLAC check: the report could not be written")
        counts = core.summarize(rows)
        total = counts.pop("files", 0)
        self._result = (gen, rows, unreadable)
        logger.info(
            "FLAC check: %s %s: %d file(s), %d without a signature, %d written, %d mismatched, %d folder(s) unread",
            kind,
            "cancelled" if cancelled else "finished",
            total,
            counts.get(fv.UNSET, 0),
            counts.get(fv.SEALED, 0),
            counts.get(fv.MISMATCH, 0),
            len(unreadable),
        )
        self._post(
            gen,
            {
                "final": True,
                "phase": "cancelled" if cancelled else "done",
                "running": False,
                "last": kind,
                "files": total if files is None else files,
                "eta": -1,
                "counts": counts,
                "fixable": counts.get(fv.UNSET, 0),
                "report": report,
                "folders_unreadable": len(unreadable),
                "cached": sum(v.cached for v in rows) if kind == "scan" else 0,
            },
        )

    def cache_busy_event(self) -> threading.Event:
        """The event a factory reset waits on: clear while a scan holds the
        remembered verdicts open."""
        return self._cache_free

    def _open_cache(self) -> core.VerdictCache | None:
        """(worker) What earlier scans found, or None: none during a factory
        reset (the wipe takes the file), and none when it cannot be opened
        (the scan then reads every file). Clears the busy event BEFORE
        looking at the reset flag, so a reset either sees the cache busy and
        waits, or this sees the flag and opens nothing."""
        free = self._cache_free
        free.clear()
        cache = self._open_cache_file()
        if cache is None:
            free.set()
        return cache

    def _close_cache(self, cache: core.VerdictCache | None) -> None:
        """(worker) Close the remembered verdicts and mark them free. The file
        is deleted when a read found it damaged (the next scan starts it
        over) or when a factory reset came while it was open."""
        try:
            if cache is None:
                return
            cache.close()
            reset = self._factory_reset()
            if cache.damaged or reset:
                if cache.damaged and not reset:
                    logger.warning("FLAC check: the remembered verdicts were damaged; starting them over")
                self.delete_cache()
        finally:
            self._cache_free.set()

    def _open_cache_file(self) -> core.VerdictCache | None:
        if self._factory_reset():
            return None
        path = self._cache_path()
        for attempt in (1, 2):
            try:
                return core.VerdictCache(path)
            except (sqlite3.Error, OSError) as exc:
                # "Not a database" (a crash mid-write, a bad sector): the file
                # only holds what earlier scans found, so it is started over
                # once. Any other failure (locked, a folder that cannot be
                # written) leaves it be.
                if attempt == 1 and type(exc) is sqlite3.DatabaseError:
                    logger.warning("FLAC check: the remembered verdicts were damaged; starting them over")
                    with contextlib.suppress(OSError):
                        os.remove(path)
                    continue
                logger.warning("FLAC check: the remembered verdicts could not be opened; every file is read this run")
                return None
        return None

    def delete_cache(self) -> None:
        """Remove the remembered verdicts and sqlite's sidecars, best effort."""
        for suffix in ("", "-journal", "-wal", "-shm"):
            with contextlib.suppress(OSError):
                os.remove(self._cache_path() + suffix)

    def _scan_job(
        self, gen: int, roots: list[str], ffmpeg: str, deep: bool, chosen: bool = False, recheck: bool = False
    ) -> None:
        alive = self._alive(gen)
        rows: list[core.Verdict] = []
        unreadable: list[str] = []
        cache = self._open_cache()
        try:
            # Every folder is opened here, on the worker: a share that stopped
            # answering can hang the first look for the mount's timeout.
            progress = self._progress(gen)
            rows = core.scan(
                roots,
                ffmpeg,
                deep=deep,
                should_continue=alive,
                on_row=progress.on_row,
                on_walk=progress.on_walk,
                unreadable=unreadable,
                cache=cache,
                recheck=recheck,
            )
        except Exception:
            logger.exception("FLAC check: the scan failed")
            self._post(gen, {"phase": "failed", "running": False, "error": "The scan failed; see the log."})
            return
        finally:
            self._close_cache(cache)
        if unreadable:
            logger.warning(
                "FLAC check: %d folder(s) could not be opened, their files were not checked", len(unreadable)
            )
        if roots and all(r in unreadable for r in roots) and alive():
            # Nothing could be walked (a drive unplugged, a share down, a
            # folder the system will not let Waves list): said so instead of
            # reporting an empty, clean scan.
            self._post(gen, {"phase": "failed", "running": False, "error": _unopened(chosen, len(roots))})
            return
        self._finish(gen, "scan", rows, cancelled=not alive(), unreadable=unreadable)

    def _fix_job(
        self, gen: int, rows: list[core.Verdict], ffmpeg: str, candidates: int, unreadable: list[str] | None = None
    ) -> None:
        alive = self._alive(gen)
        sizes = {v.path: max(v.size, 0) for v in rows if v.status == fv.UNSET}
        try:
            out = core.fix_rows(
                rows,
                ffmpeg,
                should_continue=alive,
                on_row=self._progress(gen, candidates, sizes).on_row,
                # Read at call time, so the settle window is one knob.
                settle_seconds=core.SETTLE_SECONDS,
            )
        except Exception:
            logger.exception("FLAC check: the fix failed")
            self._post(gen, {"phase": "failed", "running": False, "error": "The fix failed; see the log."})
            return
        self._finish(gen, "fix", out, cancelled=not alive(), files=candidates, unreadable=unreadable)

    # ---- back on the GUI thread ------------------------------------------

    def on_event(self, gen: int, fields: dict) -> None:
        """(GUI thread) Merge a worker's fields into the state; a stale run's
        events (a newer run has started) are dropped."""
        if gen != self._gen:
            return
        fields = dict(fields)
        final = fields.pop("final", False)
        if final:
            result_gen, rows, unreadable = self._result
            if result_gen == gen:
                self._rows = rows
                self._unreadable = unreadable
        self._state.update(fields)
        if not self._state.get("running"):
            self._settled(final)

    def _settled(self, final: bool) -> None:
        """(GUI thread) A run ended. A fix that finished, or a scan of the
        same folders that finds nothing left to fix, drops the resume marker;
        a cancelled or failed run keeps it, and so does a scan that could not
        read a folder the unfinished fix could have written in (what it left
        there was never looked at) or a fix that inherited the marker over
        such a scan. A RESUME's scan goes on to the fix when it found files
        still without a signature."""
        resuming, self._resuming = self._resuming, False
        inherited, self._keep_resume = self._keep_resume, False
        st = self._state
        if not final or st.get("phase") != "done":
            return
        marker = str(self._prefs.get("flac_check_resume") or "")
        scope = str(st.get("scope") or "")
        missed = self._missed(scope)
        # A fix inherits only what it missed; a scan also needs nothing left.
        finished = not (inherited and missed) if st.get("last") == "fix" else not (st.get("fixable") or missed)
        if marker and marker == scope and finished:
            self._resume_unread = None
            self._set_pref("flac_check_resume", "")
        if resuming and st.get("last") == "scan" and st.get("fixable"):
            self.fix()

    def _missed(self, scope: str) -> bool:
        """(GUI thread) Whether the last run could not read a folder the
        unfinished fix could have written in. A folder the scan behind that
        fix could not read either never held its work; when that scan is not
        known (the marker is from before this launch), only a selected folder
        that did not open counts, so a folder no scan can ever list (a drive
        root's ``lost+found``) cannot hold RESUME on the card for good."""
        unreadable = list(self._unreadable)
        if not unreadable:
            return False
        before = self._resume_unread
        if before is None:
            return any(_under_any(r, unreadable) for r in _scope_roots(scope))
        return any(not _under_any(u, before) for u in unreadable)
