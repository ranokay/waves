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
from tidalapi.user import LoggedInUser

from waves.constants import FAVORITES, MediaType
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


def url_ending_clean(url: str) -> str:
    """Checks if a link ends with "/u" or "?u" and removes that part.

    Args:
        url (str): The URL to clean.

    Returns:
        str: The cleaned URL.
    """
    return url[:-2] if url.endswith("/u") or url.endswith("?u") else url


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


def all_artist_album_ids(media_artist: Artist) -> list[int | None]:
    func_get_items_media: list[Callable] = [media_artist.get_albums, media_artist.get_ep_singles]
    albums: list[Album] = paginate_results(func_get_items_media)  # ty: ignore[invalid-assignment]  # album/EP callables only return Albums

    return [album.id for album in albums]


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


def user_media_lists(session: Session) -> dict[str, list]:
    """Fetch user media lists using tidalapi's built-in pagination where available.

    Returns a dictionary with 'playlists' and 'mixes' keys containing lists of media items.
    For playlists, includes both Folder and Playlist objects at the root level.

    Args:
        session (Session): TIDAL session object.

    Returns:
        dict[str, list]: Dictionary with 'playlists' (includes Folder and Playlist) and 'mixes' lists.
    """
    # Use built-in pagination for playlists (root level only)
    playlists = session.user.favorites.playlists_paginated()

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


def favorite_function_factory(tidal, favorite_item: str):
    function_name: str = FAVORITES[favorite_item]["function_name"]
    function_list: Callable = getattr(tidal.session.user.favorites, function_name)

    return function_list
