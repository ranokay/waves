"""The queue state-machine family: what is queued, what runs, what finished.

This is the source behind the queue drawer, the per-button progress faces and
the bulk actions (clear, retry, pause, resume). It owns the queue model (rows,
rollups, ledger), the delta protocol that publishes it to QML (`_emit_queue` /
`_flush_queue_changes`, the frozen interface other families program against),
and the entry points other families use to feed it (`_enqueue`,
`_set_queue_status`, `_set_queue_progress`, `_remove_rows_where`,
`_queue_resync`).

A mixin over WavesBridge rather than a section of backend.py. State stays on
the bridge, created in WavesBridge.__init__ (the queue, its index, the dirty
flags, the registries): this module owns behavior, not lifecycle. This module
must never import backend.

Pilot scope (ARCH-01): 40 of the 46 audited group-6 methods move here
mechanically. Six stay in backend until their helpers get homes: the row
builders and skip prediction (`loadQueueTracks`, `_predict_skips`) read the
row/quality vocabulary the suite patches on backend, and the refetch helpers
(`_row_object`, `_start_retry`, `retryQueueItem`, `_retry_all_with_status`)
read the download/refetch runtime owned by the coming job-runtime design.
"""

from __future__ import annotations

import contextlib
import logging
import time
from threading import current_thread, main_thread

from PySide6 import QtGui
from PySide6.QtCore import Slot

from waves.constants import CTX_TIDAL
from waves.desktop.worker import Worker

logger = logging.getLogger("waves.queue")


class QueueMixin:
    """Queue behavior for WavesBridge. See the module docstring."""

    def _trim_queue_history(self) -> None:
        """Bound what the finished half of the queue costs, without asking.

        Everything the queue does per change is proportional to its length: the
        whole list is marshalled across to QML on every status change and
        reconciled row by row there, and each collection row also holds a
        per-track registry that lives as long as the row. Unbounded, a long
        batch leaves the drawer carrying its own history and paying for it on
        every update.

        Oldest settled rows go first, and only past the cap; queued, running,
        failed and stopped rows are never touched. Nothing is lost with them: what was
        downloaded is recorded in the ownership store, which is what every
        later question (already have it? which quality? which tracks were in
        that album?) is answered from. These rows are a view of the session,
        and past a couple of hundred they are a view nobody scrolls to."""
        if len(self._queue) <= self._QUEUE_HISTORY_MAX:
            return
        with self._queue_lock:
            over = len(self._queue) - self._QUEUE_HISTORY_MAX
            kept = []
            gone = []
            for row in self._queue:
                if over > 0 and row.get("status") in self._QUEUE_SETTLED:
                    over -= 1
                    gone.append(row["qid"])
                    continue
                kept.append(row)
            if not gone:
                return  # all of it is live work; the cap does not apply
            self._queue = kept
            self._reindex_queue()
            self._qdirty_removed.extend(gone)

    def _queue_mark_changed(self, qid: int) -> None:
        """Record that a row's fields moved (any thread)."""
        with self._queue_lock:
            self._qdirty_changed[qid] = None

    def _remove_rows_where(self, pred, withdrawn_out: list[str] | None = None) -> list[int]:
        """Drop every row ``pred`` accepts in ONE pass over the queue, record
        them for QML, and return their qids. The one way a row leaves the
        queue: a per-row rebuild of the list was a quadratic stall when RETRY
        ALL or a clear walked thousands of rows (measured 25 s at 10,000).
        Caller must hold NEITHER _queue_lock nor _pending_lock (both are taken
        here, one after the other and never nested), and still calls
        _emit_queue().

        ``withdrawn_out``, when given, is filled with the media ids of the
        rows that were still ``queued`` at the instant they were dropped, for
        callers that settle those rollups (a row that never started has no
        worker left to credit it). Read here, under the one lock that decides
        the removal, because a caller that lists them itself is reading the
        queue a second time: a row can flip queued to running on the worker
        thread between the two acquisitions, and the clears that did this
        credited a row as failed that had in fact just started, painting a
        red discography over an album that went on to land."""
        # A download held for the download folder to come back is not
        # abandoned: the gate withdrew its row precisely BECAUSE it stashed a
        # replay, so a withdrawal here can be a hold rather than a give-up, and
        # the per-row state below must survive it. All three pieces of it, not
        # the plan alone: the replay re-reads the REDOWNLOAD force and the
        # library-claim override when it builds its job, so releasing those two
        # left a held REDOWNLOAD coming back as an ordinary download that
        # skipped every file the user had just confirmed replacing, with
        # nothing on screen to say why. Snapshotted before the queue lock is
        # taken and never inside it, so the two locks are never nested; skipped
        # entirely when nothing is outstanding, which is the common case.
        held: set[str] = set()
        if self._merge_plans or self._redownload_overrides or self._library_claim_overrides:
            with self._pending_lock:
                held = {str(mid) for mid, _fn in self._pending_downloads if mid}
        with self._queue_lock:
            dropped = [it for it in self._queue if pred(it)]
            if not dropped:
                return []
            gone = [it["qid"] for it in dropped]
            if withdrawn_out is not None:
                withdrawn_out.extend(str(it.get("media_id", "") or "") for it in dropped if it["status"] == "queued")
            self._queue = [it for it in self._queue if not pred(it)]
            self._reindex_queue()
            self._qdirty_removed.extend(gone)
            # A withdrawn row's quarantine paths are unreachable from the UI
            # with it; the bytes stay on disk for the skip-list's account.
            paths = getattr(self, "_apple_quarantine_paths", None)
            if paths:
                for qid in gone:
                    paths.pop(qid, None)
            forced = self._redownload_overrides
            # registerRedownload marks BOTH sets, so releasing only the first
            # left the withdrawn item exempt from the library scan's bulk
            # tag-claim gate for the rest of the session: the same half-release
            # this block exists to close, one set over.
            claims = self._library_claim_overrides
            # And the third piece of per-row state: the best-of-both plan the
            # scan stashed for this album. downloadAlbum PEEKS it (it must
            # survive a retry), so a plan left behind by a withdrawn row was
            # consumed by the next plain click on that album, bypassing the
            # preference entirely: with "best of both" since turned off, the
            # click still assembled a cross-edition copy, and the "Best of
            # both:" line that would have said so is only written on the
            # explicit path.
            plans = self._merge_plans
            # Only walked when something is actually outstanding: this is the
            # one removal path, and it was made one pass over the queue on
            # purpose (a per-row rebuild was a quadratic stall at thousands of
            # rows).
            live = (
                {str(it.get("media_id", "") or "") for it in self._queue if it["status"] in ("queued", "running")}
                if (forced or claims or plans)
                else set()
            )
        # A REDOWNLOAD force goes out with the row that asked for it. The mark
        # is a session-wide set: the job that consumes it drops it on success
        # and deliberately keeps it on failure and on cancel so a RETRY of
        # that download stays forced. Nothing dropped it when the row was
        # WITHDRAWN instead, and CANCEL, CLEAR ALL and every section clear
        # withdraw rows. So a REDOWNLOAD confirmed and then cleared before it
        # ran left its force behind, and the next click on that item this
        # session, from anywhere (a discography, a folder, a playlist's
        # albums), was silently forced too: it re-fetched and overwrote copies
        # it should have skipped, with no owned gate and nothing to show why.
        # Released only when nothing live still holds the force, so a retry
        # (which re-queues the item before its old row is dropped) keeps it.
        # Held work keeps all of it: the replay is still going to run, and a
        # merge that came back a plain album would write the identity
        # edition's own lower-quality tracks over the ones it had borrowed,
        # with nothing on screen to say so. The abandoning paths (STOP, the
        # nudge dismissal, a clear that reaches the stash) release it instead,
        # through _release_abandoned_hold: a hold that will never replay must
        # not keep a force or a plan alive for the rest of the session.
        for row in dropped if (forced or claims or plans) else ():
            mid = str(row.get("media_id", "") or "")
            if mid and mid not in live and mid not in held:
                forced.discard(mid)
                claims.discard(mid)
                plans.pop(mid, None)
        return gone

    def _remove_row(self, qid: int, withdrawn_out: list[str] | None = None) -> bool:
        return bool(self._remove_rows_where(lambda it: it["qid"] == qid, withdrawn_out))

    def _abort_if_in_flight(self, gone) -> None:
        """Abort the one job in flight when its row is among those just dropped.

        _pump_queue hands a row to the pool while it still reads ``queued``:
        the status only flips to ``running`` further in, after the download
        folder's reachability probe, which against a sleeping network share is
        seconds of probe, remount and probe again. Every bulk clear selects on
        that status, so the row of a job that was already downloading could be
        withdrawn with nothing left to stop it. The album then ran to
        completion with no row, no progress and no control (the queue reads
        idle, which hides STOP), over a drawer that had already credited it as
        failed. Setting the abort is what per-row CANCEL does for the same
        row; a row that never became a job has no abort to set and is stopped
        by dropping its spec, as before."""
        qid = self._running_qid
        if qid is None or qid not in set(gone):
            return
        ev = self._jobs.aborts.get(qid)
        if ev is not None:
            ev.set()

    def _queue_resync(self) -> None:
        """Ask for the whole queue to cross as one queueChanged: for a rebuild
        the delta signals cannot describe, and for labs and tests that set
        row fields directly (nothing marks those)."""
        with self._queue_lock:
            self._qdirty_full = True
        self._emit_queue()

    @contextlib.contextmanager
    def _queue_batch(self):
        """Hold the queue's delivery until the whole batch is in.

        A discography, a folder of playlists or a RETRY ALL adds rows one at a
        time and would otherwise deliver the queue once per row, so the drawer
        visibly counts 0 to N. Suspending coalesces that into one delivery.

        The flush belongs in the same finally as the flag: on the line after,
        a loop body that raised would skip it while the flag was still
        cleared, leaving the rows queued and marked dirty but undelivered
        until some later, unrelated change flushed the marks, with the drawer
        showing none of the work that had just started.
        """
        outer = self._queue_emit_suspended
        self._queue_emit_suspended = True
        try:
            yield
        finally:
            # Restored rather than cleared, so a batch opened inside another
            # one (none today, but nothing stops one) closes with the outer
            # batch instead of delivering half of it early. _emit_queue is a
            # no-op while a batch is still open.
            self._queue_emit_suspended = outer
            self._emit_queue()

    def _emit_queue(self) -> None:
        """Deliver what changed. On the GUI thread the flush runs now, so a
        slot's effect is on screen when it returns; a worker thread posts one
        flush request and carries on (a second request while one is pending
        is dropped: the flush picks up everything marked by then)."""
        if self._queue_emit_suspended:
            return
        if current_thread() is main_thread():
            self._flush_queue_changes()
            return
        with self._queue_lock:
            if self._qflush_posted:
                return
            self._qflush_posted = True
        self._queueFlushRequested.emit()

    @Slot()
    def _flush_queue_changes(self) -> None:
        """GUI thread: turn the dirty marks into the delta signals (or one
        queueChanged when a resync was asked for), then clear them."""
        with self._queue_lock:
            self._qflush_posted = False
        if self._queue_emit_suspended:
            return  # a batch is open; its close flushes the lot
        self._trim_queue_history()  # the finished half is bounded, not banked
        with self._queue_lock:
            full = self._qdirty_full
            added = self._qdirty_added
            changed = self._qdirty_changed
            removed = list(dict.fromkeys(self._qdirty_removed))
            # A patch set covering most of the queue (STOP over thousands of
            # queued rows) is cheaper as one resync than as that many
            # per-row patches: the reconcile updates rows in place, so
            # nothing visible differs, only the delivery.
            if len(changed) >= 1000 and len(changed) * 2 >= len(self._queue):
                full = True
            self._qdirty_added = []
            self._qdirty_changed = {}
            self._qdirty_removed = []
            self._qdirty_full = False
            index = self._queue_index
            if full:
                snapshot = list(self._queue)
            else:
                fresh = set(added)
                rows_added = [dict(index[q]) for q in added if q in index]
                patches = [dict(index[q]) for q in changed if q in index and q not in fresh]
                gone = [q for q in removed if q not in index]
        if removed:
            self._prune_job_tracks(removed)  # registries follow their queue rows out
        if full:
            self.queueChanged.emit(snapshot)
            return
        if gone:
            self.queueRowsRemoved.emit(gone)
        if rows_added:
            self.queueRowsAdded.emit(rows_added)
        if patches:
            self.queueRowsChanged.emit(patches)

    def _enqueue_albums(self, gen: int, keys) -> None:
        """Enqueue a batch of album downloads as a single queue update.

        Runs on the GUI thread (via the queued ``_albumsQueued`` signal), so
        each album's progress relay keeps GUI-thread affinity. Per-item
        ``queueChanged`` emits are coalesced into one so the whole discography
        appears at once rather than the queue visibly jumping 0 → N.

        ``gen`` is the scan generation the ordering scan captured: a batch
        posted before STOP can be DELIVERED after it, and would then queue the
        whole discography behind the press. A stale batch queues nothing and
        resets any button the scan lit for its keys."""
        if gen != self._scan_gen:
            # The scan marked every key exempt from the edition scan before it
            # emitted this batch, and the mark is consumed by the next click
            # on that album. Nothing queued, so nothing consumes them: release
            # them here, exactly as the single-album scan does when it is
            # stopped or fails. A mark left behind silently downgraded one
            # later Download-album click per key to a plain download, skipping
            # the edition scan the preference asks for.
            for key in keys:
                self._merge_scanned.discard(str(key))
                # And the plan the scan stashed under this key, for the same
                # reason: nothing queued means nothing consumes it, and a plan
                # left in _merge_plans makes the next PLAIN click on that album
                # silently download a cross-edition assembly, with no "Best of
                # both:" line anywhere to say that is what happened.
                self._merge_plans.pop(str(key), None)
                self.downloadState.emit(str(key), "")
            return
        with self._queue_batch():
            for key in keys:
                self.downloadAlbum(str(key))

    def _enqueue_tracks(self, gen: int, keys) -> None:
        """Batch counterpart of _enqueue_albums for individual tracks (guest
        appearances from a discography download). Same GUI-thread affinity,
        coalesced queueChanged, and stale-generation refusal rationale."""
        if gen != self._scan_gen:
            for key in keys:
                self.downloadState.emit(str(key), "")
            return
        with self._queue_batch():
            for key in keys:
                self.downloadTrack(str(key))

    def _enqueue_videos(self, gen: int, keys) -> None:
        """Batch counterpart of _enqueue_albums for an artist's music videos
        (queued by a discography download when the Music videos source is on).
        Same GUI-thread affinity, coalesced queueChanged, and stale-generation
        refusal rationale."""
        if gen != self._scan_gen:
            for key in keys:
                self.downloadState.emit(str(key), "")
            return
        with self._queue_batch():
            for key in keys:
                self.downloadVideo(str(key))

    def _enqueue_artists(self, gen: int, ids) -> None:
        """Batch counterpart of _enqueue_albums for a shelf's favourite
        artists: each id starts its own discography download. Same
        GUI-thread affinity, coalesced queueChanged, and stale-generation
        refusal (a batch posted before STOP starts no discography after it).
        The artists' own buttons were never lit, so a stale batch only has
        to start nothing."""
        if gen != self._scan_gen:
            return
        with self._queue_batch():
            for artist_id in ids:
                self.downloadArtist(str(artist_id))

    def _enqueue_collections(self, gen: int, kind: str, keys) -> None:
        """Batch counterpart of _enqueue_albums for a shelf's favourite
        playlists or mixes (``kind`` is "playlist" or "mix"). Same
        GUI-thread affinity, coalesced queueChanged, and stale-generation
        refusal rationale."""
        start = self.downloadPlaylist if kind == "playlist" else self.downloadMix
        if gen != self._scan_gen:
            return
        with self._queue_batch():
            for key in keys:
                start(str(key))

    def _enqueue(
        self,
        name: str,
        type_media: str,
        media_id: str = "",
        template: str = "",
        collection: bool = False,
        artist: str = "",
        tracks: int = 0,
        art: str = "",
        expected: str = "",
        ask_quality: str | None = None,
        ask_tier: str | None = None,
        audio_type: str | None = None,
        ask_toggles: dict | None = None,
    ) -> int:
        # A per-item quality choice arrives as both halves of the ask (the
        # Waves tier string the job pins, the word the drawer states); without
        # one both come from the setting as they always have.
        if ask_quality is None or ask_tier is None:
            ask_quality, ask_tier = self._queued_quality_value(), self._target_tier()
        # Which Version this row downloads (§5.2): None keeps the legacy
        # single-row shape (stereo default, byte-identical); "stereo" / "atmos"
        # mark the two rows of a dual-download pair. Seeded so the drawer's
        # model fixes the role from the first row it is handed.
        atype = str(audio_type or "").strip().lower() or None
        if atype not in (None, "stereo", "atmos"):
            atype = None
        self._queue_seq += 1
        qid = self._queue_seq
        row = {
            "qid": qid,
            "name": name,
            "type": type_media,
            "status": "queued",
            # Why a settled row ended the way it did, in the user's words, or
            # "" for every row that has nothing to explain. Seeded here like
            # `landed` and for the same reason: the drawer's model fixes its
            # roles from the first row it is handed, so a field that only
            # appears later exists on no row at all.
            "reason": "",
            "progress": 0.0,
            "media_id": media_id,
            "template": template,
            "collection": collection,
            # Shown in the queue row ("artist · done/total tracks"); the QML
            # derives the done count from progress and the track total.
            "artist": artist,
            "tracks": tracks,
            # Cover/thumb URL for the queue card (empty when unavailable).
            "art": art,
            # The tier this job will ASK for, known before a byte is fetched, so
            # the drawer can state a quality while the row is still queued. What
            # actually lands is reported per track and can differ (a release
            # without a hi-res master downgrades), which is the point of showing
            # the two separately.
            "quality": ask_tier,
            # The audio quality this job is queued at, held for its whole
            # life: a change in Settings retargets nothing that is already
            # queued or running, it applies to what is queued from then on.
            # Stored as the plain Waves tier string so the
            # row stays a QML-friendly dict.
            "askQuality": ask_quality,
            # Whether the library scan's tag claim may skip tracks for this job,
            # pinned here for the same reason the quality is: the run's gate and
            # the expanded row's prediction must answer alike, and a preference
            # flipped while a long queue works through it would otherwise move
            # one of them and not the other. See _job_library_skip.
            "askLibrarySkip": self._library_bulk_skip_on(),
            # The catalog's advertised ceiling for this release ("" when it has
            # none: playlists and mixes have no tier of their own). The drawer
            # states the LOWER of this and the request, so a lossless-only
            # album asked for in HI-RES reads LOSSLESS from the moment it is
            # queued, instead of a HI-RES that the first delivery contradicts.
            "expected": expected,
            # The delivery, rolled up from the per-track registry by
            # _track_lifecycle (see _delivered_rollup). Seeded here so every row
            # carries both fields from birth: the drawer's model fixes its roles
            # from the first row it is handed, so a field that only appears
            # later exists on no row at all.
            "landed": "",
            "mix": [],
            # The same rollup pre-serialized once here, because the QML side
            # wants it as a string role anyway (a ListModel array role turns
            # into a nested model): stringifying in Python per CHANGE beats
            # JSON.stringify in QML per row per reconcile pass.
            "mixJson": "[]",
            # Dual-download Version (§5.2): None for legacy single rows,
            # "stereo" / "atmos" for the two rows of a pair. The Atmos row is
            # badged ATMOS from its expected/quality words; both rows carry
            # their own progress, cancel, retry and file link via their qids.
            "audioType": atype or "",
            # The per-click Chooser lyrics/art pins this row was queued with
            # (base keys, booleans). Empty for a plain click: the job then
            # reads the provider's stored options. Pinned like the quality so
            # a retry asks with the same options.
            "askToggles": dict(ask_toggles or {}),
            # How many quarantined copies this row's job wrote (Apple
            # integrity failures only). The drawer shows open/delete actions
            # while it is nonzero; the paths themselves stay bridge-side.
            "quarantineCount": 0,
        }
        with self._queue_lock:
            self._queue.append(row)
            self._queue_index[qid] = row
            self._qdirty_added.append(qid)
        self._emit_queue()
        return qid

    def _reindex_queue(self) -> None:
        """Rebuild the qid index after a wholesale _queue rebuild. Caller must
        hold _queue_lock."""
        self._queue_index = {it["qid"]: it for it in self._queue}

    def _queue_item(self, qid: int) -> dict | None:
        return self._queue_index.get(qid)

    def _set_queue_status(self, qid: int, status: str, reason: str = "") -> None:
        """Move a row to its new status, optionally with the reason it got
        there. A status that carries no reason clears the one the row had --
        a row retried in place and finished cannot keep explaining a failure
        that no longer stands -- except a wordless cancel settle on a row a
        stop already worded: the provider-disable reason survives the
        worker's own settle."""
        item = self._queue_item(qid)
        if item is None:
            return
        reason = str(reason or "")
        if item["status"] == status and item.get("reason", "") == reason:
            return
        if status == "cancelled" and not reason and item["status"] == "cancelled" and item.get("reason", ""):
            # A stop that already gave the row its words (the provider was
            # disabled) is the one the user reads: the worker's wordless
            # settle that follows must not erase them.
            return
        item["status"] = status
        item["reason"] = reason
        self._queue_mark_changed(qid)
        self._emit_queue()

    def _set_queue_progress(self, qid: int, pct: float) -> None:
        item = self._queue_item(qid)
        if item is not None:
            item["progress"] = pct
            self.queueItemProgress.emit(qid, float(pct))

    def _report_pct(self, media_id: str, qid: int, pct: float) -> None:
        """Fan a per-track progress tick out to the media button, the queue row
        and any artist-discography aggregate. Called on the GUI thread via the
        _ProgressSignals bound slot."""
        item = self._queue_item(qid)
        if item is not None:
            # download.py's exact finished/total marks lag the smooth poller
            # (finished + running fractions) whenever several tracks are in
            # flight, so a lower tick would snap the bar backward: clamp to
            # keep every fan-out target monotonic per job.
            pct = max(float(pct), float(item.get("progress", 0.0)))
        pct = float(pct)
        # Coalesce only the broadcast fan-out. downloadProgress reaches every
        # instantiated download control (each re-reads it on change), and a
        # single DASH-delivered track emits item() per segment with no throttle,
        # so an ungated broadcast fires dozens of GUI-thread rebinds in a burst.
        # Gate it to a 0.5% min delta or a ~10 Hz ceiling per media id, but never
        # swallow the terminal 100% (a bar must be able to complete). The queue
        # row update below stays every-tick: it is already targeted
        # (queueItemProgress) and keeps item["progress"] fresh for the
        # monotonic clamp above. The group rollup rides the SAME gate as the
        # broadcast: it re-sums a group's whole key set and emits two signals,
        # and a discography group can hold ~2000 keys, so an ungated call is
        # O(group) GUI-thread work per segment tick. Terminal done/failed
        # bumps come from the download epilogue, not this path, so completion
        # accounting never depends on the gate.
        broadcast = self._should_broadcast_pct(media_id, pct)
        if broadcast:
            self.downloadProgress.emit(media_id, pct)
        self._set_queue_progress(qid, pct)
        if broadcast:
            self._bump_download_groups(media_id, pct, None)

    def _should_broadcast_pct(self, media_id: str, pct: float) -> bool:
        """Rate-gate the downloadProgress broadcast for one media id. GUI-thread
        only (no lock). Always lets the first tick and the terminal 100% through,
        so a bar neither starts blank nor stalls just short of complete."""
        prev = self._pct_last.get(media_id)
        now = time.monotonic()
        if prev is None or pct >= 100.0:
            self._pct_last[media_id] = (pct, now)
            return True
        prev_pct, prev_t = prev
        if abs(pct - prev_pct) >= 0.5 or (now - prev_t) >= 0.1:
            self._pct_last[media_id] = (pct, now)
            return True
        return False

    @Slot()
    def _poll_track_progress(self) -> None:
        """Read live per-track percentages out of each running job's
        Progress, each row through the TaskID the engine handed it.

        Not through the task's description: that is the display name cut to 30
        characters, and any release whose joined artist credit runs that long
        (a "Berliner Philharmoniker, Herbert von Karajan", a three-way feature)
        gives every one of its tracks the identical description. Rows then read
        whichever sibling registered last, the roll-up sums those mirrored
        values, and because the roll-up only ever rises the wrong answer sticks
        for the rest of the job."""
        if not self._jobs.dls:
            self._track_poll.stop()
            self._pct_last.clear()  # bound the broadcast-gate memo to one session
            self._prune_job_tracks()  # nothing is running: settle per-row state whose row has gone
            return
        for qid, dl in list(self._jobs.dls.items()):
            reg = self._jobs.tracks.get(qid)
            if not reg:
                continue
            try:
                tasks = {int(t.id): t.percentage for t in dl.progress.tasks}
                row_tasks = dl.row_task_ids()
            except Exception:
                # Transient: the engine mutates the task list from worker threads;
                # skip this tick and read a consistent snapshot next time.
                logger.debug("Skipped a track-progress poll tick", exc_info=True)
                continue
            ticks: dict[str, float] = {}
            for tid, row in reg.items():
                if row.get("status") != "running":
                    continue
                task_id = row_tasks.get(tid)
                if task_id is None:
                    # Running, but the engine has not sized the stream yet, so
                    # there is no task to read. The row holds at its last value.
                    continue
                pct = tasks.get(task_id)
                if pct is None:
                    continue
                pct = max(0.0, min(100.0, float(pct)))
                if abs(pct - float(row.get("pct", 0.0))) >= 0.5:
                    row["pct"] = pct
                    ticks[tid] = pct
            if ticks:
                self.queueTrackPct.emit(qid, ticks)
            self._bump_group_progress(qid, reg)

    def _bump_group_progress(self, qid: int, reg: dict) -> None:
        """Fold the in-flight tracks' fractional progress into an album or
        playlist row's roll-up so the bar creeps between track completions
        instead of jumping once per finished track: (consumed + running
        fractions) / total. Monotonic (only ever raises the row's percent);
        the exact finished/total marks from list_item are clamped the same way
        in _report_pct so they can never drag the bar backward."""
        item = self._queue_item(qid)
        if item is None or not item.get("collection"):
            return
        total = int(item.get("tracks") or 0)
        if total <= 0:
            return
        # Every settled outcome counts, not just the ones that wrote a file: a
        # track already owned, refused by TIDAL or kept out by a setting is work
        # the job will never come back to. Leaving them out only ever undercounts
        # (the engine's own per-item advance still feeds _report_pct, and the
        # clamp there takes the higher of the two), but an undercounting poller
        # is a poller that cannot be reasoned about.
        consumed = sum(
            1 for r in reg.values() if r.get("status") in ("done", "failed", "cancelled", "unavailable", "skipped")
        )
        running = sum(float(r.get("pct", 0.0)) for r in reg.values() if r.get("status") == "running")
        smooth = min(100.0, (consumed * 100.0 + running) / total)
        if smooth <= float(item.get("progress", 0.0)) + 0.1:
            return
        if item.get("media_id"):
            # Fans out to the media button and any artist-discography group
            # too, so those bars inherit the same smooth motion.
            self._report_pct(item["media_id"], qid, smooth)
        else:
            self._set_queue_progress(qid, smooth)

    def _apply_owned_marks(self, qid: int, marks) -> None:
        """GUI thread: keep an expansion's predicted skips and re-merge them
        into the list already on screen."""
        qid = int(qid)
        if self._queue_item(qid) is None:
            return  # the row went while the prediction was being worked out
        self._job_owned[qid] = dict(marks or {})
        if qid in self._job_fetched:
            self._merge_queue_tracks(qid, self._job_fetched[qid])

    def _merge_queue_tracks(self, qid: int, fetched) -> None:
        """GUI thread: overlay live track states onto the fetched album order
        (falling back to the registry alone when the fetch came back empty)."""
        if self._queue_item(int(qid)) is None:
            # Expanding a 500-track playlist row is a network fetch, and the
            # row can be cleared before it lands. The answer has nowhere to
            # go: keeping it would leave a list per row on both sides of the
            # bridge for a row neither side still has.
            return
        reg = self._jobs.tracks.get(int(qid), {})
        # Predicted skips (_predict_skips), applied only where the run has not
        # spoken for that track yet: a live event is fact and always wins.
        marks = self._job_owned.get(int(qid), {})
        rows: list[dict] = []
        if fetched:
            self._job_fetched[int(qid)] = fetched
            for entry in fetched:
                st = reg.get(str(entry["id"])) or {}
                mark = marks.get(str(entry["id"])) if st.get("status", "pending") == "pending" else None
                if mark:
                    st = {
                        # "owned" is the PREDICTED twin of "skipped": the copy
                        # and its tier are facts about the disk, the skip is
                        # what the run is expected to do when it gets there.
                        "status": "owned",
                        "quality": mark.get("tier", ""),
                        "owned": mark.get("kind", "own"),
                        "expected": st.get("expected", ""),
                    }
                rows.append(
                    {
                        **entry,
                        "status": st.get("status", "pending"),
                        "pct": float(st.get("pct", 0.0)),
                        # The tier this track actually landed at. Carried over
                        # explicitly: the fetched entry only knows the album's
                        # running order, so a row expanded AFTER its tracks
                        # finished would otherwise show a blank quality for
                        # every one of them, the registry holding the answer
                        # all along.
                        "quality": st.get("quality", ""),
                        "expected": entry.get("expected") or st.get("expected", ""),
                        "owned": st.get("owned", ""),
                        "reason": st.get("reason", ""),
                        "quarantined": bool(st.get("quarantined", False)),
                    }
                )
        else:
            rows.extend(
                {
                    "id": st.get("id", ""),
                    "num": 0,
                    "title": st.get("title", ""),
                    "duration": st.get("duration", ""),
                    "status": st.get("status", "pending"),
                    "pct": float(st.get("pct", 0.0)),
                    "quality": st.get("quality", ""),
                    "expected": st.get("expected", ""),
                    "owned": st.get("owned", ""),
                    "reason": st.get("reason", ""),
                    "quarantined": bool(st.get("quarantined", False)),
                }
                for st in sorted(reg.values(), key=lambda r: (r.get("vol", 1), r.get("num", 0)))
            )
            for i, row in enumerate(rows, start=1):
                row["num"] = i
        self.queueTracksLoaded.emit(int(qid), rows)

    def _prune_job_tracks(self, qids=None) -> None:
        """Drop the per-row state of rows that are gone: the per-track
        registry, the expansion's predicted skips and the list they were
        overlaid on, and the row's live object. Given the qids that just
        left (the flush knows them), it costs those rows; without them it
        sweeps everything against the queue, which is the safety net: it runs
        when the last collection download finishes, so anything a writer
        seeded for a row that is no longer there is settled at the next idle
        moment rather than held for the session."""
        if qids is None:
            live = {it["qid"] for it in self._queue}
            qids = [q for q in list(self._jobs.tracks) + list(self._jobs.objs) if q not in live]
        for qid in qids:
            self._jobs.tracks.pop(qid, None)
            self._job_owned.pop(qid, None)
            self._job_fetched.pop(qid, None)
            self._jobs.objs.pop(qid, None)

    @Slot(str)
    def cancelQueuedGroup(self, gid: str) -> None:
        """Give up a whole rollup (a discography, a folder "download all")
        from its own button, the way ``cancelQueueItem`` gives up one row.

        A rollup id is not a queue row's media id, so the button's cancel X
        had nothing to cancel: it queues N album or playlist rows and shows
        one button over them. The group is dropped FIRST, so the members'
        withdrawal does not credit N failures against it and leave the button
        reading RETRY over a batch the user deliberately called off; the
        button is then put back to idle by hand."""
        gid = str(gid or "")
        if not gid:
            return
        keys: set[str] = set()
        with self._artist_lock:
            grp = self._artist_groups.pop(gid, None)
        if grp is not None:
            keys |= set(grp.get("keys") or ())
        with self._folder_lock:
            fgrp = self._folder_groups.pop(gid, None)
        if fgrp is not None:
            keys |= set(fgrp.get("keys") or ())
        if grp is None and fgrp is None:
            return
        with self._queue_lock:
            qids = [
                int(it["qid"])
                for it in self._queue
                if str(it.get("media_id", "")) in keys and it.get("status") in ("queued", "running")
            ]
        for qid in qids:
            self.cancelQueueItem(qid)
        # A member HELD for recovery has no queue row (see _bump_folder_group),
        # so the sweep above cannot see it and cancelQueueItem never reaches
        # its stash. Left behind, the share comes back, the replay fires, and
        # an album the user called off downloads itself with its group already
        # popped, so it can never report anything. Cancelling a whole rollup
        # has to reach the stash the same way cancelling one row does.
        held = self._discard_pending_downloads(keys)
        self._release_abandoned_hold(held)
        self.downloadState.emit(gid, "")
        logger.info(
            "A queued rollup was cancelled from its button (%d rows, %d held)",
            len(qids),
            len(held),
        )
        self._set_status("Cancelled")

    @Slot()
    def clearFinished(self) -> None:
        """Clear the Completed section: done rows.

        Failed and stopped rows are NOT swept here: losing them silently
        alongside the completed ones would vanish a failure before it could
        be retried. The Failed and Stopped sections carry their own CLEAR, so
        dismissing a failure or a STOP is always something the user aimed
        at."""
        self._remove_rows_where(lambda q: q["status"] == "done")
        self._reap_stranded_groups()
        self._emit_queue()

    @Slot()
    def clearFailed(self) -> None:
        """Clear the Failed section: failed rows only. Terminal rows, so no
        Worker to abort. Stopped rows have their own section and CLEAR."""
        self._remove_rows_where(lambda q: q["status"] == "failed")
        self._reap_stranded_groups()
        self._emit_queue()

    @Slot()
    def clearStopped(self) -> None:
        """Clear the Stopped section: the rows STOP ended.

        Terminal rows like failed ones: their Workers were aborted by stopAll,
        so there is nothing to abort here. Failed rows are not touched, so a
        stop is dismissed without losing a failure beside it."""
        self._remove_rows_where(lambda q: q["status"] == "cancelled")
        self._reap_stranded_groups()
        self._emit_queue()

    @Slot()
    def clearQueued(self) -> None:
        """Clear the Queued section: work that has not started yet.

        A queued row is a spec waiting for its turn, so dropping the spec
        with the row is what keeps the download from going ahead invisibly
        with no row left to show or stop it (the same reasoning as
        clearQueue). The one job in flight is not queued and is left alone."""
        withdrawn: list[str] = []
        gone = self._remove_rows_where(lambda q: q["status"] == "queued", withdrawn)
        for qid in gone:
            self._jobs.specs.pop(qid, None)
        self._abort_if_in_flight(gone)
        # A clear has to reach the stash too, or an item held for the download
        # folder to come back re-downloads itself when the share answers, over
        # a queue the user has just emptied. The abort above covers the job
        # whose hold is taken AFTER this press; this covers one already held.
        self._release_abandoned_hold(self._discard_pending_downloads(withdrawn))
        # Withdrawn before starting: no worker will ever credit these rows to
        # their rollups, so settle the rollups here.
        for mid in withdrawn:
            self._bump_download_groups(mid, None, "failed")
        self._reap_stranded_groups()
        self._emit_queue()

    @Slot()
    def retryAllFailed(self) -> None:
        """Retry every failed row in one click (the Failed section's header).

        Snapshot the qids first: retryQueueItem mutates the queue (drops the
        row, re-enqueues the download) while this loop walks it."""
        self._retry_all_with_status("failed")

    @Slot()
    def retryAllStopped(self) -> None:
        """Retry every row STOP ended in one click (the Stopped section's
        header). Rows are re-queued in their original order, so
        a stopped discography resumes as it was laid out."""
        self._retry_all_with_status("cancelled")

    @Slot()
    def clearQueue(self) -> None:
        """Clear every row that is not actively downloading (the footer's CLEAR ALL).

        Rows still writing bytes are spared and keep going: killing a transfer
        mid-write is per-row CANCEL's job, not a bulk button's. A queued row
        goes with its spec, so nothing downloads invisibly behind the clear."""
        withdrawn: list[str] = []
        gone = self._remove_rows_where(lambda q: q["status"] != "running", withdrawn)
        for qid in gone:
            self._jobs.specs.pop(qid, None)
        self._abort_if_in_flight(gone)
        # The stash goes with the rows, for the same reason as the Queued
        # section's clear: nothing downloads invisibly behind a clear, and a
        # held download is exactly that if it is left behind.
        self._release_abandoned_hold(self._discard_pending_downloads(withdrawn))
        # Only the rows that never started need crediting here: done, failed
        # and stopped rows were already settled by their workers.
        for mid in withdrawn:
            self._bump_download_groups(mid, None, "failed")
        self._reap_stranded_groups()
        self._emit_queue()

    @Slot(int)
    def removeQueueItem(self, qid: int) -> None:
        self._jobs.specs.pop(qid, None)
        withdrawn: list[str] = []
        if self._remove_row(qid, withdrawn):
            self._abort_if_in_flight((qid,))
        self._release_abandoned_hold(self._discard_pending_downloads(withdrawn))
        # Same rollup settlement as cancelQueueItem: a row removed before it
        # ever started has no worker left to credit it, and the
        # same reason for reading the status from the removal rather than from
        # a separate look at the row.
        for mid in withdrawn:
            self._bump_download_groups(mid, None, "failed")
        self._reap_stranded_groups()
        self._emit_queue()

    def _retry_queue_refetch(self, item: dict) -> None:
        """The engine's by-id re-fetch of a retried row's vanished object.

        The row stays in the queue, still failed, until the object is back and
        the retry re-enters ``retryQueueItem`` (via the GUI hop), so a failed
        re-fetch leaves RETRY available instead of consuming the row."""
        bucket, media_id, qid = item["type"], item["media_id"], item["qid"]
        key = (bucket, media_id)
        if key in self._refetch_inflight or not self._logged_in:
            return
        self._refetch_inflight.add(key)
        gen = self._browse_gen
        self._set_status("Fetching item…")

        def work() -> None:
            obj = None
            try:
                obj = self.providers[CTX_TIDAL].get_object(bucket, media_id)
            except Exception:
                logger.exception("Could not re-fetch %s %s for retry", bucket, media_id)
            if gen != self._browse_gen:
                self._refetch_inflight.discard(key)
                return
            if obj is None:
                self._refetch_inflight.discard(key)
                self._set_status("That item is no longer available")
                return
            self._remember(bucket, media_id, obj)
            self._queueRetryRefetched.emit(bucket, media_id, qid)

        self.threadpool.start(Worker(work))

    def _on_queue_retry_refetched(self, bucket: str, media_id: str, qid: int) -> None:
        # GUI-thread dispatch, same anti-double-click gap rule as
        # _on_media_refetched: the in-flight marker lives until here.
        self._refetch_inflight.discard((bucket, media_id))
        self.retryQueueItem(qid)

    @Slot(str, str)
    def copyShareUrl(self, bucket: str, media_id: str) -> None:
        obj = self._objs.get(bucket, {}).get(media_id)
        if obj is None:
            return
        url = getattr(obj, "share_url", "") or ""
        get_url = getattr(obj, "get_url", None)
        if not url and callable(get_url):
            try:
                url = get_url() or ""
            except Exception:
                url = ""
        if url:
            QtGui.QGuiApplication.clipboard().setText(url)
            self._set_status("Link copied")

    def _get_paused(self) -> bool:
        return self._paused

    def _get_scanning(self) -> bool:
        return self._scans_in_flight > 0

    @Slot()
    def pauseQueue(self) -> None:
        self._event_run.clear()
        self._paused = True
        self.pausedChanged.emit()
        self._set_status("Downloads paused")

    @Slot()
    def resumeQueue(self) -> None:
        self._event_run.set()
        self._paused = False
        self.pausedChanged.emit()
        self._set_status("Downloads resumed")
        # A queue paused between jobs started nothing while it waited.
        self._pump_queue()
