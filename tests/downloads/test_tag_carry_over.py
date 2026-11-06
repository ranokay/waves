"""A replacement keeps the user's tags and never the old delivery's facts."""

from __future__ import annotations

import shutil
import subprocess

import mutagen.flac
import mutagen.mp3
import mutagen.mp4
import pytest
from mutagen import MutagenError
from mutagen.id3 import TXXX

from waves.metadata.tags import (
    GENERIC_AUDIO_TYPE_TAG,
    GENERIC_ITEM_ID_TAG,
    ITEM_ID_TAG,
    MetadataUnreadable,
    carry_over_tags,
    read_item_id,
)

pytestmark = pytest.mark.ffmpeg


def _ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        pytest.skip("ffmpeg is required for the container fixtures")
    return path


def _tone(path, *extra) -> None:
    subprocess.run(  # noqa: S603 (fixed argv: a local tone fixture)
        [_ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.2", *extra, str(path)],
        check=True,
    )


def _flac(tmp_path, name, *, genre="", comment="", item_id="", audio_type="", legacy=True) -> object:
    path = tmp_path / name
    _tone(path, "-c:a", "flac")
    handle = mutagen.flac.FLAC(str(path))
    if genre:
        handle["GENRE"] = genre
    if comment:
        handle["COMMENT"] = comment
    if item_id:
        if legacy:
            handle[ITEM_ID_TAG] = item_id
        handle[GENERIC_ITEM_ID_TAG] = item_id
    if audio_type:
        handle[GENERIC_AUDIO_TYPE_TAG] = audio_type
    handle.save()
    return path


def _m4a(
    tmp_path, name, *, genre="", comment="", composer="", grouping="", item_id="", tidal_id="", audio_type=""
) -> object:
    path = tmp_path / name
    _tone(path, "-c:a", "aac")
    handle = mutagen.mp4.MP4(str(path))
    if genre:
        handle["\xa9gen"] = genre
    if comment:
        handle["\xa9cmt"] = comment
    if composer:
        handle["\xa9wrt"] = composer
    if grouping:
        handle["\xa9grp"] = grouping
    if item_id:
        handle[f"----:com.apple.iTunes:{GENERIC_ITEM_ID_TAG}"] = item_id.encode("utf-8")
    if tidal_id:
        handle[f"----:com.apple.iTunes:{ITEM_ID_TAG}"] = tidal_id.encode("utf-8")
    if audio_type:
        handle[f"----:com.apple.iTunes:{GENERIC_AUDIO_TYPE_TAG}"] = audio_type.encode("utf-8")
    handle.save()
    return path


def test_same_container_keeps_user_tags_and_delivered_provenance(tmp_path):
    old = _flac(tmp_path, "old.flac", genre="Shoegaze", comment="mine", item_id="tidal:1", audio_type="atmos")
    new = _flac(tmp_path, "new.flac", genre="Fresh", item_id="apple:42", audio_type="stereo", legacy=False)

    carried = carry_over_tags(old, new)

    handle = mutagen.flac.FLAC(str(new))
    assert carried >= 2
    assert handle["GENRE"] == ["Shoegaze"]
    assert handle["COMMENT"] == ["mine"]
    assert handle[GENERIC_ITEM_ID_TAG] == ["apple:42"]
    assert handle[GENERIC_AUDIO_TYPE_TAG] == ["stereo"]
    assert ITEM_ID_TAG not in handle


def test_cross_container_carries_the_common_user_fields(tmp_path):
    old = _m4a(tmp_path, "old.m4a", genre="Ambient", comment="keep me", composer="Composer", grouping="Group")
    new = _flac(tmp_path, "new.flac")

    carried = carry_over_tags(old, new)

    handle = mutagen.flac.FLAC(str(new))
    assert carried == 4
    assert handle["GENRE"] == ["Ambient"]
    assert handle["COMMENT"] == ["keep me"]
    assert handle["COMPOSER"] == ["Composer"]
    assert handle["GROUPING"] == ["Group"]


def test_an_untagged_old_copy_carries_nothing_and_is_not_a_failure(tmp_path):
    old = _flac(tmp_path, "old.flac")
    new = _flac(tmp_path, "new.flac")

    assert carry_over_tags(old, new, strict=True) == 0


def test_a_strict_carry_over_failure_raises_before_commit(tmp_path):
    old = _flac(tmp_path, "old.flac", genre="Shoegaze")
    new = _flac(tmp_path, "new.flac")
    new.chmod(0o444)

    with pytest.raises(MetadataUnreadable):
        carry_over_tags(old, new, strict=True)


def _mp3(tmp_path, name, *, item_id="") -> object:
    path = tmp_path / name
    _tone(path, "-c:a", "libmp3lame")
    handle = mutagen.mp3.MP3(str(path))
    if handle.tags is None:
        handle.add_tags()
    if item_id:
        handle.tags.add(TXXX(encoding=3, desc=GENERIC_ITEM_ID_TAG, text=item_id))
    handle.save()
    return path


def test_mp4_waves_tags_are_never_carried(tmp_path):
    old = _m4a(
        tmp_path,
        "old.m4a",
        item_id="apple:111",
        tidal_id="111",
        audio_type="atmos",
    )
    new = _m4a(tmp_path, "new.m4a")

    carry_over_tags(old, new)

    handle = mutagen.mp4.MP4(str(new))
    keys = {str(key).lower() for key in handle.tags}
    assert not any("waves" in key for key in keys)
    assert read_item_id(new) == ""


def test_mp3_waves_item_id_is_never_carried(tmp_path):
    old = _mp3(tmp_path, "old.mp3", item_id="tidal:111")
    new = _mp3(tmp_path, "new.mp3")

    carry_over_tags(old, new)

    handle = mutagen.mp3.MP3(str(new))
    keys = {str(key).lower() for key in handle.tags}
    assert not any("waves" in key for key in keys)
    assert read_item_id(new) == ""


@pytest.mark.parametrize("fail_on", ["old", "new"])
def test_a_strict_read_failure_aborts_instead_of_dropping_tags(tmp_path, monkeypatch, fail_on):
    import waves.metadata.tags as tags_module

    old = _flac(tmp_path, "old.flac", genre="Shoegaze")
    new = _flac(tmp_path, "new.flac")
    before = old.read_bytes()
    real_file = tags_module.mutagen.File
    failing = old if fail_on == "old" else new

    def unreadable(path):
        if str(path) == str(failing):
            # mutagen wraps an I/O failure in MutagenError(OSError), as it does
            # for a missing file or a permission denial.
            raise MutagenError(PermissionError(13, "Permission denied", str(path)))
        return real_file(path)

    monkeypatch.setattr(tags_module.mutagen, "File", unreadable)

    with pytest.raises(MetadataUnreadable):
        carry_over_tags(old, new, strict=True)

    assert old.read_bytes() == before
    assert mutagen.flac.FLAC(str(old))["GENRE"] == ["Shoegaze"]


def test_an_unidentifiable_container_still_carries_nothing(tmp_path, monkeypatch):
    import waves.metadata.tags as tags_module

    old = _flac(tmp_path, "old.flac", genre="Shoegaze")
    new = _flac(tmp_path, "new.flac")
    real_file = tags_module.mutagen.File

    monkeypatch.setattr(
        tags_module.mutagen,
        "File",
        lambda path: None if str(path) == str(old) else real_file(path),
    )

    assert carry_over_tags(old, new, strict=True) == 0


@pytest.mark.parametrize("name", ["damaged.flac", "damaged.mp3", "empty.flac"])
def test_a_damaged_file_carries_nothing_and_the_replacement_proceeds(tmp_path, name):
    """mutagen cannot parse the bytes: there are no recoverable tags, so the
    carry returns 0 even under strict=True and the replacement goes ahead."""
    old = tmp_path / name
    old.write_bytes(b"" if name.startswith("empty") else b"not an audio container at all" * 8)
    new = _flac(tmp_path, "new.flac")

    assert carry_over_tags(old, new, strict=True) == 0
