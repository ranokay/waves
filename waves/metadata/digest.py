"""Tag-independent audio digests for safe replacement decisions.

A replacement may only touch a copy whose AUDIO is still the one Waves wrote.
Tag edits are not audio edits: the user's genre, comment or rating must not
make the file look externally modified (and then be thrown away by a refusal to
replace it). Every digest here therefore reads only the audio payload:

- FLAC: the STREAMINFO MD5 signature, which is the audio MD5 by definition.
  An all-zero signature means the encoder never wrote one; that is not a
  digest, so the file reads as uncertain.
- MP4/M4A: the concatenated ``mdat`` payloads, skipping the metadata boxes.
- MP3: the audio frames after ID3v2 and before ID3v1.
- Anything else: the whole file, the honest answer for a container whose tag
  block cannot be separated from its payload.

None means "cannot prove": a missing file, a malformed container, or a FLAC
with no audio MD5. Callers treat None as uncertain and protect the file.
"""

from __future__ import annotations

import hashlib
import pathlib
import struct
from typing import BinaryIO

_CHUNK = 1024 * 1024


def _sha256_stream(handle: BinaryIO, length: int | None = None) -> str:
    digest = hashlib.sha256()
    remaining = length
    while remaining is None or remaining > 0:
        chunk = handle.read(_CHUNK if remaining is None else min(_CHUNK, remaining))
        if not chunk:
            break
        digest.update(chunk)
        if remaining is not None:
            remaining -= len(chunk)
    return digest.hexdigest()


def _flac_digest(path: pathlib.Path) -> str | None:
    try:
        import mutagen.flac

        info = mutagen.flac.FLAC(str(path)).info
    except Exception:
        return None
    signature = int(getattr(info, "md5_signature", 0) or 0)
    return f"flac-md5:{signature:032x}" if signature else None


def _mp4_digest(path: pathlib.Path) -> str | None:  # noqa: C901 - one box walk
    digest = hashlib.sha256()
    found = False
    try:
        size = path.stat().st_size
    except OSError:
        return None
    with path.open("rb") as handle:
        offset = 0
        while offset + 8 <= size:
            handle.seek(offset)
            header = handle.read(8)
            if len(header) < 8:
                break
            box_size, box_type = struct.unpack(">I4s", header)
            header_len = 8
            if box_size == 1:
                extended = handle.read(8)
                if len(extended) < 8:
                    break
                box_size = struct.unpack(">Q", extended)[0]
                header_len = 16
            elif box_size == 0:
                box_size = size - offset
            if box_size < header_len or offset + box_size > size:
                break
            if box_type == b"mdat":
                found = True
                remaining = box_size - header_len
                handle.seek(offset + header_len)
                while remaining > 0:
                    chunk = handle.read(min(_CHUNK, remaining))
                    if not chunk:
                        break
                    digest.update(chunk)
                    remaining -= len(chunk)
            offset += box_size
    return f"mp4-mdat:{digest.hexdigest()}" if found else None


def _mp3_audio_start(path: pathlib.Path) -> int:
    try:
        with path.open("rb") as handle:
            header = handle.read(10)
    except OSError:
        return 0
    if len(header) >= 10 and header[:3] == b"ID3":
        size = ((header[6] & 0x7F) << 21) | ((header[7] & 0x7F) << 14) | ((header[8] & 0x7F) << 7) | (header[9] & 0x7F)
        return 10 + size
    return 0


def _mp3_digest(path: pathlib.Path) -> str | None:
    try:
        size = path.stat().st_size
    except OSError:
        return None
    start = _mp3_audio_start(path)
    end = size
    if size >= 128:
        try:
            with path.open("rb") as handle:
                handle.seek(size - 128)
                if handle.read(3) == b"TAG":
                    end -= 128
        except OSError:
            return None
    if end <= start:
        return None
    try:
        with path.open("rb") as handle:
            handle.seek(start)
            return f"mp3-audio:{_sha256_stream(handle, end - start)}"
    except OSError:
        return None


def audio_digest(path: str | pathlib.Path) -> str | None:
    """The tag-independent digest of the audio at ``path``, or None."""
    file_path = pathlib.Path(str(path))
    suffix = file_path.suffix.lower()
    try:
        if suffix == ".flac":
            return _flac_digest(file_path)
        if suffix in (".m4a", ".mp4"):
            return _mp4_digest(file_path)
        if suffix == ".mp3":
            return _mp3_digest(file_path)
        with file_path.open("rb") as handle:
            return f"file:{_sha256_stream(handle)}"
    except (OSError, ValueError, struct.error):
        return None


def digest_matches(recorded: str | None, path: str | pathlib.Path) -> bool:
    """Whether ``path`` still carries the audio the record describes."""
    return bool(recorded) and recorded == audio_digest(path)
