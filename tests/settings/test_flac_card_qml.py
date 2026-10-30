"""The FLAC signatures card (Settings, Advanced) driven offscreen.

The real bridge and the real QML, over a temp folder of real FLACs. What is
pinned: the deep link lands on the card inside Advanced; Scan turns files into
counts; FIX opens the confirmation with the count and writes nothing before
confirm; confirming writes only the unsigned file and saves a CSV report;
an unfinished fix leaves RESUME, which finishes it; VIEW REPORTS shows when a
report exists; Recheck all cannot flip mid-run; and a stale selection offers
no FIX.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest
from support.audio_fixtures import ffmpeg_path
from support.qml import (
    EXIT_OK,
    EXIT_REGRESSED,
    boot_main_qml,
    checkpoint,
    run_scenario,
    wait_until_true,
)
from support.qml_probe import scene_js

pytestmark = pytest.mark.qml

_FFMPEG = shutil.which("ffmpeg")


def test_the_flac_card_drives_scan_fix_and_resume():
    run_scenario(
        Path(__file__),
        "--run-scenario",
        timeout=240,
        sandbox_prefix="waves-flac-card-",
        failure_message="the FLAC signatures card lost its scan/fix/resume behaviour.",
    )


def _run(*args: str) -> bytes:
    return subprocess.run([ffmpeg_path(), "-v", "error", *args], capture_output=True, check=True).stdout  # noqa: S603


def _flac(path: Path, *, unset: bool) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    _run(
        "-y",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=0.3",
        "-ac",
        "2",
        "-ar",
        "44100",
        "-sample_fmt",
        "s16",
        "-c:a",
        "flac",
        str(path),
    )
    from waves import flac_verify as fv

    if unset:
        si = fv.read_streaminfo(path)
        fv.write_streaminfo(path, si, fv.sealed_bytes(si, bytes(16), 0))
    # An existing library file, not one still arriving: the fix's settle
    # window leaves a file written moments ago alone.
    old = time.time() - 3600
    os.utime(path, (old, old))
    return path.read_bytes()


def _run_scenario() -> int:  # noqa: C901 (one straight scenario, six checks)
    if _FFMPEG is None:
        print("ffmpeg unavailable", file=sys.stderr)
        return EXIT_OK
    booted = boot_main_qml()
    if isinstance(booted, int):
        return booted
    _root, q, settle, bridge = booted

    from waves import flac_verify as fv

    music = Path(tempfile.mkdtemp(prefix="waves-flac-card-music-"))
    signed = music / "signed.flac"
    unsigned = music / "unsigned.flac"
    signed_before = _flac(signed, unset=False)
    unsigned_before = _flac(unsigned, unset=True)
    bridge.settings.data.download_base_path = str(music)
    bridge._flac_check._prefs["flac_check_source"] = "waves"
    bridge._flac_check._prefs["flac_check_folder"] = ""

    def visible(name: str) -> bool:
        return bool(q(scene_js(f'var o = findObject(settingsPage, "{name}"); return !!(o && o.visible);')))

    def text(name: str) -> str:
        return str(q(scene_js(f'var o = findObject(settingsPage, "{name}"); return o ? String(o.text) : "";')))

    def click(name: str, scope: str = "settingsPage") -> bool:
        return bool(q(scene_js(f'var o = findObject({scope}, "{name}"); if (o) o.clicked(); return !!o;')))

    def trigger(name: str) -> bool:
        return bool(q(scene_js(f'var o = findObject(settingsPage, "{name}"); if (o) o.triggered(); return !!o;')))

    def state() -> dict:
        return dict(q("waves.flacCheckState()"))

    problems: list[str] = []
    checkpoint("open the card")
    q("settingsOpen = true")
    q("settingsPage.jumpToCard('flac')")
    settle(500)
    if q("settingsPage.flacCardItem === null"):
        problems.append("the FLAC card did not build inside Advanced")
    if not visible("flacCard"):
        problems.append("the FLAC card is not visible after jumpToCard('flac')")
    if text("flacNote") != "Not checked yet.":
        problems.append(f"a fresh card reads {text('flacNote')!r}, not 'Not checked yet.'")

    checkpoint("scan while Recheck all cannot flip")
    real_check = fv.check_file

    def slow_check(*args, **kwargs):
        time.sleep(0.2)
        return real_check(*args, **kwargs)

    fv.check_file = slow_check
    try:
        click("flacScanBtn")
        settle(80)
        if not state().get("running"):
            problems.append("SCAN did not start a run")
        if q(scene_js('var o = findObject(settingsPage, "flacRecheckToggle"); return !!(o && o.enabled);')):
            problems.append("Recheck all can be flipped while a scan is running")
        if not wait_until_true(q, "waves.flacCheckState().phase === 'done'", "scan finished", 30000):
            problems.append("the scan never finished")
    finally:
        fv.check_file = real_check

    st = state()
    if (st.get("files"), st.get("fixable")) != (2, 1):
        problems.append(f"scan state is files={st.get('files')} fixable={st.get('fixable')}")
    note = text("flacNote")
    problems.extend(
        f"the scan note {note!r} lacks {phrase!r}"
        for phrase in ("2 files", "1 without a signature")
        if phrase not in note
    )
    if not visible("flacReportsBtn"):
        problems.append("VIEW REPORTS is hidden after a report was written")
    if not visible("flacFixBtn"):
        problems.append("FIX is hidden after a scan found an unsigned file")
    if "FIX 1 FILE" not in str(
        q(scene_js('var o = findObject(settingsPage, "flacFixBtn"); return o ? String(o.label) : "";'))
    ):
        problems.append("FIX does not carry the file count")

    checkpoint("deep check and recheck all reach the run")
    trigger("flacDeepToggle")
    click("flacScanBtn")
    if not wait_until_true(q, "waves.flacCheckState().phase === 'done'", "deep scan finished", 30000):
        problems.append("the deep scan never finished")
    deep = state()
    if deep.get("mode") != "deep":
        problems.append(f"Deep check did not reach the run (mode={deep.get('mode')})")
    if deep.get("counts", {}).get("ok") != 1:
        problems.append(f"the deep scan did not verify the signed file: {deep.get('counts')}")
    trigger("flacDeepToggle")
    trigger("flacRecheckToggle")
    click("flacScanBtn")
    if not wait_until_true(q, "waves.flacCheckState().phase === 'done'", "recheck scan finished", 30000):
        problems.append("the recheck scan never finished")
    if state().get("cached") != 0:
        problems.append("Recheck all reused remembered verdicts")
    trigger("flacRecheckToggle")

    checkpoint("fix asks before writing")
    click("flacFixBtn")
    settle(100)
    if not bool(q("flacFixGate.visible")):
        problems.append("FIX did not open the confirmation gate")
    title = str(q(scene_js('var o = findObject(flacFixGate, "flacFixTitle"); return o ? String(o.text) : "";')))
    if "1 file" not in title:
        problems.append(f"the fix gate title {title!r} does not name the count")
    if unsigned.read_bytes() != unsigned_before:
        problems.append("the unsigned file changed before the confirmation")
    click("flacFixConfirm", "flacFixGate")
    if not wait_until_true(q, "waves.flacCheckState().phase === 'done'", "fix finished", 30000):
        problems.append("the fix never finished")
    if fv.read_streaminfo(unsigned).md5 == bytes(16):
        problems.append("the unsigned file still has no signature after FIX")
    if signed.read_bytes() != signed_before:
        problems.append("the signed file was rewritten by FIX")
    report = Path(state().get("report") or "")
    if not report.is_file():
        problems.append(f"the fix wrote no report ({report})")
    else:
        import csv

        with report.open(encoding="utf-8-sig", newline="") as f:
            rows = {r["file"]: r["status"] for r in csv.DictReader(f)}
        if rows.get(str(unsigned)) != fv.SEALED or rows.get(str(signed)) != fv.SET:
            problems.append(f"the fix report rows are {rows}")

    checkpoint("view reports")
    revealed: list[str] = []
    bridge._flac_check._reveal = revealed.append
    click("flacReportsBtn")
    settle(80)
    if not revealed or not Path(revealed[0]).exists():
        problems.append(f"VIEW REPORTS revealed nothing that exists: {revealed}")

    checkpoint("resume an unfinished fix")
    late = music / "late.flac"
    _flac(late, unset=True)
    click("flacScanBtn")
    if not wait_until_true(q, "waves.flacCheckState().phase === 'done'", "second scan finished", 30000):
        problems.append("the second scan never finished")
    real_seal = fv.seal_file

    def seal_then_cancel(*args, **kwargs):
        row = real_seal(*args, **kwargs)
        bridge.flacCheckCancel()
        return row

    fv.seal_file = seal_then_cancel
    try:
        click("flacFixBtn")
        settle(80)
        click("flacFixConfirm", "flacFixGate")
        if not wait_until_true(q, "waves.flacCheckState().phase === 'cancelled'", "fix cancelled", 30000):
            problems.append("the cut-short fix did not report cancelled")
    finally:
        fv.seal_file = real_seal
    if not visible("flacResumeBtn"):
        problems.append("RESUME is hidden after an unfinished fix")
    click("flacResumeBtn")
    settle(100)
    resume_title = str(q(scene_js('var o = findObject(flacFixGate, "flacFixTitle"); return o ? String(o.text) : "";')))
    if "Resume" not in resume_title:
        problems.append(f"the resume gate title is {resume_title!r}")
    click("flacFixConfirm", "flacFixGate")
    if not wait_until_true(q, "waves.flacCheckState().phase === 'done'", "resume finished", 30000):
        problems.append("RESUME never finished")
    if state().get("resume_source") != "":
        problems.append("RESUME did not clear the unfinished-fix marker")
    if fv.read_streaminfo(late).md5 == bytes(16):
        problems.append("RESUME did not sign the file the first fix missed")

    checkpoint("a stale selection offers no fix")
    stale = music / "stale.flac"
    _flac(stale, unset=True)
    click("flacScanBtn")
    if not wait_until_true(q, "waves.flacCheckState().phase === 'done'", "third scan finished", 30000):
        problems.append("the third scan never finished")
    other = Path(tempfile.mkdtemp(prefix="waves-flac-card-other-"))
    q(f"waves.flacCheckSetFolder({json.dumps(str(other))})")
    settle(150)
    if not visible("flacBrowseBtn"):
        problems.append("BROWSE is hidden after choosing a folder")
    if visible("flacFixBtn"):
        problems.append("FIX is still offered after the selection moved to another folder")
    if text("flacNote") != "Not checked yet.":
        problems.append(f"a stale card reads {text('flacNote')!r}, not 'Not checked yet.'")

    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        return EXIT_REGRESSED
    print(f"ok note={note!r} report={report.name}")
    return EXIT_OK


if __name__ == "__main__" and "--run-scenario" in sys.argv:
    sys.exit(_run_scenario())
