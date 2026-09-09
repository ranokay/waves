"""Provider-aware scan & badges (issue #36, spec §8).

The library scan reads the generic tag family first (legacy fallback) plus
WAVES_AUDIO_TYPE, with the codec sniff retired to a legacy fallback. Atmos
files attach as Versions to the canonical track set: album arithmetic counts
non-Atmos files, Atmos copies match within the album folder and its Atmos
subfolder, album cards earn an ATMOS TOO micro-badge, fully atmos-only tracks
stay their own canonical entries. Badge semantics split: IN LIBRARY /
PARTIALLY / MAYBE are scan-based and provider-blind (owning TIDAL badges the
Apple result); DOWNLOADED / HAVE / REDOWNLOAD are ownership-based, strictly
per-provider. Quarantined files never badge. Existing TIDAL-only libraries
scan identically after upgrade.
"""

from __future__ import annotations

import os

from waves import matching
from waves.library_index import LibraryIndex, _default_audio_type
from waves.ownership import OwnershipStore
from waves.waves_ui.backend import WavesBridge
from waves.waves_ui.bridge_library import _atmos_fragments, _atmos_parent


def _mk(base, rel, files):
    d = os.path.join(base, *rel.split("/"))
    os.makedirs(d, exist_ok=True)
    for name in files:
        open(os.path.join(d, name), "w").close()
    return d


def _tags(**over):
    base = {"album": "Album", "artist": "Artist", "date": "2024", "length": 200}
    base.update(over)
    return base


def _index(tmp_path, tagmap, audiomap=None):
    def read_tags(path):
        return tagmap.get(os.path.dirname(path))

    def read_audio_type(path):
        if audiomap is None:
            return "stereo"
        return audiomap.get(os.path.basename(path), "stereo")

    return LibraryIndex(
        str(tmp_path / "library.sqlite3"),
        read_tags=read_tags,
        read_audio_type=read_audio_type,
    )


def _presence_for(lib, placement=None):
    stub = type("S", (), {})()
    if placement is not None:
        stub._atmos_placement = lambda: _atmos_fragments(placement)
    return WavesBridge._build_presence_indexes(stub, lib)


# --------------------------------------------------------------------------- #
# The canonical set: Atmos copies attach, never count
# --------------------------------------------------------------------------- #
def test_atmos_twins_attach_and_never_count(tmp_path):
    lib = _mk(tmp_path, "lib", [])
    _mk(tmp_path, "lib/Artist/Album", ["01.flac", "02.flac", "03.flac", "01.m4a", "02.m4a"])

    # Per-file titles: each .m4a copy shares its twin's title.
    def read_tags(path):
        return _tags(
            title={
                "01.flac": "One",
                "02.flac": "Two",
                "03.flac": "Three",
                "01.m4a": "One",
                "02.m4a": "Two",
            }[os.path.basename(path)]
        )

    audiomap = {"01.m4a": "atmos", "02.m4a": "atmos"}
    idx = LibraryIndex(
        str(tmp_path / "library.sqlite3"),
        read_tags=read_tags,
        read_audio_type=lambda p: audiomap.get(os.path.basename(p), "stereo"),
    )
    assert idx.refresh(lib) == 1
    album = next(idx.iter_albums())
    assert album["tracks"] == 3
    assert album["has_atmos"] is True
    rows = list(idx.iter_tracks())
    assert len(rows) == 5
    by_title = {}
    for r in rows:
        by_title.setdefault(r["title"], []).append(r["audio_type"])
    assert sorted(by_title["One"]) == ["atmos", "stereo"]
    assert sorted(by_title["Two"]) == ["atmos", "stereo"]
    assert by_title["Three"] == ["stereo"]


def test_atmos_only_track_stays_its_own_canonical_entry(tmp_path):
    lib = _mk(tmp_path, "lib", [])
    _mk(tmp_path, "lib/Artist/Album", ["01.flac", "02.flac", "bonus.m4a"])

    def read_tags(path):
        return _tags(title={"01.flac": "One", "02.flac": "Two", "bonus.m4a": "Bonus"}[os.path.basename(path)])

    idx = LibraryIndex(
        str(tmp_path / "library.sqlite3"),
        read_tags=read_tags,
        read_audio_type=lambda p: "atmos" if p.endswith("bonus.m4a") else "stereo",
    )
    assert idx.refresh(lib) == 1
    album = next(idx.iter_albums())
    assert album["tracks"] == 3
    assert album["has_atmos"] is True


def test_all_atmos_folder_promotes_everything_and_reports_no_too(tmp_path):
    lib = _mk(tmp_path, "lib", [])
    _mk(tmp_path, "lib/Artist/Album", ["01.m4a", "02.m4a"])

    def read_tags(path):
        return _tags(title={"01.m4a": "One", "02.m4a": "Two"}[os.path.basename(path)])

    idx = LibraryIndex(
        str(tmp_path / "library.sqlite3"),
        read_tags=read_tags,
        read_audio_type=lambda p: "atmos",
    )
    assert idx.refresh(lib) == 1
    album = next(idx.iter_albums())
    assert album["tracks"] == 2
    assert album["has_atmos"] is False


def test_stereo_only_folder_reports_no_atmos(tmp_path):
    lib = _mk(tmp_path, "lib", [])
    d = _mk(tmp_path, "lib/Artist/Album", ["01.flac", "02.flac"])
    idx = _index(tmp_path, {d: _tags()})
    assert idx.refresh(lib) == 1
    album = next(idx.iter_albums())
    assert album["tracks"] == 2
    assert album["has_atmos"] is False


# --------------------------------------------------------------------------- #
# The Atmos subfolder folds into its parent
# --------------------------------------------------------------------------- #
def _album_tree(tmp_path):
    lib = _mk(tmp_path, "lib", [])
    parent = _mk(tmp_path, "lib/Artist/Album", ["01.flac", "02.flac", "03.flac"])
    sub = _mk(tmp_path, "lib/Artist/Album/Dolby Atmos", ["01.m4a", "02.m4a"])
    titles = {
        "01.flac": "One",
        "02.flac": "Two",
        "03.flac": "Three",
        "01.m4a": "One",
        "02.m4a": "Two",
    }

    def read_tags(path):
        return _tags(title=titles[os.path.basename(path)])

    def read_audio_type(path):
        return "atmos" if path.endswith(".m4a") else "stereo"

    idx = LibraryIndex(str(tmp_path / "library.sqlite3"), read_tags=read_tags, read_audio_type=read_audio_type)
    return lib, idx, parent, sub


def test_atmos_subfolder_folds_into_the_parent_album(tmp_path):
    lib, idx, parent, _sub = _album_tree(tmp_path)
    assert idx.refresh(lib) == 2  # both folders walked; the fold happens at the index
    local, _by_track = _presence_for(idx)
    key = matching.presence_key("Album", "Artist")
    assert key in local
    assert len(local[key]) == 1  # the subfolder is placement, not a second album
    assert local[key][0]["tracks"] == 3
    assert local[key][0]["has_atmos"] is True
    assert local[key][0]["id"] == parent
    verdict = matching.decide_presence("Album", "Artist", "2024", 3, local, 600)
    assert verdict["present"] is True
    assert verdict["local_tracks"] == 3
    assert verdict["has_atmos"] is True


def test_folded_atmos_tracks_answer_under_the_parent_release(tmp_path):
    lib, idx, parent, _sub = _album_tree(tmp_path)
    idx.refresh(lib)
    _, by_track = _presence_for(idx)
    verdict = matching.decide_track_presence("One", "Artist", by_track, "Album", "2024", 200)
    assert verdict["present"] is True
    assert verdict["sure"] is True
    assert verdict["local_album_id"] == parent


def test_atmos_only_bonus_in_the_subfolder_counts(tmp_path):
    lib = _mk(tmp_path, "lib", [])
    _mk(tmp_path, "lib/Artist/Album", ["01.flac", "02.flac"])
    _mk(tmp_path, "lib/Artist/Album/Dolby Atmos", ["bonus.m4a"])

    def read_tags(path):
        return _tags(title={"01.flac": "One", "02.flac": "Two", "bonus.m4a": "Bonus"}[os.path.basename(path)])

    idx = LibraryIndex(
        str(tmp_path / "library.sqlite3"),
        read_tags=read_tags,
        read_audio_type=lambda p: "atmos" if p.endswith(".m4a") else "stereo",
    )
    idx.refresh(lib)
    local, _ = _presence_for(idx)
    key = matching.presence_key("Album", "Artist")
    assert local[key][0]["tracks"] == 3
    assert local[key][0]["has_atmos"] is True


def test_subfolder_with_proven_stereo_stays_its_own_album(tmp_path):
    lib = _mk(tmp_path, "lib", [])
    _mk(tmp_path, "lib/Artist/Album", ["01.flac"])
    sub = _mk(tmp_path, "lib/Artist/Album/Dolby Atmos", ["01.flac"])

    def read_tags(path):
        if os.path.dirname(path) == sub:
            return _tags(album="Other Album", title="Other Song")
        return _tags(title="One")

    idx = LibraryIndex(
        str(tmp_path / "library.sqlite3"),
        read_tags=read_tags,
        read_audio_type=lambda p: "stereo",
    )
    idx.refresh(lib)
    local, _ = _presence_for(idx)
    assert matching.presence_key("Album", "Artist") in local
    # Somebody's real album under a borrowed name: left alone, not folded.
    assert matching.presence_key("Other Album", "Artist") in local


def test_multi_level_atmos_fragment_folds_to_the_album(tmp_path):
    """A configured multi-level fragment ("Surround/Dolby Atmos") resolves
    past its non-audio intermediates to the album, not to another level."""
    lib = _mk(tmp_path, "lib", [])
    parent = _mk(tmp_path, "lib/Artist/Album", ["01.flac", "02.flac"])
    _mk(tmp_path, "lib/Artist/Album/Surround/Dolby Atmos", ["01.m4a"])

    def read_tags(path):
        return _tags(title={"01.flac": "One", "02.flac": "Two", "01.m4a": "One"}[os.path.basename(path)])

    idx = LibraryIndex(
        str(tmp_path / "library.sqlite3"),
        read_tags=read_tags,
        read_audio_type=lambda p: "atmos" if p.endswith(".m4a") else "stereo",
    )
    idx.refresh(lib)
    local, _ = _presence_for(idx, placement="Surround/Dolby Atmos")
    key = matching.presence_key("Album", "Artist")
    assert len(local[key]) == 1
    assert local[key][0]["tracks"] == 2
    assert local[key][0]["has_atmos"] is True
    assert local[key][0]["id"] == parent


def test_atmos_parent_resolves_fragments():
    assert _atmos_parent("/lib/Artist/Album/Dolby Atmos", {("dolby atmos",)}) == "/lib/Artist/Album"
    assert _atmos_parent("/lib/Artist/Album/Surround/Dolby Atmos", {("surround", "dolby atmos")}) == (
        "/lib/Artist/Album"
    )
    assert _atmos_parent("/lib/Artist/Album/Surround/Dolby Atmos", {("dolby atmos",)}) == ("/lib/Artist/Album/Surround")
    assert _atmos_parent("/lib/Artist/Album", {("dolby atmos",)}) is None
    assert _atmos_parent("Dolby Atmos", {("dolby atmos",)}) is None
    assert _atmos_fragments("") == {("dolby atmos",)}
    assert _atmos_fragments("Surround/Dolby Atmos") == {("dolby atmos",), ("surround", "dolby atmos")}
    # Placeholder tokens render per album on disk: the literals still meet.
    frags = _atmos_fragments("{album_title} Atmos")
    assert _atmos_parent("/lib/Artist/Album/Discovery Atmos", frags) == "/lib/Artist/Album"
    assert _atmos_parent("/lib/Artist/Album/Discovery", frags) is None
    # Placeholders alone match nothing: no literals, no evidence-free fold.
    assert _atmos_parent("/lib/Artist/Album/2024", _atmos_fragments("{album_year}")) is None


def test_placeholder_fragment_folds_to_the_album(tmp_path):
    lib = _mk(tmp_path, "lib", [])
    parent = _mk(tmp_path, "lib/Artist/Discovery", ["01.flac"])
    _mk(tmp_path, "lib/Artist/Discovery/Discovery Atmos", ["01.m4a"])

    def read_tags(path):
        return _tags(album="Discovery", title="One")

    idx = LibraryIndex(
        str(tmp_path / "library.sqlite3"),
        read_tags=read_tags,
        read_audio_type=lambda p: "atmos" if p.endswith(".m4a") else "stereo",
    )
    idx.refresh(lib)
    local, _ = _presence_for(idx, placement="{album_title} Atmos")
    key = matching.presence_key("Discovery", "Artist")
    assert len(local[key]) == 1
    assert local[key][0]["tracks"] == 1
    assert local[key][0]["has_atmos"] is True
    assert local[key][0]["id"] == parent


def test_same_title_different_artist_never_attaches(tmp_path):
    """The twin key is (title, artist) like the track matcher: a same-titled
    Atmos Version by another artist is a different recording, its own
    canonical entry, counted."""
    lib = _mk(tmp_path, "lib", [])
    _mk(tmp_path, "lib/Artist/Album", ["a.flac", "b.m4a"])

    def read_tags(path):
        if os.path.basename(path) == "a.flac":
            return _tags(title="Song", track_artist="Artist A")
        return _tags(title="Song", track_artist="Artist B")

    idx = LibraryIndex(
        str(tmp_path / "library.sqlite3"),
        read_tags=read_tags,
        read_audio_type=lambda p: "atmos" if p.endswith(".m4a") else "stereo",
    )
    assert idx.refresh(lib) == 1
    album = next(idx.iter_albums())
    assert album["tracks"] == 2
    assert album["has_atmos"] is True


def test_all_unknown_subfolder_never_badges_atmos_too(tmp_path):
    """Folding needs positive evidence (§8.4): a subfolder whose rows predate
    Atmos capture ("", unknown) stays its own album for that one scan instead
    of badging ATMOS TOO on a guess. The backfill re-read classifies it next."""
    lib = _mk(tmp_path, "lib", [])
    _mk(tmp_path, "lib/Artist/Album", ["01.flac", "02.flac"])
    _mk(tmp_path, "lib/Artist/Album/Dolby Atmos", ["01.m4a", "02.m4a"])

    def read_tags(path):
        return _tags(title={"01.flac": "One", "02.flac": "Two"}.get(os.path.basename(path), "One"))

    idx = LibraryIndex(
        str(tmp_path / "library.sqlite3"),
        read_tags=read_tags,
        read_audio_type=lambda p: "stereo" if p.endswith(".flac") else "",
    )
    idx.refresh(lib)
    local, _ = _presence_for(idx)
    key = matching.presence_key("Album", "Artist")
    assert local[key][0]["has_atmos"] is False


# --------------------------------------------------------------------------- #
# Badge semantics I: IN LIBRARY is scan-based and provider-blind
# --------------------------------------------------------------------------- #
def test_tidal_copy_badges_the_apple_result_in_library(tmp_path):
    lib = _mk(tmp_path, "lib", [])
    d = _mk(tmp_path, "lib/Artist/Album", ["01.flac", "02.flac"])
    idx = _index(tmp_path, {d: _tags()})
    idx.refresh(lib)
    local, _ = _presence_for(idx)
    # The Apple search result names the same music, not the same provider row:
    # the scan matches by title and artist, whoever saved it.
    verdict = matching.decide_presence("Album", "Artist", "2024", 2, local, 400)
    assert verdict["present"] is True
    assert verdict["full"] is True


# --------------------------------------------------------------------------- #
# Badge semantics II: DOWNLOADED is ownership-based, strictly per-provider
# --------------------------------------------------------------------------- #
def _owned(tmp_path, name="song.flac"):
    p = tmp_path / name
    p.write_text("audio")
    return str(p)


def test_tidal_ownership_never_downloads_the_apple_row(tmp_path):
    store = OwnershipStore(str(tmp_path / "ownership.sqlite3"))
    store.record("tidal:123", _owned(tmp_path), "LOSSLESS")
    assert store.ownership_of("tidal:123") is not None
    assert store.ownership_of("apple:123") is None


def test_queue_have_marking_is_per_provider(tmp_path):
    store = OwnershipStore(str(tmp_path / "ownership.sqlite3"))
    store.record("tidal:123", _owned(tmp_path, "tidal.flac"), "LOSSLESS")
    store.record("apple:456", _owned(tmp_path, "apple.m4a"), "HIGH", audio_type="stereo")
    assert store.ownership_of("tidal:123") is not None
    assert store.ownership_of("apple:123") is None
    assert store.ownership_of("apple:456") is not None
    assert store.ownership_of("tidal:456") is None


# --------------------------------------------------------------------------- #
# Quarantine never badges; legacy libraries scan identically
# --------------------------------------------------------------------------- #
def test_quarantined_files_never_badge(tmp_path):
    lib = _mk(tmp_path, "lib", [])
    d = _mk(tmp_path, "lib/Waves Quarantine/Artist/Album", ["01.flac", "02.flac"])
    idx = _index(tmp_path, {d: _tags()})
    assert idx.refresh(lib) == 0
    local, by_track = _presence_for(idx)
    assert local == {}
    assert by_track == {}


def test_legacy_untagged_files_count_as_canonical(tmp_path):
    # Every library already on disk predates WAVES_AUDIO_TYPE: no tag, and an
    # empty file the codec sniff cannot read either. Unknown stays canonical,
    # so the upgrade changes no count.
    lib = _mk(tmp_path, "lib", [])
    _mk(tmp_path, "lib/Artist/Album", ["01.flac", "02.m4a", "03.mp3"])
    idx = LibraryIndex(str(tmp_path / "library.sqlite3"), read_tags=lambda p: _tags())
    assert idx.refresh(lib) == 1
    album = next(idx.iter_albums())
    assert album["tracks"] == 3
    assert album["has_atmos"] is False


def test_unreadable_audio_type_is_canonical_not_dropped():
    assert _default_audio_type("/nonexistent/song.m4a") is None
    assert _default_audio_type("/nonexistent/song.flac") == "stereo"
    assert _default_audio_type("/nonexistent/song.mp3") == "stereo"


def test_tag_answers_before_the_container_shape(monkeypatch):
    """Recognition never depends on codec sniffing (§8.1): the tag is read
    first on every extension, exactly like the download gate. A FLAC can
    never hold Atmos by codec, but a file Waves tagged still answers tag."""
    import waves.metadata as metadata

    monkeypatch.setattr(metadata, "read_audio_type", lambda path: "atmos")
    assert _default_audio_type("/nonexistent/song.flac") == "atmos"
    monkeypatch.setattr(metadata, "read_audio_type", lambda path: "stereo")
    assert _default_audio_type("/nonexistent/song.m4a") == "stereo"


def test_maybe_proof_and_arbiter_inputs_unchanged(tmp_path):
    # The verdict still carries both axes and the runtime witness MAYBE-proof
    # and the MusicBrainz arbiter read: this change adds has_atmos alongside,
    # never instead.
    lib = _mk(tmp_path, "lib", [])
    d = _mk(tmp_path, "lib/Artist/Album", ["01.flac", "02.flac"])
    idx = _index(tmp_path, {d: dict(_tags(), length=200)})
    idx.refresh(lib)
    local, _ = _presence_for(idx)
    verdict = matching.decide_presence("Album", "Artist", "", 0, local, 0)
    assert verdict["present"] is True
    assert verdict["sure"] is False  # unproven, the MAYBE case
    assert verdict["has_atmos"] is False
    assert verdict["local_runtime"] == 400
    missing = matching.decide_presence("Nope", "Nobody", "", 0, local, 0)
    assert missing == {
        "present": False,
        "partial": False,
        "sure": False,
        "full": False,
        "has_atmos": False,
        "local_album_id": "",
        "local_tracks": 0,
        "local_year": "",
        "local_declared": 0,
        "local_runtime": 0,
        "local_quality": "",
        "local_codec": "",
        "local_lossless": False,
        "local_bits": 0,
        "local_rate": 0,
        "local_class": "",
    }


def test_repeated_atmos_only_versions_count_once(tmp_path):
    """Two files of one atmos-only track (numbered per-provider copies
    sharing their tags) are one canonical entry: counting both inflates
    coverage toward a full claim over a partial copy."""
    lib = _mk(tmp_path, "lib", [])
    _mk(tmp_path, "lib/Artist/Album", ["song.m4a", "song (1).m4a"])

    def read_tags(path):
        return _tags(title="Song")

    idx = LibraryIndex(
        str(tmp_path / "library.sqlite3"),
        read_tags=read_tags,
        read_audio_type=lambda p: "atmos",
    )
    assert idx.refresh(lib) == 1
    album = next(idx.iter_albums())
    assert album["tracks"] == 1
    assert album["has_atmos"] is False
    assert len(list(idx.iter_tracks())) == 2


def test_repeated_atmos_only_versions_in_the_subfolder_count_once(tmp_path):
    lib = _mk(tmp_path, "lib", [])
    _mk(tmp_path, "lib/Artist/Album", ["01.flac"])
    _mk(tmp_path, "lib/Artist/Album/Dolby Atmos", ["bonus.m4a", "bonus (1).m4a"])

    def read_tags(path):
        name = os.path.basename(path)
        return _tags(title={"01.flac": "One"}.get(name, "Bonus"))

    idx = LibraryIndex(
        str(tmp_path / "library.sqlite3"),
        read_tags=read_tags,
        read_audio_type=lambda p: "atmos" if p.endswith(".m4a") else "stereo",
    )
    idx.refresh(lib)
    local, _ = _presence_for(idx)
    key = matching.presence_key("Album", "Artist")
    assert local[key][0]["tracks"] == 2
    assert local[key][0]["has_atmos"] is True


def test_unknown_audio_type_retries_the_folder(tmp_path):
    """A file whose tags read but whose Version probe fails persists
    unknown (""), never "stereo", and the folder re-reads on the next scan
    instead of believing the guess forever."""
    lib = _mk(tmp_path, "lib", [])
    _mk(tmp_path, "lib/Artist/Album", ["01.flac", "02.m4a"])
    calls: list[str] = []

    def read_tags(path):
        calls.append(path)
        return _tags(title=os.path.basename(path))

    idx = LibraryIndex(
        str(tmp_path / "library.sqlite3"),
        read_tags=read_tags,
        read_audio_type=lambda p: None if p.endswith("02.m4a") else "stereo",
    )
    assert idx.refresh(lib) == 1
    first_pass = len(calls)
    rows = {r["title"]: r["audio_type"] for r in idx.iter_tracks()}
    assert rows["02.m4a"] == ""
    assert rows["01.flac"] == "stereo"
    # Nothing changed on disk, yet the folder is owed a retry.
    idx.refresh(lib)
    assert len(calls) > first_pass


def test_classified_audio_type_settles_the_folder(tmp_path):
    """Once every file classifies, an unchanged folder is not re-read."""
    lib = _mk(tmp_path, "lib", [])
    _mk(tmp_path, "lib/Artist/Album", ["01.flac", "02.m4a"])
    calls: list[str] = []

    def read_tags(path):
        calls.append(path)
        return _tags(title=os.path.basename(path))

    idx = LibraryIndex(
        str(tmp_path / "library.sqlite3"),
        read_tags=read_tags,
        read_audio_type=lambda p: "atmos" if p.endswith(".m4a") else "stereo",
    )
    assert idx.refresh(lib) == 1
    first_pass = len(calls)
    idx.refresh(lib)
    assert len(calls) == first_pass
