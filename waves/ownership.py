"""Local record of what has actually been downloaded, so Waves can answer "do
you already have this track, and at what quality" from reality rather than
from a download ledger.

The rule this store lives by: it DESCRIBES what was downloaded (the actual
final on-disk path and the delivered quality, keyed by the track's namespaced
id, "tidal:123" -- a bare id reads as tidal, the spelling every pre-namespace
caller used); it never DECIDES ownership on its own. Ownership is answered
live, by re-checking whether a recorded path still exists on disk right now,
so a file the user deleted and wants again is offered for re-download with no
clearing step. A ledger that just says "downloaded before" would lie the
moment a file is deleted; re-checking the filesystem every time is what keeps
it honest.

Pure standard library (sqlite3), with no Qt and no tidalapi import, so it unit
tests without the GUI stack and never couples the download engine to the UI.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from threading import Lock

from waves.constants import quality_rank
from waves.ids import namespaced_id

# The delivered-quality ladder is Waves' own (waves.constants.QualityTier,
# issue #24): LOW < HIGH < LOSSLESS < HI_RES_LOSSLESS, ranked 0..3 by the
# shared quality_rank (imported here; the store's rank column and the
# ORDER BYs run the same scale the bridge and the settings rank with). A
# caller asks "is a better tier available than what is on disk" with a plain
# integer comparison. Bit depth and sample rate are deliberately NOT used for
# ranking: TIDAL omits them for some tiers (they default to 16 / 44100), so
# the tier string is the only trustworthy signal.
logger = logging.getLogger("waves.ownership")


def _nonempty_file(path: str) -> bool:
    """A recorded path counts as surviving only if it holds actual bytes."""
    try:
        return os.path.isfile(path) and os.path.getsize(path) > 0
    except OSError:
        return False


def normalize_audio_type(audio_type: str | None = None, audio_mode: str | None = None) -> str | None:
    """One spelling for a copy's audio type: "stereo" / "atmos" / None.

    Prefers the explicit audio_type (the seam's AudioType words, what
    WAVES_AUDIO_TYPE tags carry). Falls back to the legacy audio_mode
    (TIDAL's "STEREO" / "DOLBY_ATMOS"). None means unknown: a row from
    before either column, which reads as stereo everywhere it matters.
    """
    text = str(audio_type or "").strip().lower()
    if text in ("stereo", "atmos"):
        return text
    mode = str(audio_mode or "").strip().upper()
    if mode == "DOLBY_ATMOS":
        return "atmos"
    if mode == "STEREO":
        return "stereo"
    return None


def _matches_audio_type(row_type: str | None, row_mode: str | None, want: str | None) -> bool:
    """Whether a row's copy answers a per-version query for ``want``.

    None wants everything (the legacy whole-track query). "atmos" wants
    only Atmos copies; "stereo" wants stereo copies plus unknown legacy
    rows (which read as stereo, one re-download then settled).
    """
    if want is None:
        return True
    want = str(want or "").strip().lower()
    got = normalize_audio_type(row_type, row_mode)
    if want == "atmos":
        return got == "atmos"
    if want == "stereo":
        return got in ("stereo", None)
    return True


def record_is_atmos(rec) -> bool:
    """Was the copy on disk delivered as Dolby Atmos? The store keeps the
    delivered audio type beside the tier, and it is the only thing that says
    which scale that tier was measured on. A row written before the column
    existed reads as stereo, which costs one re-download and then settles.
    Prefers the explicit audio_type (stereo/atmos); falls back to the legacy
    audio_mode for rows from before the type column."""
    atype = str((rec or {}).get("audio_type") or "").strip().lower()
    if atype in ("atmos", "stereo"):
        return atype == "atmos"
    return str((rec or {}).get("audio_mode") or "").upper() == "DOLBY_ATMOS"


def record_names_a_broken_copy(rec: dict | None) -> bool:
    """True when the recorded path was written by an old build's broken name
    formatter: a "[None]" spelling where the release year belonged (any album
    TIDAL lists no date for took this through the normal path of released
    builds), or a literal unrendered "{album_track_num}" token (the album-404
    fallback before it was fixed). Such a copy must not satisfy the ownership
    gate: the fixed formatter can never rebuild those spellings, so the gate
    would freeze the garbage file as the owned copy and skip the corrected
    re-download forever. The old file itself is left alone (the app never
    deletes user-visible files); the fresh download lands at the corrected
    path and takes over the record."""
    path = str((rec or {}).get("path", "") or "")
    return "[None]" in path or "{album_track_num}" in path


# How many consecutive deliveries under the provider's own advertised ceiling
# the upgrade gate will chase before it settles for what it keeps being given.
# Two, so a genuine one-off (a bad edge node, a session that fell back mid
# stream) is still retried and a persistent under-serve costs the user one
# extra fetch, not one on every click for the rest of the install's life.
DEGRADED_RETRY_MAX = 2


def copy_is_current(rec, target_rank: int, wants_atmos: bool, ceiling_rank: int | None = None) -> bool:
    """Is the copy already on disk as good as what a download queued now would
    write, so that fetching it again would achieve nothing?

    The tier alone cannot answer that for a Dolby Atmos copy. TIDAL serves
    Atmos only through a session pinned to ATMOS_REQUEST_QUALITY
    (constants.py), so an Atmos file arrives at that tier whatever the audio
    quality setting says. Ranked on the stereo scale it would be judged stale
    against a tier it can never be granted, and stale means force: re-fetch and
    overwrite the identical file on every download while the button never
    leaves DOWNLOAD. An Atmos copy is therefore current for a job that would
    fetch Atmos, full stop: the request tier is a constant this app cannot
    raise, and a change in TIDAL's own answer is not something an ownership
    gate can see, so Redownload is the way to ask again.

    Turning Atmos on does not make an owned stereo copy read as stale: a track
    can hold Atmos and stereo copies at once (different codecs and extensions,
    so two rows), and ownership_of answers with the highest tier among them,
    the stereo one, so forcing on that mismatch would re-fetch an Atmos file
    the user already has. That guard holds only while the stereo copy sits AT
    OR ABOVE the target; below it the tier comparison forces, the fetch returns
    Atmos to a second path, and ownership_of keeps answering with the stereo
    row. Closing that needs a mode-aware store query and bridge cache
    (ownershipOf holds an id and a record, never the track's audio modes), so
    Redownload is the way out. Do not "fix" it by making an Atmos-wanting job
    read any record as current: that makes a below-target stereo copy read as
    current too and splits the gate from the button.

    The tier comparison converges at each track's achievable ceiling.
    ``ceiling_rank`` is the best rank the provider advertises at scan time
    (pass None when unknown, never a guess): a known ceiling caps the target,
    so owning the best that exists counts as current. A copy served by a run
    that already ASKED at this target or better counts as current even without
    a live ceiling, unless the advertised ceiling has risen past the record's
    stored ``ceiling_rank``, in which case a genuinely better master exists
    and the upgrade reopens. That clause lets a ceiling-blind caller
    (ownershipOf holds only an id) settle off the stored ``requested_rank``
    and ``ceiling_rank`` instead of flashing an upgrade forever.

    A DEGRADED delivery -- asked high enough, served below the ceiling its run
    saw -- must never settle on the request alone, or the copy freezes as
    current while every later run skips it. After ``DEGRADED_RETRY_MAX``
    consecutive under-ceiling deliveries the ask has been made honestly and
    the copy settles; a delivery that reaches the ceiling resets the count."""
    if wants_atmos and record_is_atmos(rec):
        return True
    # Rank -1 means no quality concept (a video's tier-less record): nothing to
    # upgrade to, so a surviving copy is simply current.
    rank = int((rec or {}).get("quality_rank", -1))
    if rank < 0:
        return True
    target = int(target_rank)
    if ceiling_rank is not None and 0 <= int(ceiling_rank) < target:
        target = int(ceiling_rank)
    if rank >= target:
        return True
    requested = (rec or {}).get("requested_rank")
    requested = int(requested) if requested is not None else -1
    stored_ceiling = (rec or {}).get("ceiling_rank")
    stored_ceiling = int(stored_ceiling) if stored_ceiling is not None else -1
    if rank < stored_ceiling:
        # Served below what its own run was told existed: a better master is
        # there for the asking, so the upgrade stays open however high that run
        # asked. (rank == stored_ceiling means this IS the best that exists, and
        # it settles below.)
        #
        # Open, but not forever: TIDAL can advertise LOSSLESS and keep serving
        # HIGH, and then "stays open" re-fetches and overwrites the track on
        # every album click with the button never settling. After
        # DEGRADED_RETRY_MAX consecutive under-ceiling attempts the ask has
        # been made honestly and the answer is not changing: settle, and let
        # Redownload ask again. A delivery that reaches the ceiling resets the
        # count, so a master TIDAL genuinely fixes is still picked up.
        tries = (rec or {}).get("degraded_tries")
        return int(tries or 0) >= DEGRADED_RETRY_MAX
    # Or the copy already sits at the ceiling its own release advertised, in
    # which case no run at any setting can do better and the ask never has to
    # be made again. Without this arm the button path (ownershipOf passes no
    # live ceiling, so the clamp above never fires) answered "requested >=
    # target" and stayed False for good once the setting was raised past what
    # the release offers: the button read DOWNLOAD forever while the gate,
    # which IS ceiling-aware, skipped every track, so the job completed as a
    # success having fetched nothing and the button never changed.
    return (requested >= target or 0 <= stored_ceiling <= rank) and (
        ceiling_rank is None or int(ceiling_rank) <= stored_ceiling
    )


# Columns beyond the primary key, with the type used to ADD them to an older DB.
# CREATE TABLE below carries the full schema; this list only drives the
# forward-compatible ALTER guard, so every entry must be nullable or defaulted
# (ALTER TABLE ADD COLUMN cannot add a bare NOT NULL column or a primary key).
_ADDED_COLUMNS = (
    ("quality_tier", "TEXT"),
    ("quality_rank", "INTEGER NOT NULL DEFAULT -1"),
    ("audio_mode", "TEXT"),
    # Explicit audio type (§5.3, issue #29): "stereo" / "atmos" in the seam's
    # AudioType spelling. audio_mode stays for backward compat (TIDAL's
    # "STEREO" / "DOLBY_ATMOS"); audio_type is what per-version gates filter
    # on, and what WAVES_AUDIO_TYPE tags carry on disk. Null means unknown
    # (a row from before the column): reads as stereo, like a missing mode.
    ("audio_type", "TEXT"),
    ("bit_depth", "INTEGER"),
    ("sample_rate", "INTEGER"),
    ("codecs", "TEXT"),
    ("user_id", "TEXT"),
    ("recorded_at", "INTEGER NOT NULL DEFAULT 0"),
    # The quality rank this download RUN asked for, and the best rank TIDAL
    # advertised for the track at that moment. Together they let the upgrade
    # gate converge: "we already asked at this quality or better, and this is
    # what was served" is a skip, not an endless re-download (a track whose
    # best available master sits below the user's target would otherwise be
    # re-fetched on every run, forever).
    ("requested_rank", "INTEGER NOT NULL DEFAULT -1"),
    ("ceiling_rank", "INTEGER NOT NULL DEFAULT -1"),
    # How many times in a row this copy has come back BELOW the ceiling TIDAL
    # advertised for it. The ranks above cannot converge that case on their
    # own, and must not: a copy served under its own advertised ceiling is the
    # one case where a better master is provably there for the asking (issue
    # #2), so the upgrade deliberately stays open. But TIDAL can advertise
    # LOSSLESS and serve HIGH persistently, and then "stays open" means the
    # track is re-fetched and overwritten on every album click, forever, with
    # nothing on screen to say why. Counted, so the retry can be given up
    # after a couple of honest attempts. Reset to 0 by any delivery that lands
    # at or above the ceiling, so a master TIDAL really does fix is taken.
    ("degraded_tries", "INTEGER NOT NULL DEFAULT 0"),
)


class OwnershipStore:
    """A small sqlite record of downloaded tracks: (track_id, final path) plus the
    delivered quality. One row per distinct on-disk path, so a re-download to a
    new location (a template change, or a higher-quality copy alongside the old
    one) adds a row rather than overwriting history. Ownership is always resolved
    against the live filesystem, never asserted from a row alone.

    Thread-safe: records are written from download worker threads while reads run
    on the GUI thread. The connection is opened with check_same_thread=False and
    every statement runs under an instance lock; WAL mode keeps a read from
    blocking behind a write.
    """

    def __init__(self, db_path: str) -> None:
        self._path = str(db_path)
        parent = os.path.dirname(self._path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._lock = Lock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("""CREATE TABLE IF NOT EXISTS downloads (
                       track_id     TEXT    NOT NULL,
                       path         TEXT    NOT NULL,
                       quality_tier TEXT,
                       quality_rank INTEGER NOT NULL DEFAULT -1,
                       audio_mode   TEXT,
                       audio_type   TEXT,
                       bit_depth    INTEGER,
                       sample_rate  INTEGER,
                       codecs       TEXT,
                       user_id      TEXT,
                       recorded_at  INTEGER NOT NULL DEFAULT 0,
                       requested_rank INTEGER NOT NULL DEFAULT -1,
                       ceiling_rank   INTEGER NOT NULL DEFAULT -1,
                       degraded_tries INTEGER NOT NULL DEFAULT 0,
                       PRIMARY KEY (track_id, path)
                   )""")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_downloads_track ON downloads(track_id)")
            self._conn.execute("""CREATE TABLE IF NOT EXISTS collection_members (
                       collection_id TEXT    NOT NULL,
                       track_id      TEXT    NOT NULL,
                       recorded_at   INTEGER NOT NULL DEFAULT 0,
                       PRIMARY KEY (collection_id, track_id)
                   )""")
            # Integrity skip-list (issue #30, spec §6.3): provider-scoped
            # quarantined tracks. One row per (track, version): a corrupt Atmos
            # source never blocks its stereo sibling, and vice versa. The
            # namespaced track_id keeps it provider-scoped (apple:… never
            # answers a tidal:… gate). encoded_date records the Encoded date
            # the failed file carried, so a REDOWNLOAD that verifies after
            # Apple re-encodes is detectable; quarantined_at is bookkeeping.
            # Cleared only by an explicit REDOWNLOAD that lands verified or by
            # the same track verifying on a later explicit ask — never by a
            # background re-check (there is none).
            self._conn.execute("""CREATE TABLE IF NOT EXISTS integrity_skip (
                       track_id       TEXT    NOT NULL,
                       audio_type     TEXT    NOT NULL DEFAULT '',
                       encoded_date   TEXT,
                       quarantined_at INTEGER NOT NULL DEFAULT 0,
                       PRIMARY KEY (track_id, audio_type)
                   )""")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_integrity_skip_track ON integrity_skip(track_id)")
            self._ensure_columns()
            self._backfill_namespaced_ids()
            self._backfill_audio_type()
            self._backfill_integrity_skip_ids()
            self._conn.commit()

    def _ensure_columns(self) -> None:
        """Add any expected column missing from an older DB. A no-op once the DB
        matches the current schema; lets a future column land without a manual
        migration. Caller holds the lock.

        The lock is this process's own, and the config folder is shared: a
        double launch on the first run after an upgrade (or the packaged app
        beside a source run) can have both copies read the column list before
        either adds anything, and SQLite answers the loser's ALTER with
        "duplicate column name". That was an unhandled exception in the store's
        constructor, which is built unguarded while the bridge is being
        constructed, so the second copy died at startup instead of opening.
        Whoever got there first is a perfectly good answer, so the column being
        there already is not an error.
        """
        have = {row[1] for row in self._conn.execute("PRAGMA table_info(downloads)")}
        for name, decl in _ADDED_COLUMNS:
            if name in have:
                continue
            try:
                self._conn.execute(f"ALTER TABLE downloads ADD COLUMN {name} {decl}")
            except sqlite3.OperationalError:
                # Ask the FILE, do not read the message. The race this handles
                # can also surface as "database is locked" once sqlite's busy
                # timeout is exceeded, and that text carries no column name at
                # all, so matching on "duplicate column" re-raised precisely
                # the loser this exists to let through, under load, at startup.
                # The only question that matters is whether the column is there
                # now.
                try:
                    present = {row[1] for row in self._conn.execute("PRAGMA table_info(downloads)")}
                except sqlite3.Error:
                    present = set()
                if name not in present:
                    raise
                logger.debug("ownership: %s was added by another copy of Waves", name)

    def _backfill_namespaced_ids(self) -> None:
        """Rewrite the bare ids older builds wrote into the namespaced spelling
        (§4.2: existing rows become ``tidal:``). Runs once per open, before any
        new write can land a bare id of its own. Caller holds the lock.

        One row each, none lost, none duplicated: a bare row maps 1:1 onto its
        namespaced self. The one way the rewrite can meet an existing
        namespaced twin on the same (track_id, path) key is a library that went
        back to an older Waves and returned -- both rows then describe the same
        copy on the same path, and the store cannot keep two rows under one
        key. The bare row replaces the twin exactly the way record()'s upsert
        settles a re-record of a known path: one row per copy, whichever
        record was written into the bare spelling last.

        Collection-membership rows are a collection-scoped ledger, not
        ownership rows; they stay as written, and their consumers re-namespace
        on read.
        """
        self._conn.execute(
            "UPDATE OR REPLACE downloads SET track_id = 'tidal:' || track_id"
            " WHERE instr(track_id, ':') = 0 AND track_id <> ''"
        )

    def _backfill_audio_type(self) -> None:
        """Fill audio_type from audio_mode where the type column is still null.

        Runs once per open, before any new write. Rows with an explicit type
        keep it; rows with only a mode gain the type that mode names; rows
        with neither stay null (unknown, reads as stereo). Caller holds the
        lock.
        """
        self._conn.execute(
            "UPDATE downloads SET audio_type = 'atmos'"
            " WHERE audio_type IS NULL AND upper(audio_mode) = 'DOLBY_ATMOS'"
        )
        self._conn.execute(
            "UPDATE downloads SET audio_type = 'stereo'" " WHERE audio_type IS NULL AND upper(audio_mode) = 'STEREO'"
        )

    def _backfill_integrity_skip_ids(self) -> None:
        """Namespace bare skip-list ids the way downloads backfills them.

        The skip-list is new with the integrity gate, so no released build
        wrote bare ids into it; this guards only against a mid-rollout mix
        (and keeps the one spelling rule in one place). Caller holds the lock.
        """
        self._conn.execute(
            "UPDATE OR REPLACE integrity_skip SET track_id = 'tidal:' || track_id"
            " WHERE instr(track_id, ':') = 0 AND track_id <> ''"
        )

    def record(
        self,
        track_id: str,
        path: str,
        quality_tier: str | None = None,
        *,
        audio_mode: str | None = None,
        audio_type: str | None = None,
        bit_depth: int | None = None,
        sample_rate: int | None = None,
        codecs: str | None = None,
        user_id: str | None = None,
        requested_rank: int = -1,
        ceiling_rank: int = -1,
        degraded: bool = False,
    ) -> int:
        """Record that ``track_id`` was written to ``path`` at ``quality_tier``.

        The row is keyed by the id in the store's namespaced spelling (a bare
        id reads as tidal, §4.2), so the same copy recorded through either
        spelling upserts onto one row.

        Upserts on (track_id, path): re-recording the same file updates its
        quality and timestamp in place; a different path for the same track adds
        a row, so every known copy survives for the live ownership check.
        ``requested_rank`` is the quality rank the run asked for and
        ``ceiling_rank`` the best rank TIDAL advertised at the time (both -1
        when unknown); see backend's _copy_is_current for how they stop a
        forever-upgrade loop. ``degraded`` says this delivery came back BELOW
        that advertised ceiling: it bumps a consecutive counter (and any
        delivery that is not degraded resets it to zero), which is what lets
        the same gate give up on a track TIDAL persistently under-serves
        instead of re-fetching it on every click for good.

        Returns:
            int: This row's consecutive degraded-delivery count after the
                write, so the caller can report which attempt this was.
        """
        tier = (quality_tier or "").upper() or None
        # One spelling on the row, whoever calls: a bare id is tidal's (the
        # spec's legacy rule), so the store's key can never fork per caller.
        track_id = namespaced_id(track_id)
        # Explicit type wins; a mode-only caller still lands typed via the
        # fallback, so every new row carries what per-version gates filter on.
        atype = normalize_audio_type(audio_type, audio_mode)
        row = (
            str(track_id),
            str(path),
            tier,
            quality_rank(tier),
            audio_mode,
            atype,
            bit_depth,
            sample_rate,
            codecs,
            user_id,
            int(time.time()),
            int(requested_rank),
            int(ceiling_rank),
            1 if degraded else 0,
        )
        with self._lock:
            self._conn.execute(
                """INSERT INTO downloads
                       (track_id, path, quality_tier, quality_rank, audio_mode, audio_type,
                        bit_depth, sample_rate, codecs, user_id, recorded_at,
                        requested_rank, ceiling_rank, degraded_tries)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(track_id, path) DO UPDATE SET
                       quality_tier = excluded.quality_tier,
                       quality_rank = excluded.quality_rank,
                       audio_mode   = excluded.audio_mode,
                       audio_type   = excluded.audio_type,
                       bit_depth    = excluded.bit_depth,
                       sample_rate  = excluded.sample_rate,
                       codecs       = excluded.codecs,
                       user_id      = excluded.user_id,
                       recorded_at  = excluded.recorded_at,
                       requested_rank = excluded.requested_rank,
                       ceiling_rank   = excluded.ceiling_rank,
                       degraded_tries = CASE
                           WHEN excluded.degraded_tries > 0 THEN downloads.degraded_tries + 1
                           ELSE 0
                       END""",
                row,
            )
            self._conn.commit()
            # Read back under the same lock, so the caller can say how many
            # attempts this makes without a second query racing another
            # worker's write (and without ownership_of's disk check, which
            # would stat a network mount for a file just written here).
            got = self._conn.execute(
                "SELECT degraded_tries FROM downloads WHERE track_id = ? AND path = ?",
                (str(track_id), str(path)),
            ).fetchone()
        return int(got[0]) if got else 0

    def record_members_replace(self, collection_id: str, track_ids: list[str]) -> None:
        """Remember the exact, current track ids that make up ``collection_id``
        (an album, playlist or mix), replacing any previous record for it.

        Called wherever Waves already has the full track list in hand for a
        reason other than this (opening the item's page, expanding an album
        panel), so a later "is this fully owned" question elsewhere in the app
        (e.g. a collapsed row that has never been opened) can be answered from
        this local table alone, no re-fetch. A playlist's contents can change,
        so this is a full replace, not an add.
        """
        cid = str(collection_id)
        ids = [str(t) for t in track_ids if t]
        now = int(time.time())
        with self._lock:
            self._conn.execute("DELETE FROM collection_members WHERE collection_id = ?", (cid,))
            self._conn.executemany(
                "INSERT OR IGNORE INTO collection_members (collection_id, track_id, recorded_at) VALUES (?, ?, ?)",
                [(cid, tid, now) for tid in ids],
            )
            self._conn.commit()

    def record_members_add(self, collection_id: str, track_ids: list[str]) -> None:
        """Additively remember that ``track_ids`` belong to ``collection_id``,
        without touching any other membership already recorded for it.

        Called incrementally as a collection download progresses (see
        ``record_members_replace`` for the alternative, authoritative case):
        Waves observes each track as it is queued, so membership for a
        downloaded album/playlist is learned for free, from data already
        flowing through the download, no extra network call.
        """
        cid = str(collection_id)
        ids = [str(t) for t in track_ids if t]
        if not ids:
            return
        now = int(time.time())
        with self._lock:
            self._conn.executemany(
                "INSERT OR IGNORE INTO collection_members (collection_id, track_id, recorded_at) VALUES (?, ?, ?)",
                [(cid, tid, now) for tid in ids],
            )
            self._conn.commit()

    def members_of(self, collection_id: str) -> list[str] | None:
        """Known member track ids for ``collection_id``, or None if Waves has
        never observed this collection's contents (never opened, never
        downloaded): distinct from an empty list, so a caller can tell
        "unknown" apart from a genuinely empty collection.

        A plain indexed lookup against Waves' own local database, not the
        user's music folder: unlike ownership_of, there is no live filesystem
        stat here, so this never risks hanging on a dropped network mount and
        is safe to call directly.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT track_id FROM collection_members WHERE collection_id = ?",
                (str(collection_id),),
            ).fetchall()
        if not rows:
            return None
        return [r[0] for r in rows]

    def ownership_of(self, track_id: str, *, user_id: str | None = None, audio_type: str | None = None) -> dict | None:
        """Best surviving copy of ``track_id`` that still exists on disk right now,
        or None if no recorded path survives (a wanted-again deleted file).

        The question is asked in the store's namespaced spelling: a bare id
        reads as tidal (every pre-namespace caller), a namespaced id only ever
        matches rows of its own provider, so one provider's ownership never
        answers another provider's gate.

        ``audio_type`` ("stereo" / "atmos") narrows to one Version (§5.3):
        per-version gates ask for the version they would fetch, so owning
        stereo leaves the Atmos half fetching and vice versa. None keeps the
        legacy whole-track answer (highest quality first), which is what the
        toggle-off path and every caller that cannot name a version still get.

        Rows are considered highest delivered quality first, then most recent, and
        the first whose path passes a live existence check wins. The deleted-path
        row is skipped, not removed, so re-creating the file makes it own again.
        """
        want = str(audio_type or "").strip().lower() or None
        if want not in (None, "stereo", "atmos"):
            want = None
        tid = namespaced_id(track_id)
        with self._lock:
            if user_id is None:
                rows = self._conn.execute(
                    """SELECT path, quality_tier, quality_rank, audio_mode, audio_type, bit_depth,
                              sample_rate, codecs, recorded_at, requested_rank, ceiling_rank,
                              degraded_tries
                       FROM downloads WHERE track_id = ?
                       ORDER BY quality_rank DESC, recorded_at DESC""",
                    (tid,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """SELECT path, quality_tier, quality_rank, audio_mode, audio_type, bit_depth,
                              sample_rate, codecs, recorded_at, requested_rank, ceiling_rank,
                              degraded_tries
                       FROM downloads WHERE track_id = ? AND user_id = ?
                       ORDER BY quality_rank DESC, recorded_at DESC""",
                    (tid, str(user_id)),
                ).fetchall()
        # Existence check is intentionally OUTSIDE the lock: it can stat the disk,
        # and a read must never hold up a worker-thread write behind it. A
        # zero-byte survivor is a truncation artifact, not a copy: skip it (not
        # removed, like a deleted path) so the track reads as wanted again.
        for path, tier, rank, mode, atype, depth, rate, codecs, recorded_at, requested, ceiling, degraded in rows:
            if want is not None and not _matches_audio_type(atype, mode, want):
                continue
            if path and _nonempty_file(path):
                return {
                    "owned": True,
                    "path": path,
                    "quality_tier": tier,
                    "quality_rank": rank,
                    "audio_mode": mode,
                    "audio_type": normalize_audio_type(atype, mode),
                    "bit_depth": depth,
                    "sample_rate": rate,
                    "codecs": codecs,
                    "recorded_at": recorded_at,
                    "requested_rank": requested,
                    "ceiling_rank": ceiling,
                    "degraded_tries": degraded,
                }
        return None

    def folder_names_under(self, base: str, limit: int = 5000) -> list[str]:
        """The first folder name under ``base`` of every path this store has
        recorded, newest first, deduplicated.

        These are not guesses. They are the exact directory names Waves itself
        wrote on that disk, which makes them the one seed list worth having when
        a share's directory listing is broken and the folders can only be found
        by asking for them by name (see LibraryIndex.probe_folders). A path that
        does not live under ``base`` is skipped, so switching library folders
        never leaks names from the old one."""
        base = os.path.normpath(os.path.expanduser(str(base or ""))).rstrip(os.sep)
        if not base:
            return []
        prefix = base + os.sep
        names: dict[str, None] = {}
        with self._lock:
            rows = self._conn.execute(
                "SELECT path FROM downloads WHERE path IS NOT NULL ORDER BY recorded_at DESC"
            ).fetchall()
        for (path,) in rows:
            text = str(path or "")
            if not text.startswith(prefix):
                continue
            head = text[len(prefix) :].split(os.sep, 1)[0].strip()
            if head and head not in (".", ".."):
                names.setdefault(head, None)
                if len(names) >= max(1, int(limit)):
                    break
        return list(names)

    # ----- Integrity skip-list (issue #30) ----------------------------------

    @staticmethod
    def _skip_audio_key(audio_type: str | None) -> str:
        """The skip-list's per-version key: "stereo" / "atmos" / "" (legacy).

        Empty means the legacy whole-track entry (a caller that cannot name a
        version). Versioned lookups match their own key only, so a corrupt
        Atmos source never blocks its stereo sibling.
        """
        text = str(audio_type or "").strip().lower()
        return text if text in ("stereo", "atmos") else ""

    def quarantine_add(self, track_id: str, audio_type: str | None = None, encoded_date: str | None = None) -> None:
        """Mark a track's version as quarantined (bulk runs auto-skip it)."""
        tid = namespaced_id(track_id)
        key = self._skip_audio_key(audio_type)
        with self._lock:
            self._conn.execute(
                """INSERT INTO integrity_skip (track_id, audio_type, encoded_date, quarantined_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(track_id, audio_type) DO UPDATE SET
                       encoded_date = excluded.encoded_date,
                       quarantined_at = excluded.quarantined_at""",
                (tid, key, str(encoded_date or "") or None, int(time.time())),
            )
            self._conn.commit()

    def quarantine_remove(self, track_id: str, audio_type: str | None = None) -> None:
        """Clear a quarantine mark: a verified copy landed (REDOWNLOAD's way back).

        A versioned clear removes only that version; a legacy (None) clear
        removes every version of the track, so one verified copy cannot leave
        a stale sibling mark behind.
        """
        tid = namespaced_id(track_id)
        with self._lock:
            if audio_type is None:
                self._conn.execute("DELETE FROM integrity_skip WHERE track_id = ?", (tid,))
            else:
                self._conn.execute(
                    "DELETE FROM integrity_skip WHERE track_id = ? AND audio_type = ?",
                    (tid, self._skip_audio_key(audio_type)),
                )
            self._conn.commit()

    def is_quarantined(self, track_id: str, audio_type: str | None = None) -> dict | None:
        """A skip-list entry for a track's version, or None.

        A versioned query matches its own key only (per-version quarantine).
        A legacy (None) query matches any version of the track, so callers
        that cannot name a version still see the mark.
        """
        tid = namespaced_id(track_id)
        with self._lock:
            if audio_type is None:
                row = self._conn.execute(
                    "SELECT track_id, audio_type, encoded_date, quarantined_at"
                    " FROM integrity_skip WHERE track_id = ? LIMIT 1",
                    (tid,),
                ).fetchone()
            else:
                row = self._conn.execute(
                    "SELECT track_id, audio_type, encoded_date, quarantined_at"
                    " FROM integrity_skip WHERE track_id = ? AND audio_type = ?",
                    (tid, self._skip_audio_key(audio_type)),
                ).fetchone()
        if not row:
            return None
        return {
            "track_id": row[0],
            "audio_type": row[1] or None,
            "encoded_date": row[2],
            "quarantined_at": row[3],
        }

    def close(self) -> None:
        with self._lock:
            self._conn.close()
