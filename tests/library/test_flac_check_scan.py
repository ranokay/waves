"""The library-side FLAC check: the folder walk, a scan, the fix loop and the
CSV reports.

Qt-free, the way the library index tests are: plain temp folders and real
files, with the decoder tests carrying the ``ffmpeg`` marker. What is pinned:
the walk covers exactly the chosen roots (dot files skipped, links kept only
inside a root, unreadable folders named), a scan never writes, a fix touches
only the UNSET rows, and every report names every file plus the folders the
walk could not read.
"""

from __future__ import annotations

import csv
import hashlib
import os
import pathlib
import subprocess

import pytest
from support.audio_fixtures import ffmpeg_path

from waves import flac_verify as fv
from waves.library import flac_check as fc


def _packed(rate: int, channels: int, bps: int, total: int) -> bytes:
    return ((rate << 44) | ((channels - 1) << 41) | ((bps - 1) << 36) | total).to_bytes(8, "big")


def _fake_flac(path: pathlib.Path, md5: bytes = bytes(16)) -> bytes:
    info = b"\x10\x00\x10\x00" + b"\x00\x00\x64" + b"\x00\x23\x28" + _packed(44100, 2, 16, 0) + md5
    data = b"fLaC" + bytes([0x80]) + (34).to_bytes(3, "big") + info + b"\xff\xf8" + b"\x11" * 100
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def _run(*args: str) -> bytes:
    # argv is ffmpeg from PATH plus literal test arguments.
    return subprocess.run([ffmpeg_path(), "-v", "error", *args], capture_output=True, check=True).stdout  # noqa: S603


def _real_flac(path: pathlib.Path, *, unset: bool) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    sine = "sine=frequency=440:duration=0.3"
    _run("-y", "-f", "lavfi", "-i", sine, "-ac", "2", "-ar", "44100", "-sample_fmt", "s16", "-c:a", "flac", str(path))
    if unset:
        si = fv.read_streaminfo(path)
        fv.write_streaminfo(path, si, fv.sealed_bytes(si, bytes(16), 0))
    pcm = _run("-i", str(path), "-f", "s16le", "-")
    return hashlib.md5(pcm).digest()  # noqa: S324


def _report_rows(path: str) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


# ---- the walk -------------------------------------------------------------------


def test_effective_roots_drops_blanks_duplicates_and_nested_folders(tmp_path):
    lib = str(tmp_path / "Music")
    dl = str(tmp_path / "Music" / "Downloads")
    other = str(tmp_path / "Other")
    assert fc.effective_roots([dl, lib]) == [lib]
    assert fc.effective_roots([lib, dl]) == [lib]
    assert fc.effective_roots(["", " ", lib, lib, other]) == [lib, other]
    assert fc.effective_roots([]) == []
    # A folder name may end in a space; the walk must use the exact spelling.
    spaced = str(tmp_path / "Albums ")
    assert fc.effective_roots([spaced]) == [spaced]


def test_iter_flac_files_scope(tmp_path):
    root = tmp_path / "root"
    (root / "Artist" / "Album").mkdir(parents=True)
    (root / ".hidden").mkdir()
    (root / "Artist" / "Album" / "01 Song.FLAC").write_bytes(b"x")
    (root / "Artist" / "Album" / "02 Song.flac").write_bytes(b"x")
    (root / "Artist" / "Album" / "._02 Song.flac").write_bytes(b"x")  # AppleDouble sidecar
    (root / "Artist" / "Album" / "cover.jpg").write_bytes(b"x")
    (root / "Artist" / "Album" / "03 Song.m4a").write_bytes(b"x")
    (root / ".hidden" / "04 Song.flac").write_bytes(b"x")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "05 Song.flac").write_bytes(b"x")
    # A folder link out of the root is not followed; a file link out of the
    # root is skipped; a file link that stays inside the root is kept, but
    # only when the walk finds no other name for its file (counted once).
    os.symlink(outside, root / "Linked folder")
    os.symlink(outside / "05 Song.flac", root / "Artist" / "06 Linked out.flac")
    os.symlink(root / "Artist" / "Album" / "02 Song.flac", root / "Artist" / "07 Linked in.flac")
    os.symlink(root / "Artist" / "07 Linked in.flac", root / "Artist" / "08 Link to a link.flac")
    os.symlink(root / ".hidden" / "04 Song.flac", root / "Artist" / "09 Linked hidden.flac")
    os.symlink(root / ".hidden" / "04 Song.flac", root / "Artist" / "10 Linked hidden again.flac")
    unreadable: list[str] = []

    found = [os.path.relpath(p, root) for p in fc.iter_flac_files([str(root), str(root / "Artist")], None, unreadable)]

    assert found == [
        os.path.join("Artist", "Album", "01 Song.FLAC"),
        os.path.join("Artist", "Album", "02 Song.flac"),
        os.path.join("Artist", "09 Linked hidden.flac"),
    ]
    assert unreadable == []


def test_iter_flac_files_reports_every_folder_it_could_not_read(tmp_path):
    """A missing root, a root that is a file, and a subfolder the system will
    not list are named, never taken for empty; what could be read is still
    walked."""
    root = tmp_path / "root"
    (root / "Open").mkdir(parents=True)
    (root / "Open" / "a.flac").write_bytes(b"x")
    locked = root / "Locked"
    locked.mkdir()
    (locked / "b.flac").write_bytes(b"x")
    not_a_folder = tmp_path / "file.flac"
    not_a_folder.write_bytes(b"x")
    missing = tmp_path / "Not mounted"
    os.chmod(locked, 0)
    try:
        if os.access(locked, os.R_OK):
            pytest.skip("permissions are not enforced for this user")
        unreadable: list[str] = []
        found = list(fc.iter_flac_files([str(missing), str(root), str(not_a_folder)], None, unreadable))
    finally:
        os.chmod(locked, 0o700)

    assert found == [str(root / "Open" / "a.flac")]
    assert sorted(unreadable) == sorted([str(missing), str(locked), str(not_a_folder)])
    # Without a list to fill the walk is the same, and still never raises.
    assert list(fc.iter_flac_files([str(missing)])) == []


def test_iter_flac_files_lists_ahead_in_the_one_at_a_time_order(tmp_path, monkeypatch):
    """Folders listed several at a time still come out in the order a
    one-at-a-time walk gives, with the same unreadable folders in order."""
    root = tmp_path / "lib"
    for a in "abcde":
        for b in "xyz":
            for n in (1, 2):
                fake = root / a / b / f"{n}.flac"
                fake.parent.mkdir(parents=True, exist_ok=True)
                fake.write_bytes(b"x")
    (root / "c" / "locked").mkdir()
    real_list = fc._list_folder

    def list_folder(folder, real_roots, unreadable):
        if folder.endswith("locked") or folder.endswith(os.path.join("a", "y")):
            unreadable.append(folder)
            return [], [], []
        return real_list(folder, real_roots, unreadable)

    monkeypatch.setattr(fc, "_list_folder", list_folder)
    walked: list[str] = []
    found = list(fc.iter_flac_files([str(root)], None, walked))
    monkeypatch.setattr(fc, "_WALK_THREADS", 1)
    monkeypatch.setattr(fc, "_WALK_AHEAD", 1)
    one: list[str] = []
    assert list(fc.iter_flac_files([str(root)], None, one)) == found
    assert walked == one == [str(root / "a" / "y"), str(root / "c" / "locked")]
    assert [os.path.relpath(p, root) for p in found[:4]] == [
        os.path.join("a", "x", "1.flac"),
        os.path.join("a", "x", "2.flac"),
        os.path.join("a", "z", "1.flac"),
        os.path.join("a", "z", "2.flac"),
    ]


def test_iter_flac_files_stops_when_asked(tmp_path):
    for i in range(5):
        d = tmp_path / f"d{i}"
        d.mkdir()
        (d / "a.flac").write_bytes(b"x")
    calls = iter([True, True, False, False, False, False])
    found = list(fc.iter_flac_files([str(tmp_path)], should_continue=lambda: next(calls)))
    assert len(found) < 5


# ---- a scan ---------------------------------------------------------------------


def test_a_scan_reads_only_and_reports_every_file(tmp_path):
    root = tmp_path / "Music"
    files = {
        root / "A" / "unset.flac": _fake_flac(root / "A" / "unset.flac"),
        root / "A" / "set.flac": _fake_flac(root / "A" / "set.flac", b"\x01" * 16),
        root / "B" / "junk.flac": b"not flac",
    }
    (root / "B").mkdir(parents=True)
    (root / "B" / "junk.flac").write_bytes(b"not flac")
    stamps = {p: os.stat(p).st_mtime_ns for p in files}

    rows = fc.scan([str(root)])

    assert fc.summarize(rows) == {"files": 3, fv.UNSET: 1, fv.SET: 1, fv.UNREADABLE: 1}
    for p, data in files.items():
        assert p.read_bytes() == data
        assert os.stat(p).st_mtime_ns == stamps[p], "a scan never writes"

    report = fc.write_new_report(tmp_path / "reports", "scan", rows)
    assert {r["file"]: r["status"] for r in _report_rows(report)} == {
        str(root / "A" / "set.flac"): fv.SET,
        str(root / "A" / "unset.flac"): fv.UNSET,
        str(root / "B" / "junk.flac"): fv.UNREADABLE,
    }


@pytest.mark.ffmpeg
def test_a_deep_scan_reports_every_status_and_writes_nothing(tmp_path):
    ok = tmp_path / "ok.flac"
    md5 = _real_flac(ok, unset=False)
    bad = tmp_path / "bad.flac"
    _real_flac(bad, unset=False)
    si = fv.read_streaminfo(bad)
    fv.write_streaminfo(bad, si, si.raw[:18] + bytes(b ^ 0xFF for b in md5))
    unset = tmp_path / "unset.flac"
    _real_flac(unset, unset=True)
    before = {p: p.read_bytes() for p in (ok, bad, unset)}

    rows = fc.scan([str(tmp_path)], ffmpeg_path(), deep=True)

    assert {os.path.basename(v.path): v.status for v in rows} == {
        "ok.flac": fv.OK,
        "bad.flac": fv.MISMATCH,
        "unset.flac": fv.UNSET,
    }
    for p, data in before.items():
        assert p.read_bytes() == data
    assert fc.summarize(rows) == {"files": 3, fv.OK: 1, fv.MISMATCH: 1, fv.UNSET: 1}


# ---- the fix loop ----------------------------------------------------------------


@pytest.mark.ffmpeg
def test_fix_rows_only_touches_unset_rows(tmp_path):
    unset = tmp_path / "u.flac"
    _real_flac(unset, unset=True)
    kept = tmp_path / "k.flac"
    _real_flac(kept, unset=False)
    busy = tmp_path / "b.flac"
    _real_flac(busy, unset=True)
    changed = tmp_path / "c.flac"
    _real_flac(changed, unset=True)
    junk = tmp_path / "j.flac"
    junk.write_bytes(b"nope")
    rows = fc.scan([str(tmp_path)])
    assert {v.status for v in rows} == {fv.UNSET, fv.SET, fv.UNREADABLE}
    # Old enough to be trusted complete, except the one written just now.
    old = 1_600_000_000
    for p in (unset, kept, changed):
        os.utime(p, (old, old))
    rows = fc.scan([str(tmp_path)])
    before = {p: p.read_bytes() for p in (unset, kept, busy, changed, junk)}
    # Rewritten after the scan: a different mtime, same shape.
    os.utime(changed, (old + 5, old + 5))
    seen: list[fc.Verdict] = []

    out = fc.fix_rows(rows, ffmpeg_path(), on_row=seen.append, settle_seconds=60.0)

    by_name = {os.path.basename(v.path): v for v in out}
    assert by_name["u.flac"].status == fv.SEALED
    assert by_name["k.flac"].status == fv.SET
    assert by_name["j.flac"].status == fv.UNREADABLE
    assert by_name["b.flac"].status == fc.BUSY
    assert by_name["c.flac"].status == fv.CHANGED
    assert [os.path.basename(v.path) for v in seen] == ["b.flac", "c.flac", "u.flac"]
    for p in (kept, busy, changed, junk):
        assert p.read_bytes() == before[p], p.name
    assert fv.read_streaminfo(unset).md5 != bytes(16)
    # The next run (the busy file has settled by then) writes it too.
    rows = fc.scan([str(tmp_path)])
    out = fc.fix_rows(rows, ffmpeg_path(), settle_seconds=0.0)
    assert {os.path.basename(v.path): v.status for v in out}["b.flac"] == fv.SEALED


@pytest.mark.ffmpeg
def test_fix_rows_cancel_leaves_the_rest_unset_for_next_time(tmp_path):
    paths = []
    for i in range(3):
        p = tmp_path / f"{i}.flac"
        _real_flac(p, unset=True)
        paths.append(p)
    rows = fc.scan([str(tmp_path)])
    before = [p.read_bytes() for p in paths]
    # One True for fix_rows's own check before the first file, then the
    # decoder's first chunk asks and is told to stop.
    budget = iter([True, False])

    out = fc.fix_rows(rows, ffmpeg_path(), should_continue=lambda: next(budget, False), settle_seconds=0.0)

    # The first file's decode was interrupted (the budget ran out inside it),
    # the rest were never reached: all stay UNSET, so a later fix sees them.
    assert [v.status for v in out] == [fv.UNSET] * 3
    assert {v.detail for v in out} == {"not reached, the run was canceled"}
    for b, p in zip(before, paths, strict=True):
        assert p.read_bytes() == b
    assert [v.status for v in fc.fix_rows(out, ffmpeg_path(), settle_seconds=0.0)] == [fv.SEALED] * 3


# ---- the report ----------------------------------------------------------------


def test_write_report_is_a_spreadsheet_friendly_csv(tmp_path):
    path = tmp_path / "Ångström" / "u.flac"
    path.parent.mkdir()
    path.write_bytes(
        b"fLaC"
        + bytes([0x80])
        + (34).to_bytes(3, "big")
        + b"\x10\x00\x10\x00"
        + b"\x00\x00\x64"
        + b"\x00\x23\x28"
        + _packed(44100, 2, 16, 10)
        + bytes(16)
    )
    rows = fc.scan([str(tmp_path)])
    rows.append(fc.Verdict(fv.Row(str(tmp_path / "gone.flac"), fv.UNREADABLE, "No such file")))
    rows.append(
        fc.Verdict(
            fv.replace(
                rows[0].row,
                status=fv.SEALED,
                detail="signature written",
                md5_audio=b"\xab" * 16,
                samples_decoded=10,
            )
        )
    )
    out = tmp_path / "reports" / fc.report_name("scan", 0)

    written = fc.write_report(out, rows)

    assert written == str(out)
    raw = out.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "a byte-order mark so a spreadsheet reads UTF-8 names"
    with out.open(encoding="utf-8-sig", newline="") as f:
        table = list(csv.DictReader(f))
    assert list(table[0].keys()) == list(fc.REPORT_COLUMNS)
    assert table[0]["status"] == fv.UNSET
    assert table[0]["meaning"] == "no signature"
    assert table[0]["file"] == str(path)
    assert (table[0]["bit_depth"], table[0]["sample_rate"], table[0]["channels"], table[0]["samples_in_header"]) == (
        "16",
        "44100",
        "2",
        "10",
    )
    assert table[0]["md5_in_header"] == ""
    assert table[1]["meaning"] == "not a readable FLAC file"
    assert table[1]["detail"] == "No such file"
    assert table[2]["md5_of_audio"] == "ab" * 16
    assert table[2]["samples_decoded"] == "10"
    assert fc.report_name("fix", 0).startswith("flac-check-fix-")


def test_the_report_lists_the_folders_it_could_not_read(tmp_path):
    out = tmp_path / "r.csv"
    fc.write_report(out, [fc.Verdict(fv.Row(str(tmp_path / "a.flac"), fv.UNSET))], [str(tmp_path / "Share")])
    with out.open(encoding="utf-8-sig", newline="") as f:
        table = list(csv.DictReader(f))
    assert [(r["status"], r["file"]) for r in table] == [
        (fv.UNSET, str(tmp_path / "a.flac")),
        (fc.FOLDER_UNREADABLE, str(tmp_path / "Share")),
    ]
    assert table[1]["meaning"] == "folder could not be opened, its files were not checked"
    assert fc.FOLDER_UNREADABLE not in fc.summarize([fc.Verdict(fv.Row("x", fv.UNSET))]), "never a file's status"


def test_a_report_never_replaces_another_from_the_same_second(tmp_path):
    names = [fc.report_name("scan", 0), fc.report_name("scan", 0, 2), fc.report_name("scan", 0, 3)]
    assert names[1] == names[0][: -len(".csv")] + "-2.csv"
    written = [
        os.path.basename(fc.write_new_report(tmp_path, "scan", [fc.Verdict(fv.Row(f"{i}.flac", fv.SET))], when=0))
        for i in range(3)
    ]
    assert written == names
    for i, name in enumerate(names):
        assert f"{i}.flac" in (tmp_path / name).read_text(encoding="utf-8-sig")
    with pytest.raises(FileExistsError):
        fc.write_report(tmp_path / names[0], [], exclusive=True)
