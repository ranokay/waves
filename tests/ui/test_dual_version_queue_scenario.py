"""The dual-version queue stays honest per version.

A dual download is two rows for one track (stereo and Atmos). One version
failing must not mark the pair done or strand the other: the failed row keeps
its retry control and its reason, the finished row keeps its settled face, and
a retry re-queues only the failed version. Cancelling another queued row
through its own X leaves the finished sibling alone, and after a restart the
badge answers per version: the finished stereo copy is owned while the
never-landed Atmos copy is not.

Proved on the real Main.qml offscreen for the queue's visible controls, with
the re-download stubbed at the engine boundary; ownership is read back through
a real OwnershipStore and the bridge's own badge slot.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

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

_ROW_STATE = (
    _ROW_JS
    + """
    var row = rowFor(__QID__);
    if (!row) return "";
    var retry = findFirst(row, function (o) { return o.objectName === "queueRetryMark"; });
    var cancel = findFirst(row, function (o) { return o.name === "close" && o.visible; });
    return JSON.stringify({
        qid: row.model.qid,
        tier: "" + row.model.quality,
        status: "" + row.model.status,
        reason: "" + row.model.reason,
        retryVisible: !!(retry && retry.visible),
        retryPoint: retry && retry.visible
            ? [retry.mapToItem(null, retry.width / 2, retry.height / 2).x,
               retry.mapToItem(null, retry.width / 2, retry.height / 2).y]
            : null,
        cancelPoint: cancel ? [cancel.mapToItem(null, cancel.width / 2, cancel.height / 2).x,
                              cancel.mapToItem(null, cancel.width / 2, cancel.height / 2).y] : null
    });
"""
)


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
    root, q, settle, bridge = booted

    def tap(point) -> None:
        """One real click at a scene point (plain MouseAreas, not gates)."""
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest

        root.requestActivate()
        settle(80)
        pos = QPoint(int(point[0]), int(point[1]))
        QTest.mouseMove(root, pos)
        settle(60)
        QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, pos)
        settle(150)

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
    if not atmos_state.get("retryVisible"):
        failures.append(f"the failed version keeps no retry control: {atmos_state}")
    if stereo_state.get("retryVisible"):
        failures.append(f"the finished version still offers a retry: {stereo_state}")

    # RETRY through the failed row's own control. The re-download is stubbed at
    # the engine boundary; all queue bookkeeping is real.
    started: list[int] = []
    bridge._row_object = lambda item: object()
    bridge._start_retry = lambda item, obj: started.append(int(item["qid"])) or True
    if not atmos_state.get("retryPoint"):
        failures.append("the retry control has no scene position")
    else:
        tap(atmos_state["retryPoint"])
    if started != [atmos]:
        failures.append(f"the retry started {started}, wanted only the failed version {[atmos]}")
    if q(_row_state(atmos)):
        failures.append("the retried version stayed in the queue")
    if json.loads(str(q(_row_state(stereo)) or "{}")).get("status") != "done":
        failures.append("retrying the Atmos version moved the finished stereo row")

    # The X on another queued row cancels just that row. Cancel removes the
    # row by design, so this is the visible control's own slot, no stub.
    third = bridge._enqueue("Dual Track Copy", "track", media_id="tidal:1", artist="Lab", audio_type="stereo")
    bridge._set_queue_status(third, "queued")
    settle(300)
    third_state = json.loads(str(q(_row_state(third)) or "{}"))
    if not third_state.get("cancelPoint"):
        failures.append(f"the queued row has no cancel control: {third_state}")
    else:
        tap(third_state["cancelPoint"])
    if q(_row_state(third)):
        failures.append("the cancel X did not remove its queued row")
    if json.loads(str(q(_row_state(stereo)) or "{}")).get("status") != "done":
        failures.append("cancelling another row moved the finished stereo row")

    # After a restart the per-version answers stand, through the bridge's own
    # badge slot and a fresh store over the same database.
    from waves.ownership import OwnershipStore

    workdir = Path(tempfile.mkdtemp())
    try:
        copy = workdir / "dual stereo.flac"
        copy.write_bytes(b"\x00" * 16)
        bridge._ownership.record("tidal:1", str(copy), "LOSSLESS", audio_type="stereo")
        bridge._ownership.set_roots(lambda: [str(workdir)])
        bridge._own_refresh("tidal:1")
        badge = bridge.ownershipOf("tidal:1")
        if not badge.get("owned"):
            failures.append("the finished stereo copy does not badge as owned")
        again = OwnershipStore(bridge._ownership._path)
        if again.ownership_of("tidal:1", audio_type="stereo") is None:
            failures.append("the finished stereo copy is not owned after a restart")
        if again.ownership_of("tidal:1", audio_type="atmos") is not None:
            failures.append("the never-landed Atmos copy reads owned after a restart")
        again.close()
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    if failures:
        for line in failures:
            print(line, file=sys.stderr)
        return EXIT_REGRESSED
    print("ok")
    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    sys.exit(_run_scenario())
