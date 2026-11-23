"""Apple catalog resources translated without display-duration truncation.

Each lookup reads one page, including one bounded album relationship page.
Continuations remain incomplete evidence instead of triggering a catalog crawl.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from waves.metadata.catalog_identity import (
    MAX_CANDIDATES,
    MAX_TRACKS,
    CatalogIdentity,
    CatalogLookup,
    catalog_identifier,
)

if TYPE_CHECKING:
    from waves.providers.apple.provider import AppleProvider


def _positive(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _facts(item: dict, kind: str, album: dict | None = None) -> CatalogIdentity:
    resource_kind = {"songs": "track", "albums": "album", "music-videos": "video"}.get(item.get("type"), "unknown")
    attrs = item.get("attributes") or {}
    release = (album or {}).get("attributes") or (attrs if kind == "album" else {})
    rating = attrs.get("contentRating")
    explicit = True if rating == "explicit" else False if rating == "clean" else None
    # Apple omits contentRating for non-explicit material. An omitted rating
    # is unknown evidence, unlike the display row's convenient False default.
    tracks = (item.get("relationships") or {}).get("tracks") or {}
    resources = tracks.get("data") or []
    return CatalogIdentity(
        media_id=f"apple:{item['id']}",
        kind=resource_kind,
        title=str(attrs.get("name") or ""),
        artist=str(attrs.get("artistName") or ""),
        identifier=str(attrs.get("upc" if kind == "album" else "isrc") or ""),
        duration_ms=_positive(attrs.get("durationInMillis")),
        explicit=explicit,
        version="" if attrs.get("name") else None,
        release_title=str(release.get("name") or attrs.get("albumName") or ""),
        release_version="" if release.get("name") or attrs.get("albumName") else None,
        release_artist=str(release.get("artistName") or ""),
        release_date=str(release.get("releaseDate") or ""),
        release_upc=str(release.get("upc") or ""),
        track_number=_positive(attrs.get("trackNumber")),
        disc_number=_positive(attrs.get("discNumber")),
        track_count=_positive(release.get("trackCount")),
        tracks=tuple(_facts(track, "track", item) for track in resources[:MAX_TRACKS] if track.get("id"))
        if kind == "album"
        else (),
        tracks_complete=kind == "album"
        and not tracks.get("next")
        and len(resources) <= MAX_TRACKS
        and len(resources) == _positive(attrs.get("trackCount")),
    )


async def request_resource(provider: AppleProvider, kind: str, raw_id: str = "", params: dict | None = None) -> dict:
    if provider._catalog is None:
        provider._catalog = await provider._catalog_factory()
    storefront = provider._catalog.storefront
    resource = "albums" if kind == "album" else "songs"
    uri = f"/v1/catalog/{storefront}/{resource}" + (f"/{raw_id}" if raw_id else "")
    return await provider._catalog._amp_request(uri, params or {})


def read_identity(provider: AppleProvider, kind: str, raw_id: str) -> CatalogIdentity:
    if kind not in provider.identity_kinds:
        raise NotImplementedError("Apple catalog identity does not support this media kind")
    response = provider._run(
        request_resource(provider, kind, raw_id, {"include": "tracks" if kind == "album" else "albums"})
    )
    resources = response.get("data") or []
    if len(resources) != 1 or str(resources[0].get("id")) != raw_id:
        message = "Selected Apple catalog item was not returned"
        raise ValueError(message)
    item = resources[0]
    albums = ((item.get("relationships") or {}).get("albums") or {}).get("data") or []
    album = albums[0] if len(albums) == 1 else None
    return _facts(item, kind, album)


def find_candidates(provider: AppleProvider, origin: CatalogIdentity) -> CatalogLookup:
    if origin.kind not in provider.identity_kinds:
        return CatalogLookup(
            complete=False, explanations=("This media kind has no supported catalog identity lookup.",)
        )
    identifier = catalog_identifier(origin.kind, origin.identifier)
    if identifier:
        key = "filter[upc]" if origin.kind == "album" else "filter[isrc]"
        response = provider._run(
            request_resource(
                provider,
                origin.kind,
                params={key: origin.identifier.strip().upper().replace("-", ""), "limit": MAX_CANDIDATES},
            )
        )
        resources, complete = _filter_resources(response, origin.kind, identifier)
    else:
        # Manual search supplies reviewable candidates; it can never certify
        # completeness of an identifier lookup or promote missing identity.
        async def search() -> dict:
            if provider._catalog is None:
                provider._catalog = await provider._catalog_factory()
            return await provider._catalog._amp_request(
                f"/v1/catalog/{provider._catalog.storefront}/search",
                {
                    "term": f"{origin.artist} {origin.title}",
                    "types": "albums" if origin.kind == "album" else "songs",
                    "limit": MAX_CANDIDATES,
                },
            )

        response = provider._run(search())
        bucket = (response.get("results") or {}).get("albums" if origin.kind == "album" else "songs") or {}
        resources = bucket.get("data") or []
        complete = False
    candidates = tuple(read_identity(provider, origin.kind, str(item["id"])) for item in resources[:MAX_CANDIDATES])
    return CatalogLookup(candidates, complete)


def _filter_resources(response: dict, kind: str, identifier: str) -> tuple[list[dict], bool]:
    """Apple may put additional matches in meta.filters rather than data."""
    resources = response.get("data") or []
    field = "upc" if kind == "album" else "isrc"
    filters = ((response.get("meta") or {}).get("filters") or {}).get(field) or {}
    listed: list[dict] = []
    known = False
    for value, references in filters.items():
        if catalog_identifier(kind, value) == identifier:
            known = True
            listed.extend(references)
    by_id = {str(item["id"]): item for item in (*resources, *listed)}
    complete = (
        known
        and "data" in response
        and not response.get("errors")
        and not response.get("next")
        and len(by_id) <= MAX_CANDIDATES
    )
    return list(by_id.values())[:MAX_CANDIDATES], complete
