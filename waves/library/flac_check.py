"""Scanning a music folder for FLAC signatures, remembering verdicts and
fixing the files that have none.

The format detail and the read/seal guarantees live in
:mod:`waves.flac_verify`; this module is the library side built on them: the
folder walk, the verdicts an earlier scan already found, the CSV reports and
the fix loop. It is Qt-free (the desktop bridge and the download engine call
it from their own threads), so the tests drive it with plain files.

What it guarantees:

1. A scan reads. The header scan opens each file for reading and reads a few
   dozen bytes; the deep check additionally decodes the audio through ffmpeg.
   Nothing in a music folder is written; what a scan found may be remembered
   under the config folder (see :class:`VerdictCache`), so the next scan
   reads only what changed.
2. The fix only ever fills in an UNSET signature, and only after the audio
   decoded cleanly to the length the header states (or the length the file's
   last frame proves). A signature that is set and does not match, a file
   whose audio and header disagree, and a file that changed since the read
   are reported and left alone (see :func:`waves.flac_verify.seal_file`).
3. Every run can write a CSV report naming every file it saw, plus a line for
   each folder the walk could not read. Reports never replace one another.
"""

from __future__ import annotations

import contextlib
import csv
import logging
import os
import pathlib
import re
import sqlite3
import time
from collections import deque
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, replace

from waves import flac_verify as fv
from waves.library.ownership import path_under

logger = logging.getLogger("waves.flac")

# A file written more recently than this is left for the next run: it may
# still be arriving (a copy in progress has a complete header long before it
# has complete audio, and a signature computed over a partial file would be a
# damaged header of our own making).
SETTLE_SECONDS = 60.0

# Row statuses owned by this layer (``flac_verify`` owns the read/seal ones).
BUSY = "busy"  # written too recently to be trusted complete; left alone
# Not a file's status: a report line for a folder the walk could not open or
# list, so the files in it were never checked. Never in a scan's rows.
FOLDER_UNREADABLE = "folder_unreadable"

# What a row's status means, in the user's words (the report and the log).
STATUS_LABELS = {
    **fv.STATUS_LABELS,
    BUSY: "written less than a minute ago, left alone",
    FOLDER_UNREADABLE: "folder could not be opened, its files were not checked",
}

REPORT_COLUMNS = (
    "status",
    "meaning",
    "file",
    "detail",
    "bit_depth",
    "sample_rate",
    "channels",
    "samples_in_header",
    "samples_decoded",
    "md5_in_header",
    "md5_of_audio",
    # "yes" when the verdict is an earlier scan's (the file has not changed
    # since); "" when the file was read in this run.
    "from_earlier_check",
)


@dataclass(frozen=True)
class Verdict:
    """One file's scan result: the read/seal row plus whether it came from an
    earlier scan of the unchanged file."""

    row: fv.Row
    cached: bool = False

    def __getattr__(self, name: str):
        # The row's fields are read everywhere a Row used to be (path, status,
        # detail, info, size, mtime_ns, md5_audio, samples_decoded).
        return getattr(self.row, name)


def _stat(path: str) -> tuple[int, int]:
    st = os.stat(path)
    return st.st_size, st.st_mtime_ns


# ---- the walk -----------------------------------------------------------------


def effective_roots(roots: Iterable[str]) -> list[str]:
    """The folders to walk: blanks dropped, duplicates and a folder that lies
    inside another dropped (the download folder inside the library is one
    walk, not two). Spelling is kept as given; nothing is stat'ed here."""
    out: list[str] = []
    for root in roots:
        r = (root or "").strip()
        if not r or any(path_under(r, kept) for kept in out):
            continue
        out = [kept for kept in out if not path_under(kept, r)]
        out.append(r)
    return out


def _list_folder(folder: str, real_roots: list[str], unreadable: list[str]) -> tuple[list[str], list[str], list[str]]:
    """One folder's subfolders, ``.flac`` files and ``.flac`` links (only
    those resolving under a root), by the walk's rules. A folder that cannot
    be opened or listed, and an entry whose type cannot be read, goes into
    ``unreadable``; what was listed before a failure is kept."""
    dirs: list[str] = []
    files: list[str] = []
    links: list[str] = []
    try:
        with os.scandir(folder) as it:
            for entry in it:
                name = entry.name
                if name.startswith("."):
                    continue
                try:
                    if entry.is_dir(follow_symlinks=False):
                        dirs.append(entry.path)
                        continue
                    if not name.casefold().endswith(".flac"):
                        continue
                    if entry.is_symlink():
                        real = os.path.realpath(entry.path)
                        if any(path_under(real, rr) for rr in real_roots) and entry.is_file():
                            links.append(entry.path)
                    elif entry.is_file():
                        files.append(entry.path)
                except OSError:
                    unreadable.append(entry.path)
    except OSError:
        unreadable.append(folder)
    return dirs, files, links


def _file_id(path: str) -> tuple[int, int] | None:
    """The file a path leads to (links followed), as (device, inode)."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_dev, st.st_ino


# Folders listed at once by the walk, and how far down its stack it lists
# ahead. A network share answers each listing after a round trip (tens of
# milliseconds), so one at a time a large library spends minutes waiting.
_WALK_THREADS = 8
_WALK_AHEAD = 32


def _list_and_stat(
    folder: str, real_roots: list[str], stat: bool
) -> tuple[list[str], list[str], list[str], list[str], dict[str, tuple[int, int]]]:
    """(walk worker) :func:`_list_folder` with its own ``unreadable`` list,
    plus, with ``stat``, each file's size and time taken straight after the
    listing, so a share's round trips for them overlap other folders'."""
    unreadable: list[str] = []
    dirs, files, links = _list_folder(folder, real_roots, unreadable)
    stamps: dict[str, tuple[int, int]] = {}
    if stat:
        for path in files:
            with contextlib.suppress(OSError):
                stamps[path] = _stat(path)
    return dirs, files, links, unreadable, stamps


def iter_flac_files(
    roots: Iterable[str],
    should_continue: Callable[[], bool] | None = None,
    unreadable: list[str] | None = None,
    stamps: dict[str, tuple[int, int]] | None = None,
) -> Iterator[str]:
    """Every ``.flac`` under the roots, sorted within each folder.

    Dot-prefixed names are skipped whatever their type (hidden folders, and
    the AppleDouble ``._Track.flac`` sidecars a share carries). Folder links
    are not followed. A file that is a link is yielded only when it resolves
    to somewhere under one of the roots: the tool's writes must never reach
    a file outside the folders it was pointed at. Links come last, and one
    that leads to a file the walk already yielded (or another link already
    did) is dropped, so each file is checked and counted once.

    Every folder that could not be opened or listed (a root included: a
    share that is not mounted, a folder the system will not let Waves read)
    is appended to ``unreadable``, so a caller can tell a clean walk from one
    that missed files.

    Folders are listed a few at a time ahead of the one being yielded, in
    the same order a one-at-a-time walk takes. With ``stamps``, each file's
    size and time go there as its folder is listed (a file that cannot be
    stat'ed is left out).
    """
    roots = effective_roots(roots)
    real_roots = [os.path.realpath(r) for r in roots]
    sink = unreadable if unreadable is not None else []
    by_name: dict[str, list[str]] = {}
    links: list[str] = []
    pool = ThreadPoolExecutor(_WALK_THREADS, thread_name_prefix="flac-walk")
    try:
        for root in roots:
            pending = [root]
            listing: dict[str, Future] = {}
            while pending:
                if should_continue is not None and not should_continue():
                    return
                for folder in pending[-_WALK_AHEAD:]:
                    if folder not in listing:
                        listing[folder] = pool.submit(_list_and_stat, folder, real_roots, stamps is not None)
                dirs, files, found, missed, stats = listing.pop(pending.pop()).result()
                sink.extend(missed)
                if stamps is not None:
                    stamps.update(stats)
                pending.extend(sorted(dirs, reverse=True))
                links.extend(sorted(found))
                for path in sorted(files):
                    by_name.setdefault(os.path.basename(path).casefold(), []).append(path)
                    yield path
    finally:
        # A share that stopped answering must not hold up a cancel: listings
        # still running are left to finish on their own.
        pool.shutdown(wait=False, cancel_futures=True)
    yield from _distinct_links(links, by_name, should_continue)


def _distinct_links(
    links: list[str], by_name: dict[str, list[str]], should_continue: Callable[[], bool] | None
) -> Iterator[str]:
    """The walk's links, each only when the walk found no other name for its
    file (``by_name``: the files it yielded, by name). Only files sharing the
    target's name are stat'ed to tell, so a library with no links costs
    nothing extra."""
    seen: set[tuple[int, int]] = set()
    for link in links:
        if should_continue is not None and not should_continue():
            return
        key = _file_id(link)
        if key is not None:
            if key in seen:
                continue
            seen.add(key)
            name = os.path.basename(os.path.realpath(link)).casefold()
            if any(_file_id(p) == key for p in by_name.get(name, ())):
                continue
        yield link


# ---- what earlier scans found -------------------------------------------------

# The file under the config folder that remembers verdicts between runs.
CACHE_NAME = "flac-check.sqlite3"
CACHE_FILES = tuple(CACHE_NAME + suffix for suffix in ("", "-journal", "-wal", "-shm"))
_CACHE_VERSION = 1
# Commit the remembered verdicts at least this often, so a run that is
# canceled or cut short by a quit still keeps what it read.
_CACHE_COMMIT_ROWS = 500
_CACHE_COMMIT_S = 5.0
# Deep verdicts worth keeping: each says what the audio is. A failed decode is
# never kept (a share that stopped answering fails one too), nor a cancel.
_DEEP_KEPT = frozenset({fv.OK, fv.MISMATCH, fv.UNSUPPORTED, fv.UNSET})


class VerdictCache:
    """What earlier scans found, per file, so scanning a library that has not
    changed reads nothing but each file's size and times.

    A verdict is reused only while the file's size and modification time
    are the ones it was read at. The change time is left out on purpose: a
    share can report it unreliably, which would turn the reuse off for the
    very libraries that need it most, and a tagger that keeps the
    modification time leaves the header and audio alone anyway. A file
    modified within ``SETTLE_SECONDS`` of its read is never remembered: on a
    volume with coarse timestamps a second write in the same tick would leave
    the time as it was.

    Kept per file: the header (the 34 bytes and where they sit, so a fix
    still proves the file is the one the scan saw) and, after a deep check,
    the audio's verdict. Nothing here ever decides a write on its own: a fix
    re-reads, decodes and compares every file it touches (see
    :func:`fix_rows`). A cache that cannot be opened or read is dropped and
    the run carries on reading every file.

    One connection, used by the one thread a scan runs on.
    """

    def __init__(self, path: str, now: Callable[[], float] = time.time) -> None:
        self._now = now
        # Set when a read or write found the file damaged ("malformed", not
        # merely locked): the caller deletes it after close, and the next
        # scan starts it over instead of tripping on it every run.
        self.damaged = False
        self._pending = 0
        self._last_commit = time.monotonic()
        self._conn: sqlite3.Connection | None = sqlite3.connect(path)
        try:
            if self._conn.execute("PRAGMA user_version").fetchone()[0] != _CACHE_VERSION:
                self._conn.execute("DROP TABLE IF EXISTS verdicts")
                self._conn.execute("""CREATE TABLE verdicts (
                           path        TEXT PRIMARY KEY,
                           size        INTEGER NOT NULL,
                           mtime_ns    INTEGER NOT NULL,
                           status      TEXT NOT NULL,
                           detail      TEXT NOT NULL,
                           offset      INTEGER,
                           raw         BLOB,
                           deep_status TEXT,
                           deep_detail TEXT,
                           md5_audio   BLOB,
                           samples     INTEGER
                       )""")
                self._conn.execute(f"PRAGMA user_version = {_CACHE_VERSION}")
                self._conn.commit()
        except sqlite3.Error:
            self._conn.close()
            raise

    def _drop(self, exc: BaseException | None = None) -> None:
        if type(exc) is sqlite3.DatabaseError:
            self.damaged = True
        logger.warning("FLAC check: the remembered verdicts could not be used; every file is read this run")
        if self._conn is not None:
            with contextlib.suppress(sqlite3.Error):
                self._conn.close()
        self._conn = None

    def lookup(self, path: str, deep: bool, reuse: bool = True) -> tuple[Verdict | None, tuple[int, int] | None]:
        """The remembered verdict for the file as it is now, or None, plus
        the stat it was judged by (None when the file cannot be stat'ed);
        that stat is what :meth:`store` keys a fresh verdict on. Without
        ``reuse`` only the stat is taken: the file is read again, and what
        that read finds replaces what was remembered."""
        try:
            stamp = _stat(path)
        except OSError:
            return None, None
        if self._conn is None or not reuse:
            return None, stamp
        return self.remembered(path, deep, stamp), stamp

    def remembered(self, path: str, deep: bool, stamp: tuple[int, int]) -> Verdict | None:
        """The verdict remembered for ``path`` at exactly ``stamp`` (its size
        and modification time), or None."""
        if self._conn is None:
            return None
        try:
            rec = self._conn.execute(
                "SELECT size, mtime_ns, status, detail, offset, raw,"
                " deep_status, deep_detail, md5_audio, samples FROM verdicts WHERE path = ?",
                (path,),
            ).fetchone()
        except UnicodeError:
            # A name that is not valid UTF-8 (an old Latin-1 rip on Linux):
            # sqlite cannot hold it, so the file is simply read every scan.
            return None
        except sqlite3.Error as exc:
            self._drop(exc)
            return None
        if rec is None or tuple(rec[:2]) != stamp:
            return None
        status, detail, offset, raw, deep_status, deep_detail, md5_audio, samples = rec[2:]
        size, mtime_ns = stamp
        if status == fv.UNREADABLE:
            return Verdict(fv.Row(path, fv.UNREADABLE, detail, size=size, mtime_ns=mtime_ns), cached=True)
        try:
            info = fv.parse_streaminfo(int(offset), bytes(raw))
        except (fv.FlacHeaderError, TypeError, ValueError):
            return None
        if not deep:
            status = fv.UNSET if info.md5_unset else fv.SET
            return Verdict(fv.Row(path, status, info=info, size=size, mtime_ns=mtime_ns), cached=True)
        if deep_status is None:
            return None
        return Verdict(
            fv.Row(
                path,
                deep_status,
                deep_detail or "",
                info=info,
                size=size,
                mtime_ns=mtime_ns,
                md5_audio=bytes(md5_audio) if md5_audio is not None else None,
                samples_decoded=samples if samples is not None else -1,
            ),
            cached=True,
        )

    def store(self, verdict: Verdict, stamp: tuple[int, int] | None, deep: bool) -> None:
        """Remember a verdict read just now against ``stamp``, the stat taken
        before the read. Skipped when the read saw another size or time (the
        file changed in between) or the file changed too recently to trust."""
        row = verdict.row
        if self._conn is None or stamp is None or (row.size, row.mtime_ns) != stamp:
            return
        if self._now() - stamp[1] / 1e9 < SETTLE_SECONDS:
            return
        info = row.info
        if info is None:
            if row.status != fv.UNREADABLE:
                return
            header = (fv.UNREADABLE, row.detail, None, None)
        else:
            header = (fv.UNSET if info.md5_unset else fv.SET, "", info.offset, info.raw)
        audio = (None, None, None, None)
        if deep and info is not None and row.status in _DEEP_KEPT and (row.status != fv.UNSET or row.md5_audio):
            audio = (row.status, row.detail, row.md5_audio, row.samples_decoded if row.md5_audio else None)
        try:
            self._conn.execute(
                "INSERT OR REPLACE INTO verdicts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (row.path, *stamp, *header, *audio),
            )
            self._pending += 1
            if self._pending >= _CACHE_COMMIT_ROWS or time.monotonic() - self._last_commit >= _CACHE_COMMIT_S:
                self.flush()
        except UnicodeError:
            return  # not valid UTF-8, see remembered
        except sqlite3.Error as exc:
            self._drop(exc)

    def prune(self, roots: Iterable[str], seen: Iterable[str], unreadable: Iterable[str] = ()) -> None:
        """Forget files under ``roots`` that a finished walk no longer found
        (deleted or renamed), except under a folder it could not read."""
        if self._conn is None:
            return
        roots = effective_roots(roots)
        found = set(seen)
        missed = list(unreadable)
        try:
            gone = [
                (p,)
                for (p,) in self._conn.execute("SELECT path FROM verdicts")
                if p not in found and any(path_under(p, r) for r in roots) and not any(path_under(p, u) for u in missed)
            ]
            if gone:
                self._conn.executemany("DELETE FROM verdicts WHERE path = ?", gone)
                self._pending += len(gone)
        except sqlite3.Error as exc:
            self._drop(exc)

    def flush(self) -> None:
        if self._conn is None:
            return
        try:
            self._conn.commit()
        except sqlite3.Error as exc:
            self._drop(exc)
            return
        self._pending = 0
        self._last_commit = time.monotonic()

    def close(self) -> None:
        """Commit what is pending and close."""
        self.flush()
        if self._conn is not None:
            with contextlib.suppress(sqlite3.Error):
                self._conn.close()
            self._conn = None


def _walk(
    roots: Iterable[str],
    should_continue: Callable[[], bool] | None,
    on_walk: Callable[[int, bool], None] | None,
    unreadable: list[str],
    stamps: dict[str, tuple[int, int]] | None = None,
) -> list[str]:
    """Every file :func:`scan` checks, with ``on_walk`` told as they are found.
    With ``stamps``, each file's size and time are taken the moment its
    folder has been listed and kept there by path (see :func:`scan`)."""
    paths: list[str] = []
    for path in iter_flac_files(roots, should_continue, unreadable, stamps):
        paths.append(path)
        if on_walk is not None:
            on_walk(len(paths), False)
    if on_walk is not None:
        on_walk(len(paths), True)
    return paths


# Files read at once by a scan, a header scan and a deep check. Over a network
# share each header read waits on round trips, so one at a time a large
# library takes most of an hour; a decode also keeps a core busy, so fewer.
_READ_THREADS = 8
_DECODE_THREADS = max(1, min(4, (os.cpu_count() or 2) // 2))


def _read_fresh(
    path: str, ffmpeg: str | None, deep: bool, should_continue: Callable[[], bool] | None, stat: bool, shared: int
) -> tuple[Verdict, tuple[int, int] | None]:
    """(read worker) A fresh verdict, plus with ``stat`` the size and time
    taken just before the read (what :meth:`VerdictCache.store` keys it on)."""
    stamp = None
    if stat:
        with contextlib.suppress(OSError):
            stamp = _stat(path)
    return Verdict(fv.check_file(path, ffmpeg, deep=deep, should_continue=should_continue, shared=shared)), stamp


def _verdicts(
    paths: list[str],
    ffmpeg: str | None,
    deep: bool,
    cache: VerdictCache | None,
    should_continue: Callable[[], bool] | None,
    stamps: dict[str, tuple[int, int]] | None,
) -> Iterator[Verdict]:
    """Each file's verdict for :func:`scan`, in ``paths`` order: the
    remembered one while the file is unchanged since the walk's stat
    (``stamps``; None for a recheck), else a fresh read. Reads run a few at
    a time ahead of the row being handed out; the cache is asked and told
    on this thread only, and a fresh verdict is remembered unless the run
    was stopped."""
    workers = _DECODE_THREADS if deep else _READ_THREADS
    ahead = workers * 4
    pending: deque[tuple[str, Verdict | Future]] = deque()
    todo = iter(paths)
    pool = ThreadPoolExecutor(workers, thread_name_prefix="flac-read")

    def alive() -> bool:
        return should_continue is None or should_continue()

    def fill() -> None:
        while len(pending) < ahead and alive():
            path = next(todo, None)
            if path is None:
                return
            seen = stamps.get(path) if stamps is not None else None
            verdict = cache.remembered(path, deep, seen) if cache is not None and seen is not None else None
            if verdict is None:
                verdict = pool.submit(_read_fresh, path, ffmpeg, deep, should_continue, cache is not None, workers)
            pending.append((path, verdict))

    try:
        fill()
        while pending:
            _path, item = pending.popleft()
            if isinstance(item, Verdict):
                yield item
            else:
                verdict, stamp = item.result()
                if cache is not None and verdict.status != fv.CANCELLED and alive():
                    cache.store(verdict, stamp, deep)
                yield verdict
            fill()
    finally:
        # Reads still running finish on their own (a cancel stops a decode).
        pool.shutdown(wait=False, cancel_futures=True)


def scan(
    roots: Iterable[str],
    ffmpeg: str | None = None,
    *,
    deep: bool = False,
    should_continue: Callable[[], bool] | None = None,
    on_row: Callable[[Verdict], None] | None = None,
    on_walk: Callable[[int, bool], None] | None = None,
    unreadable: list[str] | None = None,
    cache: VerdictCache | None = None,
    recheck: bool = False,
) -> list[Verdict]:
    """Check every FLAC under the roots. Never writes a music file.

    The folders are walked first and the files checked after, so the run
    knows its total before the first file is read: ``on_walk(found, done)``
    is called for each file found, then once with ``done`` set. Folders the
    walk could not open or list are appended to ``unreadable`` (see
    :func:`iter_flac_files`).

    With a ``cache``, a file unchanged since an earlier scan takes that
    scan's verdict (the verdict is marked ``cached``) and each fresh verdict
    is remembered; a walk that finished forgets the files it no longer found.
    ``recheck`` reads every file again (damage that left a file's size and
    time alone shows only that way) and remembers what it finds. The caller
    closes the cache.

    Whether a file is unchanged is judged on the size and time the walk's
    workers take as they list its folder, several folders at once: on a
    network share every stat is a round trip, and one at a time once the
    walk is over they take minutes on a large library. Files read afresh
    are read several at a time too (see :func:`_verdicts`). A file changed
    after its folder was listed is caught by the next scan, and a fix reads
    every file again before it writes, whatever a scan remembered."""
    if unreadable is None:
        unreadable = []
    deep = deep and bool(ffmpeg)
    stamps: dict[str, tuple[int, int]] | None = {} if cache is not None and not recheck else None
    paths = _walk(roots, should_continue, on_walk, unreadable, stamps)

    def alive() -> bool:
        return should_continue is None or should_continue()

    rows: list[Verdict] = []
    for verdict in _verdicts(paths, ffmpeg, deep, cache, should_continue, stamps):
        if not alive():
            break
        rows.append(verdict)
        if on_row is not None:
            on_row(verdict)
        if verdict.status == fv.CANCELLED:
            break
    if cache is not None and len(rows) == len(paths) and alive():
        cache.prune(roots, paths, unreadable)
    return rows


def fix_rows(
    rows: Iterable[Verdict],
    ffmpeg: str,
    *,
    should_continue: Callable[[], bool] | None = None,
    on_row: Callable[[Verdict], None] | None = None,
    settle_seconds: float = SETTLE_SECONDS,
    now: Callable[[], float] = time.time,
) -> list[Verdict]:
    """Seal the ``UNSET`` rows of a scan; every other row passes through
    untouched. Each candidate is re-read, re-stat'ed and decoded before its
    header is written (see :func:`waves.flac_verify.seal_file`), and one
    written less than ``settle_seconds`` ago is left for the next run. A
    cancel leaves the rows not reached, and the one it interrupted
    mid-decode, ``UNSET`` (with a note), so the next fix still sees them."""
    out: list[Verdict] = []
    for verdict in rows:
        row = verdict.row
        if row.status != fv.UNSET or row.info is None:
            out.append(verdict)
            continue
        if should_continue is not None and not should_continue():
            # Still UNSET: nothing was done to it, so a later fix picks it up.
            row = replace(row, detail="not reached, the run was canceled")
        else:
            try:
                size, mtime_ns = _stat(row.path)
            except OSError as exc:
                row = replace(row, status=fv.UNREADABLE, detail=exc.strerror or str(exc))
            else:
                if (size, mtime_ns) != (row.size, row.mtime_ns):
                    row = replace(row, status=fv.CHANGED)
                elif now() - mtime_ns / 1e9 < settle_seconds:
                    row = replace(row, status=BUSY)
                else:
                    sealed = fv.seal_file(row.path, ffmpeg, expected=row.info, should_continue=should_continue)
                    # Canceled mid-decode: nothing was written, so it stays
                    # UNSET for the next fix like the rows after it.
                    if sealed.status == fv.CANCELLED:
                        row = replace(row, detail="not reached, the run was canceled")
                    else:
                        row = sealed
        out.append(Verdict(row, verdict.cached))
        if on_row is not None:
            on_row(Verdict(row, verdict.cached))
    return out


def summarize(rows: Iterable[Verdict]) -> dict[str, int]:
    """Counts per status, plus ``files`` for the total."""
    counts: dict[str, int] = {"files": 0}
    for verdict in rows:
        counts["files"] += 1
        counts[verdict.status] = counts.get(verdict.status, 0) + 1
    return counts


# ---- the report ---------------------------------------------------------------


def write_report(
    path: str | os.PathLike,
    rows: Iterable[Verdict],
    unreadable: Iterable[str] = (),
    *,
    exclusive: bool = False,
) -> str:
    """Write the rows as a CSV (UTF-8 with a byte-order mark, so a
    spreadsheet opens accented file names correctly), then a line for each
    folder in ``unreadable`` (``FOLDER_UNREADABLE``: its files were never
    checked). Returns the path. ``exclusive`` refuses to replace a file that
    is already there (:class:`FileExistsError`)."""
    out = pathlib.Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    # backslashreplace: a file name that is not valid UTF-8 is written as
    # escapes instead of failing the whole report.
    with out.open("x" if exclusive else "w", encoding="utf-8-sig", errors="backslashreplace", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(REPORT_COLUMNS)
        for verdict in rows:
            row = verdict.row
            info = row.info
            writer.writerow(
                [
                    row.status,
                    STATUS_LABELS.get(row.status, row.status),
                    row.path,
                    row.detail,
                    info.bits_per_sample if info else "",
                    info.sample_rate if info else "",
                    info.channels if info else "",
                    info.total_samples if info else "",
                    row.samples_decoded if row.samples_decoded >= 0 else "",
                    "" if info is None or info.md5_unset else info.md5.hex(),
                    row.md5_audio.hex() if row.md5_audio else "",
                    "yes" if verdict.cached else "",
                ]
            )
        for folder in unreadable:
            writer.writerow(
                [FOLDER_UNREADABLE, STATUS_LABELS[FOLDER_UNREADABLE], folder] + [""] * (len(REPORT_COLUMNS) - 3)
            )
    return str(out)


# Reports written in the same second are told apart by a counter, up to this.
_REPORT_SUFFIX_MAX = 999


def report_name(kind: str, when: float | None = None, n: int = 1) -> str:
    """``flac-check-<kind>-YYYYMMDD-HHMMSS.csv`` (kind is ``scan`` or ``fix``);
    a second report in the same second is ``...-HHMMSS-2.csv``, and so on
    (``n``)."""
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(when))
    suffix = f"-{n}" if n > 1 else ""
    return f"flac-check-{kind}-{stamp}{suffix}.csv"


_REPORT_RE = re.compile(r"flac-check-(?:scan|fix)-(\d{8}-\d{6})(?:-(\d+))?\.csv")


def _report_names(folder: str | os.PathLike) -> list[str]:
    try:
        return [n for n in os.listdir(folder) if _REPORT_RE.fullmatch(n)]
    except OSError:
        return []


def has_report(folder: str | os.PathLike) -> bool:
    """Whether the folder holds any report (one listing, no stat)."""
    return bool(_report_names(folder))


def newest_report(folder: str | os.PathLike) -> str:
    """The report written last, by its modification time (the local time in
    its name can run backwards when the clock falls back or the time zone
    changes), then the time and counter in its name; "" when there is none."""
    best: tuple[int, str, int] | None = None
    newest = ""
    for name in _report_names(folder):
        try:
            written = os.stat(os.path.join(folder, name)).st_mtime_ns
        except OSError:
            continue
        m = _REPORT_RE.fullmatch(name)
        assert m is not None  # noqa: S101 (_report_names matched it)
        key = (written, m.group(1), int(m.group(2) or 1))
        if best is None or key > best:
            best, newest = key, name
    return os.path.join(folder, newest) if newest else ""


def write_new_report(
    folder: str | os.PathLike,
    kind: str,
    rows: Iterable[Verdict],
    unreadable: Iterable[str] = (),
    when: float | None = None,
) -> str:
    """Write a report under a name no earlier report has (see
    :func:`report_name`): one never replaces another. Returns the path."""
    when = time.time() if when is None else when
    rows = list(rows)
    unreadable = list(unreadable)
    for n in range(1, _REPORT_SUFFIX_MAX + 1):
        with contextlib.suppress(FileExistsError):
            return write_report(os.path.join(folder, report_name(kind, when, n)), rows, unreadable, exclusive=True)
    raise FileExistsError(os.path.join(folder, report_name(kind, when, _REPORT_SUFFIX_MAX)))
