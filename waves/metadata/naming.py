"""TIDAL objects to the names the library writes.

Artist credits, album credits and titles: the one place that decides what a
tidalapi object contributes to a filename or a tag. Pure formatting; the
provider seam's session and query helpers live in
:mod:`waves.providers.tidal_client`.
"""

from __future__ import annotations

from tidalapi import Album, Mix, Playlist, Track, Video
from tidalapi.artist import Artist, Role


def name_builder_artist(media: Track | Video | Album, delimiter: str = ", ") -> str:
    """Builds a string of artist names for a track, video, or album.

    Returns a delimited string of all artist names associated with the given media.

    Args:
        media (Track | Video | Album): The media object to extract artist names from.
        delimiter (str, optional): The delimiter to use between artist names. Defaults to ", ".

    Returns:
        str: A delimited string of artist names.
    """
    return delimiter.join(artist.name or "" for artist in media.artists or [])


def get_album_artist_objects(media: Track | Album) -> list[Artist]:
    """The album's main-credit artists, in the album's own order.

    The one place the main-credit filter lives, so neither the names written to
    a tag nor the ids written beside them can carry an artist the other's filter
    excluded. The two are not positionally aligned, though: the ids drop an
    id-less stub, and the name tag can be collapsed to the primary by a user
    setting (the engine's tag writer applies it; see waves/download.py). Never
    pair them by index.
    """
    # A playlist can carry a track whose album block never arrived, so the
    # album credit is simply unknown. Answer "no album artists" rather than
    # raising: the track still has its own artists and still deserves to land.
    album = media.album if isinstance(media, Track) else media
    artists: list[Artist] = (getattr(album, "artists", None) or []) if album is not None else []

    # Albums from TIDAL's V2 home feed carry artists without a role/type
    # field, so tidalapi leaves .roles as None: treat the missing information
    # as a main credit rather than crashing on the lookup.
    return [artist for artist in artists if artist.roles is None or Role.main in artist.roles]


def get_album_artists(media: Track | Album) -> list[str]:
    return [artist.name or "" for artist in get_album_artist_objects(media)]


def get_album_artist_ids(media: Track | Album) -> list[str]:
    """TIDAL ids for the same album artists :func:`get_album_artists` names.

    Ids only, so an id-less stub artist is dropped rather than written as an
    empty value. That makes this a set of identities, not a positional mirror
    of the name tag: the album-artist NAME tag can be collapsed to the primary
    by a user setting (the engine's tag writer applies it; see
    waves/download.py), and identity should not shrink because a display
    preference did.
    """
    return [str(artist.id) for artist in get_album_artist_objects(media) if getattr(artist, "id", None)]


def name_builder_album_artist(media: Track | Album, first_only: bool = False, delimiter: str = ", ") -> str:
    """Builds a string of main album artist names for a track or album.

    Returns a delimited string of main artist names from the album, optionally including only the first main artist.

    Args:
        media (Track | Album): The media object to extract artist names from.
        first_only (bool, optional): If True, only the first main artist is included. Defaults to False.
        delimiter (str, optional): The delimiter to use between artist names. Defaults to ", ".

    Returns:
        str: A delimited string of main album artist names.
    """
    album_artists = get_album_artists(media)

    if first_only:
        # An album with no main-artist credit (various-artists edge cases)
        # must not fail the whole download with an IndexError.
        return album_artists[0] if album_artists else ""

    return delimiter.join(album_artists)


def name_builder_title(media: Track | Video | Mix | Playlist | Album | Video) -> str:
    if isinstance(media, Mix):
        return media.title

    full_name = getattr(media, "full_name", None)
    return full_name if full_name is not None else media.name or ""


def name_builder_item(media: Track | Video) -> str:
    return f"{name_builder_artist(media)} - {name_builder_title(media)}"
