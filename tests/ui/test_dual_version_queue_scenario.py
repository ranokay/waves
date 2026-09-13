"""The dual-version queue stays honest per version.

A dual download is two rows for one track (stereo and Atmos). One version
failing must not mark the pair done or strand the other: the failed row keeps
its RETRY and its reason, the finished row keeps its settled face, and a retry
re-queues only the failed version. After a restart, ownership answers per
version: the finished stereo copy is owned while the never-landed Atmos copy
is not.

Proved on the real Main.qml offscreen for the queue's visible states, and
against a real OwnershipStore for the after-restart answers.
"""

from __future__ import annotations

import json
import sys
import tempfile

import pytest
from support.qml import EXIT_OK, EXIT_REGRESSED, boot_main_qml, run_scenario
from support.qml_probe import scene_js

_ROW_JS = """
    function rowFor(qid) {
        var n = queueList.count;
        for (var i = 0; i < n; i++) {
            var it = queueList.itemAtIndex(i);
            if (it && it.model && it.model.qid === qid) return it;
        }
        return null;
    }
"""

_ROW_STATE = _ROW_JS + """
    var row = rowFor(__QID__);
    if (!row) return "";
    var retry = false;
    function walk(o) {
        if (!o) return;
        if (o.objectName === "queueRetryMark" && o.visible) retry = true;
        var kids = o.children || [];
        for (var i = 0; i < kids.length; i++) walk(kids[i]);
    }
    walk(row);
    return JSON.stringify({
        qid: row.model.qid,
        tier: "" + row.model.quality,
        status: "" + row.model.status,
        reason: "" + row.model.reason,
        retryShown: retry
    });
"""


def _row_state(qid: int) -> str:
    return scene_js(_ROW_STATE.replace("__QID__", str(qid)))


@pytest.mark.qml
def test_dual_version_rows_fail_and_retry_apart():
    run_scenario(
        __file__,
        "--run-scenario",
        timeout=180,
        sandbox_prefix="waves-dual-version-queue-",
        failure_message="the two versions of the queue row stopped moving apart",
    )


def _run_scenario() -> int:
    booted = boot_main_qml()
    if isinstance(booted, int):
        return booted
    _root, q, settle, bridge = booted

    stereo = bridge._enqueue(
        "Dual Track",
        "track",
        media_id="tidal:1",
        artist="Lab",
        audio_type="stereo",
        ask_quality="HI_RES_LOSSLESS",
        ask_tier="LOSSLESS",
    )
    atmos = bridge._enqueue(
        "Dual Track",
        "track",
        media_id="tidal:1",
        artist="Lab",
        audio_type="atmos",
        ask_quality="HI_RES_LOSSLESS",
        ask_tier="ATMOS",
    )
    bridge._set_queue_status(stereo, "running")
    bridge._set_queue_status(atmos, "running")
    bridge._set_queue_progress(stereo, 40)
    # One version fails; the other finishes. Both through the real mutators.
    bridge._set_queue_status(atmos, "failed", "the Atmos stream was unavailable")
    bridge._set_queue_progress(stereo, 100)
    bridge._set_queue_status(stereo, "done")
    settle(200)

    q("queueDrawer.open()")
    settle(900)

    failures = []
    stereo_state = json.loads(str(q(_row_state(stereo)) or "{}"))
    atmos_state = json.loads(str(q(_row_state(atmos)) or "{}"))
    if (stereo_state.get("tier"), stereo_state.get("status")) != ("LOSSLESS", "done"):
        failures.append(f"the finished stereo row reads {stereo_state}")
    if (atmos_state.get("tier"), atmos_state.get("status")) != ("ATMOS", "failed"):
        failures.append(f"the failed Atmos row reads {atmos_state}")
    if atmos_state.get("reason") != "the Atmos stream was unavailable":
        failures.append(f"the failed version lost why: {atmos_state}")
    if not atmos_state.get("retryShown"):
        failures.append(f"the failed version keeps no retry control: {atmos_state}")
    if stereo_state.get("retryShown"):
        failures.append(f"the finished version still offers a retry: {stereo_state}")

    # RETRY moves only the failed version: the re-download is stubbed at the
    # engine boundary, all queue bookkeeping is real.
    started: list[int] = []
    bridge._row_object = lambda item: object()
    bridge._start_retry = lambda item, obj: started.append(int(item["qid"])) or True
    bridge.retryQueueItem(atmos)
    settle(300)
    if started != [atmos]:
        failures.append(f"the retry started {started}, wanted only the failed version {[atmos]}")
    if q(_row_state(atmos)):
        failures.append("the retried version stayed in the queue")
    if json.loads(str(q(_row_state(stereo)) or "{}")).get("status") != "done":
        failures.append("retrying the Atmos version moved the finished stereo row")

    # After a restart the per-version ownership answers stand: the finished
    # stereo copy is owned, the Atmos fetch that never landed is not.
    from pathlib import Path

    from waves.ownership import OwnershipStore

    copy = Path(tempfile.mkdtemp()) / "dual stereo.flac"
    copy.write_bytes(b"\x00" * 16)
    bridge._ownership.record("tidal:1", str(copy), "LOSSLESS", audio_type="stereo")
    again = OwnershipStore(bridge._ownership._path)
    if again.ownership_of("tidal:1", audio_type="stereo") is None:
        failures.append("the finished stereo copy is not owned after a restart")
    if again.ownership_of("tidal:1", audio_type="atmos") is not None:
        failures.append("the never-landed Atmos copy reads owned after a restart")
    again.close()

    if failures:
        for line in failures:
            print(line, file=sys.stderr)
        return EXIT_REGRESSED
    print("ok")
    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    sys.exit(_run_scenario())
