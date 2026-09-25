"""The one-job runtime: per-qid download records with a GUI-thread contract.

``_start_job`` is the only place with QObject affinity rules: it constructs
the per-job ``_ProgressSignals`` relay, which must live on the GUI thread
(the app's main thread). Before this module that rule was convention; a move
that constructed the relay elsewhere would re-open the freeze class of bugs
with no test able to see it.

This class owns the six per-qid lifecycle registries (specs, live objects,
abort events, signal relays, track registries, live downloads) and refuses
to be constructed — or to construct a relay — off the GUI thread. Derived
caches (``_job_fetched``/``_job_owned``/``_job_quality``/``_job_library``/
``_job_audio``) and scheduling state (``_pending_qids``/``_running_qid``/
``_pct_last``) stay on the bridge with reason: caches are read-mostly maps,
scheduling belongs to the queue pump. This module must never import backend:
the relay class arrives as a factory argument, resolved from backend's
globals at the call site so patches on ``backend._ProgressSignals`` still
reach construction.
"""

from __future__ import annotations

from collections.abc import Callable
from threading import current_thread, main_thread


def _require_gui_thread(what: str) -> None:
    if current_thread() is not main_thread():
        raise RuntimeError(f"{what} must run on the GUI thread")  # noqa: TRY003 (affinity contract wording is the assertion)


class JobRuntime:
    """Per-qid download records. Construct on the GUI thread; use anywhere."""

    def __init__(self, parent=None) -> None:
        _require_gui_thread("JobRuntime construction")
        self._parent = parent
        self.specs: dict = {}
        self.objs: dict = {}
        self.aborts: dict = {}
        self.signals: dict = {}
        self.tracks: dict = {}
        self.dls: dict = {}

    def construct_signals(self, factory: Callable[..., object], qid: int, media_id: str, collection) -> object:
        """Build one job's progress relay via ``factory`` and file it by qid."""
        _require_gui_thread("progress-relay construction")
        signals = factory(self._parent, qid, media_id, collection)
        self.signals[qid] = signals
        return signals
