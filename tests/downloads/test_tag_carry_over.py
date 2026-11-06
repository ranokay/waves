"""A replacement keeps the user's tags and never the old delivery's facts."""

from __future__ import annotations

import shutil
import subprocess

import mutagen.flac
import mutagen.mp4
import pytest

from waves.metadata.tags import (
    GENERIC_AUDIO_TYPE_TAG,
    GENERIC_ITEM_ID_TAG,
    ITEM_ID_TAG,
    MetadataUnreadable,
    carry_over_tags,
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


def _m4a(tmp_path, name, *, genre="", comment="", composer="", grouping="", item_id="", audio_type="") -> object:
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
        handle[GENERIC_ITEM_ID_TAG] = item_id.encode("utf-8")
    if audio_type:
        handle[GENERIC_AUDIO_TYPE_TAG] = audio_type.encode("utf-8")
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
    old = tmp_path / "old.flac"
    old.write_bytes(b"not a container")
    new = _flac(tmp_path, "new.flac")

    with pytest.raises(MetadataUnreadable):
        carry_over_tags(old, new, strict=True)
