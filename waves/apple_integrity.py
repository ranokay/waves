"""Apple integrity gate: verification, outbreak pre-filter, quarantine paths.

Spec §6 (issue #30): every Apple audio delivery is verified pre-swap with an
ffmpeg decode-to-null check (always-on, never a setting; TIDAL untouched).
Persistent failures land in a scan-excluded "Waves Quarantine" folder inside
the library root plus a provider-scoped skip-list that bulk runs auto-skip.
REDOWNLOAD is the explicit re-ask and clears when a verified copy lands.

Pure standard library plus mutagen/ffprobe reads, no Qt, so it unit tests
without the GUI stack. The download runner (backend) owns retry pacing,
queue wording and ownership; this module owns the pure decisions: what the
failure words are, what counts as outbreak-era, and where quarantine files go.
"""

from __future__ import annotations

import datetime
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger("waves.apple_integrity")

# The queue row's plain-words verdict after the retry cap. Counted as failed,
# covered by RETRY ALL. The em dash is the spec's own wording.
INTEGRITY_FAIL_MESSAGE: str = "failed integrity check \u2014 quarantined"

# The quarantine folder's fixed name. The library scan excludes exactly this
# name (see library_index), so a quarantined file can never badge IN LIBRARY.
# A custom quarantine location keeps this folder's role; only its parent moves.
QUARANTINE_DIR_NAME: str = "Waves Quarantine"

# Outbreak pre-filter: Apple's own ALAC encoder has emitted malformed packets
# since ~May 2025 (research/alac-verification). An outbreak-era file
# quarantines after 1 retry instead of the normal 2: re-fetching known-bad
# Apple sources is pure waste.
OUTBREAK_YEAR: int = 2025
OUTBREAK_MONTH: int = 5

# How an Encoded date can arrive: ffmpeg creation_time ("2025-06-23T04:06:21Z"),
# mutagen freeform text, or a bare "2025-06-23" / "20250623". The year-month is
# all the pre-filter needs; a day that cannot be parsed still yields its month.
_DATE_RE = re.compile(r"(19|20)\d{2}[-_/.]?(0[1-9]|1[0-2])(?:[-_/.]?\d{1,2})?")


def resolve_quarantine_dir(download_base: str | Path, custom: str | Path | None = None) -> Path:
    """Where quarantined Apple files land.

    Empty custom means the default: <download_base>/Waves Quarantine. A set
    custom value is the full folder path (absolute, or ~/expanded). The folder
    is created on use, never here.
    """
    text = str(custom or "").strip()
    if text:
        return Path(os.path.expanduser(text))
    return Path(os.path.expanduser(str(download_base or ""))) / QUARANTINE_DIR_NAME


def quarantine_dest(quarantine_root: str | Path, relative: str, extension: str = ".m4a") -> Path:
    """The quarantine path for one track: the intended relative path, kept.

    Files keep their intended names (same relative path and stem as the
    library copy) so a later verified copy replaces them by name and a human
    can tell what failed. Numbered on collision, mirroring pick_destination,
    so two same-named failures never share a name.
    """
    relative = str(relative or "").strip().lstrip("/\\")
    if not relative:
        raise ValueError("quarantine destination needs a relative path")  # noqa: TRY003
    parent = Path(str(quarantine_root)).expanduser() / Path(relative).parent
    parent.mkdir(parents=True, exist_ok=True)
    stem = Path(relative).name
    candidate = parent / f"{stem}{extension}"
    index = 0
    while candidate.exists():
        index += 1
        candidate = parent / f"{stem}_{index:02d}{extension}"
    return candidate


def parse_encoded_date(text: str | None) -> datetime.date | None:
    """An Encoded/creation date string onto a date, or None when unreadable.

    Accepts ffmpeg creation_time, ISO dates, and compact YYYYMMDD. Only the
    year-month-day matters; time and timezone are dropped.
    """
    if not text:
        return None
    match = _DATE_RE.search(str(text))
    if not match:
        return None
    digits = re.sub(r"\D", "", match.group(0))
    try:
        if len(digits) >= 8:
            return datetime.date(int(digits[0:4]), int(digits[4:6]), int(digits[6:8]))
        if len(digits) >= 6:
            return datetime.date(int(digits[0:4]), int(digits[4:6]), 1)
    except ValueError:
        return None
    return None


def is_outbreak_era(encoded_date: datetime.date | str | None) -> bool:
    """Whether an Encoded date falls in the outbreak window (>= 2025-05)."""
    if isinstance(encoded_date, str):
        encoded_date = parse_encoded_date(encoded_date)
    if not isinstance(encoded_date, datetime.date):
        return False
    return (encoded_date.year, encoded_date.month) >= (OUTBREAK_YEAR, OUTBREAK_MONTH)


def encoded_date_of(path: str | Path, ffprobe_path: str = "") -> datetime.date | None:
    """A staged Apple file's Encoded/creation date, or None when unknown.

    ffprobe first (format + stream creation_time, the research's signal),
    mutagen freeform second. Unknown stays unknown: the normal retry budget
    applies, never the sharpened one. Never raises; a date read must not fail
    a download that verification already passed.
    """
    target = Path(str(path))
    if not target.is_file():
        return None
    probed = _ffprobe_creation_date(target, ffprobe_path)
    if probed is not None:
        return probed
    return _mutagen_encoded_date(target)


def _ffprobe_creation_date(path: Path, ffprobe_path: str) -> datetime.date | None:
    import json
    import shutil
    import subprocess

    ffprobe = str(ffprobe_path or "").strip() or (shutil.which("ffprobe") or "")
    if not ffprobe:
        # Nothing to probe with means unknown, not an error.
        return None
    try:
        proc = subprocess.run(  # noqa: S603 (resolved binary, fixed argv)
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format_tags=creation_time:stream_tags=creation_time",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    try:
        payload = json.loads(proc.stdout or "{}")
    except ValueError:
        return None
    for text in _creation_candidates(payload):
        parsed = parse_encoded_date(text)
        if parsed is not None:
            return parsed
    return None


def _creation_candidates(payload: dict) -> list[str]:
    """Every creation/encoded date string an ffprobe JSON payload carries."""
    import contextlib

    candidates: list[str] = []
    with contextlib.suppress(Exception):
        tags = (payload.get("format") or {}).get("tags") or {}
        if isinstance(tags, dict):
            for key in ("creation_time", "creationdate", "encoded_date"):
                if tags.get(key):
                    candidates.append(str(tags[key]))
        for stream in payload.get("streams") or []:
            tags = (stream or {}).get("tags") or {}
            if isinstance(tags, dict) and any(tags.get(key) for key in ("creation_time", "creationdate", "encoded_date")):
                for key in ("creation_time", "creationdate", "encoded_date"):
                    if tags.get(key):
                        candidates.append(str(tags[key]))
    return candidates


def _mutagen_encoded_date(path: Path) -> datetime.date | None:
    try:
        from mutagen.mp4 import MP4
    except Exception:
        return None
    try:
        tags = MP4(str(path)).tags or {}
    except Exception:
        return None
    for key in (
        "----:com.apple.iTunes:Encoded Date",
        "----:com.apple.iTunes:encoded_date",
        "----:com.apple.iTunes:creation_time",
        "\xa9day",
        "trkn",
    ):
        values = tags.get(key)
        if not values:
            continue
        items = list(values) if isinstance(values, (list, tuple)) else [values]
        for item in items:
            if isinstance(item, bytes):
                try:
                    item = item.decode("utf-8", "replace")
                except Exception:
                    logger.debug("Could not decode an Encoded date tag value", exc_info=True)
                    continue
            parsed = parse_encoded_date(str(item))
            if parsed is not None:
                return parsed
    return None


def integrity_retries(settings_data, *, outbreak: bool = False) -> int:
    """Automatic re-downloads after an integrity failure (not total attempts).

    Normal files get the tunable count (default 2); outbreak-era files get at
    most 1: re-fetching known-bad Apple sources is pure waste. Never negative.
    """
    try:
        configured = int(getattr(settings_data, "apple_integrity_retries", 2))
    except (TypeError, ValueError):
        configured = 2
    configured = max(0, configured)
    if outbreak:
        return min(configured, 1)
    return configured


def integrity_retry_delay(settings_data) -> float:
    """Seconds between integrity retries: brief pacing, tunable in Advanced."""
    try:
        delay = float(getattr(settings_data, "apple_integrity_retry_delay_sec", 5.0))
    except (TypeError, ValueError):
        return 5.0
    return max(0.0, delay)
