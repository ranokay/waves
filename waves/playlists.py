"""Playlist files (m3u8) for landed downloads, one writer for every provider.

The TIDAL engine and the Apple landings both promise `_Name.m3u8` per folder a
run filled. The writer here owns the whole shape: names sanitized like every
other library path, an existing legacy `.m3u` kept rather than shadowed, the
collection's own order applied only when the folder agrees with what the run
landed (a partial run must not shrink a complete playlist), symlink entries
written as the link's relative target, and the bytes staged through a hidden
temp sibling and swapped in atomically.
"""

from __future__ import annotations

import contextlib
import logging
import os
import pathlib
from collections.abc import Callable

from pathvalidate import sanitize_filename

from waves.constants import (
    PLAYLIST_EXTENSION,
    PLAYLIST_EXTENSION_LEGACY,
    PLAYLIST_PREFIX,
    AudioExtensionsValid,
)
from waves.helper.path import (
    name_comparison_key,
    path_file_sanitize,
    sanitize_name_component,
    staging_path,
    strip_apple_double,
)

logger = logging.getLogger("waves.playlists")


def populate_playlists(
    dirs_scoped: set[pathlib.Path],
    name_list: str,
    *,
    is_album: bool,
    sort_alphabetically: bool,
    paths_ordered: list[pathlib.Path] | None = None,
    illegal_replacement: str = "",
    illegal_map: dict[str, str] | None = None,
    log: Callable[[str], None] | None = None,
    best_effort: bool = False,
) -> list[pathlib.Path]:
    """Create one playlist file per directory a download filled.

    ``paths_ordered`` is the collection's landed file paths in its own track
    order: each directory's playlist lists exactly those files in that order
    when the folder agrees on the contents, which is what makes a downloaded
    playlist play back in the provider's order. Without it (or when the folder
    disagrees) the directory is globbed and sorted by name or file age, which
    reconstructs an album's order from numbered filenames but knows nothing of
    a playlist's.

    ``best_effort`` keeps one directory's failure to itself: the other
    directories still get their playlists, and the error is logged instead of
    raised (the Apple landings' contract; the engine fails loudly).

    Args:
        dirs_scoped (set[pathlib.Path]): Directories the run lands files in.
        name_list (str): The playlist or album's display name.
        is_album (bool): Whether a stand-down listing follows album rules.
        sort_alphabetically (bool): Stand-down sort: name when true, else file
            age for playlists.
        paths_ordered (list[pathlib.Path] | None): The run's landed paths in
            collection order.
        illegal_replacement (str): The general stand-in for rejected chars.
        illegal_map (dict[str, str] | None): Per-character stand-ins.
        log (Callable[[str], None] | None): Receives each final playlist name.
        best_effort (bool): Log and continue when one directory fails.

    Returns:
        list[pathlib.Path]: The playlist files written.
    """
    result: list[pathlib.Path] = []
    for dir_scoped in dirs_scoped:
        try:
            result.append(
                _write_one_playlist(
                    dir_scoped,
                    name_list,
                    is_album=is_album,
                    sort_alphabetically=sort_alphabetically,
                    paths_ordered=paths_ordered,
                    illegal_replacement=illegal_replacement,
                    illegal_map=illegal_map,
                    log=log,
                )
            )
        except (OSError, ValueError):
            if not best_effort:
                raise
            logger.debug("Could not write a playlist file in %s", dir_scoped, exc_info=True)
    return result


def _write_one_playlist(
    dir_scoped: pathlib.Path,
    name_list: str,
    *,
    is_album: bool,
    sort_alphabetically: bool,
    paths_ordered: list[pathlib.Path] | None,
    illegal_replacement: str,
    illegal_map: dict[str, str] | None,
    log: Callable[[str], None] | None,
) -> pathlib.Path:
    """One directory's playlist file, written and swapped into place."""
    # Spelled like every other name in the library: the per-character stand-ins
    # first, then the general one, then the spacing tidy. Passing the whole
    # "_<name>.m3u" string to pathvalidate with no stand-ins would make a
    # playlist called "?" come out as the bare prefix while an album called "?"
    # keeps its name.
    name_sanitized: str = sanitize_name_component(name_list, illegal_replacement, illegal_map)
    path_playlist = dir_scoped / sanitize_filename(PLAYLIST_PREFIX + name_sanitized + PLAYLIST_EXTENSION)
    path_playlist = pathlib.Path(path_file_sanitize(path_playlist, adapt=True))

    # A playlist file the library already holds keeps its name: releases before
    # the .m3u8 spelling wrote .m3u, and older spellings could leave the doubled
    # space a removed character created. Writing the new name beside an old one
    # would leave two files for one playlist, both ingested by a library
    # scanner, and the stale one can never be removed (prevention-only
    # cleanup). Most recent spelling first.
    for stem, extension in (
        (name_sanitized, PLAYLIST_EXTENSION_LEGACY),
        (name_list, PLAYLIST_EXTENSION_LEGACY),
    ):
        if path_playlist.is_file():
            break

        path_playlist_legacy = dir_scoped / sanitize_filename(PLAYLIST_PREFIX + stem + extension)
        path_playlist_legacy = pathlib.Path(path_file_sanitize(path_playlist_legacy, adapt=True))

        if path_playlist_legacy.name != path_playlist.name and path_playlist_legacy.is_file():
            path_playlist = path_playlist_legacy
            break

    # The NAME only, and as content: the full path spells out the download
    # root, which normally sits under the user's home.
    if log is not None:
        log(path_playlist.name)

    path_tracks: list[pathlib.Path] = _playlist_entries(dir_scoped, is_album, sort_alphabetically, paths_ordered)

    # Write the m3u the way every other file reaches the library: into a hidden
    # temp sibling, flushed to stable storage, then swapped into the real name.
    # Opening the real name in truncating mode would leave an emptied or
    # half-written playlist behind after a crash, a full disk or a share going
    # away mid-write. This is the only file the engine writes at its
    # destination rather than moving into place, so it needs the swap spelled
    # out here (the pattern mirrors BaseConfig.save and _stage_and_swap).
    # Through staging_path, never hand-decorated: the sanitizer fits the FINAL
    # name to the caps, and 42 unbudgeted characters on top of a name at the cap
    # would make the temp unopenable, failing the whole job at its very last
    # step with every track already landed.
    path_playlist_tmp: pathlib.Path = staging_path(path_playlist)

    try:
        with path_playlist_tmp.open(mode="w", encoding="utf-8") as f:
            for path_track in path_tracks:
                # A symlink entry names the real track relative to the link's
                # own folder, so the playlist plays from a folder that only
                # links into the track tree.
                if path_track.is_symlink():
                    try:
                        media_file_target = path_track.resolve().relative_to(path_track.parent, walk_up=True)
                    except (OSError, ValueError):
                        # resolve() can spell the target on a different anchor
                        # than the link's own folder: a Windows mapped drive
                        # resolves to its UNC name, so the two are 'Z:\...' and
                        # '\\server\share\...', and relating them raises
                        # ValueError. The link's own name plays exactly as well:
                        # a player follows the link the way it followed the
                        # relative target.
                        media_file_target = path_track.name
                else:
                    media_file_target = path_track.name

                # Write a plain '\n'; text mode ('w') translates it to the
                # platform line ending. os.linesep here would double-translate
                # on Windows ('\r\n' -> '\r\r\n').
                f.write(str(media_file_target) + "\n")

            f.flush()
            os.fsync(f.fileno())

        path_playlist_tmp.replace(path_playlist)
    except (OSError, ValueError):
        # Never leave the throwaway behind, and never let a failing cleanup
        # mask what actually went wrong. ValueError is here so the cleanup is
        # never narrower than the body it guards: a path comparison inside can
        # raise it, and the temp would then survive every attempt.
        with contextlib.suppress(OSError):
            path_playlist_tmp.unlink(missing_ok=True)

        raise

    # Written directly at the destination, so it needs the same AppleDouble
    # cleanup the moved files get.
    strip_apple_double(path_playlist)

    return path_playlist


def _playlist_entries(
    dir_scoped: pathlib.Path,
    is_album: bool,
    sort_alphabetically: bool,
    paths_ordered: list[pathlib.Path] | None,
) -> list[pathlib.Path]:
    """One directory's playlist lines, in playback order (two stand-down modes:
    name sort, or file age for playlists)."""
    # Every audio file the directory holds, which is what an m3u describes. The
    # ordered list below is only allowed to REORDER this, never to shorten it.
    path_tracks: list[pathlib.Path] = []

    for extension_audio in AudioExtensionsValid:
        # pathlib's glob matches hidden files, so filter dotfiles: macOS
        # AppleDouble ghosts (._Track.flac) must never become playlist entries.
        path_tracks = path_tracks + [p for p in dir_scoped.glob(f"*{extension_audio!s}") if not p.name.startswith(".")]

    # Sort alphabetically, e.g. if items are prefixed with numbers
    if sort_alphabetically:
        path_tracks.sort()
    elif not is_album:
        # If it is not an album sort by creation time
        def _born(p: pathlib.Path) -> float:
            try:
                st = p.stat()
            except OSError:
                # A playlist-folder entry is a symlink into the track tree, and
                # a target on a share that is away cannot be stat'd. It still
                # belongs in the list, so it sorts oldest-first rather than
                # taking the whole write down with it.
                return 0.0
            return float(getattr(st, "st_birthtime", st.st_ctime))

        path_tracks.sort(key=_born)

    if paths_ordered is None:
        return path_tracks

    # The collection's own order, but only when this run can account for every
    # file in the folder. A run reports back only what it actually fetched: a
    # re-download skips the tracks you already have, a cancelled run stops
    # partway, an item can fail. Writing just those, on a folder that already
    # held a full playlist, would REPLACE a complete m3u with a one-line one,
    # which is the file equivalent of losing the playlist. So the folder is the
    # truth about what belongs in the list, and this run's order is applied to
    # it only when the two agree on the contents; otherwise the folder listing
    # stands.
    # Matched on the key two spellings of one file share, not on the raw path:
    # a normalizing filesystem (HFS+ externals, several NAS shares) stores an
    # accented name as NFD while this run writes it as NFC, and those compare
    # unequal. Every accented track would then miss the folder set, the counts
    # could not agree, and the provider's order would stand down on exactly the
    # libraries most likely to hold accented titles, silently.
    here: dict[str, pathlib.Path] = {}
    for landed in path_tracks:
        here.setdefault(name_comparison_key(str(landed)), landed)
    # First occurrences only: a playlist can carry the same track twice, and
    # both occurrences land on ONE file (the name ledger lets an item retake
    # its own name), so the raw ordered list could hold that path twice, could
    # never match the folder's count, and the order fix would silently stand
    # down for exactly those playlists. One entry per file keeps the order; the
    # duplicate spin is the playlist's business, not the m3u's.
    seen: set[str] = set()
    ordered: list[pathlib.Path] = []

    for wrote in paths_ordered:
        key = name_comparison_key(str(wrote))

        if key in seen or key not in here:
            continue

        seen.add(key)
        # The folder's spelling, never this run's: the m3u has to name each
        # file the way the filesystem actually stores it.
        ordered.append(here[key])

    return ordered if len(ordered) == len(path_tracks) else path_tracks
