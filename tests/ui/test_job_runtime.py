"""JobRuntime without a bridge: the GUI-thread contract and the registries.

The affinity rule is the whole point of the runtime (ARCH-03): the progress
relay must be constructed on the GUI thread, and this is where that rule is
pinned — a relay built elsewhere re-opens the freeze class of bugs with no
other test able to see it. The main thread is the GUI thread, so construction
here succeeds and construction from a worker thread refuses.
"""

from __future__ import annotations

import threading

import pytest

from waves.desktop.job_runtime import JobRuntime


def test_constructs_on_the_gui_thread_with_empty_registries():
    jobs = JobRuntime()
    assert jobs.specs == {} and jobs.objs == {}
    assert jobs.aborts == {} and jobs.signals == {}
    assert jobs.tracks == {} and jobs.dls == {}


def test_construction_off_the_gui_thread_refuses():
    with pytest.raises(RuntimeError, match="GUI thread"):
        _construct_off_thread(JobRuntime)


def _construct_off_thread(factory):
    outcome = {}

    def build():
        try:
            outcome["jobs"] = factory()
        except RuntimeError as exc:
            outcome["error"] = exc

    worker = threading.Thread(target=build)
    worker.start()
    worker.join()
    if "error" in outcome:
        raise outcome["error"]
    return outcome["jobs"]


def test_relay_construction_files_the_relay_and_returns_it():
    jobs = JobRuntime()
    made = []
    relay = jobs.construct_signals(
        lambda parent, qid, media_id, collection: made.append((qid, media_id)) or "relay", 7, "m7", False
    )
    assert relay == "relay"
    assert jobs.signals[7] == "relay"


def test_relay_construction_off_the_gui_thread_refuses():
    jobs = JobRuntime()
    with pytest.raises(RuntimeError, match="GUI thread"):
        _construct_off_thread(lambda: jobs.construct_signals(lambda *a: None, 7, "m7", False))
    assert jobs.signals == {}
