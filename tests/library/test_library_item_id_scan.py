"""The scan carries each file's Waves item id (ADR 0007, issue #222).

WHAT THIS FENCES OFF
--------------------
The Library section's Saved view is "the files Waves itself saved", which the
scan could not answer: the tracks table held a file's title, artist and
quality but not the item id the download gate writes into its tags. Without
it, a saved file is indistinguishable from a ripped one.

These tests pin the scan half: every file is probed once for its id (generic
first, legacy fallback -- the same read the download gate performs), the id
lands on the track row, a cache from before the column backfills itself with
ONE re-read and then settles, an untagged file settles too (the whole library
must not re-read forever because most of it predates Waves), a failed probe
retries rather than hardening "untagged", and the Library section's pages
filter and page on that stored answer.
"""

from __future__ import annotations

import os

import pytest

from waves.library_index import LibraryIndex


def _mk(base, rel, files):
    d = os.path.join(base, *rel.split("/"))
    os.makedirs(d, exist_ok=True)
    for name in files:
        open(os.path.join(d, name), "w").close()
    return d


def _path_reader(pathmap, counter=None):
    def read(path):
        if counter is not None:
            counter.append(path)
        return pathmap.get(path)

    return read


def _index(tmp_path, *, pathmap=None, idmap=None, tags=None, id_counter=None):
    """An index whose tag reader is keyed by path (falling back to None) and
    whose item-id probe is keyed by path, with an optional probe counter."""
    pathmap = pathmap or {}
    idmap = idmap or {}

    def probe(path):
        if id_counter is not None:
            id_counter.append(path)
        return idmap.get(path, "")

    return LibraryIndex(
        str(tmp_path / "library.sqlite3"),
        read_tags=_path_reader(pathmap),
        read_item_id=probe,
    )


def _album_tags(title="Alb", artist="A", date="2000"):
    return {"album": title, "artist": artist, "date": date}


# --- the scan reads and stores the id ---------------------------------------


def test_track_rows_carry_the_item_id_tag(tmp_path):
    lib = _mk(tmp_path, "lib", [])
    d = _mk(tmp_path, "lib/A/Alb", ["1.flac", "2.flac", "3.flac"])
    pathmap = {
        os.path.join(d, "1.flac"): {**_album_tags(), "title": "One"},
        os.path.join(d, "2.flac"): {**_album_tags(), "title": "Two"},
        os.path.join(d, "3.flac"): {**_album_tags(), "title": "Three"},
    }
    idmap = {
        os.path.join(d, "1.flac"): "apple:91",
        os.path.join(d, "2.flac"): "77",  # a legacy TIDAL id reads bare
        # 3.flac is untagged: a plain library file.
    }
    idx = _index(tmp_path, pathmap=pathmap, idmap=idmap)
    idx.refresh(lib)
    got = {t["title"]: t["item_id"] for t in idx.iter_tracks()}
    assert got == {"One": "apple:91", "Two": "77", "Three": ""}


def test_the_files_page_exposes_the_stored_id(tmp_path):
    lib = _mk(tmp_path, "lib", [])
    d = _mk(tmp_path, "lib/A/Alb", ["1.flac"])
    pathmap = {os.path.join(d, "1.flac"): {**_album_tags(), "title": "One", "length": 123}}
    idx = _index(tmp_path, pathmap=pathmap, idmap={os.path.join(d, "1.flac"): "apple:91"})
    idx.refresh(lib)
    page, more = idx.files_page("all")
    assert more is False
    assert page == [
        {
            "folder_path": d,
            "title": "One",
            "artist": "A",
            "album": "Alb",
            "album_artist": "A",
            "year": "2000",
            "item_id": "apple:91",
            "codec": "",
            "bitrate": 0,
            "bits": 0,
            "rate": 0,
            "length": 123,
            "audio_type": "stereo",
        }
    ]


def test_the_default_probe_reads_through_the_download_gates_reader(tmp_path, monkeypatch):
    """The real wiring (no injected probe) reads the tag family the download
    gate wrote, legacy fallback included: the scan must not invent its own
    tag read, or a file Waves saved would be invisible to Saved."""
    lib = _mk(tmp_path, "lib", [])
    d = _mk(tmp_path, "lib/A/Alb", ["1.flac"])
    pathmap = {os.path.join(d, "1.flac"): {**_album_tags(), "title": "One"}}
    asked: list[str] = []

    def fake_read_item_id(path):
        asked.append(path)
        return "1234"  # what a legacy WAVES_TIDAL_ID answers

    monkeypatch.setattr("waves.metadata.read_item_id", fake_read_item_id)
    idx = LibraryIndex(str(tmp_path / "library.sqlite3"), read_tags=_path_reader(pathmap))
    idx.refresh(lib)
    assert asked == [os.path.join(d, "1.flac")]
    assert [t["item_id"] for t in idx.iter_tracks()] == ["1234"]


# --- the freshness gates ----------------------------------------------------


def test_a_warm_scan_probes_no_file(tmp_path):
    """The id probe is per file on a COLD read and never on an unchanged
    folder: the scan's time budget survives the new column (the issue's own
    requirement)."""
    lib = _mk(tmp_path, "lib", [])
    d = _mk(tmp_path, "lib/A/Alb", ["1.flac", "2.flac"])
    pathmap = {
        os.path.join(d, "1.flac"): {**_album_tags(), "title": "One"},
        os.path.join(d, "2.flac"): {**_album_tags(), "title": "Two"},
    }
    probes: list[str] = []
    idx = _index(tmp_path, pathmap=pathmap, idmap={}, id_counter=probes)
    idx.refresh(lib)
    assert sorted(probes) == sorted(os.path.join(d, n) for n in ("1.flac", "2.flac"))
    probes.clear()
    idx.refresh(lib)
    assert probes == []


def test_a_pre_item_id_cache_backfills_once_then_rests(tmp_path):
    """An existing cache holds track rows with no item_id (NULL). The next
    scan owes exactly one re-read, which writes the ids; the scan after that
    is warm again."""
    lib = _mk(tmp_path, "lib", [])
    d = _mk(tmp_path, "lib/A/Alb", ["1.flac"])
    pathmap = {os.path.join(d, "1.flac"): {**_album_tags(), "title": "One"}}
    reads: list[str] = []
    idx = LibraryIndex(
        str(tmp_path / "library.sqlite3"),
        read_tags=_path_reader(pathmap, reads),
        read_item_id=lambda p: "42",
    )
    idx.refresh(lib)
    # Simulate the pre-#222 cache: the column arrives with NULL on every row.
    with idx._lock:
        idx._conn.execute("UPDATE tracks SET item_id = NULL")
        idx._conn.commit()
    reads.clear()
    idx.refresh(lib)
    assert reads == [os.path.join(d, "1.flac")]  # the one backfill re-read
    assert [t["item_id"] for t in idx.iter_tracks()] == ["42"]
    reads.clear()
    idx.refresh(lib)
    assert reads == []  # settled: NULL was the only reason to re-read


def test_untagged_files_settle_instead_of_retrying_forever(tmp_path):
    """Most of a real library predates Waves: those files answer "" forever,
    and re-reading their folders every scan would blow the scan's budget."""
    lib = _mk(tmp_path, "lib", [])
    d = _mk(tmp_path, "lib/A/Alb", ["1.flac"])
    pathmap = {os.path.join(d, "1.flac"): {**_album_tags(), "title": "One"}}
    reads: list[str] = []
    idx = LibraryIndex(
        str(tmp_path / "library.sqlite3"),
        read_tags=_path_reader(pathmap, reads),
        read_item_id=lambda p: "",  # read fine, no Waves id
    )
    idx.refresh(lib)
    reads.clear()
    idx.refresh(lib)
    assert reads == []
    assert [t["item_id"] for t in idx.iter_tracks()] == [""]


def test_a_failed_id_probe_retries_instead_of_hardening_untagged(tmp_path):
    """None from the probe means the read failed, never "no id": the row is
    persisted unknown so the folder retries, and the file joins Saved as soon
    as the probe can answer."""
    lib = _mk(tmp_path, "lib", [])
    d = _mk(tmp_path, "lib/A/Alb", ["1.flac"])
    pathmap = {os.path.join(d, "1.flac"): {**_album_tags(), "title": "One"}}
    answers: list[str | None] = [None, "apple:7"]
    reads: list[str] = []
    idx = LibraryIndex(
        str(tmp_path / "library.sqlite3"),
        read_tags=_path_reader(pathmap, reads),
        read_item_id=lambda p: answers.pop(0),
    )
    idx.refresh(lib)
    assert [t["item_id"] for t in idx.iter_tracks()] == [""]  # unknown reads as no id
    reads.clear()
    idx.refresh(lib)  # the NULL row forced the retry
    assert reads == [os.path.join(d, "1.flac")]
    assert [t["item_id"] for t in idx.iter_tracks()] == ["apple:7"]
    saved, _ = idx.files_page("saved")
    assert [r["title"] for r in saved] == ["One"]


# --- the Saved / All files views --------------------------------------------


def test_saved_lists_only_tagged_files_and_all_lists_everything(tmp_path):
    lib = _mk(tmp_path, "lib", [])
    saved = _mk(tmp_path, "lib/A/Saved", ["1.flac", "2.flac"])
    own = _mk(tmp_path, "lib/B/Ripped", ["1.flac"])
    pathmap = {
        os.path.join(saved, "1.flac"): {**_album_tags("Saved"), "title": "One"},
        os.path.join(saved, "2.flac"): {**_album_tags("Saved"), "title": "Two"},
        os.path.join(own, "1.flac"): {**_album_tags("Ripped"), "title": "Rip"},
    }
    idmap = {
        os.path.join(saved, "1.flac"): "apple:1",
        os.path.join(saved, "2.flac"): "2",
    }
    idx = _index(tmp_path, pathmap=pathmap, idmap=idmap)
    idx.refresh(lib)

    saved_page, saved_more = idx.files_page("saved")
    all_page, all_more = idx.files_page("all")
    assert [r["title"] for r in saved_page] == ["One", "Two"]
    assert [r["item_id"] for r in saved_page] == ["apple:1", "2"]
    assert saved_more is False and all_more is False
    assert [r["title"] for r in all_page] == ["One", "Two", "Rip"]  # folder order
    assert [r["item_id"] for r in all_page] == ["apple:1", "2", ""]
    assert idx.files_count("saved") == 2
    assert idx.files_count("all") == 3


def test_files_page_pages_folder_major_without_losing_a_row(tmp_path):
    lib = _mk(tmp_path, "lib", [])
    d1 = _mk(tmp_path, "lib/A/One", ["1.flac", "2.flac"])
    d2 = _mk(tmp_path, "lib/B/Two", ["1.flac"])
    pathmap = {}
    for d, title in ((d1, "One"), (d2, "Two")):
        for name in sorted(os.listdir(d)):
            pathmap[os.path.join(d, name)] = {**_album_tags(title), "title": name}
    idx = _index(tmp_path, pathmap=pathmap, idmap={os.path.join(d1, "1.flac"): "9"})
    idx.refresh(lib)

    first, more = idx.files_page("all", 0, 2)
    assert more is True
    assert [(r["folder_path"], r["title"]) for r in first] == [(d1, "1.flac"), (d1, "2.flac")]
    second, more = idx.files_page("all", 2, 2)
    assert more is False
    assert [(r["folder_path"], r["title"]) for r in second] == [(d2, "1.flac")]
    # The Saved window is paged the same way over its own filtered set.
    only, more = idx.files_page("saved", 0, 1)
    assert more is False
    assert [r["title"] for r in only] == ["1.flac"]


def test_files_page_rejects_an_unknown_view(tmp_path):
    idx = LibraryIndex(str(tmp_path / "library.sqlite3"), read_tags=_path_reader({}), read_item_id=lambda p: "")
    with pytest.raises(ValueError):
        idx.files_page("downloads")


def test_a_file_moved_out_of_the_root_leaves_both_views(tmp_path):
    """The scan's prune is the Saved view's only way to lose a row: a file
    moved out of the library is not on disk any more, so neither view may
    keep claiming it."""
    lib = _mk(tmp_path, "lib", [])
    kept = _mk(tmp_path, "lib/A/Keep", ["1.flac"])
    d = _mk(tmp_path, "lib/B/Moved", ["1.flac"])
    pathmap = {
        os.path.join(kept, "1.flac"): {**_album_tags("Keep", "A"), "title": "K"},
        os.path.join(d, "1.flac"): {**_album_tags("Moved", "B"), "title": "M"},
    }
    idx = _index(tmp_path, pathmap=pathmap, idmap={os.path.join(d, "1.flac"): "5"})
    idx.refresh(lib)
    assert [r["title"] for r in idx.files_page("saved")[0]] == ["M"]
    # Move the saved file out of the walked root entirely; the other album
    # stays, so the walk is not the "library went empty" ghost case.
    outside = _mk(tmp_path, "elsewhere", [])
    os.replace(os.path.join(d, "1.flac"), os.path.join(outside, "1.flac"))
    idx.refresh(lib)
    assert idx.files_page("saved")[0] == []
    assert [r["title"] for r in idx.files_page("all")[0]] == ["K"]
    assert idx.files_count("saved") == 0
