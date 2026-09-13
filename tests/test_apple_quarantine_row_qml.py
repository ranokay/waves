"""The failed Apple row's quarantine actions work, and a stop can explain itself.

The bridge can record quarantined copies and offer slots all it likes; the
drawer is where the user meets them. This boots the real Main.qml offscreen,
seeds a failed Apple row holding a quarantined copy plus a row stopped by a
provider disable, then drives the drawer with real clicks: the actions must
render, DELETE must remove the bytes from disk, and the stopped row must say
why it stopped instead of a bare "Stopped".

Runs in a SUBPROCESS like the other Main.qml scenarios (shares the sibling's
``_boot``).
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from test_progress_matrix_stable_width import _EXIT_NO_QT, _EXIT_OK, _EXIT_PRECONDITION, _boot

_INTEGRITY_REASON = "failed integrity check \u2014 quarantined"
_DISABLED_REASON = "Apple Music was disabled"


def _button_point(label: str) -> str:
    return (
        "(function(){"
        " function walk(it){"
        "  if (!it) return null;"
        f"  if (it.label !== undefined && String(it.label) === '{label}') return it;"
        "  var kids = it.children || [];"
        "  for (var i = 0; i < kids.length; i++){"
        "   var hit = walk(kids[i].item || kids[i]);"
        "   if (hit) return hit;"
        "  }"
        "  return null;"
        " }"
        " var hit = walk(queueDrawer.contentItem);"
        " return hit ? hit.mapToItem(null, hit.width/2, hit.height/2) : null;"
        "})()"
    )


def _rendered_text(q, needle: str):
    return q(
        "(function(){"
        " function walk(it){"
        "  if (!it) return null;"
        "  if (it.text !== undefined && String(it.text).indexOf("
        f"'{needle}') >= 0) return it;"
        "  var kids = it.children || [];"
        "  for (var i = 0; i < kids.length; i++){"
        "   var hit = walk(kids[i].item || kids[i]);"
        "   if (hit) return hit;"
        "  }"
        "  return null;"
        " }"
        " return walk(queueDrawer.contentItem);"
        "})()"
    )


def _quarantine_count(q, qid: int) -> str:
    expr = (
        "(function(){ var i = queueRowIndexOf(" + str(qid) + "); "
        "return i < 0 ? '<no row>' : '' + queueModel.get(i).quarantineCount; })()"
    )
    return str(q(expr))


def _scenario() -> int:
    booted = _boot()
    if not isinstance(booted, tuple):
        return booted
    root, q, settle, bridge = booted
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    problems: list[str] = []

    qid = bridge._enqueue("Quarantined Album", "album", media_id="apple:album:q1", collection=True, tracks=2)
    settle(80)
    folder = Path(tempfile.mkdtemp(prefix="waves-quarantine-row-"))
    copy = folder / "Artist" / "Album" / "01 Track.m4a"
    copy.parent.mkdir(parents=True)
    copy.write_bytes(b"bad")
    bridge._apple_quarantine_paths[qid] = [str(copy)]
    bridge._queue_item(qid)["quarantineCount"] = 1
    bridge._set_queue_status(qid, "failed", _INTEGRITY_REASON)
    stopped = bridge._enqueue("Apple Off Album", "album", media_id="apple:album:q2", collection=True, tracks=1)
    bridge._queue_item(stopped)["status"] = "cancelled"
    bridge._queue_item(stopped)["reason"] = _DISABLED_REASON
    bridge._queue_resync()
    settle(150)

    q("queueDrawer.open()")
    settle(300)

    if _quarantine_count(q, qid) != "1":
        problems.append(f"the row lost its quarantine count: {_quarantine_count(q, qid)!r}")
    if _rendered_text(q, _INTEGRITY_REASON) is None:
        problems.append("the failed row does not show its integrity verdict")
    if _rendered_text(q, _DISABLED_REASON) is None:
        problems.append("the stopped row does not say the provider was disabled")

    if q(_button_point("OPEN QUARANTINE")) is None:
        problems.append("the failed row exposes no OPEN QUARANTINE action")

    point = q(_button_point("DELETE COPY"))
    if point is None:
        problems.append("the failed row exposes no DELETE COPY action")
    else:
        root.requestActivate()
        settle(80)
        QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, QPoint(int(point.x()), int(point.y())))
        settle(300)
        if copy.exists():
            problems.append("DELETE COPY did not remove the quarantined bytes")
        if _quarantine_count(q, qid) != "0":
            problems.append(f"the row kept its quarantine count: {_quarantine_count(q, qid)!r}")

    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    print("QUARANTINE ROW: OK")
    return _EXIT_OK


def test_a_failed_apple_row_can_reveal_and_delete_its_quarantined_copy():
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    # Sandboxed: this scenario builds a REAL WavesBridge, and a bridge that
    # finds the packaged app's config dir adopts its settings, writes its log,
    # and starts a real scan of the user's music library.
    env["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="waves-quarantine-row-test-")
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--run-scenario"],
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    lines = [ln for ln in (proc.stdout + proc.stderr).strip().splitlines() if "waves.qt" not in ln]
    tail = "\n".join(lines[-12:])
    if proc.returncode == _EXIT_NO_QT:
        pytest.skip("PySide6 / offscreen Qt unavailable")
    if proc.returncode == _EXIT_PRECONDITION:
        pytest.skip(f"could not set up the scenario in this environment:\n{tail}")
    assert proc.returncode == _EXIT_OK, f"the quarantine row actions regressed:\n{tail}"


if __name__ == "__main__":
    if "--run-scenario" in sys.argv:
        raise SystemExit(_scenario())
    raise SystemExit(_EXIT_PRECONDITION)
