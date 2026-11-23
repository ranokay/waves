"""The replacement digest reads audio, never the tag block.

A user's genre or comment edit must not make a Waves-owned file look externally
modified; a content replacement must. FLAC's STREAMINFO MD5 is the audio MD5,
an all-zero one is not a digest, and MP4/MP3 payloads exclude their metadata.
"""

from __future__ import annotations

import struct
from types import SimpleNamespace

from waves.metadata.digest import audio_digest, digest_matches


def _box(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(payload), kind) + payload


def _mp4(path, metadata: bytes, audio: bytes) -> None:
    path.write_bytes(_box(b"ftyp", b"M4A ") + _box(b"moov", metadata) + _box(b"mdat", audio))


def _mp3(path, id3: bytes, audio: bytes, id3v1: bool = False) -> None:
    header = b"ID3\x04\x00\x00" + bytes(
        [(len(id3) >> 21) & 0x7F, (len(id3) >> 14) & 0x7F, (len(id3) >> 7) & 0x7F, len(id3) & 0x7F]
    )
    tail = b"TAG" + b"\x00" * 125 if id3v1 else b""
    path.write_bytes(header + id3 + audio + tail)


def test_mp4_digest_ignores_a_tag_only_edit(tmp_path):
    path = tmp_path / "song.m4a"
    _mp4(path, b"tags-one", b"audio-payload")
    first = audio_digest(path)

    _mp4(path, b"tags-two-longer", b"audio-payload")

    assert first and first == audio_digest(path)


def test_mp4_digest_changes_when_the_audio_changes(tmp_path):
    path = tmp_path / "song.m4a"
    _mp4(path, b"tags", b"audio-one")
    first = audio_digest(path)

    _mp4(path, b"tags", b"audio-two")

    assert first != audio_digest(path)


def test_mp3_digest_ignores_id3v2_and_id3v1_edits(tmp_path):
    path = tmp_path / "song.mp3"
    _mp3(path, b"old-tags", b"audio-frames", id3v1=True)
    first = audio_digest(path)

    _mp3(path, b"new-tags-here", b"audio-frames", id3v1=True)

    assert first and first == audio_digest(path)


def test_flac_audio_md5_is_the_digest(tmp_path, monkeypatch):
    path = tmp_path / "song.flac"
    path.write_bytes(b"not really flac")
    monkeypatch.setattr(
        "mutagen.flac.FLAC",
        lambda *_a, **_k: SimpleNamespace(info=SimpleNamespace(md5_signature=0x1234)),
    )

    assert audio_digest(path) == "flac-md5:" + f"{0x1234:032x}"


def test_an_all_zero_flac_md5_is_not_a_digest(tmp_path, monkeypatch):
    path = tmp_path / "song.flac"
    path.write_bytes(b"not really flac")
    monkeypatch.setattr(
        "mutagen.flac.FLAC",
        lambda *_a, **_k: SimpleNamespace(info=SimpleNamespace(md5_signature=0)),
    )

    assert audio_digest(path) is None
    assert digest_matches(None, path) is False


def test_a_missing_or_unreadable_file_is_uncertain(tmp_path):
    assert audio_digest(tmp_path / "missing.flac") is None
    assert digest_matches("flac-md5:0" * 1, tmp_path / "missing.flac") is False
