"""The Library section's bridge data (ADR 0007, issue #222).

WHAT THIS FENCES OFF
--------------------
My Music had no view of the files on disk at all. The section's two views are
"Saved" (the files Waves itself saved, carrying the provider the file came
from) and "All files" (every audio file the scan sees, untagged rows carrying
no badge), and both are the SCAN's answers: no provider is consulted, so a
signed-out pane still lists the library.

These tests drive the real slots on the Qt-free library stub: the seed scan
runs first, then the pages, so the rows under test are the ones the scanner
really wrote. The file-id variety (a generic Apple id, a legacy bare TIDAL id,
an untagged file) is the same spread the on-disk tags produce.
"""

from __future__ import annotations

import os

from support.library_fakes import make_album_dir, make_library_bridge

from waves.waves_ui.backend import _library_file_row


def _tags(album="Alb", artist="A", date="2000", **over):
    return {"album": album, "artist": artist, "date": date, **over}


def _seed(tmp_path):
    """A two-album library: one Waves saved (two files, both id spellings) and
    one the user ripped (no ids). Returns (bridge, pathmap, item_ids)."""
    lib = os.path.join(tmp_path, "lib")
    saved = make_album_dir(lib, "A/Saved", ["01.flac", "02.flac"])
    ripped = make_album_dir(lib, "B/Ripped", ["01.mp3"])
    pathmap = {
        os.path.join(saved, "01.flac"): _tags("Saved", title="First", length=95),
        os.path.join(saved, "02.flac"): _tags("Saved", title="Second", length=180),
        os.path.join(ripped, "01.mp3"): _tags("Ripped", "B", title="Tripped"),
    }
    item_ids = {
        os.path.join(saved, "01.flac"): "apple:91",
        os.path.join(saved, "02.flac"): "77",  # legacy TIDAL, read bare
    }
    bridge = make_library_bridge(tmp_path, library_folder=lib, path_tags=pathmap, item_ids=item_ids)
    bridge._library.refresh(lib, force_full=True)
    return bridge, pathmap, item_ids


def test_the_views_are_bridge_data_with_saved_first(tmp_path):
    bridge = make_library_bridge(tmp_path, library_folder=os.path.join(tmp_path, "lib"))
    data = bridge.myMusicLibrary()
    assert data["configured"] is True
    assert data["views"] == [{"id": "saved", "label": "Saved"}, {"id": "all", "label": "All files"}]


def test_an_unconfigured_library_still_answers_its_section(tmp_path):
    """The section is always present: with no folder it must say how to point
    Waves at one, which is what ``configured`` False drives."""
    bridge = make_library_bridge(tmp_path, library_enabled=False, library_folder="")
    data = bridge.myMusicLibrary()
    assert data["configured"] is False
    assert [v["id"] for v in data["views"]] == ["saved", "all"]


def test_saved_lists_the_tagged_files_with_their_provider_namespaces(tmp_path):
    bridge, _pathmap, _ids = _seed(tmp_path)
    bridge.loadLibraryFiles("saved")
    ((view, items, more, total),) = bridge.libraryFilesLoaded.emits
    assert (view, more, total) == ("saved", False, 2)
    assert [(r["title"], r["provider"], r["item_id"]) for r in items] == [
        ("First", "apple", "apple:91"),
        ("Second", "tidal", "77"),
    ]
    # The row vocabulary the pane renders is the bridge's own: the album and
    # artist words come from the scan's folder identity, the duration in the
    # same readable spelling every other row uses.
    assert items[0]["album"] == "Saved" and items[0]["artist"] == "A"
    assert items[0]["folder"].endswith(os.path.join("A", "Saved"))
    assert items[0]["duration"] == "1:35" and items[0]["duration_sec"] == 95


def test_all_files_lists_everything_with_no_badge_on_untagged_rows(tmp_path):
    bridge, _pathmap, _ids = _seed(tmp_path)
    bridge.loadLibraryFiles("all")
    ((view, items, more, total),) = bridge.libraryFilesLoaded.emits
    assert (view, more, total) == ("all", False, 3)
    titles = [(r["title"], r["provider"]) for r in items]
    assert titles == [("First", "apple"), ("Second", "tidal"), ("Tripped", "")]
    # The Saved filter and the All-files list come from one scan: the tagged
    # rows agree row for row, so the section's counts cannot disagree with
    # the badges the same ids light in search.
    assert {r["item_id"] for r in items if r["provider"]} == {"apple:91", "77"}


def test_the_row_builder_derives_the_provider_from_the_id_namespace():
    """One rule, in one place: a bare id is TIDAL's (the ids module's own rule,
    so a legacy file answers like a new one), another provider keeps its
    namespace, and no id means no provider -- never a guess."""
    assert _library_file_row({"item_id": "apple:9", "length": 61})["provider"] == "apple"
    assert _library_file_row({"item_id": "42"})["provider"] == "tidal"
    assert _library_file_row({"item_id": ""})["provider"] == ""
    assert _library_file_row({"length": 61})["duration"] == "1:01"


def test_the_second_page_appends_from_the_offset_the_section_holds(tmp_path, monkeypatch):
    bridge, _pathmap, _ids = _seed(tmp_path)
    monkeypatch.setattr("waves.waves_ui.backend._LIBRARY_PAGE", 2)
    bridge.loadLibraryFiles("all")
    assert bridge.libraryFilesLoaded.emits[0][1] and len(bridge.libraryFilesLoaded.emits[0][1]) == 2
    assert bridge.libraryFilesLoaded.emits[0][2] is True  # a third row waits
    assert bridge.libraryFilesLoaded.emits[0][3] == 3
    bridge.loadMoreLibraryFiles("all", 2)
    ((view, items, more, total),) = bridge.libraryFilesMore.emits
    assert (view, more, total) == ("all", False, -1)
    assert [r["title"] for r in items] == ["Tripped"]


def test_a_page_load_is_not_dropped_by_another_views_load(tmp_path):
    """One view's in-flight load never cancels another's (the #259 lesson):
    each view owns its own load counter."""
    bridge, _pathmap, _ids = _seed(tmp_path)
    bridge.loadLibraryFiles("saved")
    bridge.loadLibraryFiles("all")
    assert [(e[0], e[3]) for e in bridge.libraryFilesLoaded.emits] == [("saved", 2), ("all", 3)]


def test_a_reload_drops_the_first_pages_answer_in_flight(tmp_path):
    """A first page that was superseded (a scan publish reloaded the view)
    must not repaint the list it no longer describes."""
    bridge, _pathmap, _ids = _seed(tmp_path)
    held = []

    class _HeldPool:
        def start(self, worker, priority=0):
            held.append(worker)

    bridge.threadpool = _HeldPool()
    bridge.loadLibraryFiles("saved")
    bridge.loadLibraryFiles("saved")  # supersedes the first
    held[0].run()  # the stale worker lands first
    assert bridge.libraryFilesLoaded.emits == []
    held[1].run()
    assert [e[0] for e in bridge.libraryFilesLoaded.emits] == ["saved"]


def test_a_scan_that_loses_a_file_empties_its_saved_row(tmp_path):
    """The acceptance's moved-out file: after the rescan the file is gone from
    the scan, and the next page must not keep claiming it."""
    lib = os.path.join(tmp_path, "lib")
    kept = make_album_dir(lib, "A/Keep", ["01.flac"])
    moved = make_album_dir(lib, "B/Moved", ["01.flac"])
    pathmap = {
        os.path.join(kept, "01.flac"): _tags("Keep", title="Kept"),
        os.path.join(moved, "01.flac"): _tags("Moved", "B", title="Moved Away"),
    }
    item_ids = {os.path.join(moved, "01.flac"): "5"}
    bridge = make_library_bridge(tmp_path, library_folder=lib, path_tags=pathmap, item_ids=item_ids)
    bridge._library.refresh(lib, force_full=True)
    bridge.loadLibraryFiles("saved")
    assert [r["title"] for r in bridge.libraryFilesLoaded.emits[0][1]] == ["Moved Away"]

    outside = os.path.join(tmp_path, "elsewhere")
    os.makedirs(outside, exist_ok=True)
    os.replace(os.path.join(moved, "01.flac"), os.path.join(outside, "01.flac"))
    bridge._library.refresh(lib, force_full=True)
    bridge.loadLibraryFiles("saved")
    _view, items, _more, total = bridge.libraryFilesLoaded.emits[-1]
    assert items == [] and total == 0


def test_the_section_reads_the_scan_never_a_provider(tmp_path):
    """A signed-out pane still lists the library: the file slots must not
    consult a provider registry at all (this stub has none)."""
    bridge, _pathmap, _ids = _seed(tmp_path)
    assert not hasattr(bridge, "providers")
    bridge.loadLibraryFiles("saved")
    assert bridge.libraryFilesLoaded.emits[0][3] == 2


def test_an_unknown_view_defaults_to_saved(tmp_path):
    """QML reads the ids from myMusicLibrary(); anything else is a wiring bug
    and must not blank the section."""
    bridge, _pathmap, _ids = _seed(tmp_path)
    bridge.loadLibraryFiles("nonsense")
    assert [e[0] for e in bridge.libraryFilesLoaded.emits] == ["saved"]


def test_the_slots_survive_a_bridge_with_no_library_index(tmp_path):
    """The defensive path: no index object (a closed scan) answers empty
    instead of raising into QML."""
    bridge = make_library_bridge(tmp_path, library_folder=os.path.join(tmp_path, "lib"))
    bridge._library = None
    bridge.loadLibraryFiles("all")
    assert bridge.libraryFilesLoaded.emits == [("all", [], False, 0)]
    bridge.loadMoreLibraryFiles("all", 0)
    assert bridge.libraryFilesMore.emits == [("all", [], False, -1)]
