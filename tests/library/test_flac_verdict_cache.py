"""The FLAC check's remembered verdicts: a second scan of an unchanged
library reads nothing but each file's size and time.

Pinned here: an unchanged file takes the earlier verdict without being opened
(a deep check without being decoded); any change to its size or time sends it
back to the disk; a verdict is never remembered for a file modified moments
before its read, for a failed decode, or for a file that changed between the
stat and the read; a finished walk forgets files that are gone, a cut-short
one forgets nothing; a fix over remembered rows still proves every file
itself.
"""

from __future__ import annotations

import csv
import hashlib
import os
import sqlite3
import subprocess
import threading
import time
from pathlib import Path

import pytest
from support.audio_fixtures import ffmpeg_path

from waves import flac_verify as fv
from waves.library import flac_check as fc

# Every file in these tests counts as settled (written long before the scan).
_LATER = time.time() + 3600


def _packed(rate: int, channels: int, bps: int, total: int) -> bytes:
    return ((rate << 44) | ((channels - 1) << 41) | ((bps - 1) << 36) | total).to_bytes(8, "big")


def _fake_flac(path: Path, md5: bytes = bytes(16)) -> None:
    info = b"\x10\x00\x10\x00" + b"\x00\x00\x64" + b"\x00\x23\x28" + _packed(44100, 2, 16, 0) + md5
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fLaC" + bytes([0x80]) + (34).to_bytes(3, "big") + info + b"\xff\xf8" + b"\x11" * 100)


def _cache(tmp_path: Path, now: float = _LATER) -> fc.VerdictCache:
    return fc.VerdictCache(str(tmp_path / fc.CACHE_NAME), now=lambda: now)


def _scan(tmp_path: Path, root: Path, **kw) -> list[fc.Verdict]:
    cache = _cache(tmp_path, kw.pop("now", _LATER))
    try:
        return fc.scan([str(root)], cache=cache, **kw)
    finally:
        cache.close()


def _no_reads(monkeypatch) -> None:
    def refuse(path):
        raise AssertionError(f"read again: {path}")

    monkeypatch.setattr(fv, "read_streaminfo", refuse)


def _music(tmp_path: Path) -> Path:
    root = tmp_path / "Music"
    _fake_flac(root / "A" / "unset.flac")
    _fake_flac(root / "A" / "set.flac", b"\x01" * 16)
    (root / "B").mkdir()
    (root / "B" / "junk.flac").write_bytes(b"not flac at all")
    return root


def test_an_unchanged_library_is_not_read_again(tmp_path, monkeypatch):
    root = _music(tmp_path)
    first = _scan(tmp_path, root)
    assert not any(v.cached for v in first)

    _no_reads(monkeypatch)
    second = _scan(tmp_path, root)

    assert all(v.cached for v in second)
    assert [(v.path, v.status, v.detail, v.info, v.size, v.mtime_ns) for v in second] == [
        (v.path, v.status, v.detail, v.info, v.size, v.mtime_ns) for v in first
    ], "the same verdicts, headers and stats a fresh read gives"


def test_an_unchanged_file_is_stat_ed_once_right_after_its_folder_is_listed(tmp_path, monkeypatch):
    """A share answers a stat taken just after it listed the folder from that
    listing; one taken once the whole walk is over costs a round trip per
    file. So a rescan stats each file once, by the same walk worker that
    listed its folder, straight after the listing."""
    root = _music(tmp_path)
    _fake_flac(root / "C" / "more.flac")
    _scan(tmp_path, root)

    events: list[tuple[int, str, str]] = []
    real_list, real_stat = fc._list_folder, fc._stat

    def list_folder(folder, *a):
        events.append((threading.get_ident(), "list", folder))
        return real_list(folder, *a)

    def stat(path):
        events.append((threading.get_ident(), "stat", path))
        return real_stat(path)

    monkeypatch.setattr(fc, "_list_folder", list_folder)
    monkeypatch.setattr(fc, "_stat", stat)
    _no_reads(monkeypatch)
    rows = _scan(tmp_path, root)

    assert all(v.cached for v in rows)
    stats = [p for _t, kind, p in events if kind == "stat"]
    assert sorted(stats) == sorted(v.path for v in rows), "one stat a file, none after the walk"
    for i, (thread, kind, path) in enumerate(events):
        if kind == "stat":
            own = [p for t, k, p in events[:i] if t == thread and k == "list"]
            assert own and os.path.dirname(path) == own[-1], "stat'ed straight after its folder's listing"


def test_a_file_changed_before_the_walk_is_read_and_remembered_at_its_new_stat(tmp_path):
    root = _music(tmp_path)
    _scan(tmp_path, root)
    target = root / "A" / "set.flac"
    st = os.stat(target)
    os.utime(target, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))

    rows = {os.path.basename(v.path): v for v in _scan(tmp_path, root)}
    assert not rows["set.flac"].cached

    again = {os.path.basename(v.path): v for v in _scan(tmp_path, root)}
    assert again["set.flac"].cached, "remembered against the stat taken before the read"


def test_recheck_takes_no_stat_during_the_walk(tmp_path, monkeypatch):
    """A recheck reuses nothing, so the walk's stat would be wasted: files
    are stat'ed only once the walk is over, as each is read."""
    root = _music(tmp_path)
    events: list[str] = []
    real_stat = fc._stat
    monkeypatch.setattr(fc, "_stat", lambda p: (events.append("stat"), real_stat(p))[1])
    _scan(tmp_path, root, recheck=True, on_walk=lambda n, done: done and events.append("walked"))
    assert events[0] == "walked"
    assert "stat" in events


def test_a_changed_file_is_read_again(tmp_path):
    root = _music(tmp_path)
    _scan(tmp_path, root)
    target = root / "A" / "unset.flac"
    st = os.stat(target)
    _fake_flac(target, b"\x02" * 16)  # same size, signature now set
    os.utime(target, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))

    rows = {os.path.basename(v.path): v for v in _scan(tmp_path, root)}

    assert not rows["unset.flac"].cached
    assert rows["unset.flac"].status == fv.SET
    assert rows["set.flac"].cached


def test_a_file_that_changed_size_is_read_again(tmp_path):
    root = _music(tmp_path)
    _scan(tmp_path, root)
    target = root / "B" / "junk.flac"
    st = os.stat(target)
    target.write_bytes(b"still not flac, but longer now")
    os.utime(target, ns=(st.st_atime_ns, st.st_mtime_ns))

    rows = {os.path.basename(v.path): v for v in _scan(tmp_path, root)}

    assert not rows["junk.flac"].cached


def test_a_file_modified_moments_before_its_read_is_not_remembered(tmp_path):
    root = _music(tmp_path)
    _scan(tmp_path, root, now=time.time())

    assert not any(v.cached for v in _scan(tmp_path, root))


def test_a_file_that_changed_between_the_stat_and_the_read_is_not_remembered(tmp_path):
    path = tmp_path / "a.flac"
    _fake_flac(path)
    cache = _cache(tmp_path)
    verdict, stamp = cache.lookup(str(path), deep=False)
    assert verdict is None
    fresh = fc.Verdict(fv.check_file(str(path)))

    cache.store(fresh, (stamp[0], stamp[1] - 1), deep=False)
    cache.store(fresh, None, deep=False)
    cache.close()

    cache = _cache(tmp_path)
    assert cache.lookup(str(path), deep=False)[0] is None
    cache.close()


def test_a_file_that_cannot_be_opened_is_not_remembered(tmp_path):
    cache = _cache(tmp_path)
    cache.store(fc.Verdict(fv.Row(str(tmp_path / "x.flac"), fv.UNREADABLE, "Permission denied")), (10, 10), deep=False)
    cache.close()
    with sqlite3.connect(tmp_path / fc.CACHE_NAME) as conn:
        assert conn.execute("SELECT COUNT(*) FROM verdicts").fetchone()[0] == 0


def test_a_header_verdict_does_not_answer_a_deep_check(tmp_path, monkeypatch):
    root = _music(tmp_path)
    _scan(tmp_path, root)
    decoded: list[str] = []

    def fake_decode(path, ffmpeg, info, should_continue=None, shared=1):
        decoded.append(os.path.basename(path))
        return b"\x01" * 16, 0

    monkeypatch.setattr(fv, "decode_md5", fake_decode)

    rows = {os.path.basename(v.path): v for v in _scan(tmp_path, root, ffmpeg="ffmpeg", deep=True)}

    assert sorted(decoded) == ["set.flac", "unset.flac"]
    assert rows["junk.flac"].cached, "nothing to decode in a file that is not FLAC"
    assert (rows["set.flac"].status, rows["unset.flac"].status) == (fv.OK, fv.UNSET)

    # The deep verdicts are kept now: a second deep check decodes nothing.
    decoded.clear()
    again = {os.path.basename(v.path): v for v in _scan(tmp_path, root, ffmpeg="ffmpeg", deep=True)}
    assert decoded == []
    assert all(v.cached for v in again.values())
    assert again["unset.flac"].md5_audio == b"\x01" * 16
    assert (again["set.flac"].status, again["unset.flac"].status) == (fv.OK, fv.UNSET)
    # And a header scan still answers from the header alone.
    plain = {os.path.basename(v.path): v for v in _scan(tmp_path, root)}
    assert (plain["set.flac"].status, plain["set.flac"].md5_audio) == (fv.SET, None)


def test_recheck_reads_every_file_again_and_remembers_what_it_finds(tmp_path, monkeypatch):
    root = _music(tmp_path)
    _scan(tmp_path, root)
    reads: list[str] = []
    real = fv.read_streaminfo

    def counting(path):
        reads.append(os.path.basename(path))
        return real(path)

    monkeypatch.setattr(fv, "read_streaminfo", counting)

    rows = _scan(tmp_path, root, recheck=True)

    assert sorted(reads) == ["junk.flac", "set.flac", "unset.flac"]
    assert not any(v.cached for v in rows)
    reads.clear()
    assert all(v.cached for v in _scan(tmp_path, root)), "a normal scan after it reuses again"
    assert reads == []


def test_a_deep_recheck_decodes_every_file_again(tmp_path, monkeypatch):
    root = _music(tmp_path)
    decoded: list[str] = []

    def fake_decode(path, ffmpeg, info, should_continue=None, shared=1):
        decoded.append(os.path.basename(path))
        return b"\x01" * 16, 0

    monkeypatch.setattr(fv, "decode_md5", fake_decode)
    _scan(tmp_path, root, ffmpeg="ffmpeg", deep=True)
    decoded.clear()

    _scan(tmp_path, root, ffmpeg="ffmpeg", deep=True, recheck=True)

    assert sorted(decoded) == ["set.flac", "unset.flac"]


def test_a_failed_decode_is_tried_again_next_time(tmp_path, monkeypatch):
    root = tmp_path / "Music"
    _fake_flac(root / "a.flac", b"\x01" * 16)
    calls: list[int] = []

    def failing(path, ffmpeg, info, should_continue=None, shared=1):
        calls.append(1)
        raise fv.DecodeFailed("the decoder did not finish within 120 seconds")

    monkeypatch.setattr(fv, "decode_md5", failing)
    _scan(tmp_path, root, ffmpeg="ffmpeg", deep=True)
    rows = _scan(tmp_path, root, ffmpeg="ffmpeg", deep=True)

    assert len(calls) == 2
    assert rows[0].status == fv.DECODE_FAILED
    assert not rows[0].cached


def test_a_finished_walk_forgets_files_that_are_gone(tmp_path):
    root = _music(tmp_path)
    other = tmp_path / "Other"
    _fake_flac(other / "kept.flac")
    _scan(tmp_path, root)
    _scan(tmp_path, other)
    (root / "A" / "set.flac").unlink()

    _scan(tmp_path, root)

    with sqlite3.connect(tmp_path / fc.CACHE_NAME) as conn:
        paths = {p for (p,) in conn.execute("SELECT path FROM verdicts")}
    assert str(root / "A" / "set.flac") not in paths
    assert str(root / "A" / "unset.flac") in paths
    assert str(other / "kept.flac") in paths, "a folder this scan did not walk keeps its verdicts"


def test_a_cut_short_scan_forgets_nothing(tmp_path):
    root = _music(tmp_path)
    _scan(tmp_path, root)
    (root / "A" / "set.flac").unlink()
    seen: list[fc.Verdict] = []

    _scan(tmp_path, root, should_continue=lambda: len(seen) < 1, on_row=seen.append)

    with sqlite3.connect(tmp_path / fc.CACHE_NAME) as conn:
        paths = {p for (p,) in conn.execute("SELECT path FROM verdicts")}
    assert str(root / "A" / "set.flac") in paths


def test_prune_keeps_what_sits_under_a_folder_the_walk_could_not_read(tmp_path):
    root = _music(tmp_path)
    _scan(tmp_path, root)
    cache = _cache(tmp_path)

    cache.prune([str(root)], [str(root / "A" / "unset.flac")], [str(root / "B")])
    cache.close()

    with sqlite3.connect(tmp_path / fc.CACHE_NAME) as conn:
        paths = {p for (p,) in conn.execute("SELECT path FROM verdicts")}
    assert paths == {str(root / "A" / "unset.flac"), str(root / "B" / "junk.flac")}


def test_an_older_cache_layout_is_started_over(tmp_path):
    db = tmp_path / fc.CACHE_NAME
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE verdicts (path TEXT)")
        conn.execute("INSERT INTO verdicts VALUES ('x')")
    root = _music(tmp_path)

    rows = _scan(tmp_path, root)

    assert len(rows) == 3
    assert all(v.cached for v in _scan(tmp_path, root))


def test_a_cache_that_breaks_mid_run_falls_back_to_reading(tmp_path):
    root = _music(tmp_path)
    _scan(tmp_path, root)
    cache = _cache(tmp_path)
    cache._conn.close()  # any sqlite error from here on

    rows = fc.scan([str(root)], cache=cache)
    cache.close()

    assert len(rows) == 3
    assert not any(v.cached for v in rows)


def test_the_report_says_which_verdicts_are_from_an_earlier_check(tmp_path):
    root = _music(tmp_path)
    _scan(tmp_path, root)
    target = root / "A" / "set.flac"
    st = os.stat(target)
    os.utime(target, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    out = tmp_path / "r.csv"

    fc.write_report(out, _scan(tmp_path, root))

    with out.open(encoding="utf-8-sig", newline="") as f:
        table = {os.path.basename(r["file"]): r["from_earlier_check"] for r in csv.DictReader(f)}
    assert table == {"set.flac": "", "unset.flac": "yes", "junk.flac": "yes"}


# ---- with a real decoder ------------------------------------------------------------


def _run(*args: str) -> bytes:
    # argv is ffmpeg from PATH plus literal test arguments.
    return subprocess.run([ffmpeg_path(), "-v", "error", *args], capture_output=True, check=True).stdout  # noqa: S603


def _real_flac(path: Path) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    sine = "sine=frequency=440:duration=0.3"
    _run("-y", "-f", "lavfi", "-i", sine, "-ac", "2", "-ar", "44100", "-sample_fmt", "s16", "-c:a", "flac", str(path))
    si = fv.read_streaminfo(path)
    fv.write_streaminfo(path, si, fv.sealed_bytes(si, bytes(16), 0))
    return hashlib.md5(_run("-i", str(path), "-f", "s16le", "-")).digest()  # noqa: S324


@pytest.mark.ffmpeg
def test_a_fix_over_remembered_rows_still_proves_each_file(tmp_path):
    root = tmp_path / "Music"
    md5 = _real_flac(root / "a.flac")
    _real_flac(root / "b.flac")
    _scan(tmp_path, root, ffmpeg=ffmpeg_path())
    rows = _scan(tmp_path, root, ffmpeg=ffmpeg_path())
    assert all(v.cached and v.status == fv.UNSET for v in rows)
    # b.flac changes behind the remembered verdict's back, keeping its stat.
    b = root / "b.flac"
    st = os.stat(b)
    si = fv.read_streaminfo(b)
    fv.write_streaminfo(b, si, si.raw[:18] + b"\x07" * 16)
    os.utime(b, ns=(st.st_atime_ns, st.st_mtime_ns))

    out = {os.path.basename(v.path): v for v in fc.fix_rows(rows, ffmpeg_path(), settle_seconds=0.0)}

    assert out["a.flac"].status == fv.SEALED
    assert fv.read_streaminfo(root / "a.flac").md5 == md5
    assert out["b.flac"].status == fv.CHANGED, "the header on disk is not the one remembered: left alone"
    assert fv.read_streaminfo(b).md5 == b"\x07" * 16
    # The sealed file's time moved, so the next scan reads it again.
    again = {os.path.basename(v.path): v for v in _scan(tmp_path, root, ffmpeg=ffmpeg_path())}
    assert (again["a.flac"].cached, again["a.flac"].status) == (False, fv.SET)


def _slow_reads(monkeypatch, delay: float = 0.02) -> dict:
    """Make each header read take a moment and record how many overlap."""
    seen = {"now": 0, "most": 0}
    lock = threading.Lock()
    real = fv._read_row

    def read_row(path):
        with lock:
            seen["now"] += 1
            seen["most"] = max(seen["most"], seen["now"])
        time.sleep(delay)
        with lock:
            seen["now"] -= 1
        return real(path)

    monkeypatch.setattr(fv, "_read_row", read_row)
    return seen


def _many(tmp_path: Path, n: int = 24) -> Path:
    root = tmp_path / "Many"
    for i in range(n):
        _fake_flac(root / f"{i // 6}" / f"{i:02d}.flac", bytes([i % 2]) * 16)
    return root


def test_a_first_scan_reads_several_files_at_once_and_keeps_the_walk_order(tmp_path, monkeypatch):
    root = _many(tmp_path)
    order = list(fc.iter_flac_files([str(root)]))
    seen = _slow_reads(monkeypatch)
    rows = _scan(tmp_path, root)
    assert [v.path for v in rows] == order
    assert seen["most"] > 1, "reads overlap"
    assert seen["most"] <= fc._READ_THREADS
    assert [v.status for v in rows] == [fv.UNSET if i % 2 == 0 else fv.SET for i in range(24)]


def test_the_cache_is_asked_and_told_on_the_scan_thread_only(tmp_path, monkeypatch):
    """sqlite connections belong to the thread that opened them."""
    root = _many(tmp_path)
    _slow_reads(monkeypatch, 0.005)
    threads: set[int] = set()
    for name in ("remembered", "store"):
        real = getattr(fc.VerdictCache, name)

        def spy(self, *a, _real=real, **kw):
            threads.add(threading.get_ident())
            return _real(self, *a, **kw)

        monkeypatch.setattr(fc.VerdictCache, name, spy)
    first = _scan(tmp_path, root)
    second = _scan(tmp_path, root)
    assert not any(v.cached for v in first)
    assert all(v.cached for v in second)
    assert threads == {threading.get_ident()}


def test_a_cancel_mid_scan_stops_reading_and_keeps_the_rows_in_order(tmp_path, monkeypatch):
    root = _many(tmp_path)
    order = list(fc.iter_flac_files([str(root)]))
    _slow_reads(monkeypatch)
    stop = threading.Event()
    got: list[fc.Verdict] = []

    def on_row(verdict):
        got.append(verdict)
        if len(got) == 5:
            stop.set()

    rows = _scan(tmp_path, root, should_continue=lambda: not stop.is_set(), on_row=on_row)
    assert 5 <= len(rows) < 24
    assert [v.path for v in rows] == order[: len(rows)]
    again = _scan(tmp_path, root)
    assert sum(v.cached for v in again) == 5, "only the rows handed out before the cancel were remembered"


def test_a_deep_check_decodes_fewer_files_at_once_than_a_header_scan_reads():
    assert 1 <= fc._DECODE_THREADS <= 4 < fc._READ_THREADS


def test_a_deep_scan_gives_each_decode_its_share_of_the_time(tmp_path, monkeypatch):
    root = _many(tmp_path, 4)
    calls: list[int] = []

    def check_file(path, ffmpeg=None, *, deep=False, should_continue=None, shared=1):
        calls.append(shared)
        return fv._read_row(path)

    monkeypatch.setattr(fv, "check_file", check_file)
    fc.scan([str(root)], "ffmpeg", deep=True)
    fc.scan([str(root)])
    assert calls == [fc._DECODE_THREADS] * 4 + [fc._READ_THREADS] * 4


def test_a_name_that_is_not_utf8_is_read_every_scan_and_never_fails_it(tmp_path, monkeypatch):
    """An old Latin-1 rip on Linux: the name arrives with surrogate escapes,
    which sqlite cannot store. The file is a miss each time, the rest of
    the scan and its report carry on."""
    odd = b"/music/Caf\xe9.flac".decode("utf-8", "surrogateescape")
    cache = _cache(tmp_path)
    assert cache.remembered(odd, False, (10, 10**9)) is None
    cache.store(fc.Verdict(fv.Row(odd, fv.UNREADABLE, "x", size=10, mtime_ns=10**9)), (10, 10**9), False)
    assert cache._conn is not None and not cache.damaged, "a miss, not a broken cache"
    cache.close()

    root = _music(tmp_path)
    real = fc.iter_flac_files

    def walk(roots, should_continue=None, unreadable=None, stamps=None):
        yield from real(roots, should_continue, unreadable, stamps)
        if stamps is not None:
            stamps[odd] = (10, 10**9)
        yield odd

    monkeypatch.setattr(fc, "iter_flac_files", walk)
    rows = _scan(tmp_path, root)
    assert rows[-1].path == odd and rows[-1].status == fv.UNREADABLE
    again = _scan(tmp_path, root)
    assert [v.cached for v in again] == [True] * (len(again) - 1) + [False]
    report = fc.write_report(tmp_path / "r.csv", rows)
    assert "Caf\\udce9.flac" in Path(report).read_text(encoding="utf-8-sig")
