"""The explicit-edition axis (UP-01): clean and explicit copies never vouch
for each other, on any surface.

Ports the removed v0.1.31 coverage (the audit's presence, merge-adjacent,
dressing and tag-truth pins) onto the restructured tree:

* the matcher weighs the advisory fact on the album and the track verdict,
  joins disc sets' facts, reads both TRACKTOTAL conventions, refuses
  cross-release disc joins and lone-disc self-completion;
* the scanner captures the fact (tags, folder vote, name-marker fallback),
  votes a blank album-artist across the folder, files compilations keyless,
  migrates old caches once and drops keys stamped by another normaliser;
* the bridge slots and both claim gates weigh the same flag, the album page
  header and the card dressing pass it, every QML asker sends it, and reveal
  shows a package-suffixed folder instead of running it.

Every test drives the real functions: the matcher on hand-built indexes, the
scanner on a temp tree with an injected tag reader, the bridge slots and
gates bound onto bare stubs. The whole design is biased against a FALSE "in
library", so several cases assert a verdict is deliberately withheld.
"""

from __future__ import annotations

import os
import pathlib
import re
import sqlite3
import sys
from types import SimpleNamespace

import pytest

import waves.metadata.matching as matching
from waves.desktop.bridge_library import LibraryMixin
from waves.library.index import (
    LibraryIndex,
    _advisory_word,
    _flat_set_declared,
    _marker_word,
    _primary_credit,
)
from waves.metadata.matching import (
    decide_presence,
    decide_track_presence,
    presence_key,
    track_key,
)


@pytest.fixture(autouse=True)
def _no_item_ids(monkeypatch):
    """Item ids are not what these tests are about: without this every folder
    owes a re-read for its NULL item ids, and the backfill tests cannot tell
    which fact caused the second read."""
    monkeypatch.setattr("waves.library.index._default_item_id", lambda path: "")


# ---- helpers ------------------------------------------------------------------


def _album_index(*entries):
    """A presence index from (title, artist, year, tracks, folder, extra)."""
    idx: dict = {}
    for title, artist, year, tracks, fp, extra in entries:
        idx.setdefault(presence_key(title, artist), []).append(
            {"title": title, "year": year, "tracks": tracks, "id": fp, **extra}
        )
    return idx


def _track_index(*entries):
    idx: dict = {}
    for title, artist, facts in entries:
        idx.setdefault(track_key(title, artist), []).append({"id": "/lib/A/Alb", "codec": "flac", **facts})
    return idx


def _mk(base, rel, files):
    d = os.path.join(base, *rel.split("/"))
    os.makedirs(d, exist_ok=True)
    for name in files:
        open(os.path.join(d, name), "w").close()
    return d


def _by_name(filemap):
    def read(path):
        return filemap.get(os.path.basename(path))

    return read


def _tags(album="Album", artist="A", **extra):
    return {"album": album, "artist": artist, "date": "2020", "title": "Song", **extra}


def _scan(tmp_path, rel, filemap, db="library.sqlite3"):
    lib = _mk(tmp_path, "lib", [])
    _mk(tmp_path, f"lib/{rel}", sorted(filemap))
    idx = LibraryIndex(
        str(tmp_path / db),
        read_tags=_by_name(filemap),
        read_audio_type=lambda path: "stereo",
    )
    idx.refresh(lib)
    return idx


# ---- the album verdict and the clean/explicit divide --------------------


def test_a_clean_copy_never_proves_the_explicit_release():
    idx = _album_index(("Album", "A", "2020", 10, "/m/A/Album", {"explicit": 0}))
    r = decide_presence("Album", "A", "2020", 10, idx, explicit=True)
    assert r["present"] is True, "the pill still lights: the user does hold the record"
    assert r["sure"] is False and r["partial"] is True, "but the bulk gate must not skip the other edition"


def test_an_explicit_copy_never_proves_the_clean_release():
    idx = _album_index(("Album", "A", "2020", 10, "/m/A/Album", {"explicit": 1}))
    r = decide_presence("Album", "A", "2020", 10, idx, explicit=False)
    assert r["present"] is True and r["sure"] is False and r["partial"] is True


@pytest.mark.parametrize("local,release", [(-1, True), (-1, False), (0, None), (1, None), (-1, None)])
def test_an_unknown_advisory_on_either_side_changes_nothing(local, release):
    idx = _album_index(("Album", "A", "2020", 10, "/m/A/Album", {"explicit": local}))
    r = decide_presence("Album", "A", "2020", 10, idx, explicit=release)
    assert r["sure"] is True and r["full"] is True and r["partial"] is False


def test_agreeing_advisory_facts_still_prove():
    idx = _album_index(("Album", "A", "2020", 10, "/m/A/Album", {"explicit": 1}))
    assert decide_presence("Album", "A", "2020", 10, idx, explicit=True)["partial"] is False
    idx = _album_index(("Album", "A", "2020", 10, "/m/A/Album", {"explicit": 0}))
    assert decide_presence("Album", "A", "2020", 10, idx, explicit=False)["partial"] is False


def test_a_row_from_before_the_fact_existed_reads_unknown():
    # No "explicit" key at all (an older index dict), and junk values.
    for extra in ({}, {"explicit": None}, {"explicit": "yes"}, {"explicit": 7}):
        idx = _album_index(("Album", "A", "2020", 10, "/m/A/Album", extra))
        assert decide_presence("Album", "A", "2020", 10, idx, explicit=True)["partial"] is False


def test_a_joined_set_is_explicit_when_any_disc_is():
    idx = _album_index(
        ("Album", "A", "2020", 10, "/m/A/Album/CD1", {"explicit": 0, "disc_no": 1, "disc_total": 2}),
        ("Album", "A", "2020", 10, "/m/A/Album/CD2", {"explicit": 1, "disc_no": 2, "disc_total": 2}),
    )
    assert decide_presence("Album", "A", "2020", 20, idx, explicit=False)["sure"] is False
    assert decide_presence("Album", "A", "2020", 20, idx, explicit=True)["partial"] is False


@pytest.mark.parametrize("clean_first", [True, False])
def test_the_edition_on_the_releases_side_is_chosen_whatever_the_row_order(clean_first):
    clean = ("Album", "A", "2020", 10, "/m/A/[2020] Album", {"explicit": 0})
    dirty = ("Album", "A", "2020", 10, "/m/A/[2020] Album (Explicit)", {"explicit": 1})
    idx = _album_index(*((clean, dirty) if clean_first else (dirty, clean)))
    r = decide_presence("Album", "A", "2020", 10, idx, explicit=True)
    assert r["sure"] is True and r["partial"] is False, "the user holds the explicit edition"
    assert r["local_album_id"] == "/m/A/[2020] Album (Explicit)", "and the reveal opens it"
    r = decide_presence("Album", "A", "2020", 10, idx, explicit=False)
    assert r["sure"] is True and r["local_album_id"] == "/m/A/[2020] Album"


def test_a_lone_other_edition_still_withholds_proof():
    idx = _album_index(("Album", "A", "2020", 10, "/m/A/Album", {"explicit": 0}))
    r = decide_presence("Album", "A", "2020", 10, idx, explicit=True)
    assert r["present"] is True and r["sure"] is False and r["local_explicit"] == 0


def test_the_edition_title_still_outranks_the_advisory_side():
    """Holding the standard clean and the deluxe explicit, the standard
    explicit release on screen is still matched against the standard copy
    (and so stays unproven), never against a different edition."""
    idx = _album_index(
        ("Album", "A", "2020", 10, "/m/A/Album", {"explicit": 0}),
        ("Album (Deluxe)", "A", "2020", 14, "/m/A/Album (Deluxe)", {"explicit": 1}),
    )
    r = decide_presence("Album", "A", "2020", 10, idx, explicit=True)
    assert r["local_album_id"] == "/m/A/Album" and r["sure"] is False


def test_an_unknown_flag_changes_nothing_about_the_choice():
    idx = _album_index(
        ("Album", "A", "2020", 10, "/m/A/one", {"explicit": 0}),
        ("Album", "A", "2020", 12, "/m/A/two", {"explicit": 1}),
    )
    assert decide_presence("Album", "A", "2020", 10, idx)["local_album_id"] == "/m/A/two", "the fuller copy, as before"


# ---- the track claim and the divide ---------------------------------------


def test_a_clean_file_never_proves_the_explicit_track():
    idx = _track_index(("Song", "A", {"album": "Album", "album_year": "2020", "length": 200, "explicit": 0}))
    r = decide_track_presence("Song", "A", idx, "Album", "2020", 201, explicit=True)
    assert r["present"] is True and r["sure"] is False


def test_an_explicit_file_never_proves_the_clean_track():
    idx = _track_index(("Song", "A", {"album": "Album", "album_year": "2020", "length": 200, "explicit": 1}))
    assert decide_track_presence("Song", "A", idx, "Album", "2020", 201, explicit=False)["sure"] is False


@pytest.mark.parametrize("local,want", [(-1, True), (0, None), (1, True), (0, False)])
def test_the_track_claim_is_unchanged_unless_both_sides_know_and_clash(local, want):
    idx = _track_index(("Song", "A", {"album": "Album", "album_year": "2020", "length": 200, "explicit": local}))
    assert decide_track_presence("Song", "A", idx, "Album", "2020", 201, explicit=want)["sure"] is True


# ---- disc joins and track totals ---------------------------------------


def test_a_complete_split_set_tagged_with_the_release_total_is_full():
    # Waves writes TRACKTOTAL=album.num_tracks on every file of every disc, so
    # Album/CD1 and Album/CD2 each declare 20. Summing read "20 OF 40".
    idx = _album_index(
        ("Album", "A", "2015", 10, "/m/A/Album/CD1", {"declared": 20, "disc_no": 1, "disc_total": 2}),
        ("Album", "A", "2015", 10, "/m/A/Album/CD2", {"declared": 20, "disc_no": 2, "disc_total": 2}),
    )
    r = decide_presence("Album", "A", "2015", 20, idx)
    assert r["local_tracks"] == 20 and r["sure"] is True and r["full"] is True and r["partial"] is False


def test_per_disc_totals_still_add_up():
    idx = _album_index(
        ("Album", "A", "2015", 10, "/m/A/Album/CD1", {"declared": 10, "disc_no": 1, "disc_total": 2}),
        ("Album", "A", "2015", 12, "/m/A/Album/CD2", {"declared": 12, "disc_no": 2, "disc_total": 2}),
    )
    r = decide_presence("Album", "A", "2015", 22, idx)
    assert r["local_declared"] == 22 and r["full"] is True


def test_equal_per_disc_totals_exceeded_by_the_files_add_up():
    idx = _album_index(
        ("Album", "A", "2015", 10, "/m/A/Album/CD1", {"declared": 10, "disc_no": 1, "disc_total": 2}),
        ("Album", "A", "2015", 10, "/m/A/Album/CD2", {"declared": 10, "disc_no": 2, "disc_total": 2}),
    )
    r = decide_presence("Album", "A", "2015", 20, idx)
    assert r["local_declared"] == 20 and r["full"] is True


def test_a_short_split_set_is_still_short_under_either_reading():
    idx = _album_index(
        ("Album", "A", "2015", 8, "/m/A/Album/CD1", {"declared": 20, "disc_no": 1, "disc_total": 2}),
        ("Album", "A", "2015", 7, "/m/A/Album/CD2", {"declared": 20, "disc_no": 2, "disc_total": 2}),
    )
    r = decide_presence("Album", "A", "2015", 0, idx)
    assert r["local_declared"] == 20 and r["full"] is False and r["partial"] is True


def test_an_ambiguous_complete_looking_set_needs_tidals_count():
    # Two half-held discs whose per-disc claims add up to exactly the files
    # held are indistinguishable from a complete release-wide set, so the set
    # declares nothing and cannot complete itself without a count on screen.
    idx = _album_index(
        ("Album", "A", "2015", 5, "/m/A/Album/CD1", {"declared": 10, "disc_no": 1, "disc_total": 2}),
        ("Album", "A", "2015", 5, "/m/A/Album/CD2", {"declared": 10, "disc_no": 2, "disc_total": 2}),
    )
    r = decide_presence("Album", "A", "2015", 0, idx)
    assert r["local_declared"] == 0 and r["full"] is False
    assert decide_presence("Album", "A", "2015", 20, idx)["full"] is False


def test_disc_siblings_from_two_releases_never_join():
    idx = _album_index(
        ("Album", "A", "2019", 10, "/m/A/Album (Disc 1)", {"disc_no": 1, "disc_total": 3}),
        ("Album", "A", "2019", 10, "/m/A/Album (Disc 2)", {"disc_no": 2, "disc_total": 2}),
    )
    r = decide_presence("Album", "A", "2019", 20, idx)
    assert r["local_tracks"] == 10 and r["full"] is False and r["partial"] is True


def test_disc_siblings_agreeing_on_the_total_still_join():
    idx = _album_index(
        ("Album", "A", "2019", 10, "/m/A/Album (Disc 1)", {"disc_no": 1, "disc_total": 2}),
        ("Album", "A", "2019", 10, "/m/A/Album (Disc 2)", {"disc_no": 2, "disc_total": 0}),
    )
    assert decide_presence("Album", "A", "2019", 20, idx)["local_tracks"] == 20


def test_a_lone_disc_of_a_set_cannot_complete_itself_without_a_count():
    idx = _album_index(
        ("Album", "A", "2010", 10, "/m/A/Album (Disc 1)", {"declared": 10, "disc_no": 1, "disc_total": 3}),
    )
    for tracks in (0, -1, None):
        r = decide_presence("Album", "A", "2010", tracks, idx)
        assert r["sure"] is True and r["full"] is False and r["partial"] is True, tracks
    assert decide_presence("Album", "A", "2010", 30, idx)["partial"] is True


def test_a_flat_set_in_one_folder_still_completes_itself():
    # disc_no 0 with disc_total 2 is the whole set sitting flat, not one disc.
    idx = _album_index(("Album", "A", "2010", 20, "/m/A/Album", {"declared": 20, "disc_no": 0, "disc_total": 2}))
    assert decide_presence("Album", "A", "2010", 0, idx)["partial"] is False


def test_a_single_disc_release_still_completes_itself():
    idx = _album_index(("Album", "A", "2010", 10, "/m/A/Album", {"declared": 10, "disc_no": 1, "disc_total": 1}))
    assert decide_presence("Album", "A", "2010", 0, idx)["partial"] is False


def test_flat_set_declared_reads_both_conventions():
    picard = [(1, 10)] * 10 + [(2, 10)] * 10
    assert _flat_set_declared(picard, 20) == 20
    waves_complete = [(1, 20)] * 10 + [(2, 20)] * 10
    assert _flat_set_declared(waves_complete, 20) == 0, "ambiguous: TIDAL's count decides"
    waves_short = [(1, 20)] * 8 + [(2, 20)] * 7
    assert _flat_set_declared(waves_short, 15) == 20
    unequal = [(1, 10)] * 10 + [(2, 12)] * 12
    assert _flat_set_declared(unequal, 22) == 22
    silent_disc = [(1, 10)] * 10 + [(2, 0)] * 10
    assert _flat_set_declared(silent_disc, 20) == 0
    split_disc = [(1, 10)] * 5 + [(1, 11)] * 5 + [(2, 10)] * 10
    assert _flat_set_declared(split_disc, 20) == 0


def test_a_flat_picard_set_declares_the_whole_release(tmp_path):
    names = [f"{i:02d}.flac" for i in range(1, 21)]
    filemap = {n: _tags(track_total=10, disc_no=1 if i < 10 else 2, disc_total=2) for i, n in enumerate(names)}
    idx = _scan(tmp_path, "A/Album", filemap)
    row = next(idx.iter_albums())
    assert row["tracks"] == 20 and row["disc_no"] == 0 and row["declared"] == 20
    r = decide_presence(
        "Album", "A", "2020", 20, {presence_key("Album", "A"): idx.presence_facts(presence_key("Album", "A"))}
    )
    assert r["sure"] is True and r["full"] is True and r["partial"] is False


def test_a_flat_waves_set_short_a_few_tracks_is_not_complete(tmp_path):
    names = [f"{i:02d}.flac" for i in range(1, 16)]
    filemap = {n: _tags(track_total=20, disc_no=1 if i < 8 else 2, disc_total=2) for i, n in enumerate(names)}
    idx = _scan(tmp_path, "A/Album", filemap)
    row = next(idx.iter_albums())
    assert row["declared"] == 20
    r = decide_presence("Album", "A", "2020", 0, {presence_key("Album", "A"): [row]})
    assert r["full"] is False


# ---- the album-artist vote ------------------------------------------------


def test_a_comp_without_an_album_artist_is_never_keyed_under_its_first_track(tmp_path):
    artists = ["Queen", "ABBA", "Blondie", "Cher", "Devo", "Eagles", "Foreigner", "Genesis", "Heart", "INXS"]
    filemap = {
        f"{i:02d}.flac": _tags("Greatest Hits", artist=a, albumartist="", track_artist=a) for i, a in enumerate(artists)
    }
    idx = _scan(tmp_path, "X/Greatest Hits", filemap)
    row = next(idx.iter_albums())
    assert matching.is_various_artists(row["artist"])
    assert idx.presence_facts(presence_key("Greatest Hits", "Queen")) == []
    assert decide_presence("Greatest Hits", "Queen", "2020", 10, {})["present"] is False
    # The files themselves still answer as their own artists' tracks.
    assert idx.track_facts(track_key("Song", "ABBA"))


def test_agreeing_track_artists_still_fill_a_blank_album_artist(tmp_path):
    named = ["Queen"] * 8 + ["Queen feat. David Bowie", "Queen; Freddie Mercury"]
    filemap = {
        f"{i:02d}.flac": _tags("Greatest Hits", artist=a, albumartist="", track_artist=a) for i, a in enumerate(named)
    }
    idx = _scan(tmp_path, "X/Greatest Hits", filemap)
    assert next(idx.iter_albums())["artist"] == "Queen"
    assert len(idx.presence_facts(presence_key("Greatest Hits", "Queen"))) == 1


def test_one_stray_credit_does_not_unkey_an_album(tmp_path):
    named = ["Queen"] * 9 + ["Brian May"]
    filemap = {
        f"{i:02d}.flac": _tags("Greatest Hits", artist=a, albumartist="", track_artist=a) for i, a in enumerate(named)
    }
    assert next(_scan(tmp_path, "X/Greatest Hits", filemap).iter_albums())["artist"] == "Queen"


def test_a_set_album_artist_is_believed_over_the_track_credits(tmp_path):
    artists = ["Queen", "ABBA", "Blondie", "Cher"]
    filemap = {
        f"{i:02d}.flac": _tags("Greatest Hits", artist="Now", albumartist="Now", track_artist=a)
        for i, a in enumerate(artists)
    }
    assert next(_scan(tmp_path, "X/Greatest Hits", filemap).iter_albums())["artist"] == "Now"


def test_a_compilation_flag_files_the_folder_as_various_artists(tmp_path):
    filemap = {f"{i:02d}.flac": _tags("Greatest Hits", artist="Queen", compilation=True) for i in range(10)}
    row = next(_scan(tmp_path, "X/Greatest Hits", filemap).iter_albums())
    assert matching.is_various_artists(row["artist"])


def test_a_reader_that_never_reports_the_album_artist_keeps_the_old_fallback(tmp_path):
    filemap = {f"{i:02d}.flac": _tags("Greatest Hits", artist="Queen") for i in range(3)}
    assert next(_scan(tmp_path, "X/Greatest Hits", filemap).iter_albums())["artist"] == "Queen"


@pytest.mark.parametrize("collab", ["Jay-Z & Kanye West", "Jay-Z, Beyonce", "Jay-Z x Future", "Jay-Z with Rihanna"])
def test_collaborations_led_by_the_artist_keep_the_album_keyed(tmp_path, collab):
    named = ["Jay-Z"] * 9 + [collab] * 3
    filemap = {f"{i:02d}.flac": _tags("Album", artist=a, albumartist="", track_artist=a) for i, a in enumerate(named)}
    idx = _scan(tmp_path, "X/Album", filemap)
    row = next(idx.iter_albums())
    assert not matching.is_various_artists(row["artist"]), collab
    assert idx.presence_facts(presence_key("Album", "Jay-Z")), "the album still answers for its artist"


def test_a_collaboration_sorting_first_still_agrees_with_the_rest(tmp_path):
    named = ["Jay-Z & Kanye West"] * 3 + ["Jay-Z"] * 9
    filemap = {f"{i:02d}.flac": _tags("Album", artist=a, albumartist="", track_artist=a) for i, a in enumerate(named)}
    assert not matching.is_various_artists(next(_scan(tmp_path, "X/Album", filemap).iter_albums())["artist"])


def test_a_compilation_of_collaborations_still_goes_keyless(tmp_path):
    named = ["Queen & David Bowie", "ABBA", "Blondie x Cher", "Devo, Eagles", "Genesis with Heart", "INXS"] * 2
    filemap = {
        f"{i:02d}.flac": _tags("Greatest Hits", artist=a, albumartist="", track_artist=a) for i, a in enumerate(named)
    }
    idx = _scan(tmp_path, "X/Greatest Hits", filemap)
    assert matching.is_various_artists(next(idx.iter_albums())["artist"])
    assert idx.presence_facts(presence_key("Greatest Hits", "Queen & David Bowie")) == []


def test_the_primary_credit_is_the_first_name():
    assert _primary_credit("jay-z and kanye west") == "jay-z"
    assert _primary_credit("drake x future") == "drake"
    assert _primary_credit("malcolm x") == "malcolm x", "a trailing x names no second artist"
    assert _primary_credit("queen") == "queen"


# ---- the scanner's advisory fact ------------------------------------------------


def test_advisory_values_read_the_itunes_convention():
    assert [_advisory_word(v) for v in ("1", "4", "2", "0", " 1 ", "", "x", None)] == [1, 1, 0, 0, 1, -1, -1, -1]


def test_name_markers_only_ever_fall_back():
    assert _marker_word("[2020] Album (Explicit)") == 1
    assert _marker_word("Album [E]") == 1
    assert _marker_word("Album", "Album (Clean)") == 0
    assert _marker_word("Album", "Album") == -1


@pytest.mark.parametrize(
    "per_file,folder,expected",
    [
        ([1, 1, 1], "Album", 1),
        ([0, 0, 0], "Album", 0),
        ([0, 1, 0], "Album", 1),  # one explicit cut makes the explicit release
        ([-1, -1, -1], "Album (Explicit)", 1),  # the files never said: Waves' folder marker
        ([-1, -1, -1], "Album", -1),
        ([0, 0, -1], "Album (Explicit)", 0),  # the files outrank the name
    ],
)
def test_the_folder_records_its_files_advisory_fact(tmp_path, per_file, folder, expected):
    names = [f"{i:02d}.flac" for i in range(len(per_file))]
    filemap = {n: _tags(explicit=e) for n, e in zip(names, per_file, strict=True)}
    idx = _scan(tmp_path, f"A/{folder}", filemap)
    assert next(idx.iter_albums())["explicit"] == expected
    assert idx.presence_facts(presence_key("Album", "A"))[0]["explicit"] == expected
    facts = idx.track_facts(track_key("Song", "A"))
    assert sorted(f["explicit"] for f in facts) == sorted(per_file)
    assert sorted(t["explicit"] for t in idx.iter_tracks()) == sorted(per_file)


def test_a_mixed_folder_declares_no_advisory_fact(tmp_path):
    names = [f"{i:02d}.flac" for i in range(12)]
    filemap = {n: _tags(explicit=1) for n in names}
    filemap["11.flac"] = _tags("Other", explicit=0)
    idx = _scan(tmp_path, "A/Album", filemap)
    assert next(idx.iter_albums())["explicit"] == -1


def test_a_cache_from_before_the_advisory_fact_rereads_once(tmp_path):
    lib = _mk(tmp_path, "lib", [])
    d = _mk(tmp_path, "lib/A/Album", ["01.flac", "02.flac"])
    reads: list = []

    def read(path):
        reads.append(path)
        return _tags(explicit=1) if os.path.dirname(path) == d else None

    db = str(tmp_path / "library.sqlite3")
    idx = LibraryIndex(db, read_tags=read, read_audio_type=lambda path: "stereo")
    idx.refresh(lib)
    assert next(idx.iter_albums())["explicit"] == 1
    idx.close()
    conn = sqlite3.connect(db)  # rewind the row to its pre-migration state
    conn.execute("UPDATE albums SET explicit = NULL")
    conn.commit()
    conn.close()
    reads.clear()
    aged = LibraryIndex(db, read_tags=read, read_audio_type=lambda path: "stereo")
    aged.refresh(lib)
    assert reads, "an unread row must not stay unread behind an unchanged mtime"
    assert next(aged.iter_albums())["explicit"] == 1
    reads.clear()
    aged.refresh(lib)
    assert not reads, "once read, the fact rests like every other column"


# ---- the key normaliser version -----------------------------------------


def test_keys_derived_by_another_normaliser_are_rebuilt_once(tmp_path):
    lib = _mk(tmp_path, "lib", [])
    d = _mk(tmp_path, "lib/A/Album", ["01.flac"])
    tags = {d: _tags()}
    db = str(tmp_path / "library.sqlite3")
    idx = LibraryIndex(db, read_tags=lambda p: tags.get(os.path.dirname(p)), read_audio_type=lambda p: "stereo")
    idx.refresh(lib)
    assert idx.presence_facts(presence_key("Album", "A")) and idx.keys_missing() == 0
    idx.close()

    conn = sqlite3.connect(db)
    conn.execute("UPDATE meta SET value = 'stale' WHERE key = 'key_normaliser_version'")
    # A key the running normaliser would never derive, standing in for one
    # an older release stored.
    conn.execute("UPDATE albums SET pkey_title = 'old-title-key'")
    conn.commit()
    conn.close()

    reopened = LibraryIndex(db, read_tags=lambda p: tags.get(os.path.dirname(p)), read_audio_type=lambda p: "stereo")
    assert reopened.keys_missing() > 0, "the stale keys are dropped at open"
    assert reopened.presence_facts(presence_key("Album", "A")) == []
    reopened.backfill_keys()
    assert reopened.presence_facts(presence_key("Album", "A")), "and rebuilt from the raw tags"
    assert reopened.keys_missing() == 0
    reopened.close()

    again = LibraryIndex(db, read_tags=lambda p: tags.get(os.path.dirname(p)), read_audio_type=lambda p: "stereo")
    assert again.keys_missing() == 0, "the same version never drops the keys again"


def test_a_cache_that_never_stamped_a_version_is_rekeyed_once(tmp_path):
    lib = _mk(tmp_path, "lib", [])
    d = _mk(tmp_path, "lib/A/Album", ["01.flac"])
    tags = {d: _tags()}
    db = str(tmp_path / "library.sqlite3")
    idx = LibraryIndex(db, read_tags=lambda p: tags.get(os.path.dirname(p)), read_audio_type=lambda p: "stereo")
    idx.refresh(lib)
    idx.close()
    conn = sqlite3.connect(db)
    conn.execute("DELETE FROM meta WHERE key = 'key_normaliser_version'")
    conn.commit()
    conn.close()
    reopened = LibraryIndex(db, read_tags=lambda p: tags.get(os.path.dirname(p)), read_audio_type=lambda p: "stereo")
    assert reopened.keys_missing() > 0
    reopened.refresh(lib)  # the scan's own backfill pass
    assert reopened.keys_missing() == 0 and reopened.presence_facts(presence_key("Album", "A"))


# ---- an old prune marker sweeps once more -----------------------------------


def _recycled_cache(tmp_path, marker):
    lib = _mk(tmp_path, "lib", [])
    real = _mk(tmp_path, "lib/A/[2020] Alpha", ["01.flac"])
    tags = {real: {"album": "Alpha", "artist": "A", "date": "2020"}}
    db = str(tmp_path / "library.sqlite3")

    def read(p):
        return tags.get(os.path.dirname(p))

    idx = LibraryIndex(db, read_tags=read, read_audio_type=lambda p: "stereo")
    assert idx.refresh(lib) == 1
    idx.close()
    # What an earlier build left behind on a Windows drive root: an album
    # deleted in Explorer, indexed inside the NTFS bin before the rule folded,
    # in a cache already marked swept by that earlier rule.
    binned = os.path.join(lib, "$Recycle.Bin", "S-1-5-21-1", "$R1ABC")
    conn = sqlite3.connect(db)
    (gen,) = conn.execute("SELECT MAX(seen_gen) FROM dirs").fetchone()
    conn.execute(
        "INSERT INTO dirs (path, parent, mtime, listed, is_album, seen_gen) VALUES (?, ?, 0, 1, 1, ?)",
        (binned, os.path.dirname(binned), gen),
    )
    conn.execute("INSERT INTO albums (folder_path, album, artist, year) VALUES (?, 'Gone', 'A', '2019')", (binned,))
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('skipped_dirs_pruned', ?)", (marker,))
    conn.commit()
    conn.close()
    return db, read, binned


def test_a_cache_marked_by_the_older_rule_drops_its_recycled_albums(tmp_path):
    db, read, binned = _recycled_cache(tmp_path, "1")
    reopened = LibraryIndex(db, read_tags=read, read_audio_type=lambda p: "stereo")
    assert [x["title"] for x in reopened.iter_albums()] == ["Alpha"], "the real album stays, the recycled one goes"
    with reopened._lock:
        assert reopened._conn.execute("SELECT COUNT(*) FROM dirs WHERE path = ?", (binned,)).fetchone() == (0,)
        (marker,) = reopened._conn.execute("SELECT value FROM meta WHERE key = 'skipped_dirs_pruned'").fetchone()
    assert marker != "1", "restamped, so the sweep runs once"
    reopened.close()


def test_a_cache_marked_by_the_current_rule_is_not_swept_again(tmp_path):
    db, read, _binned = _recycled_cache(tmp_path, "1")
    LibraryIndex(db, read_tags=read, read_audio_type=lambda p: "stereo").close()
    conn = sqlite3.connect(db)
    (marker,) = conn.execute("SELECT value FROM meta WHERE key = 'skipped_dirs_pruned'").fetchone()
    # A row planted AFTER the current rule's sweep stays until a scan says
    # otherwise: the open-time sweep is once per rule, not every launch.
    late = os.path.join(str(tmp_path / "lib"), "$Recycle.Bin", "S-1-5-21-1", "$R2DEF")
    (gen,) = conn.execute("SELECT MAX(seen_gen) FROM dirs").fetchone()
    conn.execute(
        "INSERT INTO dirs (path, parent, mtime, listed, is_album, seen_gen) VALUES (?, ?, 0, 1, 1, ?)",
        (late, os.path.dirname(late), gen),
    )
    conn.commit()
    conn.close()
    again = LibraryIndex(db, read_tags=read, read_audio_type=lambda p: "stereo")
    with again._lock:
        assert again._conn.execute("SELECT COUNT(*) FROM dirs WHERE path = ?", (late,)).fetchone() == (1,)
        assert again._conn.execute("SELECT value FROM meta WHERE key = 'skipped_dirs_pruned'").fetchone() == (marker,)
    again.close()


# ---- the bridge gates -----------------------------------------------------------


class _GateStub:
    _library_track_claim = LibraryMixin._library_track_claim
    _library_claims_track = LibraryMixin._library_claims_track
    _library_claims_album = LibraryMixin._library_claims_album

    def __init__(self, albums=None, tracks=None):
        self._library_index = albums
        self._library_track_index = tracks


def _clean_track_stub():
    return _GateStub(
        tracks=_track_index(("Song", "A", {"album": "Album", "album_year": "2020", "length": 200, "explicit": 0}))
    )


def test_the_track_gate_refuses_the_other_cut():
    s = _clean_track_stub()
    assert s._library_track_claim("A", "Song", "Album", "2020", 200, True) is None
    assert s._library_claims_track("A", "Song", "Album", "2020", 200, True) is False


def test_the_track_gate_is_unchanged_without_a_flag():
    s = _clean_track_stub()
    assert s._library_track_claim("A", "Song", "Album", "2020", 200) is not None
    assert s._library_track_claim("A", "Song", "Album", "2020", 200, None) is not None
    assert s._library_track_claim("A", "Song", "Album", "2020", 200, False) is not None
    assert s._library_track_claim("A", "Song", "Album", "2020", 200, "garbage") is not None


def _album(**kw):
    base = {"name": "Album", "artist": SimpleNamespace(name="A"), "year": 2020, "num_tracks": 10}
    base.update(kw)
    return SimpleNamespace(**base)


def test_the_album_gate_refuses_the_other_edition_only_when_tidal_said():
    s = _GateStub(albums=_album_index(("Album", "A", "2020", 10, "/m/A/Album", {"explicit": 0})))
    assert s._library_claims_album(_album(explicit=True)) is False
    assert s._library_claims_album(_album(explicit=False)) is True
    # tidalapi leaves the flag None when the payload carried none, and an
    # older Album object has no attribute at all: neither is a claim.
    assert s._library_claims_album(_album(explicit=None)) is True
    assert s._library_claims_album(_album()) is True


def test_a_caller_vouched_flag_wins_over_the_release_flag():
    s = _GateStub(albums=_album_index(("Album", "A", "2020", 10, "/m/A/Album", {"explicit": 0})))
    assert s._library_claims_album(_album(explicit=True), explicit=False) is True
    assert s._library_claims_album(_album(explicit=None), explicit=True) is False


def test_release_explicit_only_passes_a_real_bool():
    f = LibraryMixin._release_explicit
    assert f(_album(explicit=True)) is True and f(_album(explicit=False)) is False
    assert f(_album(explicit=None)) is None and f(_album(explicit=1)) is None and f(_album()) is None
    assert f(_album(explicit=True), explicit=False) is False and f(None) is None


def test_an_old_stub_without_a_flag_still_binds_the_album_gate():
    s = _GateStub(albums=_album_index(("Album", "A", "2020", 10, "/m/A/Album", {})))
    assert s._library_claims_album(_album(explicit=True)) is True, "an unknown local fact changes nothing"


# ---- the presence slots -----------------------------------------------------------


class _SlotStub:
    libraryAlbumPresence = LibraryMixin.libraryAlbumPresence
    libraryTrackPresence = LibraryMixin.libraryTrackPresence
    _mb_arbitrated = LibraryMixin._mb_arbitrated

    def __init__(self, albums=None, tracks=None):
        self._library_index = albums
        self._library_track_index = tracks
        self._presence_memo = {}
        self._presence_memo_src = None
        self._track_presence_memo = {}
        self._track_presence_memo_src = None

    def _library_probe_miss(self, artist):
        pass

    def _waves_pref_bool(self, key):
        return False


def _slot_index(tmp_path, explicit):
    """A scanned single-album library as the slot's dict indexes."""
    filemap = {f"{i}.flac": _tags(explicit=explicit) for i in range(1, 4)}
    idx = _scan(tmp_path, "A/Album", filemap)
    local: dict = {}
    for a in idx.iter_albums():
        local.setdefault(presence_key(a["title"], a["artist"]), []).append(a)
    by_track: dict = {}
    for t in idx.iter_tracks():
        by_track.setdefault(track_key(t["title"], t["artist"]), []).append(t)
    return _SlotStub(albums=local, tracks=by_track)


def test_the_album_pill_does_not_vouch_for_the_other_edition(tmp_path):
    s = _slot_index(tmp_path, explicit=0)
    assert s.libraryAlbumPresence("A", "Album", "2020", 3)["sure"] is True, "no flag: as before"
    clash = s.libraryAlbumPresence("A", "Album", "2020", 3, 0, 1)
    assert clash["present"] is True and clash["sure"] is False, "the explicit release is not the clean copy"
    assert s.libraryAlbumPresence("A", "Album", "2020", 3, 0, 0)["sure"] is True
    assert s.libraryAlbumPresence("A", "Album", "2020", 3, 0, -1)["sure"] is True, "-1 is unknown"


def test_the_album_pill_and_the_bulk_gate_agree(tmp_path):
    s = _slot_index(tmp_path, explicit=0)
    album = SimpleNamespace(name="Album", artist=SimpleNamespace(name="A"), year=2020, num_tracks=3, duration=0)
    for flag in (True, False):
        album.explicit = flag
        pill = s.libraryAlbumPresence("A", "Album", "2020", 3, 0, 1 if flag else 0)
        gate = LibraryMixin._library_claims_album(s, album)
        assert gate == (pill["present"] and not pill["partial"]), flag


def test_the_album_memo_is_keyed_by_the_flag(tmp_path, monkeypatch):
    s = _slot_index(tmp_path, explicit=0)
    calls = []
    real = matching.decide_presence
    monkeypatch.setattr(matching, "decide_presence", lambda *a, **k: calls.append(a[-1]) or real(*a, **k))
    first = s.libraryAlbumPresence("A", "Album", "2020", 3, 0, 1)
    second = s.libraryAlbumPresence("A", "Album", "2020", 3, 0, 0)
    assert first["sure"] is False and second["sure"] is True, "one flag's verdict never answers for the other"
    s.libraryAlbumPresence("A", "Album", "2020", 3, 0, 1)
    assert calls == [True, False], "the same flag is answered from the memo"


def test_no_second_opinion_may_swear_the_other_edition_is_this_one(tmp_path):
    s = _slot_index(tmp_path, explicit=0)
    asked = []
    s._mb_arbitrated = lambda verdict, *a: asked.append(1) or dict(verdict, sure=True)
    assert s.libraryAlbumPresence("A", "Album", "2020", 3, 0, 1)["sure"] is False
    assert asked == [], "a known clash never reaches the overlay"
    s.libraryAlbumPresence("A", "Other", "2020", 3, 0, 1)
    s.libraryAlbumPresence("A", "Album", "2019", 5, 0, -1)
    assert asked, "an unknown flag still reaches it"


def test_the_track_pill_does_not_vouch_for_the_other_cut(tmp_path):
    s = _slot_index(tmp_path, explicit=0)
    assert s.libraryTrackPresence("A", "Song", "Album", "2020", 0)["sure"] is True, "no flag: as before"
    clash = s.libraryTrackPresence("A", "Song", "Album", "2020", 0, 1)
    assert clash["present"] is True and clash["sure"] is False
    assert s.libraryTrackPresence("A", "Song", "Album", "2020", 0, 0)["sure"] is True
    # The claim face and the claim gate reach the same verdict.
    assert LibraryMixin._library_track_claim(s, "A", "Song", "Album", "2020", 0, True) is None
    assert LibraryMixin._library_track_claim(s, "A", "Song", "Album", "2020", 0, False) is not None


def test_the_advisory_flag_reads_only_a_real_answer():
    f = LibraryMixin._advisory_flag
    assert f(1) is True and f(0) is False and f(True) is True and f(False) is False
    assert f(-1) is None and f(2) is None and f(None) is None and f("1") is None


def test_the_slots_keep_every_older_overload():
    import inspect

    album = inspect.signature(LibraryMixin.libraryAlbumPresence).parameters
    track = inspect.signature(LibraryMixin.libraryTrackPresence).parameters
    assert album["explicit"].default == -1 and track["explicit"].default == -1


# ---- the card dressing passes the flag ------------------------------------------------


def test_a_dressed_card_and_the_live_ask_agree_on_the_other_edition(tmp_path):
    """Only the clean copy on disk, the explicit release on screen: the
    verdict baked for first render, the one a publish asks for live (the QML
    passes 1 for an explicit card) and the bulk gate all refuse to vouch."""
    from waves.desktop.backend import WavesBridge

    s = _slot_index(tmp_path, explicit=0)
    s._CARD_DRESS_KINDS = WavesBridge._CARD_DRESS_KINDS
    s.collectionOwnership = lambda _id: False
    card = {
        "kind": "album",
        "id": "al-1",
        "title": "Album",
        "artist": "A",
        "year": "2020",
        "tracks": 3,
        "duration_sec": 0,
        "explicit": True,
    }
    baked = WavesBridge._dress_card(s, card)["lib"]
    live = s.libraryAlbumPresence("A", "Album", "2020", 3, 0, 1)
    assert baked == live, "the baked verdict and the live ask disagree"
    assert baked["present"] is True and baked["sure"] is False, "the pill vouched for the clean copy"
    album = SimpleNamespace(
        name="Album", artist=SimpleNamespace(name="A"), year=2020, num_tracks=3, duration=0, explicit=True
    )
    assert LibraryMixin._library_claims_album(s, album) == (baked["present"] and not baked["partial"])


def test_a_dressed_card_with_an_unknown_flag_answers_as_before(tmp_path):
    """An album dict's False may be TIDAL saying nothing, so it is never read
    as clean: the card answers exactly as the flagless ask did."""
    from waves.desktop.backend import WavesBridge

    s = _slot_index(tmp_path, explicit=1)
    s._CARD_DRESS_KINDS = WavesBridge._CARD_DRESS_KINDS
    s.collectionOwnership = lambda _id: False
    before = s.libraryAlbumPresence("A", "Album", "2020", 3, 0)
    assert before["sure"] is True
    assert WavesBridge._dress_card(s, {**_album_card(False)})["lib"] == before, "a missing flag was read as clean"
    card = _album_card(False)
    del card["explicit"]
    assert WavesBridge._dress_card(s, card)["lib"] == before, "a payload cached before the flag existed"


def _album_card(explicit):
    # The shape _album_dict emits: its explicit is bool(Album.explicit), so a
    # flag TIDAL never sent arrives here as False.
    return {
        "kind": "album",
        "id": "al-1",
        "title": "Album",
        "artist": "A",
        "year": "2020",
        "tracks": 3,
        "duration_sec": 0,
        "explicit": explicit,
    }


def test_the_card_flag_is_1_or_unknown_never_clean():
    from waves.desktop.backend import _album_card_flag

    assert _album_card_flag({"explicit": True}) == 1
    assert _album_card_flag({"explicit": False}) == -1, "False may be TIDAL saying nothing"
    assert _album_card_flag({}) == -1


# ---- every QML asker passes the flag ------------------------------------------------


def _call_args(src, name):
    """The top-level argument lists of every ``waves.<name>(...)`` call."""
    out = []
    for m in re.finditer(r"waves\." + name + r"\(", src):
        depth, i, args, cur = 1, m.end(), [], ""
        while depth:
            ch = src[i]
            depth += ch in "([{"
            depth -= ch in ")]}"
            if ch == "," and depth == 1:
                args.append(cur.strip())
                cur = ""
            elif depth:
                cur += ch
            i += 1
        out.append([*args, cur.strip()])
    return out


def test_every_qml_presence_ask_passes_the_flag():
    """A QML asker left on the five-argument overload asks as if the flag
    were unknown and so vouches for the other edition the gate refuses."""
    qml_dir = pathlib.Path(__file__).resolve().parents[2] / "waves" / "desktop" / "qml"
    checked = 0
    for path in sorted(qml_dir.glob("*.qml")):
        src = path.read_text(encoding="utf-8")
        for name in ("libraryAlbumPresence", "libraryTrackPresence"):
            for args in _call_args(src, name):
                assert len(args) == 6 and "explicit" in args[5], (path.name, name, args)
                checked += 1
    assert checked > 0, "no QML presence asks found"


# ---- the album page header carries the gate's flag ------------------------------------------------


def _page_stub(album=None, playlist=None):
    from waves.desktop.backend import CTX_TIDAL

    obj = album if album is not None else playlist
    kind = "album" if album is not None else "playlist"

    def get_object(_kind, _media_id, _obj=obj):
        return _obj

    b = SimpleNamespace()
    b.providers = {CTX_TIDAL: SimpleNamespace(get_object=get_object, collection_items=lambda o, **k: [])}
    b._objs = {"album": {}, "playlist": {}, "mix": {}}

    def remember(_kind, _media_id, _obj, _store=b._objs):
        _store[_kind][_media_id] = _obj

    b._remember = remember
    b._track_dict = lambda t: {}
    b._record_page_members = lambda payload: None
    return b, kind


def test_the_album_page_header_carries_the_gates_flag():
    from waves.desktop.backend import WavesBridge

    for flag in (True, False, None):
        album = SimpleNamespace(id="5", name="Album", artist=SimpleNamespace(name="A"), year=2020)
        album.tracks = lambda limit=200: []
        album.explicit = flag
        b, _kind = _page_stub(album=album)
        payload = WavesBridge._build_browse_item(b, "album", "5", "album:5")
        assert payload["header"]["explicit"] is LibraryMixin._release_explicit(album) is flag


def test_only_an_album_page_names_a_release():
    from waves.desktop.backend import WavesBridge

    playlist = SimpleNamespace(id="p", name="Mix", sub_title="Mix")
    playlist.tracks = lambda limit=200: []
    playlist.items = lambda limit=100, offset=0: []
    b, _kind = _page_stub(playlist=playlist)
    payload = WavesBridge._build_browse_item(b, "playlist", "p", "playlist:p")
    assert payload["header"]["explicit"] is None, "only an album page names a release"


# ---- reveal, do not open ----------------------------------------------------


def _reveal(monkeypatch, platform, target):
    popen: list = []
    opened: list = []
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr("waves.desktop.bridge_library.subprocess.Popen", lambda argv, **kw: popen.append((argv, kw)))
    from PySide6 import QtGui

    monkeypatch.setattr(QtGui.QDesktopServices, "openUrl", lambda url: opened.append(url.toLocalFile()))
    LibraryMixin._reveal_in_file_manager(str(target))
    return popen, opened


def test_macos_reveals_the_item_in_its_parent_without_a_shell(tmp_path, monkeypatch):
    bundle = tmp_path / "Artist" / "Album.app"
    bundle.mkdir(parents=True)
    popen, opened = _reveal(monkeypatch, "darwin", bundle)
    assert popen == [(["/usr/bin/open", "-R", str(bundle)], {})], "a fixed argument list, nothing launched"
    assert opened == []


def test_macos_reveals_a_plain_album_folder_the_same_way(tmp_path, monkeypatch):
    folder = tmp_path / "Artist" / "[2020] Album"
    folder.mkdir(parents=True)
    popen, opened = _reveal(monkeypatch, "darwin", folder)
    assert popen[0][0] == ["/usr/bin/open", "-R", str(folder)] and opened == []


def test_a_failed_finder_reveal_falls_back_to_showing_the_parent(tmp_path, monkeypatch):
    bundle = tmp_path / "Artist" / "Album.pkg"
    bundle.mkdir(parents=True)
    opened: list = []
    monkeypatch.setattr(sys, "platform", "darwin")
    from PySide6 import QtGui

    def boom(argv, **kw):
        raise OSError("no open")

    monkeypatch.setattr("waves.desktop.bridge_library.subprocess.Popen", boom)
    monkeypatch.setattr(QtGui.QDesktopServices, "openUrl", lambda url: opened.append(url.toLocalFile()))
    LibraryMixin._reveal_in_file_manager(str(bundle))
    assert opened == [str(bundle.parent)]


@pytest.mark.parametrize("suffix", [".app", ".pkg", ".bundle", ".framework", ".kext", ".plugin", ".prefPane", ".xpc"])
def test_elsewhere_a_package_suffixed_folder_shows_its_parent(tmp_path, monkeypatch, suffix):
    bundle = tmp_path / "Artist" / f"Album{suffix}"
    bundle.mkdir(parents=True)
    popen, opened = _reveal(monkeypatch, "linux", bundle)
    assert popen == [] and opened == [str(bundle.parent)]


def test_elsewhere_a_plain_folder_opens_as_before(tmp_path, monkeypatch):
    folder = tmp_path / "Artist" / "[2020] Album"
    folder.mkdir(parents=True)
    popen, opened = _reveal(monkeypatch, "win32", folder)
    assert popen == [] and opened == [str(folder)]


def test_the_reveal_stats_nothing_on_the_gui_thread(tmp_path, monkeypatch):
    """A share that stopped answering hangs any stat for its timeout; the
    ancestor walk runs on a worker for exactly that reason, so the GUI-thread
    half must not stat again."""
    from PySide6 import QtGui

    opened: list = []
    stats: list = []
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(QtGui.QDesktopServices, "openUrl", lambda url: opened.append(url.toLocalFile()))
    real_is_dir, real_exists = pathlib.Path.is_dir, pathlib.Path.exists
    monkeypatch.setattr(pathlib.Path, "is_dir", lambda self, *a, **k: stats.append(str(self)) or real_is_dir(self))
    monkeypatch.setattr(pathlib.Path, "exists", lambda self, *a, **k: stats.append(str(self)) or real_exists(self))
    target = tmp_path / "gone" / "[2020] Album"  # need not exist: nothing may look
    LibraryMixin._reveal_in_file_manager(str(target))
    assert opened == [str(target)] and stats == []


def test_the_resolved_reveal_slot_routes_through_the_safe_reveal(monkeypatch):
    seen: list = []
    monkeypatch.setattr(LibraryMixin, "_reveal_in_file_manager", staticmethod(lambda t: seen.append(t)))
    LibraryMixin._on_reveal_resolved(SimpleNamespace(), str(pathlib.Path.cwd()))
    assert seen == [str(pathlib.Path.cwd())]
