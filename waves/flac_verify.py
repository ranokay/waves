"""Checking and sealing FLAC audio signatures without ever touching the audio.

A FLAC file opens with a STREAMINFO block that carries, among the stream's
shape, the MD5 of the decoded audio and the total sample count. ``flac -t``
and every checker built on libFLAC decode the file and compare; a header
whose signature is all zeros ("unset") cannot be verified, so those tools
report the file as failing even though every audio frame is intact, and
strict players treat it as corrupt. TIDAL's packaging shipped such headers
for a while and a copied-out extraction keeps the header verbatim, which is
how a Waves library can hold files like that.

This module is the one place the download engine (right after an extraction)
and the library check go through. Three guarantees hold for everything in it:

1. Reading never writes. The header scan opens each file for reading and
   reads a few dozen bytes; the deep check additionally decodes the audio
   through ffmpeg, which reads too.
2. The seal writes exactly the 34-byte STREAMINFO block, in place, through a
   single ``write`` of those 34 bytes. The file never changes size, no byte
   outside the block is written, the block's shape fields (block and frame
   sizes, sample rate, channels, bit depth) are carried over byte for byte,
   and the bytes on disk are compared with what was read right before the
   write and read back right after it.
3. The seal only ever fills in an UNSET signature, and only after the audio
   decoded cleanly (every frame's checksum verified, the file ending on a
   whole frame), to the length the header states (or, when the header states
   none, to the length the file's last frame proves). A signature that is set
   and does not match the audio is reported and left alone, and so is a file
   whose audio decodes shorter or longer than its header says: either the
   audio or the header is damaged, and writing the hash of whatever the audio
   now is over it would only hide that. A file that changed between the read
   and the write is left alone.

Qt-free on purpose: the download engine calls :func:`seal_file` directly and
the tests drive it with plain files. The library check's folder walk,
remembered verdicts, reports and fix loop live in :mod:`waves.library.flac_check`
and build on these read and seal primitives.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace

from waves.constants import CHUNK_SIZE

STREAMINFO_SIZE = 34
_MARKER = b"fLaC"
_MD5_UNSET = bytes(16)
_TOTAL_SAMPLES_MASK = (1 << 36) - 1
# The PCM layouts whose MD5 libFLAC's definition and ffmpeg's output agree
# on: each sample as wide as its bit depth, little endian, interleaved. A
# depth that is not a whole number of bytes (20-bit, say) decodes to a
# wider, shifted sample, so its hash would come out different; such files
# are reported as unsupported and never written.
_PCM_FORMATS = {16: "s16le", 24: "s24le", 32: "s32le"}
# A decode that has not finished after this long is stopped and reported, so
# a share that stopped answering cannot hold a worker forever: a fixed floor
# plus the time the file would take at a crawl (a healthy decode runs at tens
# of megabytes a second, so only a stalled read ever reaches the limit).
DECODE_MIN_SECONDS = 120.0
DECODE_MIN_BYTES_PER_SECOND = 128 * 1024
# How often the decode's watchdog looks at the cancel flag and the clock.
_WATCH_POLL_S = 0.25

# Windows: a console process started from the windowless app flashes a
# console window. The engine's decode spawn lives here, outside the desktop
# and Apple provider modules that carry their own copy of this flag.
NO_WINDOW: int = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

# Row statuses. The first group comes out of a scan, the second out of a seal.
UNSET = "unset"  # no signature in the header: the case the seal is for
SET = "set"  # a signature is present (header scan only, not verified)
OK = "ok"  # deep check or seal: the signature matches the decoded audio
MISMATCH = "mismatch"  # a signature is present and does not match; reported, never rewritten
UNREADABLE = "unreadable"  # not a FLAC stream this checker can parse
UNSUPPORTED = "unsupported"  # a bit depth whose hash this checker cannot reproduce
DECODE_FAILED = "decode_failed"  # ffmpeg could not decode the audio cleanly
LENGTH_DIFFERS = "length_differs"  # the audio length differs from the header, or nothing proves it; left alone
SEALED = "sealed"  # the signature was unset, computed and written
CHANGED = "changed"  # the file changed since the read; left alone
WRITE_FAILED = "write_failed"  # the header could not be written (permissions, a read-only share)
CANCELLED = "cancelled"  # the run was canceled before this file was finished

# What a row's status means, in the user's words (the log and, later, the report).
STATUS_LABELS = {
    UNSET: "no signature",
    SET: "signature present",
    OK: "verified",
    MISMATCH: "signature does not match the audio",
    UNREADABLE: "not a readable FLAC file",
    UNSUPPORTED: "bit depth not supported by this check",
    DECODE_FAILED: "audio did not decode cleanly",
    LENGTH_DIFFERS: "audio length differs from the header or cannot be confirmed, left alone",
    SEALED: "signature written",
    CHANGED: "changed since the read, left alone",
    WRITE_FAILED: "header could not be written",
    CANCELLED: "not checked (canceled)",
}


class FlacHeaderError(ValueError):
    """The file does not start with a STREAMINFO block this checker can read."""


_NOT_FLAC = "not a native FLAC stream"
_TRUNCATED_HEADER = "truncated before the first metadata block"
_NOT_FIRST = "STREAMINFO is not the first metadata block"
_TRUNCATED_BLOCK = "truncated STREAMINFO block"
_BAD_MD5_LEN = "an MD5 signature is 16 bytes"
_BAD_BLOCK_LEN = "STREAMINFO must stay 34 bytes"
_SHAPE_FIELDS = "the block and frame size fields are never rewritten"
_HEADER_MOVED = "the header on disk is not the one the read saw"
_READ_BACK = "the header read back differently from what was written"
_NOT_WHOLE = "the file ends partway through an audio frame (cut off, or bytes after the last frame)"
_UNPROVEN = (
    "the header gives no sample count and the end of the file does not prove the audio is complete"
    " (it may be cut off on a frame boundary)"
)


class DecodeFailed(RuntimeError):
    """ffmpeg did not decode the audio cleanly."""


class Unsupported(RuntimeError):
    """A bit depth whose MD5 this checker cannot reproduce."""


class HeaderChanged(RuntimeError):
    """The header bytes on disk are not the ones the read saw."""


class Cancelled(RuntimeError):
    """The caller asked to stop."""


@dataclass(frozen=True)
class StreamInfo:
    """The STREAMINFO block as read, plus where it sits in the file."""

    offset: int  # file offset of the 34 block bytes
    raw: bytes  # those 34 bytes, exactly as read
    sample_rate: int
    channels: int
    bits_per_sample: int
    total_samples: int
    md5: bytes  # 16 bytes

    @property
    def md5_unset(self) -> bool:
        return self.md5 == _MD5_UNSET


@dataclass(frozen=True)
class Row:
    """One file's verdict. ``info`` is kept so the seal can prove the header
    is still the one it read; ``size``/``mtime_ns`` so it can prove the file
    is."""

    path: str
    status: str
    detail: str = ""
    info: StreamInfo | None = None
    size: int = -1
    mtime_ns: int = -1
    md5_audio: bytes | None = None
    samples_decoded: int = -1


# ---- the header ---------------------------------------------------------------


def _syncsafe(raw: bytes) -> int:
    return (raw[0] << 21) | (raw[1] << 14) | (raw[2] << 7) | raw[3]


def read_streaminfo(path: str | os.PathLike) -> StreamInfo:
    """Read the STREAMINFO block (a few dozen bytes; nothing else is read).

    An ID3v2 tag in front of the stream (some taggers write one) is stepped
    over. The block must be the first metadata block, as the format
    requires; anything else raises :class:`FlacHeaderError`.
    """
    with open(path, "rb") as f:
        head = f.read(10)
        pos = 0
        if head[:3] == b"ID3" and len(head) == 10:
            footer = 10 if head[5] & 0x10 else 0
            pos = 10 + _syncsafe(head[6:10]) + footer
            f.seek(pos)
            head = f.read(4)
        if head[:4] != _MARKER:
            raise FlacHeaderError(_NOT_FLAC)
        pos += 4
        f.seek(pos)
        block_header = f.read(4)
        if len(block_header) != 4:
            raise FlacHeaderError(_TRUNCATED_HEADER)
        block_type = block_header[0] & 0x7F
        length = int.from_bytes(block_header[1:4], "big")
        if block_type != 0 or length != STREAMINFO_SIZE:
            raise FlacHeaderError(_NOT_FIRST)
        offset = pos + 4
        raw = f.read(STREAMINFO_SIZE)
    return _parse_streaminfo(offset, raw)


def parse_streaminfo(offset: int, raw: bytes) -> StreamInfo:
    """The STREAMINFO fields of the 34 block bytes found at ``offset``.

    Public for the verdict store, which keeps the block bytes and rebuilds
    the same StreamInfo a read would give."""
    return _parse_streaminfo(offset, raw)


def _parse_streaminfo(offset: int, raw: bytes) -> StreamInfo:
    """The STREAMINFO fields of the 34 block bytes found at ``offset``."""
    if len(raw) != STREAMINFO_SIZE:
        raise FlacHeaderError(_TRUNCATED_BLOCK)
    packed = int.from_bytes(raw[10:18], "big")
    return StreamInfo(
        offset=offset,
        raw=raw,
        sample_rate=packed >> 44,
        channels=((packed >> 41) & 0x7) + 1,
        bits_per_sample=((packed >> 36) & 0x1F) + 1,
        total_samples=packed & _TOTAL_SAMPLES_MASK,
        md5=raw[18:34],
    )


def sealed_bytes(info: StreamInfo, md5: bytes, total_samples: int) -> bytes:
    """The 34 block bytes with the signature and sample count filled in.

    Bytes 0..9 (block sizes, frame sizes) and the shape bits of the packed
    field (sample rate, channels, bit depth) are carried over unchanged. A
    sample count the 36-bit field cannot hold keeps the header's own.
    """
    if len(md5) != 16:
        raise ValueError(_BAD_MD5_LEN)
    packed = int.from_bytes(info.raw[10:18], "big")
    if 0 <= total_samples <= _TOTAL_SAMPLES_MASK:
        packed = (packed & ~_TOTAL_SAMPLES_MASK) | total_samples
    out = info.raw[:10] + packed.to_bytes(8, "big") + md5
    if len(out) != STREAMINFO_SIZE:  # pragma: no cover (arithmetic above fixes the length)
        raise ValueError(_BAD_BLOCK_LEN)
    return out


def write_streaminfo(path: str | os.PathLike, info: StreamInfo, new_raw: bytes) -> None:
    """Replace the 34 STREAMINFO bytes in place, and nothing else.

    Refuses (:class:`HeaderChanged`) when the bytes on disk are not the ones
    ``info`` was read from, so a file rewritten since the scan is never
    touched on stale knowledge. One ``write`` call of exactly 34 bytes at an
    offset inside the file: the size cannot change. The bytes are read back
    and compared, and a difference is raised as :class:`OSError`.
    """
    if len(new_raw) != STREAMINFO_SIZE:
        raise ValueError(_BAD_BLOCK_LEN)
    if new_raw[:10] != info.raw[:10]:
        raise ValueError(_SHAPE_FIELDS)
    with open(path, "r+b") as f:
        f.seek(info.offset)
        current = f.read(STREAMINFO_SIZE)
        if current != info.raw:
            raise HeaderChanged(_HEADER_MOVED)
        f.seek(info.offset)
        f.write(new_raw)
        f.flush()
        # A share that cannot fsync has still taken the write; the read-back
        # below is the check that counts.
        with contextlib.suppress(OSError):
            os.fsync(f.fileno())
        f.seek(info.offset)
        back = f.read(STREAMINFO_SIZE)
    if back != new_raw:
        raise OSError(_READ_BACK)


# ---- the audio ----------------------------------------------------------------


def _ensure_alive(should_continue: Callable[[], bool] | None) -> None:
    if should_continue is not None and not should_continue():
        raise Cancelled


def _crc_table(poly: int, width: int) -> tuple[int, ...]:
    top, mask = 1 << (width - 1), (1 << width) - 1
    table = []
    for byte in range(256):
        crc = byte << (width - 8)
        for _ in range(8):
            crc = ((crc << 1) ^ poly) & mask if crc & top else (crc << 1) & mask
        table.append(crc)
    return tuple(table)


# The format's two checksums: CRC-8 (x^8+x^2+x+1) closes every frame header,
# CRC-16 (x^16+x^15+x^2+1) closes every frame. Both start at 0 with no final
# xor, so a frame run through CRC-16 together with its own footer gives 0.
_CRC8 = _crc_table(0x07, 8)
_CRC16 = _crc_table(0x8005, 16)


def _crc8(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc = _CRC8[crc ^ byte]
    return crc


def _crc16(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc = ((crc << 8) & 0xFFFF) ^ _CRC16[(crc >> 8) ^ byte]
    return crc


def _frame_header_len(buf: bytes, i: int) -> int:
    """The length of the frame header at ``buf[i]`` (sync code through its
    CRC-8), or 0 when no valid one starts there."""
    if i + 5 > len(buf) or buf[i] != 0xFF or buf[i + 1] not in (0xF8, 0xF9):
        return 0
    block_code, rate_code = buf[i + 2] >> 4, buf[i + 2] & 0x0F
    if block_code == 0 or rate_code == 0x0F or buf[i + 3] & 0x01:
        return 0
    # The frame or sample number, UTF-8 style: the lead byte's run of high
    # ones is the length (0xFE leads the longest, 7 bytes).
    lead = buf[i + 4]
    if lead < 0x80:
        coded = 1
    elif 0xC0 <= lead < 0xFF:
        coded = 8 - (~lead & 0xFF).bit_length()
    else:
        return 0
    length = 4 + coded + {6: 1, 7: 2}.get(block_code, 0) + {12: 1, 13: 2, 14: 2}.get(rate_code, 0)
    if i + length >= len(buf) or _crc8(buf[i : i + length]) != buf[i + length]:
        return 0
    return length + 1


def _frame_fields(head: bytes) -> tuple[bool, int, int]:
    """A valid frame header (see :func:`_frame_header_len`) read into
    (variable blocking, frame or sample number, block size in samples)."""
    variable = bool(head[1] & 0x01)
    block_code = head[2] >> 4
    lead = head[4]
    coded = 1 if lead < 0x80 else 8 - (~lead & 0xFF).bit_length()
    number = lead if coded == 1 else lead & ((1 << (7 - coded)) - 1)
    for byte in head[5 : 4 + coded]:
        number = (number << 6) | (byte & 0x3F)
    pos = 4 + coded
    if block_code == 1:
        block = 192
    elif block_code <= 5:
        block = 576 << (block_code - 2)
    elif block_code == 6:
        block = head[pos] + 1
    elif block_code == 7:
        block = int.from_bytes(head[pos : pos + 2], "big") + 1
    else:
        block = 256 << (block_code - 8)
    return variable, number, block


def _last_frame_header(path: str | os.PathLike, info: StreamInfo) -> bytes | None:
    """The header of the whole frame the file ends on, or None when the file
    does not end on one. Reads only the tail (at most the largest frame the
    header allows); see :func:`ends_on_whole_frame`."""
    max_frame = int.from_bytes(info.raw[7:10], "big")
    max_block = int.from_bytes(info.raw[2:4], "big") or 65535
    # The largest frame the format allows for this stream: every channel
    # stored verbatim (the side channel one bit wider), plus headers. The
    # header's own figure is taken when larger, within reason: a damaged
    # header must not turn this into a read of megabytes.
    bound = max_block * info.channels * (info.bits_per_sample + 1) // 8 + 64
    window = max(min(max_frame, 2 * bound), bound)
    with open(path, "rb") as f:
        size = f.seek(0, os.SEEK_END)
        start = max(info.offset + STREAMINFO_SIZE, size - window)
        f.seek(start)
        tail = f.read(size - start)
    i = len(tail) - 2
    while (i := tail.rfind(b"\xff", 0, i)) >= 0:
        head = _frame_header_len(tail, i)
        if head and len(tail) - i >= head + 2 and _crc16(tail[i:]) == 0:
            return tail[i : i + head]
    return None


def ends_on_whole_frame(path: str | os.PathLike, info: StreamInfo) -> bool:
    """Whether the file's last byte closes a whole audio frame. Reads only
    the tail (at most the largest frame the header allows).

    ffmpeg's parser drops a few stray bytes after the last frame without a
    word, which is what a cut a few bytes into a frame leaves behind; the
    decode then comes out clean and short. With a sample count in the header
    the length guard catches that, but a header that says 0 (unknown) has
    nothing to compare against, so the end of the file is checked here: some
    frame header near the end must start a run of bytes, up to the file's
    last byte, whose CRC-16 checks out.

    The CRC cannot see zero bytes after a frame (they leave it at 0), so a
    few zeros after the last whole frame pass. That hides no damage: every
    frame before them is whole, and a cut that lost a frame would leave far
    more than a few bytes to fill.

    A cut exactly on a frame boundary also ends on a whole frame; see
    :func:`proven_total_samples` for what can tell that one apart.
    """
    return _last_frame_header(path, info) is not None


def proven_total_samples(path: str | os.PathLike, info: StreamInfo) -> int | None:
    """The stream's length in samples as its last frame proves it, or None
    when the end of the file proves nothing. Reads only the tail.

    A cut on a frame boundary leaves a shorter stream of whole frames that
    decodes cleanly, so with no sample count in the header something else
    has to show the stream is complete. In a fixed-blocksize stream (the
    blocking bit clear, the header's least and largest block equal) every
    frame holds the same number of samples except the stream's very last,
    which holds what is left over: a file that ends on a frame shorter than
    the others ends where the encoder stopped, and the frame's number times
    the block size plus its own size is the length. A last frame of the full
    size (a cut, or a length that happens to be a whole number of blocks), a
    variable-blocksize stream, or a header whose block sizes disagree proves
    nothing, and None is returned: the caller must not sign such a file.
    """
    try:
        head = _last_frame_header(path, info)
    except OSError:
        return None
    if head is None:
        return None
    variable, number, block = _frame_fields(head)
    min_block = int.from_bytes(info.raw[0:2], "big")
    max_block = int.from_bytes(info.raw[2:4], "big")
    if variable or min_block != max_block or not 0 < block < max_block:
        return None
    return number * max_block + block


def decode_time_limit(size: int) -> int:
    """Seconds a decode of a file of ``size`` bytes may take before it is
    stopped (see ``DECODE_MIN_SECONDS``)."""
    return round(DECODE_MIN_SECONDS + size / DECODE_MIN_BYTES_PER_SECOND)


def _watch_decode(
    proc: subprocess.Popen,
    should_continue: Callable[[], bool] | None,
    deadline: float,
    done: threading.Event,
    stopped: list[str],
) -> None:
    """(watchdog thread) Kill the decoder on a cancel or past the deadline,
    noting which in ``stopped``; return once ``done`` is set either way."""
    while not done.wait(_WATCH_POLL_S):
        if should_continue is not None and not should_continue():
            stopped.append("cancelled")
        elif time.monotonic() > deadline:
            stopped.append("timeout")
        else:
            continue
        with contextlib.suppress(OSError):
            proc.kill()
        return


def decode_md5(
    path: str | os.PathLike,
    ffmpeg: str,
    info: StreamInfo,
    should_continue: Callable[[], bool] | None = None,
    shared: int = 1,
) -> tuple[bytes, int]:
    """Decode the file through ffmpeg and hash the PCM the way libFLAC
    defines the signature. Returns the 16-byte digest and the sample count.
    ``shared`` is how many decodes run at once: they split the link between
    them, so each gets that many times as long before it counts as stuck.

    Reads only. The decoder child is killed on cancel and on any error.

    The decode has to be clean, not merely finished: left to itself ffmpeg
    skips a damaged or missing frame, carries on and exits 0, so a truncated
    file would hand back a shorter stream and a hash of it. ``-xerror`` makes
    the first decoder error fatal (a bad frame, a cut-off tail, bytes after
    the last frame), and ``-err_detect crccheck+explode`` makes the decoder
    verify each frame's CRC-16 and stop at a mismatch: with ``crccheck``
    alone a mismatch is only logged and the frame's damaged samples are
    decoded and hashed like any other, which is how one flipped bit in the
    middle of a file used to get signed. The few stray bytes a cut can leave
    after the last whole frame, which the parser drops silently, are caught
    by :func:`ends_on_whole_frame` before the decode starts. Such a file is
    reported and never signed.

    A watchdog thread stops the decoder on a cancel or once the time limit
    for the file's size has passed (see ``DECODE_MIN_SECONDS``), so a read
    stalled on a share that stopped answering ends the run's wait too: the
    pipe closes, the row comes back canceled or failed, and the thread
    ends with the call.
    """
    pcm_fmt = _PCM_FORMATS.get(info.bits_per_sample)
    if pcm_fmt is None or info.channels < 1:
        raise Unsupported(f"{info.bits_per_sample}-bit")
    if not ends_on_whole_frame(path, info):
        raise DecodeFailed(_NOT_WHOLE)
    argv = [
        str(ffmpeg),
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-xerror",
        "-err_detect",
        "crccheck+explode",
        "-i",
        os.fspath(path),
        "-f",
        pcm_fmt,
        "-",
    ]
    limit = decode_time_limit(os.path.getsize(path)) * max(1, shared)
    digest = hashlib.md5(usedforsecurity=False)  # the FLAC format mandates MD5; nothing here is a security claim
    n_bytes = 0
    # argv is the configured ffmpeg path plus one file under the user's folders.
    proc: subprocess.Popen[bytes] = subprocess.Popen(  # noqa: S603
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        creationflags=NO_WINDOW,
    )
    with proc:
        done = threading.Event()
        stopped: list[str] = []
        watchdog = threading.Thread(
            target=_watch_decode,
            args=(proc, should_continue, time.monotonic() + limit, done, stopped),
            name="flac-decode-watchdog",
            daemon=True,
        )
        watchdog.start()
        try:
            while proc.stdout is not None and (chunk := proc.stdout.read(CHUNK_SIZE)):
                _ensure_alive(should_continue)
                digest.update(chunk)
                n_bytes += len(chunk)
        except BaseException:
            proc.kill()
            raise
        finally:
            done.set()
            watchdog.join()
    if stopped == ["cancelled"]:
        raise Cancelled
    if stopped:
        raise DecodeFailed(f"the decoder did not finish within {limit} seconds")  # noqa: TRY003
    if proc.returncode != 0 or n_bytes == 0:
        raise DecodeFailed(f"the decoder reported an error (ffmpeg exit {proc.returncode})")  # noqa: TRY003
    sample_bytes = info.bits_per_sample // 8
    return digest.digest(), n_bytes // (sample_bytes * info.channels)


# ---- one file -----------------------------------------------------------------


def _stat(path: str) -> tuple[int, int]:
    st = os.stat(path)
    return st.st_size, st.st_mtime_ns


def _read_row(path: str) -> Row:
    """The header read into a row: ``SET`` or ``UNSET``, or ``UNREADABLE``
    with the reason (then ``info`` is None)."""
    size, mtime_ns = -1, -1
    try:
        size, mtime_ns = _stat(path)
        info = read_streaminfo(path)
    except FlacHeaderError as exc:
        # What the file holds, not a failure to read it: the stat is kept so
        # the verdict can be remembered against it.
        return Row(path, UNREADABLE, str(exc), size=size, mtime_ns=mtime_ns)
    except OSError as exc:
        return Row(path, UNREADABLE, exc.strerror or str(exc))
    return Row(path, UNSET if info.md5_unset else SET, info=info, size=size, mtime_ns=mtime_ns)


def _decode_row(row: Row, ffmpeg: str, should_continue: Callable[[], bool] | None, shared: int = 1) -> Row:
    """The row with the audio decoded and hashed, or with the status that
    says why it could not be (the status is unchanged on success)."""
    assert row.info is not None  # noqa: S101 (callers pass a header row)
    try:
        md5, samples = decode_md5(row.path, ffmpeg, row.info, should_continue, shared)
    except Cancelled:
        return replace(row, status=CANCELLED)
    except Unsupported as exc:
        return replace(row, status=UNSUPPORTED, detail=str(exc))
    except (DecodeFailed, OSError) as exc:
        return replace(row, status=DECODE_FAILED, detail=str(exc))
    return replace(row, md5_audio=md5, samples_decoded=samples)


def check_file(
    path: str,
    ffmpeg: str | None = None,
    *,
    deep: bool = False,
    should_continue: Callable[[], bool] | None = None,
    shared: int = 1,
) -> Row:
    """Read one file's verdict. Header only by default; ``deep`` decodes the
    audio and compares (``shared``: how many decodes run at once, see
    :func:`decode_md5`). Never writes."""
    row = _read_row(path)
    if row.info is None or not deep or not ffmpeg:
        return row
    row = _decode_row(row, ffmpeg, should_continue, shared)
    info = row.info
    if info is None or row.md5_audio is None or info.md5_unset:
        return row
    if row.md5_audio != info.md5:
        return replace(row, status=MISMATCH)
    detail = "" if info.total_samples in (0, row.samples_decoded) else "sample count in the header differs"
    return replace(row, status=OK, detail=detail)


def seal_file(
    path: str | os.PathLike,
    ffmpeg: str,
    *,
    expected: StreamInfo | None = None,
    fill_sample_count: bool = False,
    should_continue: Callable[[], bool] | None = None,
) -> Row:
    """Verify one file and fill in an unset signature.

    The only writing entry point. The audio is decoded first; a set
    signature that matches is left alone (``OK``), one that does not is
    reported (``MISMATCH``) and never rewritten; an unset one is written
    together with the sample count (``SEALED``), but only when the audio
    decoded to the length the header states. A shorter or longer decode
    means the file is cut off or damaged: it is reported (``LENGTH_DIFFERS``)
    and left alone, header count included, since that count is what shows
    the damage. A header count of 0 means unknown, and then the file's own
    end has to prove the length (see :func:`proven_total_samples`); when it
    cannot, nothing shows whether a cut on a frame boundary took the end of
    the audio, so the file is reported the same way and never signed (fail
    closed: signing it would make the cut look verified). With
    ``fill_sample_count`` a matching signature beside a wrong sample count
    has the count written too (the download engine's case: the file is one it
    just made, and the matching signature proves the audio complete).
    ``expected`` is the header a scan read earlier; a header that no longer
    matches it is ``CHANGED`` and left alone.
    """
    row = _read_row(os.fspath(path))
    info = row.info
    if info is None:
        return row
    if expected is not None and (info.raw != expected.raw or info.offset != expected.offset):
        return replace(row, status=CHANGED)
    row = _decode_row(row, ffmpeg, should_continue)
    md5, samples = row.md5_audio, row.samples_decoded
    if md5 is None:
        return row
    if not info.md5_unset:
        if md5 != info.md5:
            return replace(row, status=MISMATCH)
        if not fill_sample_count or info.total_samples == samples:
            return replace(row, status=OK)
        detail = "sample count written"
    elif refused := _length_refusal(row.path, info, samples):
        return replace(row, status=LENGTH_DIFFERS, detail=refused)
    else:
        detail = "signature and sample count written" if info.total_samples == 0 else "signature written"
    return _write_row(row, md5, samples, detail)


def _length_refusal(path: str, info: StreamInfo, samples: int) -> str:
    """Why an unset signature must not be written over a decode of
    ``samples`` samples, or "" when it may: the header's count must match
    it, or, when the header has none, the length the end of the file
    proves must (see :func:`proven_total_samples`)."""
    if info.total_samples == 0:
        proven = proven_total_samples(path, info)
        if proven is None:
            return _UNPROVEN
        if proven != samples:
            return f"decoded {samples} samples, the last frame ends at {proven}"
    elif info.total_samples != samples:
        return f"decoded {samples} samples, the header says {info.total_samples}"
    return ""


def _write_row(row: Row, md5: bytes, samples: int, detail: str) -> Row:
    """The write itself, after the decode proved the audio: the file must
    still be the one that was hashed, and the header the one that was read."""
    info = row.info
    assert info is not None  # noqa: S101 (seal_file passes a decoded header row)
    try:
        if _stat(row.path) != (row.size, row.mtime_ns):
            return replace(row, status=CHANGED, detail="modified while it was being decoded")
        write_streaminfo(row.path, info, sealed_bytes(info, md5, samples))
    except HeaderChanged:
        return replace(row, status=CHANGED)
    except OSError as exc:
        return replace(row, status=WRITE_FAILED, detail=exc.strerror or str(exc))
    return replace(row, status=SEALED, detail=detail)
