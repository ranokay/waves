"""Apple file layout: template paths, tags and sidecars for Apple downloads.

The shared template engine (helper.path) only speaks tidalapi objects, so
Apple rows get a small dedicated formatter covering the same music-template
vocabulary from row-dict fields, sanitized the same way. Video/mix tokens
have no Apple meaning and render empty; unknown tokens render empty with a
warning, the same spirit as the engine's blanket catch (a token must never
stop a download).

Tagging reuses the neutral Metadata writer with legacy_ids=False: Apple
files carry the generic WAVES_* family only, never the TIDAL legacy trio.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
from pathlib import Path

from pathvalidate import sanitize_filename

from waves.constants import (
    FORMAT_TEMPLATE_EXPLICIT,
    METADATA_LOOKUP_UPC,
    PLAYLIST_EXTENSION,
    PLAYLIST_PREFIX,
    MetadataTargetUPC,
)
from waves.helper.path import (
    _drop_empty_segments,
    calculate_number_padding,
    path_file_sanitize,
    sanitize_name_component,
)
from waves.metadata import Metadata

logger = logging.getLogger("waves.apple_files")


def _raw_apple_id(value: object) -> str:
    return str(value or "").removeprefix("apple:")


def format_apple_path(
    template: str,
    *,
    track: dict,
    album: dict | None = None,
    playlist: dict | None = None,
    list_pos: int = 0,
    list_total: int = 0,
    num_volumes: int = 1,
    isrc: str = "",
    pad_min: int = 1,
    delimiter_artist: str = ", ",
    delimiter_album_artist: str = ", ",
    illegal_replacement: str = "",
    illegal_map: dict[str, str] | None = None,
    provider_name: str = "Apple Music",
) -> str:
    """A settings template rendered for one Apple track, sanitized per token."""

    def clean(value: object) -> str:
        text = str(value or "")
        # The explicit marker carries a leading space the sanitizer would eat
        # (the shared template engine exempts it for the same reason).
        if text == FORMAT_TEMPLATE_EXPLICIT:
            return text
        return sanitize_name_component(text, illegal_replacement, illegal_map)

    track_num = int(track.get("num") or 0)
    vol = int(track.get("vol") or 1)
    album_tracks = int((album or {}).get("tracks") or list_total or 0)
    padded_num = calculate_number_padding(pad_min, track_num, album_tracks) if track_num else ""
    album_year = str((album or {}).get("year") or track.get("year") or "")
    album_date = str((album or {}).get("date") or track.get("date") or "")
    album_title = str((album or {}).get("title") or track.get("album") or "")
    album_artist = str((album or {}).get("artist") or track.get("artist") or "")
    artist_names = [a.get("name") for a in track.get("artists") or [] if isinstance(a, dict) and a.get("name")]
    artists_full = track.get("artist") or ""
    album_artists = (
        delimiter_album_artist.join(
            [a.get("name") for a in (album or {}).get("artists") or [] if isinstance(a, dict) and a.get("name")]
        )
        or album_artist
    )
    values: dict[str, str] = {
        "artist_name": artists_full,
        "artist_name_primary": (artist_names or [artists_full])[0] if (artist_names or artists_full) else "",
        "album_artist": album_artist,
        "album_artists": album_artists,
        "track_title": str(track.get("title") or ""),
        "album_title": album_title,
        "playlist_name": str((playlist or {}).get("title") or ""),
        "album_track_num": padded_num,
        "album_num_tracks": str(album_tracks) if album_tracks else "",
        "album_num_volumes": str(num_volumes) if num_volumes > 1 else "",
        "track_volume_num": str(track.get("vol") or 1),
        "track_volume_num_optional": "" if num_volumes <= 1 else f"{vol}-",
        "track_volume_num_optional_CD": "" if num_volumes <= 1 else f"CD{vol}",
        "list_pos": str(list_pos) if list_pos else "",
        "list_total": str(list_total) if list_total else "",
        "album_year": album_year,
        "album_date": album_date,
        "track_id": _raw_apple_id(track.get("id") or ""),
        "album_id": _raw_apple_id((album or {}).get("id") or track.get("album_id") or ""),
        "track_artist_id": _raw_apple_id(track.get("artist_id") or ""),
        "album_artist_id": _raw_apple_id((album or {}).get("artist_id") or ""),
        "isrc": isrc,
        "track_duration_seconds": str(track.get("duration_sec") or ""),
        "track_duration_minutes": str(int(track.get("duration_sec") or 0) // 60),
        "track_quality": str(track.get("quality") or ""),
        "track_explicit": FORMAT_TEMPLATE_EXPLICIT if track.get("explicit") else "",
        "album_explicit": FORMAT_TEMPLATE_EXPLICIT if (album or {}).get("explicit") else "",
        "media_type": "",
        "folder_path": "",
        # Provider separation (issue #65): "" renders the token as "" so the
        # segment collapses away (the pre-token layout).
        "provider_name": provider_name,
    }

    def replace(match: re.Match) -> str:
        token = match.group(1)
        if token not in values:
            logger.warning("path: Apple download has no meaning for the '%s' token", token)
            return ""
        return clean(values[token])

    rendered = re.sub(r"\{(.+?)\}", replace, template)
    # Same traversal safety as the shared engine: a token sanitizing to ""
    # or ".." must not escape the library root (see _drop_empty_segments).
    return _drop_empty_segments(rendered)


def pick_destination(base_dir: str | Path, relative: str, extension: str) -> Path:
    """A free file path under the library: numbered suffix on collision.

    Mirrors the engine's "X_01" step-aside so two same-named tracks never
    share a name (issue #19's lesson), without consulting anything but disk.
    The relative path must stay relative (format_apple_path drops empty and
    dot segments); an absolute or empty one fails loudly instead of escaping
    the library root.
    """
    if not str(relative or "").strip():
        raise ValueError("Apple download rendered an empty relative path")  # noqa: TRY003
    relative_path = Path(relative)
    if relative_path.is_absolute():
        logger.warning("path: Apple relative path escaped to absolute, stripping: %s", relative)
        relative = str(relative).lstrip("/\\")
        relative_path = Path(relative)
    parent = Path(str(base_dir)).expanduser() / relative_path.parent
    parent.mkdir(parents=True, exist_ok=True)
    stem = relative_path.name
    candidate = parent / f"{stem}{extension}"
    index = 0
    while candidate.exists():
        index += 1
        candidate = parent / f"{stem}_{index:02d}{extension}"
    return candidate


def write_text_sidecar(directory: str | Path, stem: str, suffix: str, content: str) -> Path | None:
    """A lyrics sidecar beside the track, written atomically, or None."""
    if not content:
        return None
    target = Path(directory) / f"{stem}{suffix}"
    tmp = target.with_suffix(f"{target.suffix}.tmp")
    try:
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, target)
    except OSError:
        logger.debug("Could not write the Apple lyrics sidecar", exc_info=True)
        return None
    return target


def write_cover_sidecar(directory: str | Path, image: bytes, file_format: str = "jpg") -> Path | None:
    """Cover sidecar beside the track, written atomically, or None.

    ``file_format`` is ``jpg`` (default) or ``png`` on both providers, plus
    ``raw`` on Apple (the true original-master bytes, whose extension follows
    the served image). The format only names the file; the bytes are already
    in that format (embedded art stays jpg per spec section 9.1).
    """
    if not image:
        return None
    fmt = str(file_format or "jpg").strip().lower()
    if fmt not in ("jpg", "jpeg", "png", "raw"):
        fmt = "jpg"
    if fmt == "raw":
        # The raw master arrives as jpg or png; sniff the magic rather than
        # trusting the setting. PNG magic first, else jpg.
        name = "cover.png" if bytes(image[:8]).startswith(b"\x89PNG\r\n\x1a\n") else "cover.jpg"
    elif fmt == "png":
        name = "cover.png"
    else:
        name = "cover.jpg"
    target = Path(directory) / name
    if target.exists():
        return target
    tmp = Path(str(target) + ".tmp")
    try:
        tmp.write_bytes(image)
        os.replace(tmp, target)
    except OSError:
        logger.debug("Could not write the Apple cover sidecar", exc_info=True)
        return None
    return target


def write_collection_playlist(
    landed: list[Path],
    name: str,
    illegal_replacement: str = "",
    illegal_map: dict[str, str] | None = None,
) -> None:
    """The _Name.m3u8 the playlist_create setting promises, per directory.

    Compact mirror of the engine's playlist_populate for Apple landings:
    landed paths in collection order, one file per directory this run filled,
    basenames as entries, written through a temp sibling and swapped in.
    Best-effort throughout: a playlist file must never fail landed tracks.
    """
    if not landed:
        return
    ordered: dict[Path, list[Path]] = {}
    for path in landed:
        ordered.setdefault(path.parent, []).append(path)
    for directory, paths in ordered.items():
        playlist_name = sanitize_filename(
            f"{PLAYLIST_PREFIX}{sanitize_name_component(name, illegal_replacement, illegal_map)}{PLAYLIST_EXTENSION}"
        )
        target = Path(path_file_sanitize(directory / playlist_name, adapt=True))
        tmp = target.with_name(f"{target.name}.tmp")
        try:
            with tmp.open(mode="w", encoding="utf-8") as handle:
                for path in paths:
                    handle.write(path.name + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, target)
        except OSError:
            logger.debug("Could not write the Apple playlist file", exc_info=True)
            with contextlib.suppress(OSError):
                tmp.unlink()


def tag_apple_file(
    path: str | Path,
    *,
    title: str,
    facts: dict,
    lyrics_synced: str = "",
    lyrics_unsynced: str = "",
    cover_data: bytes | None = None,
    mark_explicit: bool = False,
    metadata_target_upc: str = "UPC",
    audio_type: str | None = None,
    # Custom-template omit flags (issue #61): all written by default.
    write_composer: bool = True,
    write_copyright: bool = True,
    write_isrc: bool = True,
    write_bpm: bool = True,
    write_initial_key: bool = True,
    write_upc: bool = True,
) -> bool:
    """Tag one Apple file: generic WAVES_* family only, never TIDAL legacy."""
    album = facts.get("album") or {}
    artists = [name for _id, name in facts.get("artists") or [] if name]
    try:
        meta = Metadata(
            path_file=path,
            target_upc=METADATA_LOOKUP_UPC[MetadataTargetUPC(metadata_target_upc)],
            title=str(title or "") + (" 🅴" if facts.get("explicit") and mark_explicit else ""),
            album=str(album.get("name") or ""),
            artists=artists,
            albumartist=facts.get("album_artists") or [],
            copy_right=facts.get("copyright") or "",
            tracknumber=int(facts.get("track_num") or 0),
            discnumber=int(facts.get("volume_num") or 1),
            totaltrack=int(album.get("num_tracks") or 0),
            totaldisc=0,
            isrc=facts.get("isrc") or "",
            date=str(facts.get("release_date") or ""),
            lyrics=lyrics_synced,
            lyrics_unsynced=lyrics_unsynced,
            cover_data=cover_data,
            url_share=facts.get("share_url") or "",
            upc=str(album.get("upc") or ""),
            explicit=bool(facts.get("explicit", False)),
            replay_gain_write=False,  # Apple serves no ReplayGain; untagged is the rule
            item_id=facts.get("item_id") or "",
            artist_ids=facts.get("artist_ids") or [],
            album_artist_ids=facts.get("album_artist_ids") or [],
            legacy_ids=False,
            audio_type=audio_type,
            write_composer=write_composer,
            write_copyright=write_copyright,
            write_isrc=write_isrc,
            write_bpm=write_bpm,
            write_initial_key=write_initial_key,
            write_upc=write_upc,
        )
    except KeyError:
        logger.debug("Unknown UPC target for Apple tags", exc_info=True)
        return False
    try:
        return bool(meta.save())
    except Exception:
        logger.debug("Could not tag the Apple file", exc_info=True)
        return False
