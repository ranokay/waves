"""Quarantine actions on a failed row: reveal and delete the bad bytes.

A kept quarantine copy is recorded against its queue row, the row's count
drives the drawer's OPEN/DELETE actions, opening reveals the holding folder,
and deleting removes the copies (pruning the folders they emptied) while
leaving the skip-list to REDOWNLOAD. A copy that cannot be deleted stays
recorded, so the actions never hide bytes that are still on disk.

Behavior, not spelling: every assertion is about bytes on disk, recorded
paths, the row the drawer reads, or the status words the user sees.
"""

from __future__ import annotations

from pathlib import Path
from threading import Lock
from types import SimpleNamespace

import waves.waves_ui.backend as backend
from waves.waves_ui.backend import WavesBridge

_METHODS = (
    "_apple_record_quarantine",
    "_apple_quarantine_file",
    "openQuarantine",
    "deleteQuarantine",
    "_apple_quarantine_folder",
)


def _stub(root: Path) -> SimpleNamespace:
    stub = SimpleNamespace()
    stub._apple_quarantine_paths = {}
    stub._queue_index = {}
    stub.marked = []
    stub.queue_emits = 0
    stub.last_status = ""
    stub._queue_item = lambda qid: stub._queue_index.get(int(qid))
    stub._queue_mark_changed = lambda qid: stub.marked.append(int(qid))
    stub._emit_queue = lambda: setattr(stub, "queue_emits", stub.queue_emits + 1)
    stub._set_status = lambda msg: setattr(stub, "last_status", msg)
    stub._apple_quarantine_root = lambda: root
    stub._apple_quarantine_keep = lambda: True
    for name in _METHODS:
        setattr(stub, name, getattr(WavesBridge, name).__get__(stub, SimpleNamespace))
    return stub


def _failed_row(stub: SimpleNamespace, qid: int = 7) -> dict:
    row = {"qid": qid, "status": "failed", "reason": "failed integrity check", "quarantineCount": 0}
    stub._queue_index[qid] = row
    return row


def _copy(root: Path, name: str = "01 Track.m4a") -> Path:
    path = root / "Artist" / "Album" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"bad")
    return path


def test_a_kept_copy_lands_in_the_folder_and_on_its_row(tmp_path):
    root = tmp_path / "Waves Quarantine"
    stub = _stub(root)
    row = _failed_row(stub)
    staged = tmp_path / "staged.m4a"
    staged.write_bytes(b"bad")

    dest = stub._apple_quarantine_file(
        staged, relative="Artist/Album/01 Track", track_id="apple:t1", audio_type="stereo", qid=7
    )

    assert dest == root / "Artist" / "Album" / "01 Track.m4a"
    assert Path(dest).is_file()
    assert row["quarantineCount"] == 1
    assert stub._apple_quarantine_paths[7] == [str(dest)]


def test_keep_off_writes_no_bytes_and_leaves_the_row_clean(tmp_path):
    root = tmp_path / "Waves Quarantine"
    stub = _stub(root)
    stub._apple_quarantine_keep = lambda: False
    row = _failed_row(stub)
    staged = tmp_path / "staged.m4a"
    staged.write_bytes(b"bad")

    assert stub._apple_quarantine_file(staged, relative="A/01", track_id="apple:t1", qid=7) is None
    assert row["quarantineCount"] == 0
    assert stub._apple_quarantine_paths == {}


def test_recording_counts_each_copy_once(tmp_path):
    root = tmp_path / "Waves Quarantine"
    stub = _stub(root)
    row = _failed_row(stub)
    first = _copy(root, "01 Track.m4a")
    second = _copy(root, "02 Track.m4a")

    stub._apple_record_quarantine(7, first)
    assert row["quarantineCount"] == 1
    stub._apple_record_quarantine(7, first)
    assert row["quarantineCount"] == 1
    stub._apple_record_quarantine(7, second)
    assert row["quarantineCount"] == 2
    assert stub._apple_quarantine_paths[7] == [str(first), str(second)]


def test_open_reveals_the_folder_holding_the_copy(tmp_path, monkeypatch):
    root = tmp_path / "Waves Quarantine"
    stub = _stub(root)
    _failed_row(stub)
    copy = _copy(root)
    stub._apple_record_quarantine(7, copy)

    opened: list[str] = []
    fake = SimpleNamespace(QDesktopServices=SimpleNamespace(openUrl=lambda url: opened.append(url.toLocalFile())))
    monkeypatch.setattr(backend, "QtGui", fake)

    stub.openQuarantine(7)

    assert opened == [str(copy.parent)]


def test_delete_removes_the_copies_and_prunes_the_emptied_folders(tmp_path):
    root = tmp_path / "Waves Quarantine"
    stub = _stub(root)
    row = _failed_row(stub)
    first = _copy(root, "01 Track.m4a")
    second = _copy(root, "02 Track.m4a")
    stub._apple_record_quarantine(7, first)
    stub._apple_record_quarantine(7, second)

    stub.deleteQuarantine(7)

    assert not first.exists() and not second.exists()
    assert not first.parent.exists()  # the emptied album folder is gone
    assert root.is_dir()  # the quarantine root itself stays
    assert row["quarantineCount"] == 0
    assert 7 not in stub._apple_quarantine_paths
    assert "deleted" in stub.last_status


def test_a_copy_that_cannot_be_deleted_stays_on_the_row(tmp_path, monkeypatch):
    root = tmp_path / "Waves Quarantine"
    stub = _stub(root)
    row = _failed_row(stub)
    locked = _copy(root, "locked.m4a")
    free = _copy(root, "free.m4a")
    stub._apple_record_quarantine(7, locked)
    stub._apple_record_quarantine(7, free)

    real_unlink = Path.unlink

    def flaky_unlink(self, *args, **kwargs):
        if self.name == "locked.m4a":
            raise PermissionError("locked")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)
    stub.deleteQuarantine(7)

    assert locked.is_file(), "the locked copy must stay on disk"
    assert not free.exists()
    assert row["quarantineCount"] == 1
    assert stub._apple_quarantine_paths[7] == [str(locked)]
    assert "could not delete" in stub.last_status.lower()


def test_delete_keeps_a_sibling_rows_copies(tmp_path):
    root = tmp_path / "Waves Quarantine"
    stub = _stub(root)
    _failed_row(stub, qid=7)
    keep = _copy(root, "other.m4a")
    stub._apple_quarantine_paths[8] = [str(keep)]
    doomed = _copy(root, "doomed.m4a")
    stub._apple_quarantine_paths[7] = [str(doomed)]

    stub.deleteQuarantine(7)

    assert not doomed.exists()
    assert keep.is_file()
    assert stub._apple_quarantine_paths[8] == [str(keep)]


def test_delete_with_nothing_recorded_says_so(tmp_path):
    root = tmp_path / "Waves Quarantine"
    stub = _stub(root)
    _failed_row(stub)

    stub.deleteQuarantine(7)

    assert "No quarantined copy" in stub.last_status


def test_withdrawing_a_row_forgets_its_quarantine_paths():
    row = {"qid": 7, "status": "failed", "reason": "x", "quarantineCount": 1, "media_id": "apple:1"}
    stub = SimpleNamespace(
        _queue=[row],
        _queue_index={7: row},
        _queue_lock=Lock(),
        _pending_lock=Lock(),
        _pending_downloads=[],
        _merge_plans={},
        _redownload_overrides=set(),
        _library_claim_overrides=set(),
        _qdirty_removed=[],
        _apple_quarantine_paths={7: ["/tmp/waves-quarantine-whatever.m4a"]},
    )
    stub._reindex_queue = lambda: setattr(stub, "_queue_index", {it["qid"]: it for it in stub._queue})

    gone = WavesBridge._remove_rows_where.__get__(stub, SimpleNamespace)(lambda it: it["qid"] == 7)

    assert gone == [7]
    assert stub._apple_quarantine_paths == {}
