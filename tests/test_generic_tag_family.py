"""Every new download answers "which item is this?" in the generic WAVES_*
family the provider spec names (§8.1), written BESIDE the legacy WAVES_TIDAL_*
tags it does not replace.

Two families on one file, one identity in two spellings: the generic tags
carry the seam's namespaced ids ("tidal:123" -- the format both providers
share, and the only one an Apple file can carry), the legacy tags keep the
bare ids every existing library file and reader already speaks. Nothing is
migrated and nothing is removed: a pre-namespace library stays recognized
through its legacy tags, and a TIDAL-only library behaves exactly as before
because the reader still hands back the bare spelling it always did.

The reader is generic-first, legacy-fallback (§8.1). One subtlety is
deliberate and pinned: a generic id carrying TIDAL's namespace is read back
bare, so a new file and an old one answer a gate identically; a FOREIGN
namespace stays prefixed, because another provider's file must never equal a
bare TIDAL id -- never be claimed, skipped or replaced as this provider's own.
"""

from __future__ import annotations

from unittest.mock import patch

import mutagen.flac
import mutagen.mp3
import mutagen.mp4
import pytest

from waves.metadata import (
    ALBUM_ARTIST_ID_TAG,
    ARTIST_ID_TAG,
    GENERIC_ALBUM_ARTIST_ID_TAG,
    GENERIC_ARTIST_IDS_TAG,
    GENERIC_ITEM_ID_TAG,
    ITEM_ID_TAG,
    Metadata,
    read_item_id,
)

_UPC = {"FLAC": "UPC", "MP4": "UPC", "MP3": "UPC"}

_ITEM = "123"
_ITEM_NAMESPACED = "tidal:123"
_ARTISTS = ["4676988", "77"]
_ARTISTS_NAMESPACED = ["tidal:4676988", "tidal:77"]
_ALBUM_ARTIST = "4676988"
_ALBUM_ARTIST_NAMESPACED = "tidal:4676988"


def _flac_stub():
    fake = mutagen.flac.FLAC.__new__(mutagen.flac.FLAC)
    fake.tags = None
    fake.metadata_blocks = []
    fake.save = lambda *a, **k: None
    return fake


def _mp3_stub():
    fake = mutagen.mp3.MP3.__new__(mutagen.mp3.MP3)
    fake.tags = None
    fake.save = lambda *a, **k: None
    return fake


def _mp4_stub():
    fake = mutagen.mp4.MP4.__new__(mutagen.mp4.MP4)
    fake.tags = None
    fake.save = lambda *a, **k: None
    return fake


def _write(stub, tmp_path, name, **kw):
    file = tmp_path / name
    file.write_bytes(b"x")
    with patch("waves.metadata.mutagen.File", return_value=stub):
        assert Metadata(path_file=file, target_upc=_UPC, **kw).save() is True
    return stub


def _tagged(tmp_path, name, stub):
    """A file written with namespaced ids, the way the seam's facts carry them."""
    return _write(
        stub,
        tmp_path,
        name,
        title="T",
        artists=["Marina", "Guest"],
        albumartist=["Marina"],
        item_id=_ITEM_NAMESPACED,
        artist_ids=_ARTISTS_NAMESPACED,
        album_artist_ids=[_ALBUM_ARTIST_NAMESPACED],
    )


# Per-container spelling of the generic item-id atom, so the read-side tests
# can rewrite or drop exactly one family and prove which one answered.
def _set_generic_item(stub, value):
    if isinstance(stub, mutagen.flac.FLAC):
        stub.tags[GENERIC_ITEM_ID_TAG] = value
    elif isinstance(stub, mutagen.mp3.MP3):
        stub.tags[f"TXXX:{GENERIC_ITEM_ID_TAG}"].text = [value]
    else:
        stub.tags[f"----:com.apple.iTunes:{GENERIC_ITEM_ID_TAG}"] = value.encode("utf-8")


def _drop_generic_item(stub):
    if isinstance(stub, mutagen.flac.FLAC):
        del stub.tags[GENERIC_ITEM_ID_TAG]
    elif isinstance(stub, mutagen.mp3.MP3):
        del stub.tags[f"TXXX:{GENERIC_ITEM_ID_TAG}"]
    else:
        del stub.tags[f"----:com.apple.iTunes:{GENERIC_ITEM_ID_TAG}"]


def _drop_legacy_item(stub):
    if isinstance(stub, mutagen.flac.FLAC):
        del stub.tags[ITEM_ID_TAG]
    elif isinstance(stub, mutagen.mp3.MP3):
        del stub.tags[f"TXXX:{ITEM_ID_TAG}"]
    else:
        del stub.tags[f"----:com.apple.iTunes:{ITEM_ID_TAG}"]


# --------------------------------------------------------------------------- #
# Both families land on every container Waves can write
# --------------------------------------------------------------------------- #
def test_flac_carries_the_generic_family_beside_the_legacy_one(tmp_path):
    flac = _tagged(tmp_path, "t.flac", _flac_stub())
    # Legacy: bare, exactly as v0.1.x wrote it.
    assert flac.tags[ITEM_ID_TAG] == [_ITEM]
    assert flac.tags[ARTIST_ID_TAG] == _ARTISTS
    assert flac.tags[ALBUM_ARTIST_ID_TAG] == [_ALBUM_ARTIST]
    # Generic: the namespaced spelling, beside it.
    assert flac.tags[GENERIC_ITEM_ID_TAG] == [_ITEM_NAMESPACED]
    assert flac.tags[GENERIC_ARTIST_IDS_TAG] == _ARTISTS_NAMESPACED
    assert flac.tags[GENERIC_ALBUM_ARTIST_ID_TAG] == [_ALBUM_ARTIST_NAMESPACED]


def test_mp3_carries_the_generic_family_beside_the_legacy_one(tmp_path):
    mp3 = _tagged(tmp_path, "t.mp3", _mp3_stub())
    assert mp3.tags[f"TXXX:{ITEM_ID_TAG}"].text == [_ITEM]
    assert mp3.tags[f"TXXX:{GENERIC_ITEM_ID_TAG}"].text == [_ITEM_NAMESPACED]
    assert mp3.tags[f"TXXX:{GENERIC_ARTIST_IDS_TAG}"].text == _ARTISTS_NAMESPACED
    assert mp3.tags[f"TXXX:{GENERIC_ALBUM_ARTIST_ID_TAG}"].text == [_ALBUM_ARTIST_NAMESPACED]


def test_mp4_carries_the_generic_family_beside_the_legacy_one(tmp_path):
    mp4 = _tagged(tmp_path, "t.m4a", _mp4_stub())
    assert mp4.tags[f"----:com.apple.iTunes:{ITEM_ID_TAG}"] == _ITEM.encode("utf-8")
    assert mp4.tags[f"----:com.apple.iTunes:{GENERIC_ITEM_ID_TAG}"] == _ITEM_NAMESPACED.encode("utf-8")
    assert mp4.tags[f"----:com.apple.iTunes:{GENERIC_ARTIST_IDS_TAG}"] == [
        a.encode("utf-8") for a in _ARTISTS_NAMESPACED
    ]
    assert mp4.tags[f"----:com.apple.iTunes:{GENERIC_ALBUM_ARTIST_ID_TAG}"] == [
        _ALBUM_ARTIST_NAMESPACED.encode("utf-8")
    ]


def test_a_music_video_carries_the_generic_family_too(tmp_path):
    """set_mp4_video is a separate branch, and it is the one that gets forgotten.
    The video body hands bare engine ids -- the legacy convention -- and the
    generic tags must still come out namespaced."""
    mp4 = _write(
        _mp4_stub(),
        tmp_path,
        "v.m4a",
        title="V",
        artists=["Marina"],
        albumartist=["Marina"],
        is_video=True,
        item_id=_ITEM,
        artist_ids=_ARTISTS,
        album_artist_ids=[_ALBUM_ARTIST],
    )
    assert mp4.tags[f"----:com.apple.iTunes:{ITEM_ID_TAG}"] == _ITEM.encode("utf-8")
    assert mp4.tags[f"----:com.apple.iTunes:{GENERIC_ITEM_ID_TAG}"] == _ITEM_NAMESPACED.encode("utf-8")
    assert mp4.tags[f"----:com.apple.iTunes:{GENERIC_ARTIST_IDS_TAG}"] == [
        a.encode("utf-8") for a in _ARTISTS_NAMESPACED
    ]


def test_a_nameless_tagged_file_writes_the_generic_item_id_alone(tmp_path):
    """An id-less credit writes no id tag (unknown is never somebody else); the
    generic family follows the same rule its legacy half always had."""
    flac = _write(
        _flac_stub(),
        tmp_path,
        "t.flac",
        title="T",
        artists=["Marina"],
        albumartist=["Marina"],
        item_id=_ITEM_NAMESPACED,
    )
    assert flac.tags[GENERIC_ITEM_ID_TAG] == [_ITEM_NAMESPACED]
    assert GENERIC_ARTIST_IDS_TAG not in flac.tags
    assert GENERIC_ALBUM_ARTIST_ID_TAG not in flac.tags


def test_the_two_families_are_different_questions_asked_twice():
    names = {
        ITEM_ID_TAG,
        ARTIST_ID_TAG,
        ALBUM_ARTIST_ID_TAG,
        GENERIC_ITEM_ID_TAG,
        GENERIC_ARTIST_IDS_TAG,
        GENERIC_ALBUM_ARTIST_ID_TAG,
    }
    assert len(names) == 6


# --------------------------------------------------------------------------- #
# The reader: generic-first, legacy-fallback, and the bare answer unchanged
# --------------------------------------------------------------------------- #
def test_a_namespaced_id_never_doubles_its_prefix(tmp_path):
    """The generic tag must carry what the seam handed over, not a namespace
    applied twice to an already-namespaced value."""
    flac = _write(
        _flac_stub(),
        tmp_path,
        "t.flac",
        title="T",
        artists=["Marina"],
        albumartist=["Marina"],
        item_id=_ITEM_NAMESPACED,
    )
    assert flac.tags[GENERIC_ITEM_ID_TAG] == [_ITEM_NAMESPACED]


@pytest.mark.parametrize(
    ("stub", "name"),
    [(_flac_stub, "t.flac"), (_mp3_stub, "t.mp3"), (_mp4_stub, "t.m4a")],
)
def test_a_legacy_only_file_is_still_recognized(tmp_path, stub, name):
    """The whole reason the legacy tags stay: every file already in a library
    answers through them, unchanged."""
    written = _tagged(tmp_path, name, stub())
    _drop_generic_item(written)
    with patch("waves.metadata.mutagen.File", return_value=written):
        assert read_item_id(tmp_path / name) == _ITEM


@pytest.mark.parametrize(
    ("stub", "name"),
    [(_flac_stub, "t.flac"), (_mp3_stub, "t.mp3"), (_mp4_stub, "t.m4a")],
)
def test_a_generic_only_file_reads_the_same_bare_id(tmp_path, stub, name):
    """A new file and an old one must answer a gate identically, so TIDAL's
    namespace is read back off: the comparison spelling never moved."""
    written = _tagged(tmp_path, name, stub())
    _drop_legacy_item(written)
    with patch("waves.metadata.mutagen.File", return_value=written):
        assert read_item_id(tmp_path / name) == _ITEM


@pytest.mark.parametrize(
    ("stub", "name"),
    [(_flac_stub, "t.flac"), (_mp3_stub, "t.mp3"), (_mp4_stub, "t.m4a")],
)
def test_the_generic_tag_is_read_first(tmp_path, stub, name):
    written = _tagged(tmp_path, name, stub())
    _set_generic_item(written, "tidal:999")
    with patch("waves.metadata.mutagen.File", return_value=written):
        assert read_item_id(tmp_path / name) == "999"


@pytest.mark.parametrize(
    ("stub", "name"),
    [(_flac_stub, "t.flac"), (_mp3_stub, "t.mp3"), (_mp4_stub, "t.m4a")],
)
def test_a_foreign_provider_never_reads_as_a_bare_tidal_id(tmp_path, stub, name):
    """An Apple file sharing TIDAL's numeric id space must never be claimed,
    skipped or replaced as this provider's own copy: its namespace stays on."""
    written = _tagged(tmp_path, name, stub())
    _set_generic_item(written, "apple:123")
    with patch("waves.metadata.mutagen.File", return_value=written):
        answer = read_item_id(tmp_path / name)
    assert answer == "apple:123"
    assert answer != _ITEM
