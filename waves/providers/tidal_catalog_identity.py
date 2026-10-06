"""TIDAL owns bounded API reads and translation to neutral catalog facts."""

from __future__ import annotations

from math import isfinite
from typing import TYPE_CHECKING

from waves.metadata.catalog_identity import (
    MAX_CANDIDATES,
    MAX_TRACKS,
    CatalogIdentity,
    CatalogLookup,
    catalog_identifier,
)

if TYPE_CHECKING:
    from tidalapi import Session


def _positive(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _facts(
    item: dict, kind: str, album: dict | None = None, tracks: tuple[CatalogIdentity, ...] = (), complete=False
) -> CatalogIdentity:
    release = album or (item if kind == "album" else item.get("album") or {})
    seconds = item.get("duration")
    duration = (
        round(seconds * 1000)
        if isinstance(seconds, int | float) and not isinstance(seconds, bool) and isfinite(seconds) and seconds > 0
        else None
    )
    artist = item.get("artist") or {}
    release_artist = release.get("artist") or {}
    return CatalogIdentity(
        media_id=f"tidal:{item['id']}",
        kind=kind,
        title=str(item.get("title") or ""),
        artist=str(artist.get("name") or ""),
        identifier=str(item.get("upc" if kind == "album" else "isrc") or ""),
        duration_ms=duration,
        explicit=item.get("explicit") if isinstance(item.get("explicit"), bool) else None,
        version=str(item.get("version") or "") if "version" in item else None,
        release_title=" ".join(
            filter(None, (str(release.get("title") or ""), f"({release['version']})" if release.get("version") else ""))
        ),
        release_artist=str(release_artist.get("name") or ""),
        release_version=str(release.get("version") or "") if "version" in release else None,
        release_date=str(release.get("releaseDate") or ""),
        release_upc=str(release.get("upc") or ""),
        track_number=_positive(item.get("trackNumber")),
        disc_number=_positive(item.get("volumeNumber")),
        track_count=_positive(release.get("numberOfTracks")),
        tracks=tracks,
        tracks_complete=complete,
    )


def read_identity(session: Session, kind: str, raw_id: str) -> CatalogIdentity:
    if kind not in ("track", "album"):
        raise NotImplementedError("TIDAL catalog identity does not support this media kind")
    item = session.request.request("GET", f"{'albums' if kind == 'album' else 'tracks'}/{raw_id}").json()
    if str(item.get("id")) != raw_id:
        message = "Selected TIDAL catalog item was not returned"
        raise ValueError(message)
    if kind == "track":
        embedded = item.get("album") or {}
        album = session.request.request("GET", f"albums/{embedded['id']}").json() if embedded.get("id") else None
        return _facts(item, kind, album)
    response = session.request.request(
        "GET", f"albums/{raw_id}/tracks", params={"limit": MAX_TRACKS, "offset": 0}
    ).json()
    resources = response.get("items") or []
    tracks = tuple(_facts(track, "track", item) for track in resources[:MAX_TRACKS])
    complete = not (response.get("links") or {}).get("next") and len(resources) == _positive(item.get("numberOfTracks"))
    complete = complete and not item.get("numberOfVideos")
    return _facts(item, kind, tracks=tracks, complete=complete)


def find_candidates(session: Session, origin: CatalogIdentity) -> CatalogLookup:
    if origin.kind not in ("track", "album"):
        return CatalogLookup(
            complete=False, explanations=("This media kind has no supported catalog identity lookup.",)
        )
    kind = "albums" if origin.kind == "album" else "tracks"
    identifier = catalog_identifier(origin.kind, origin.identifier)
    if identifier:
        key = "filter[barcodeId]" if origin.kind == "album" else "filter[isrc]"
        response = session.request.request(
            "GET",
            kind,
            params={
                key: origin.identifier.strip().upper().replace("-", ""),
                "page[limit]": MAX_CANDIDATES,
                "limit": MAX_CANDIDATES,
            },
            base_url=session.config.openapi_v2_location,
        ).json()
        resources = response.get("data") or []
        complete = (
            "data" in response
            and not response.get("errors")
            and not (response.get("links") or {}).get("next")
            and len(resources) < MAX_CANDIDATES
        )
    else:
        response = session.request.request(
            "GET",
            f"search/{kind}",
            params={"query": f"{origin.artist} {origin.title}", "limit": MAX_CANDIDATES, "offset": 0},
        ).json()
        resources = response.get("items") or []
        complete = False
    candidates = tuple(read_identity(session, origin.kind, str(item["id"])) for item in resources[:MAX_CANDIDATES])
    return CatalogLookup(candidates, complete)
