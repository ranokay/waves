"""Apple Music catalog access through gamdl's embedded client."""

from __future__ import annotations

import asyncio
import logging
from threading import Lock
from urllib.parse import urlparse

from waves.constants import CTX_APPLE, QualityTier
from waves.providers.base import AudioType, Capability, Provider, Refusal, RefusalKind, StreamInfo


class _QuietCatalogLog:
    def bind(self, **_values):
        return self

    def debug(self, *_args, **_values) -> None:
        return None


class AppleCatalogUnavailable(RuntimeError):
    """gamdl could not reach Apple's public catalog."""

    def __init__(self) -> None:
        super().__init__("Apple changed its web app. A Waves update is needed.")


logger = logging.getLogger("waves.providers.apple")


def _song_query_id(query: str) -> str | None:
    """The ``?i=<songId>`` song id off an album URL, if present."""
    for chunk in query.split("&"):
        if chunk.startswith("i=") and len(chunk) > 2:
            return chunk[2:].split("/")[0]
    return None


def _catalog_path_id(type_seg: str, raw_id: str) -> tuple[str, str, None] | None:
    """A catalog path's (kind, id) for the four linkable Apple kinds."""
    kinds = {"album": "album", "artist": "artist", "playlist": "playlist", "song": "track", "songs": "track"}
    kind = kinds.get(type_seg)
    if kind is None or not raw_id:
        return None
    return (kind, raw_id, None)


class AppleProvider(Provider):
    id = CTX_APPLE
    name = "Apple Music"
    capabilities = frozenset({Capability.SEARCH, Capability.CATALOG, Capability.OPEN_URL, Capability.PREVIEW})

    def __init__(self, catalog=None, catalog_factory=None) -> None:
        self._catalog = catalog
        self._catalog_factory = catalog_factory or self._create_catalog
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_lock = Lock()
        self._objects: dict[str, dict[str, dict]] = {
            "artist": {},
            "album": {},
            "track": {},
            "playlist": {},
        }
        # Ids fetched through get_object (the canonical endpoints, carrying
        # track lists and artist views). Search summaries share _objects but
        # are never complete: a search album has no tracks, a search artist
        # no views, so page builders must not reuse them (see _is_complete).
        self._complete: set[tuple[str, str]] = set()

    def _run(self, awaitable):
        with self._loop_lock:
            if self._loop is None:
                self._loop = asyncio.new_event_loop()
            return self._loop.run_until_complete(awaitable)

    async def _search(self, needle: str) -> dict:
        if self._catalog is None:
            self._catalog = await self._catalog_factory()
        return await self._catalog.get_search_results(needle, types="songs,albums,playlists,artists")

    @staticmethod
    async def _create_catalog():
        from gamdl.api import apple_music

        # gamdl's default structlog logger prints the complete catalog reply at
        # debug level. The provider reports failures through Waves' own logger;
        # dumping hundreds of result dictionaries adds no useful diagnosis.
        apple_music.logger = _QuietCatalogLog()
        return await apple_music.AppleMusicApi.create()

    def search(self, needle: str) -> dict:
        """Return Apple's public catalog matches as complete Waves row dictionaries."""
        try:
            response = self._run(self._search(needle))
            results = response.get("results") or {}
            artist_resources = self._resources(results, "artists")
            artist_ids = {
                str(self._attributes(item).get("name") or "").casefold(): self._id(item.get("id"))
                for item in artist_resources
                if self._attributes(item).get("name") and item.get("id")
            }
            return {
                "artists": [self._artist_row(item) for item in artist_resources],
                "albums": [self._album_row(item, artist_ids) for item in self._resources(results, "albums")],
                "tracks": [self._track_row(item, artist_ids) for item in self._resources(results, "songs")],
                "videos": [],
                "playlists": [self._playlist_row(item) for item in self._resources(results, "playlists")],
                "mixes": [],
                "top": None,
            }
        except Exception as exc:
            raise AppleCatalogUnavailable from exc

    @staticmethod
    def _resources(results: dict, kind: str) -> list[dict]:
        bucket = results.get(kind) or {}
        return [item for item in bucket.get("data") or [] if isinstance(item, dict)]

    @staticmethod
    def _attributes(item: dict) -> dict:
        attrs = item.get("attributes") or {}
        return attrs if isinstance(attrs, dict) else {}

    @staticmethod
    def _id(raw) -> str:
        raw = str(raw or "")
        return f"{CTX_APPLE}:{raw}" if raw else ""

    @classmethod
    def _related_id(cls, item: dict, kind: str) -> str:
        relationships = item.get("relationships") or {}
        related = relationships.get(kind) or {}
        data = related.get("data") or []
        if data and isinstance(data[0], dict):
            return cls._id(data[0].get("id"))
        return ""

    @classmethod
    def _artist_id(cls, item: dict, attrs: dict, artist_ids: dict[str, str]) -> str:
        related = cls._related_id(item, "artists")
        if related:
            return related
        path = urlparse(str(attrs.get("artistUrl") or "")).path.rstrip("/")
        if path:
            return cls._id(path.rsplit("/", 1)[-1])
        return artist_ids.get(str(attrs.get("artistName") or "").casefold(), "")

    @classmethod
    def _album_id(cls, item: dict, attrs: dict) -> str:
        related = cls._related_id(item, "albums")
        if related:
            return related
        path = urlparse(str(attrs.get("url") or "")).path.rstrip("/")
        return cls._id(path.rsplit("/", 1)[-1]) if path else ""

    @staticmethod
    def _art(attrs: dict, width: int, height: int | None = None) -> str:
        artwork = attrs.get("artwork") or {}
        template = str(artwork.get("url") or "") if isinstance(artwork, dict) else ""
        if not template:
            return ""
        return (
            template.replace("{w}", str(width))
            .replace("{h}", str(height if height is not None else width))
            .replace("{f}", "jpg")
        )

    @staticmethod
    def _seconds(attrs: dict) -> int:
        try:
            return max(0, int(attrs.get("durationInMillis") or 0) // 1000)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _duration(seconds: int) -> str:
        return f"{seconds // 60}:{seconds % 60:02d}"

    @staticmethod
    def _date(attrs: dict) -> str:
        return str(attrs.get("releaseDate") or "")[:10]

    @classmethod
    def _artist_credit(cls, item: dict, attrs: dict, artist_ids: dict[str, str]) -> tuple[str, list[dict]]:
        name = str(attrs.get("artistName") or "")
        artist_id = cls._artist_id(item, attrs, artist_ids)
        return artist_id, ([{"id": artist_id, "name": name, "roles": []}] if name else [])

    @staticmethod
    def _quality(attrs: dict) -> str:
        traits = {str(trait).lower() for trait in attrs.get("audioTraits") or []}
        if "hi-res-lossless" in traits:
            return "HI-RES"
        if "lossless" in traits:
            return "LOSSLESS"
        return "HIGH"

    def _remember(self, kind: str, item: dict) -> str:
        raw_id = str(item.get("id") or "")
        # Only a DIFFERENT object invalidates completeness: rendering the
        # fetched object itself (row_for on a get_object result) passes the
        # identical dict back and must preserve its marker, or a legitimately
        # empty collection refetches on every read.
        if raw_id and self._objects[kind].get(raw_id) is not item:
            self._objects[kind][raw_id] = item
            self._complete.discard((kind, raw_id))
        return self._id(raw_id)

    def _artist_row(self, item: dict) -> dict:
        attrs = self._attributes(item)
        return {
            "id": self._remember("artist", item),
            "name": str(attrs.get("name") or ""),
            "art": self._art(attrs, 320),
            "roles": "Artist",
            "popularity": -1,
        }

    def _album_row(self, item: dict, artist_ids: dict[str, str]) -> dict:
        attrs = self._attributes(item)
        artist_id, artists = self._artist_credit(item, attrs, artist_ids)
        date = self._date(attrs)
        return {
            "id": self._remember("album", item),
            "title": str(attrs.get("name") or ""),
            "artist": str(attrs.get("artistName") or ""),
            "artist_id": artist_id,
            "artists": artists,
            "art": self._art(attrs, 320),
            "year": date[:4],
            "date": date,
            "tracks": int(attrs.get("trackCount") or 0),
            "duration_sec": self._seconds(attrs),
            "quality": self._quality(attrs),
            "popularity": -1,
            "explicit": attrs.get("contentRating") == "explicit",
            "added": "",
        }

    def _track_row(self, item: dict, artist_ids: dict[str, str]) -> dict:
        attrs = self._attributes(item)
        artist_id, artists = self._artist_credit(item, attrs, artist_ids)
        date = self._date(attrs)
        seconds = self._seconds(attrs)
        return {
            "id": self._remember("track", item),
            "title": str(attrs.get("name") or ""),
            "artist": str(attrs.get("artistName") or ""),
            "artist_id": artist_id,
            "artists": artists,
            "album": str(attrs.get("albumName") or ""),
            "album_id": self._album_id(item, attrs),
            "num": int(attrs.get("trackNumber") or 0),
            "vol": int(attrs.get("discNumber") or 1),
            "art": self._art(attrs, 160),
            "year": date[:4],
            "date": date,
            "duration": self._duration(seconds),
            "duration_sec": seconds,
            "quality": self._quality(attrs),
            "popularity": -1,
            "explicit": attrs.get("contentRating") == "explicit",
            "added": "",
        }

    def _playlist_row(self, item: dict) -> dict:
        attrs = self._attributes(item)
        relationships = item.get("relationships") or {}
        tracks = relationships.get("tracks") or {}
        meta = tracks.get("meta") or {}
        return {
            "id": self._remember("playlist", item),
            "title": str(attrs.get("name") or ""),
            "art": self._art(attrs, 320),
            "tracks": int(attrs.get("trackCount") or meta.get("total") or 0),
            "creator": str(attrs.get("curatorName") or ""),
            "added": "",
            "kind": "playlist",
            "sub": "",
            "path": "",
            "plCount": 0,
        }

    def login_begin(self) -> str:
        return ""

    def login_complete(self, payload: str) -> bool:
        return False

    def logout(self) -> None:
        return None

    def login_resume(self) -> bool:
        return False

    def reset_session(self) -> None:
        return None

    def account_id(self) -> str:
        return ""

    def credential_facts(self) -> dict[str, str]:
        return {}

    @property
    def is_logged_in(self) -> bool:
        return False

    def apply_quality(self, tier: QualityTier, audio_type: AudioType) -> None:
        return None

    def open_url(self, url: str) -> object | None:
        """Resolve a pasted Apple Music share URL to its catalog resource.

        Returns ``{"kind": ..., "item": ...}`` where kind is one of
        "album" / "artist" / "playlist" / "track", or None when the URL is
        not Apple's grammar or the item is gone. The bridge builds the page
        payload from the resolved resource.
        """
        parsed = self.parse_apple_url(url)
        if parsed is None:
            return None
        kind, raw_id, _song_id = parsed
        try:
            item = self.get_object(kind, raw_id)
        except Exception:
            return None
        return {"kind": kind, "item": item}

    @staticmethod
    def parse_apple_url(url: str) -> tuple[str, str, str | None] | None:
        """An Apple Music share URL into (kind, raw_id, song_id).

        Kinds: "album" / "artist" / "playlist" / "track". A song link is an
        album URL with a ``?i=<songId>`` query, so it answers ("track",
        songId, None). Playlist ids travel as ``pl.<hash>``.
        """
        try:
            parsed = urlparse(str(url or ""))
        except Exception:
            return None
        if "apple.com" not in (parsed.hostname or ""):
            return None
        parts = [seg for seg in parsed.path.split("/") if seg]
        if len(parts) < 3:
            return None
        song_id = _song_query_id(parsed.query or "")
        if song_id:
            return ("track", song_id, None)
        return _catalog_path_id(parts[1].lower(), parts[-1])

    def get_object(self, kind: str, raw_id: str) -> object:
        raw_id = str(raw_id or "").removeprefix(f"{CTX_APPLE}:")
        cached = self._objects.get(kind, {}).get(raw_id)
        if cached is not None and ((kind, raw_id) in self._complete or self._is_complete(kind, cached)):
            return cached
        if kind == "album":
            item = self._first_data(self._run(self._fetch_album(raw_id)))
        elif kind == "artist":
            item = self._first_data(self._run(self._fetch_artist(raw_id)))
        elif kind == "playlist":
            item = self._first_data(self._run(self._fetch_playlist(raw_id)))
        elif kind == "track":
            item = self._first_data(self._run(self._fetch_song(raw_id)))
        else:
            raise KeyError(kind)
        if not isinstance(item, dict) or not item.get("id"):
            raise KeyError(raw_id)
        self._objects[kind][raw_id] = item
        self._complete.add((kind, raw_id))
        return item

    @staticmethod
    def _has_view_data(views: object) -> bool:
        """Whether a JSON:API views map holds any rows."""
        if not isinstance(views, dict):
            return False
        for view in views.values():
            view_data = (view or {}).get("data") if isinstance(view, dict) else None
            if isinstance(view_data, list) and view_data:
                return True
        return False

    @classmethod
    def _is_complete(cls, kind: str, item: dict) -> bool:
        """Whether a cached resource carries what the page builders need.

        Search summaries name the item but omit the collections: albums and
        playlists without their track lists, artists without albums or top
        songs. Tracks are complete when named (previews ride the attributes).
        Fetched objects bypass this via _complete, so a genuinely empty
        collection does not refetch on every read.
        """
        if not isinstance(item, dict):
            return False
        if kind == "track":
            return bool(cls._attributes(item).get("name"))
        if kind in ("album", "playlist"):
            return bool(cls._relationship_items(item, "tracks"))
        if kind == "artist":
            relationships = item.get("relationships") or {}
            for rel in relationships.values():
                if not isinstance(rel, dict):
                    continue
                data = rel.get("data")
                if isinstance(data, list) and data:
                    return True
                if cls._has_view_data(rel.get("views")):
                    return True
            return cls._has_view_data(item.get("views"))
        return False

    async def _fetch_album(self, raw_id: str) -> dict:
        if self._catalog is None:
            self._catalog = await self._catalog_factory()
        return await self._catalog.get_album(raw_id)

    async def _fetch_artist(self, raw_id: str) -> dict:
        if self._catalog is None:
            self._catalog = await self._catalog_factory()
        return await self._catalog.get_artist(raw_id)

    async def _fetch_playlist(self, raw_id: str) -> dict:
        if self._catalog is None:
            self._catalog = await self._catalog_factory()
        return await self._catalog.get_playlist(raw_id)

    async def _fetch_song(self, raw_id: str) -> dict:
        if self._catalog is None:
            self._catalog = await self._catalog_factory()
        return await self._catalog.get_song(raw_id)

    @staticmethod
    def _first_data(response: dict) -> dict:
        data = (response or {}).get("data")
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return data[0]
        if isinstance(data, dict):
            return data
        return {}

    def collection_items(self, obj, include_videos: bool = True) -> list:
        """An album's or playlist's songs as Waves track row dicts.

        The catalog resource already carries its tracks in
        ``relationships.tracks.data``; entries without attributes are
        re-fetched individually. Artists read through :meth:`artist_page`.
        """
        if isinstance(obj, dict) and obj.get("_apple_kind") == "artist":
            page = self.artist_page(obj["item"])
            return list(page.get("tracks") or [])
        item = obj["item"] if isinstance(obj, dict) and "item" in obj else obj
        if not isinstance(item, dict):
            return []
        tracks = self._relationship_items(item, "tracks")
        return self._track_rows(tracks)

    def _track_rows(self, resources: list[dict]) -> list[dict]:
        rows: list[dict] = []
        for res in resources:
            if not isinstance(res, dict) or not res.get("id"):
                continue
            if not self._attributes(res).get("name"):
                try:
                    res = self.get_object("track", str(res.get("id")))
                except Exception:
                    logger.debug("Skipping an Apple track refetch that failed", exc_info=True)
                    continue
                if not isinstance(res, dict):
                    continue
            rows.append(self._track_row(res, {}))
        return rows

    @classmethod
    def _relationship_items(cls, item: dict, kind: str) -> list[dict]:
        # One window only: a playlist longer than the fetch window carries a
        # `next` continuation that v1 does not follow (no seam exists for
        # arbitrary continuation URLs; the fetch asks for 300 tracks, which
        # covers the realistic range, and albums are complete by definition).
        relationships = item.get("relationships") or {}
        related = relationships.get(kind) or {}
        data = related.get("data") or []
        return [entry for entry in data if isinstance(entry, dict)]

    def artist_page(self, artist_item: dict) -> dict:
        """An artist's albums, singles and top tracks as Waves row dicts."""
        attrs = self._attributes(artist_item)
        albums: list[dict] = []
        singles: list[dict] = []
        tracks: list[dict] = []
        artist_ids = {
            str(attrs.get("name") or "").casefold(): self._id(artist_item.get("id")) if artist_item.get("id") else ""
        }
        relationships = artist_item.get("relationships") or {}
        for key, rel in relationships.items():
            if not isinstance(rel, dict):
                continue
            data = rel.get("data")
            items = data if isinstance(data, list) else []
            views = rel.get("views") if isinstance(rel.get("views"), dict) else None
            if views:
                for view_name, view in views.items():
                    view_data = (view or {}).get("data") if isinstance(view, dict) else None
                    if isinstance(view_data, list):
                        self._sort_artist_resources(view_data, str(view_name), albums, singles, tracks, artist_ids)
            self._sort_artist_resources(items, str(key), albums, singles, tracks, artist_ids)
        views = artist_item.get("views") or {}
        if isinstance(views, dict):
            for view_name, view in views.items():
                view_data = (view or {}).get("data") if isinstance(view, dict) else None
                if isinstance(view_data, list):
                    self._sort_artist_resources(view_data, str(view_name), albums, singles, tracks, artist_ids)
        return {
            "id": self._id(artist_item.get("id")),
            "name": str(attrs.get("name") or ""),
            "art": self._art(attrs, 320),
            "bio": "",
            "albums": albums,
            "eps": singles,
            "tracks": tracks,
        }

    def _sort_artist_resources(
        self,
        resources: list,
        view_name: str,
        albums: list[dict],
        singles: list[dict],
        tracks: list[dict],
        artist_ids: dict[str, str],
    ) -> None:
        lowered = view_name.lower()
        for res in resources:
            if not isinstance(res, dict) or not res.get("id"):
                continue
            rtype = str(res.get("type") or "").lower()
            if rtype == "songs" or (("top" in lowered or "song" in lowered) and rtype in ("", "songs")):
                if rtype == "" and not self._attributes(res).get("albumName"):
                    continue
                tracks.append(self._track_row(res, artist_ids))
            elif rtype in ("albums", ""):
                row = self._album_row(res, artist_ids)
                if "single" in lowered or "ep" in lowered:
                    singles.append(row)
                else:
                    albums.append(row)

    def row_for(self, kind: str, item: dict) -> dict:
        """One catalog resource as the Waves row dict the pages render."""
        if kind == "artist":
            return self._artist_row(item)
        if kind == "album":
            return self._album_row(item, {})
        if kind == "track":
            return self._track_row(item, {})
        if kind == "playlist":
            return self._playlist_row(item)
        raise KeyError(kind)

    def user_collections(self) -> dict | None:
        return None

    def folder_tree(self, root_folders: list | None = None) -> object | None:
        return None

    def search_tracks(self, needle: str, limit: int = 10) -> list:
        return []

    def browse_page(self, title: str, api_path: str) -> object | None:
        return None

    def browse_home(self) -> object | None:
        return None

    def browse_window(self, title: str, data_path: str, mod_type: str, offset: int, limit: int = 50):
        raise NotImplementedError

    def favorites_page(
        self, kind: str, offset: int, limit: int, order: tuple[str, str] | None = None
    ) -> tuple[list, bool]:
        return [], False

    def favorite_ids(self, kind: str) -> set[str]:
        return set()

    def advertised_tier(self, obj) -> QualityTier | None:
        return None

    def advertised_deliveries(self, obj) -> list[tuple[QualityTier, AudioType]]:
        return []

    def advertised_ceiling(self, obj) -> int | None:
        return None

    def resolve_stream(self, track, tier: QualityTier, audio_type: AudioType) -> StreamInfo:
        raise NotImplementedError

    def preview_url(self, track) -> str | None:
        """The documented 30-second preview URL off a song resource.

        No session, no wrapper, no setup: ``attributes.previews[0].url`` is a
        plain AAC clip. None when Apple serves no preview for the song.
        """
        item = track["item"] if isinstance(track, dict) and "item" in track else track
        attrs = self._attributes(item if isinstance(item, dict) else {})
        previews = attrs.get("previews")
        if isinstance(previews, list):
            for entry in previews:
                if isinstance(entry, dict) and entry.get("url"):
                    return str(entry["url"])
        return None

    def fetch_lyrics(self, track) -> tuple[str, str]:
        return "", ""

    def cover_url(self, obj, dimension: int) -> str:
        """Best-effort cover URL at the requested square dimension."""
        item = obj["item"] if isinstance(obj, dict) and "item" in obj else obj
        attrs = self._attributes(item if isinstance(item, dict) else {})
        try:
            dim = max(16, int(dimension))
        except (TypeError, ValueError):
            dim = 320
        return self._art(attrs, dim)

    def track_facts(self, track) -> dict:
        return {}

    def classify_refusal(self, exc) -> Refusal:
        return Refusal(RefusalKind.FAILURE, str(exc) or type(exc).__name__)
