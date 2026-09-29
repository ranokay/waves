"""Thin wrappers over tidalapi's session surface.

Search paging, collection expansion, URL parsing and media instantiation for
the TIDAL provider. Name and credit formatting lives in
:mod:`waves.metadata.naming`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from tidalapi import Album, Mix, Playlist, Session, Track, UserPlaylist, Video
from tidalapi.artist import Artist
from tidalapi.media import MediaMetadataTags, Quality
from tidalapi.types import OrderDirection, PlaylistOrder
from tidalapi.user import LoggedInUser

from waves.constants import MediaType
from waves.errors import MediaUnknown

logger = logging.getLogger(__name__)


def get_tidal_media_id(url_or_id_media: str) -> str:

    id_dirty = url_or_id_media.rsplit("/", 1)[-1]
    id_media = id_dirty.rsplit("?", 1)[0]

    return id_media


def get_tidal_media_type(url_media: str) -> MediaType | bool:
    result: MediaType | bool = False
    url_split = url_media.split("/")[-2]

    if len(url_split) > 1:
        media_name = url_media.split("/")[-2]

        if media_name == "track":
            result = MediaType.TRACK
        elif media_name == "video":
            result = MediaType.VIDEO
        elif media_name == "album":
            result = MediaType.ALBUM
        elif media_name == "playlist":
            result = MediaType.PLAYLIST
        elif media_name == "mix":
            result = MediaType.MIX
        elif media_name == "artist":
            result = MediaType.ARTIST

    return result


def search_results_all(
    session: Session, needle: str, types_media: list[object] | None = None, single_page: bool = False
) -> dict[str, list]:
    """Search TIDAL, accumulating every page of results per type.

    ``single_page=True`` stops after the first page (300 per type): a caller
    that keeps only a bounded head of each list (the GUI keeps at most 80 of
    any type) pays one round-trip instead of several serial ones whose extra
    rows it immediately discards. Exhaustive paging stays the default.
    """
    limit: int = 300
    offset: int = 0
    result: dict[str, list] = {}

    while True:
        # tidalapi's SearchResults TypedDict carries the same per-type buckets.
        tmp_result: dict[str, list] = session.search(  # ty: ignore[invalid-assignment]
            query=needle, models=types_media, limit=limit, offset=offset
        )

        has_page_results: bool = False

        for key, value in tmp_result.items():
            if key == "top_hit":
                # TIDAL names one best match for the query on the first page
                # (an artist, album, track, video or playlist object, or
                # None). Carried through untouched; the per-type lists below
                # are what the paging accumulates.
                if offset == 0:
                    result[key] = value
                continue

            # init the list
            if offset == 0:
                result[key] = []

            if isinstance(value, list) and value:
                result[key].extend(value)
                has_page_results = True

        if single_page or not has_page_results:
            break

        offset += limit

    return result


def items_results_all(
    media: Mix | Playlist | Album | Artist, videos_include: bool = True
) -> list[Track | Video | Album]:
    result: list[Track | Video | Album] = []

    if isinstance(media, Mix):
        result = media.items()  # ty: ignore[invalid-assignment]  # mix items are Track|Video; the local carries the wider union

        if not videos_include:
            # A mix is the one collection whose items() hands back tracks and
            # videos together (an album or a playlist has a .tracks call to ask
            # instead, used just below). Without this the "music videos" switch
            # was silently ignored for mixes: full .mp4 videos landed in the
            # mix folder, counted as real writes, whatever the setting said.
            result = [item for item in result if not isinstance(item, Video)]
    else:
        func_get_items_media: list[Callable] = []

        if isinstance(media, Playlist | Album):
            if videos_include:
                func_get_items_media.append(media.items)
            else:
                func_get_items_media.append(media.tracks)
        else:
            func_get_items_media.append(media.get_albums)
            func_get_items_media.append(media.get_ep_singles)

        result = paginate_results(func_get_items_media)  # ty: ignore[invalid-assignment]  # the paginate family returns the wide union

    return result


def paginate_results(func_get_items_media: list[Callable]) -> list[Track | Video | Album | Playlist | UserPlaylist]:
    result: list[Track | Video | Album | Playlist | UserPlaylist] = []

    for func_media in func_get_items_media:
        limit: int = 100
        offset: int = 0
        done: bool = False

        if func_media.__func__ == LoggedInUser.playlist_and_favorite_playlists:
            limit: int = 50

        while not done:
            tmp_result: list[Track | Video | Album | Playlist | UserPlaylist] = func_media(limit=limit, offset=offset)

            if bool(tmp_result):
                result += tmp_result
                # Get the next page in the next iteration.
                offset += limit
            else:
                done = True

    return result


# The v2 collection endpoints cap a page at 50.
_ROOT_PLAYLIST_PAGE = 50


def _page_root_playlists(
    favorites, order: PlaylistOrder, direction: OrderDirection, expected: int | None
) -> tuple[list, int]:
    """Every root playlist in ``order``, one page after another, each id once.

    Returns the playlists in the server's order and how many rows the pages
    repeated. A short page ends the pass only once ``expected`` rows are in
    hand (the server drops an unavailable playlist from its window, which
    must not cost every page after it); an empty page, or one that brings
    nothing new, always ends it, so a server that ignored the offset could
    never loop here forever.
    """
    result: list = []
    seen: set[str] = set()
    repeats = 0
    offset = 0
    while True:
        batch = favorites.playlists(limit=_ROOT_PLAYLIST_PAGE, offset=offset, order=order, order_direction=direction)
        if not batch:
            break
        fresh = [p for p in batch if str(p.id) not in seen]
        if not fresh:
            break
        repeats += len(batch) - len(fresh)
        seen.update(str(p.id) for p in fresh)
        result.extend(fresh)
        if len(batch) < _ROOT_PLAYLIST_PAGE and (expected is None or len(result) >= expected):
            break
        offset += _ROOT_PLAYLIST_PAGE
    return result, repeats


def _root_playlists(favorites, root_folder_count: int) -> list:
    """The account's root playlists, newest first, each exactly once (#46).

    tidalapi's ``playlists_paginated`` fetched its pages in parallel, sorted by
    creation date. Playlists created together (an import from another service
    stamps a whole batch with one date) tie on that key, and the server breaks
    the tie differently for each page, so one playlist came back on two or
    three pages while others fell off the list. Its total also counted the root
    folders, which the playlist pages never return.

    Here the pages are read one after another in the same newest-first order
    (the list's default order in My Tidal, which the rows themselves cannot
    always restore: the v2 rows carry their added date outside the part
    tidalapi parses), keeping every row once by id. If that still comes up
    short of the account's own count, a pass sorted by name, where ties are
    rare, fills the gaps at the end of the list.
    """
    try:
        expected = int(favorites.get_playlists_count()) - root_folder_count
    except Exception:
        logger.info("Root playlist count unavailable; paging until the pages run out")
        expected = None
    by_id: dict[str, object] = {}
    repeats = 0
    for order, direction in (
        (PlaylistOrder.DateCreated, OrderDirection.Descending),
        (PlaylistOrder.Name, OrderDirection.Ascending),
    ):
        page, repeated = _page_root_playlists(favorites, order, direction, expected)
        repeats += repeated
        for playlist in page:
            by_id.setdefault(str(playlist.id), playlist)
        if expected is None or len(by_id) >= expected:
            break
    if repeats:
        logger.info("Root playlist pages repeated %d rows; kept %d playlists", repeats, len(by_id))
    if expected is not None and len(by_id) < expected:
        logger.warning("Root playlist listing is short: %d of %d", len(by_id), expected)
    return list(by_id.values())


def user_media_lists(session: Session) -> dict[str, list]:
    """Fetch the user's root playlists and folders, and their mixes.

    Returns a dictionary with 'playlists' and 'mixes' keys containing lists of media items.
    For playlists, includes both Folder and Playlist objects at the root level.

    Args:
        session (Session): TIDAL session object.

    Returns:
        dict[str, list]: Dictionary with 'playlists' (includes Folder and Playlist) and 'mixes' lists.
    """
    # Fetch root-level folders manually (no paginated version available)
    folders = []
    offset = 0
    limit = 50

    while True:
        batch = session.user.favorites.playlist_folders(limit=limit, offset=offset, parent_folder_id="root")
        if not batch:
            break
        folders.extend(batch)
        if len(batch) < limit:
            break
        offset += limit

    playlists = _root_playlists(session.user.favorites, len(folders))

    # Combine folders and playlists
    all_playlists = folders + playlists

    # Get mixes. Degrade to "no mixes" on any failure: this is the LAST
    # statement, so an unguarded raise here throws away all the playlist and
    # folder paging above, nothing gets cached, every retry repeats the whole
    # sweep, and the user reads "0 playlists" instead of an error.
    user_mixes: list = []
    try:
        categories = session.mixes().categories or []
        if categories:
            # The parsed category's items are a list; some stub members type
            # the same attribute as a method.
            user_mixes = categories[0].items  # ty: ignore[invalid-assignment]
    except Exception:
        logger.exception("Could not load the user's mixes; keeping the playlists")

    return {"playlists": all_playlists, "mixes": user_mixes}


def instantiate_media(
    session: Session,
    media_type: MediaType,
    id_media: str,
) -> Track | Video | Album | Playlist | Mix | Artist:
    if media_type == MediaType.TRACK:
        media = session.track(id_media, with_album=True)
    elif media_type == MediaType.VIDEO:
        media = session.video(id_media)
    elif media_type == MediaType.ALBUM:
        media = session.album(id_media)
    elif media_type == MediaType.PLAYLIST:
        media = session.playlist(id_media)
    elif media_type == MediaType.MIX:
        media = session.mix(id_media)
    elif media_type == MediaType.ARTIST:
        media = session.artist(id_media)
    else:
        raise MediaUnknown

    return media


def quality_audio_highest(media: Track | Album) -> Quality:
    quality: Quality
    tags = media.media_metadata_tags
    if tags is None:
        # tidalapi leaves this None on tracks TIDAL flags allowStreaming=false.
        # The TypeError is the "no answer" sentinel that backend's
        # advertised_tier and _quality_rank catch; keep it deliberate.
        raise TypeError("quality_audio_highest: media_metadata_tags is None")  # noqa: TRY003

    if MediaMetadataTags.hi_res_lossless in tags:
        quality = Quality.hi_res_lossless
    elif MediaMetadataTags.lossless in tags:
        quality = Quality.high_lossless
    else:
        # The stub types audio_quality as str | None; at runtime it is the
        # wire's quality string, which the str-enum members compare equal to.
        quality = media.audio_quality  # ty: ignore[invalid-assignment]

    return quality
