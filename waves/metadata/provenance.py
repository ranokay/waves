"""Descriptive provenance: origin catalog facts beside delivered facts.

ADR 0011: descriptive metadata and organization default to the origin, with an
optional fulfillment policy. A field the origin does not carry may be filled
from the delivered item only when the match is consistent. Technical facts --
the item/artist catalog ids, ISRC, UPC, codec, quality and the delivering
provider -- always describe the delivered file and are never taken from the
origin.

The values here are the existing ``Provider.track_facts`` shape plus ``title``;
the tag and path writers consume them unchanged.
"""

from __future__ import annotations

from typing import Any

from waves.constants import FORMAT_TEMPLATE_EXPLICIT


def origin_facts(identity: Any) -> dict:
    """A ``CatalogIdentity`` as descriptive facts, for a track or an album."""
    kind = str(getattr(identity, "kind", "") or "")
    if kind == "track":
        return {
            "kind": "track",
            "title": str(getattr(identity, "title", "") or ""),
            "version": getattr(identity, "version", None),
            "artist": str(getattr(identity, "artist", "") or ""),
            "album_title": str(getattr(identity, "release_title", "") or ""),
            "album_version": getattr(identity, "release_version", None),
            "album_artist": str(getattr(identity, "release_artist", "") or ""),
            "release_date": str(getattr(identity, "release_date", "") or ""),
            "track_num": getattr(identity, "track_number", None),
            "volume_num": getattr(identity, "disc_number", None),
            "explicit": getattr(identity, "explicit", None),
            "isrc": str(getattr(identity, "identifier", "") or ""),
            "track_count": getattr(identity, "track_count", None),
            "tracks": (),
            "tracks_complete": False,
        }
    if kind == "album":
        return {
            "kind": "album",
            "title": str(getattr(identity, "title", "") or getattr(identity, "release_title", "") or ""),
            "version": getattr(identity, "version", None),
            "artist": str(getattr(identity, "artist", "") or getattr(identity, "release_artist", "") or ""),
            "album_title": str(getattr(identity, "release_title", "") or getattr(identity, "title", "") or ""),
            "album_version": getattr(identity, "release_version", None),
            "album_artist": str(getattr(identity, "release_artist", "") or getattr(identity, "artist", "") or ""),
            "release_date": str(getattr(identity, "release_date", "") or ""),
            "track_num": None,
            "volume_num": None,
            "explicit": getattr(identity, "explicit", None),
            "isrc": "",
            "track_count": getattr(identity, "track_count", None),
            "tracks": tuple(origin_facts(track) for track in getattr(identity, "tracks", ()) or ()),
            "tracks_complete": bool(getattr(identity, "tracks_complete", False)),
        }
    return {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _match_origin_track(origin: dict, delivered: dict) -> dict | None:
    """The one ordered-list entry this delivered track is, or None.

    Ordered track-list evidence is the album match's own evidence: a unique
    disc/track position, or a unique ISRC. No fuzzy promotion: an entry that
    cannot be named uniquely keeps the delivered facts.
    """
    if origin.get("kind") != "album" or not origin.get("tracks_complete"):
        return None
    tracks = [track for track in origin.get("tracks") or () if isinstance(track, dict)]
    if not tracks:
        return None
    track_num = delivered.get("track_num")
    volume_num = delivered.get("volume_num")
    if track_num is not None:
        positional = [
            track
            for track in tracks
            if track.get("track_num") == track_num and track.get("volume_num") in (volume_num, None)
        ]
        if len(positional) == 1:
            return positional[0]
    isrc = _text(delivered.get("isrc")).upper()
    if isrc:
        identified = [track for track in tracks if _text(track.get("isrc")).upper() == isrc]
        if len(identified) == 1:
            return identified[0]
    return None


def _title_with_version(title: str, version: Any) -> str:
    base = _text(title)
    suffix = _text(version)
    return f"{base} ({suffix})" if base and suffix else base


def resolve_track_facts(  # noqa: C901 - one field-by-field provenance rule
    delivered: dict,
    origin: dict | None,
    source: str,
    consistent: bool,
    *,
    delivered_title: str = "",
) -> dict:
    """The tag/path facts this delivered file should carry.

    ``source="origin"`` (the default) overlays the origin's descriptive facts
    and fills a missing origin field from the delivered facts only when
    ``consistent`` is true. ``source="fulfillment"`` returns the delivered
    facts untouched. Technical fields are copied from ``delivered`` in every
    case.
    """
    result = dict(delivered or {})
    if source != "origin" or not isinstance(origin, dict) or not origin:
        return result
    track = origin if origin.get("kind") == "track" else _match_origin_track(origin, delivered or {})
    if track is None:
        # An album offer whose delivered entry cannot be matched uniquely:
        # descriptive facts stay the delivered file's own.
        result["title"] = delivered_title
        return result

    def pick(value: Any, fallback: Any) -> Any:
        if value not in (None, "", (), []):
            return value
        if consistent:
            return fallback
        return "" if isinstance(fallback, str) else None

    album = dict(result.get("album") or {})
    album_origin = origin if origin.get("kind") == "album" else track
    origin_title = _title_with_version(track.get("title", ""), track.get("version"))
    result["title"] = pick(origin_title, delivered_title)
    origin_artist = _text(track.get("artist"))
    if origin_artist:
        ids = [str(artist_id or "") for artist_id, _name in result.get("artists") or ()]
        result["artists"] = [(ids[0] if ids else "", origin_artist)]
    elif not consistent:
        result["artists"] = []
    origin_album_artist = _text(album_origin.get("album_artist"))
    if origin_album_artist:
        result["album_artists"] = [origin_album_artist]
    elif not consistent:
        result["album_artists"] = []
    album_name = _title_with_version(
        album_origin.get("album_title", album_origin.get("title", "")),
        album_origin.get("album_version", album_origin.get("version")),
    )
    album["name"] = pick(album_name, album.get("name"))
    track_count = album_origin.get("track_count")
    album["num_tracks"] = pick(track_count, album.get("num_tracks"))
    # UPC and the remaining technical fields describe the delivered release.
    result["album"] = album
    result["track_num"] = pick(track.get("track_num"), result.get("track_num"))
    result["volume_num"] = pick(track.get("volume_num"), result.get("volume_num"))
    result["release_date"] = pick(track.get("release_date"), result.get("release_date"))
    explicit = track.get("explicit")
    result["explicit"] = explicit if explicit is not None else (result.get("explicit") if consistent else False)
    # Origin identity has no copyright, BPM, key, URL or release type; a
    # consistent match may fill those from the delivered facts.
    for name in ("copyright", "bpm", "key", "key_scale", "share_url", "release_type"):
        if not consistent:
            result[name] = "" if name != "bpm" else 0
    return result


def path_facts(resolved: dict) -> dict[str, str]:
    """Token values the path formatter should use for a resolved track."""
    album = resolved.get("album") or {}
    artists = [str(name) for _artist_id, name in resolved.get("artists") or () if name]
    album_artists = [str(name) for name in resolved.get("album_artists") or () if name]
    release_date = _text(resolved.get("release_date"))
    explicit = bool(resolved.get("explicit"))
    values = {
        "track_title": _text(resolved.get("title")),
        "artist_name": ", ".join(artists),
        "artist_name_primary": artists[0] if artists else "",
        "album_title": _text(album.get("name")),
        "album_artist": album_artists[0] if album_artists else "",
        "album_artists": ", ".join(album_artists),
        "album_date": release_date,
        "album_year": release_date[:4],
        "track_explicit": FORMAT_TEMPLATE_EXPLICIT if explicit else "",
        "album_explicit": FORMAT_TEMPLATE_EXPLICIT if explicit else "",
    }
    return values


def album_path_facts(origin: dict) -> dict[str, str]:
    """Token values an album-level template should use from origin facts."""
    album_title = _title_with_version(origin.get("album_title", origin.get("title", "")), origin.get("album_version"))
    artist = _text(origin.get("album_artist", origin.get("artist", "")))
    release_date = _text(origin.get("release_date"))
    explicit = bool(origin.get("explicit"))
    return {
        "album_title": album_title,
        "album_artist": artist,
        "album_artists": artist,
        "album_date": release_date,
        "album_year": release_date[:4],
        "album_explicit": FORMAT_TEMPLATE_EXPLICIT if explicit else "",
    }
