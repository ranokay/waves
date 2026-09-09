"""Apple Music catalog access through gamdl's embedded client."""

from __future__ import annotations

import asyncio
import logging
from threading import Lock
from urllib.parse import urlparse

from waves.constants import CTX_APPLE, QualityTier, quality_rank
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
        # Cookies-tier download configuration, written by the bridge (which
        # owns Settings) whenever settings save, read here at resolve time.
        self.cookies_path: str = ""
        self.nm3u8dlre_path: str = ""
        self.ffmpeg_path: str = ""
        # Managed wrapper configuration for the ALAC path (issue #32): the
        # wrapper HTTP API URL (a persisted free high port, never port 80).
        # Written by the bridge from the runtime manager; empty means the
        # wrapper tier is not set up and the cookies tier serves alone. The
        # session itself lives in the guest (tokens persist across container
        # restarts), so Waves stores no Apple ID secret here, only the URL.
        self.wrapper_url: str = ""
        self.wrapper_decrypt_host: str = "127.0.0.1"
        self.wrapper_decrypt_port: int = 10020
        # Staged deliveries by their file path: resolve_stream decrypts into
        # a workdir the caller moves out of, then releases here so the temp
        # tree is removed. Never global: one entry per in-flight track.
        self._staged: dict[str, object] = {}

    @property
    def wrapper_available(self) -> bool:
        """Whether the managed wrapper tier can serve ALAC right now."""
        return bool(str(self.wrapper_url or "").strip())

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
    def _unwrap(obj):
        """A catalog resource out of its {"kind", "item"} open_url wrapper."""
        return obj["item"] if isinstance(obj, dict) and "item" in obj else obj

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

    def cached(self, kind: str, raw_id: str) -> dict | None:
        """A remembered resource without spending a catalog call, if present.

        The download slots read this on the GUI thread: a hit queues at once,
        a miss refetches on a worker exactly like the TIDAL _objs dance.
        """
        raw_id = str(raw_id or "").removeprefix(f"{CTX_APPLE}:")
        item = self._objects.get(kind, {}).get(raw_id)
        return item if isinstance(item, dict) else None

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

    def collection_has_tracks(self, obj) -> bool:
        """Whether a collection resource already carries its track list.

        Search summaries name the collection but omit it; the download slots
        refetch those on a worker instead of queueing an empty job.
        """
        item = self._unwrap(obj)
        return bool(isinstance(item, dict) and self._relationship_items(item, "tracks"))

    def collection_items(self, obj, include_videos: bool = True) -> list:
        """An album's or playlist's songs as Waves track row dicts.

        The catalog resource already carries its tracks in
        ``relationships.tracks.data``; entries without attributes are
        re-fetched individually. Artists read through :meth:`artist_page`.
        """
        if isinstance(obj, dict) and obj.get("_apple_kind") == "artist":
            page = self.artist_page(obj["item"])
            return list(page.get("tracks") or [])
        item = self._unwrap(obj)
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
    def _relationship_items(
        cls, item: dict, kind: str
    ) -> list[dict]:  # One window only: a playlist longer than the fetch window carries a
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
        # Servable ceiling, not catalog prose: without the wrapper only AAC
        # 256 serves (HIGH whatever the traits say); with the wrapper the
        # catalog's own traits decide (ALAC 16/44.1 LOSSLESS, 24-bit hi-res
        # HI_RES_LOSSLESS). The row words already name the master; this tier
        # is what a download at this object would actually serve.
        if not self.wrapper_available:
            return QualityTier.HIGH
        item = self._unwrap(obj)
        if not isinstance(item, dict):
            return QualityTier.HIGH
        traits = {str(trait).lower() for trait in self._attributes(item).get("audioTraits") or []}
        if "hi-res-lossless" in traits:
            return QualityTier.HI_RES_LOSSLESS
        if "lossless" in traits:
            return QualityTier.LOSSLESS
        return QualityTier.HIGH

    def advertised_deliveries(self, obj) -> list[tuple[QualityTier, AudioType]]:
        deliveries = [(QualityTier.HIGH, AudioType.STEREO)]
        item = self._unwrap(obj)
        if isinstance(item, dict) and self._has_atmos(item):
            deliveries.append((QualityTier.HIGH, AudioType.ATMOS))
        if self.wrapper_available and isinstance(item, dict):
            traits = {str(trait).lower() for trait in self._attributes(item).get("audioTraits") or []}
            # The wrapper unlocks the lossless rungs the master actually
            # holds; detail ("ALAC 24/192") rides Chooser label text, never
            # rank, so both hi-res sample rates share the one rung.
            if "hi-res-lossless" in traits:
                if (QualityTier.LOSSLESS, AudioType.STEREO) not in deliveries:
                    deliveries.append((QualityTier.LOSSLESS, AudioType.STEREO))
                deliveries.append((QualityTier.HI_RES_LOSSLESS, AudioType.STEREO))
            elif "lossless" in traits:
                deliveries.append((QualityTier.LOSSLESS, AudioType.STEREO))
        return deliveries

    def advertised_ceiling(self, obj) -> int | None:
        # Servable ceiling, per-track when the object is known (issue #32).
        # Cookies tier alone: HIGH always. Wrapper tier: the master's own
        # traits (HI_RES for hi-res, LOSSLESS for lossless, HIGH otherwise),
        # so an AAC-only master never over-promises HI_RES. None when the
        # object is unknown and the wrapper is up (never a guess; the gate
        # settles off the stored ranks then, per _copy_is_current).
        if not self.wrapper_available:
            return quality_rank(QualityTier.HIGH)
        if obj is None:
            return None
        item = self._unwrap(obj)
        if not isinstance(item, dict):
            return None
        traits = {str(trait).lower() for trait in self._attributes(item).get("audioTraits") or []}
        if "hi-res-lossless" in traits:
            return quality_rank(QualityTier.HI_RES_LOSSLESS)
        if "lossless" in traits:
            return quality_rank(QualityTier.LOSSLESS)
        return quality_rank(QualityTier.HIGH)

    @staticmethod
    def _has_atmos(item: dict) -> bool:
        """Whether a song resource carries a Dolby Atmos variant."""
        attrs = AppleProvider._attributes(item)
        traits = {str(trait).lower() for trait in attrs.get("audioTraits") or []}
        variants = {str(variant).lower() for variant in attrs.get("audioVariants") or []}
        return "dolby-atmos" in traits or "dolby-atmos" in variants or "atmos" in traits

    def has_atmos(self, item) -> bool:
        """Whether a song resource carries a Dolby Atmos variant."""
        unwrapped = self._unwrap(item)
        return isinstance(unwrapped, dict) and self._has_atmos(unwrapped)

    def _delivery_atmos(self, track, audio_type: AudioType | None) -> bool:
        """Instead-of semantics (issue #28): the toggle's Atmos replaces
        stereo for tracks that carry it, and tracks without it fall back to
        stereo so no album is left with a hole."""
        item = self._unwrap(track)
        if not isinstance(item, dict):
            return False
        return audio_type == AudioType.ATMOS and self._has_atmos(item)

    def resolve_stream(self, track, tier: QualityTier, audio_type: AudioType) -> StreamInfo:
        """Fetch and locally decrypt one song through the gamdl engine.

        Unlike TIDAL's stream manifests this is a whole-file delivery: the
        engine downloads and decrypts into a staged .m4a and ``local_file``
        carries it; ``urls`` stays empty because no segment pipeline can
        replay an encrypted Apple delivery. The caller stages the file and
        reads ``delivered`` for the ownership record.

        Stereo LOSSLESS/HI_RES takes the ALAC path through the managed
        wrapper when it is set up (issue #32); everything else takes the
        cookies path (AAC 256 stereo, E-AC-3 Atmos). The delivered tier is
        honest (probed off the staged bytes, e.g. 24/96 where the master
        tops out); the "ALAC 24/192" detail rides codecs/bit_depth/
        sample_rate label text, never rank.
        """
        from waves.apple_engine import download_song_file

        item = self._unwrap(track)
        if not isinstance(item, dict) or not item.get("id"):
            raise KeyError(str(getattr(track, "id", track)))
        atmos = self._delivery_atmos(item, audio_type)
        try:
            want = QualityTier(tier) if isinstance(tier, QualityTier) else QualityTier(str(tier))
        except ValueError:
            want = QualityTier.HIGH
        if not atmos and want in (QualityTier.LOSSLESS, QualityTier.HI_RES_LOSSLESS) and self.wrapper_available:
            try:
                return self._resolve_via_wrapper(item, want)
            except Exception as exc:
                from waves.apple_engine import AppleCredentialsError, AppleIntegrityError

                if isinstance(exc, (AppleCredentialsError, AppleIntegrityError)):
                    # Credentials need the wizard; integrity needs retry +
                    # quarantine (spec §6). Neither falls back to AAC: a bad
                    # ALAC file must never arrive as a good AAC one.
                    raise
                # Only a genuinely unavailable ALAC variant (no ALAC master,
                # FairPlay missing) falls back to cookies AAC when cookies
                # exist, so one AAC-only master cannot hole its album. The
                # verdict comes from the shared refusal vocabulary (§4.4).
                try:
                    kind = self.classify_refusal(exc).kind
                except Exception:
                    kind = None
                if str(kind) != str(RefusalKind.UNAVAILABLE) or not str(self.cookies_path or "").strip():
                    raise
                logger.debug("Apple ALAC unavailable, falling back to AAC", exc_info=True)
        delivery = download_song_file(
            song_id=str(item.get("id")),
            atmos=atmos,
            cookies_path=self.cookies_path,
            nm3u8dlre_path=self.nm3u8dlre_path,
            ffmpeg_path=self.ffmpeg_path,
        )
        self._staged[str(delivery.staged_path)] = delivery
        # The staged file is the provider's to clean once the caller has
        # moved it out; keep the handle beside the answer, never global.
        codecs = "ec-3" if atmos else "mp4a.40.2"
        return StreamInfo(
            urls=[],
            file_extension=".m4a",
            codecs=codecs,
            requires_flac_extraction=False,
            delivered={
                "tier": QualityTier.HIGH.value,
                "audio_type": str(AudioType.ATMOS if atmos else AudioType.STEREO),
                "bit_depth": None,
                "sample_rate": self._probe_sample_rate(str(delivery.staged_path)),
                "codecs": codecs,
            },
            replay_gain=None,
            encrypted=False,
            single_file=True,
            local_file=str(delivery.staged_path),
        )

    def _resolve_via_wrapper(self, item: dict, want: QualityTier) -> StreamInfo:
        """One stereo song through the managed wrapper's ALAC path."""
        from waves.apple_engine import (
            apple_delivery_detail,
            apple_tier_for_delivery,
            download_song_alac_file,
            probe_audio_file,
        )

        delivery = download_song_alac_file(
            song_id=str(item.get("id")),
            wrapper_url=self.wrapper_url,
            nm3u8dlre_path=self.nm3u8dlre_path,
            ffmpeg_path=self.ffmpeg_path,
            decrypt_host=self.wrapper_decrypt_host,
            decrypt_port=self.wrapper_decrypt_port,
        )
        self._staged[str(delivery.staged_path)] = delivery
        # Honest tier off the staged bytes: the master may top out at 24/96
        # where HI_RES was asked, and the readout must say so. Detail rides
        # codecs/bit_depth/sample_rate; the tier alone ranks. A probe that
        # fails too cannot record the ask as verified: ALAC proves at least
        # LOSSLESS, so that is the substitute, never the requested rung.
        try:
            probe = probe_audio_file(str(delivery.staged_path), self._probe_path())
        except Exception:
            logger.debug("Apple ALAC probe failed; recording LOSSLESS, not the ask", exc_info=True)
            probe = {"codec": "alac", "sample_rate": "", "bit_depth": None}
        codec = str(probe.get("codec") or "alac")
        bit_depth = probe.get("bit_depth")
        try:
            sample_rate: int | None = int(str(probe.get("sample_rate") or "").strip())
        except (TypeError, ValueError):
            sample_rate = None
        tier_value = apple_tier_for_delivery(codec, bit_depth, sample_rate or "", fallback=QualityTier.LOSSLESS.value)
        logger.debug(
            "Apple ALAC delivery %s",
            apple_delivery_detail(codec, bit_depth, sample_rate or ""),
            extra={"tier": tier_value},
        )
        return StreamInfo(
            urls=[],
            file_extension=".m4a",
            codecs=codec or "alac",
            requires_flac_extraction=False,
            delivered={
                "tier": tier_value,
                "audio_type": str(AudioType.STEREO),
                "bit_depth": bit_depth,
                "sample_rate": sample_rate,
                "codecs": codec or "alac",
            },
            replay_gain=None,
            encrypted=False,
            single_file=True,
            local_file=str(delivery.staged_path),
        )

    def _probe_path(self) -> str:
        """An ffprobe binary for the ALAC honesty probe, or "" to trust."""
        try:
            from waves.apple_engine import ffprobe_for

            return ffprobe_for(self.ffmpeg_path)
        except Exception:
            return ""

    def _probe_sample_rate(self, staged_path: str) -> int | None:
        """A staged AAC file's sample rate for the ownership record, if known."""
        try:
            from waves.apple_engine import probe_audio_file

            probe = probe_audio_file(staged_path, self._probe_path())
        except Exception:
            return None
        else:
            try:
                rate = int(str(probe.get("sample_rate") or "").strip())
            except (TypeError, ValueError):
                return None
            return rate if rate > 0 else None

    def discard_delivery(self, local_file: str) -> None:
        """Remove a staged delivery's workdir after its file moved out."""
        from waves.apple_engine import cleanup_delivery

        delivery = self._staged.pop(str(local_file), None)
        if delivery is not None:
            try:
                cleanup_delivery(delivery)
            except Exception:
                logger.debug("Could not clean the Apple staging area", exc_info=True)

    def preview_url(self, track) -> str | None:
        """The documented 30-second preview URL off a song resource.

        No session, no wrapper, no setup: ``attributes.previews[0].url`` is a
        plain AAC clip. None when Apple serves no preview for the song.
        """
        item = self._unwrap(track)
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
        item = self._unwrap(obj)
        attrs = self._attributes(item if isinstance(item, dict) else {})
        try:
            dim = max(16, int(dimension))
        except (TypeError, ValueError):
            dim = 320
        return self._art(attrs, dim)

    def track_facts(self, track) -> dict:
        """The fact schema the tag writer reads, in the seam's namespaced
        spelling (mirrors TidalProvider.track_facts field for field, so the
        Metadata writer consumes it unchanged).

        The album block is best-effort from this session's album cache (the
        album job fetched it first); a bare track read never spends a catalog
        call on it, so UPC and track totals may be "" where TIDAL fills them.
        """
        item = self._unwrap(track)
        attrs = self._attributes(item if isinstance(item, dict) else {})
        raw_id = str((item or {}).get("id") or "") if isinstance(item, dict) else ""
        artist_ids = self._track_artist_ids(item if isinstance(item, dict) else {}, attrs)
        album_attrs: dict = {}
        album_id = self._album_id(item if isinstance(item, dict) else {}, attrs)
        if album_id:
            album_raw = self._objects.get("album", {}).get(album_id.removeprefix(f"{CTX_APPLE}:"))
            if isinstance(album_raw, dict):
                maybe = self._attributes(album_raw)
                if isinstance(maybe, dict):
                    album_attrs = maybe
        artist_name = str(attrs.get("artistName") or "")
        return {
            "item_id": self._id(raw_id),
            "artist_ids": artist_ids,
            "album_artist_ids": [artist_ids[0]] if artist_ids else [],
            # One combined display credit: per-artist names are unavailable,
            # so only the first id carries it and the rest stay id-only
            # instead of repeating the same string per credit.
            "artists": [(artist_ids[0], artist_name)] + [(aid, "") for aid in artist_ids[1:]] if artist_ids else [],
            "album_artists": [artist_name] if artist_name else [],
            "copyright": str(attrs.get("copyright") or ""),
            "isrc": str(attrs.get("isrc") or ""),
            "explicit": attrs.get("contentRating") == "explicit",
            "bpm": 0,
            "key": None,
            "key_scale": None,
            "share_url": str(attrs.get("url") or ""),
            "volume_num": int(attrs.get("discNumber") or 1),
            "track_num": int(attrs.get("trackNumber") or 0),
            "release_date": str(attrs.get("releaseDate") or "")[:10],
            "release_type": "",
            "album": {
                "name": str(attrs.get("albumName") or ""),
                "num_tracks": album_attrs.get("trackCount"),
                "num_volumes": None,
                "upc": str(album_attrs.get("upc") or ""),
                "type": "",
            },
        }

    def _track_artist_ids(self, item: dict, attrs: dict) -> list[str]:
        """This track's credited artist ids, relationship first."""
        relationships = item.get("relationships") or {}
        artists = relationships.get("artists") or {}
        ids = [self._id(entry.get("id")) for entry in artists.get("data") or [] if isinstance(entry, dict)]
        if ids:
            return ids
        single = self._artist_id(item, attrs, {})
        return [single] if single else []

    def classify_refusal(self, exc) -> Refusal:
        """Apple engine errors into the shared refusal vocabulary."""
        from waves.apple_engine import AppleCredentialsError

        if isinstance(exc, AppleCredentialsError):
            return Refusal(RefusalKind.FAILURE, str(exc))
        name = type(exc).__name__
        text = f"{name}: {exc}"
        lowered = str(exc).lower()
        if "429" in text or "TooManyRequests" in name or ("rate" in lowered and "limit" in lowered):
            return Refusal(RefusalKind.THROTTLED, "Apple is rate-limiting; back off and retry")
        if (
            "NotStreamable" in name
            or "FormatNotAvailable" in name
            or "DecryptionNotAvailable" in name
            or "formatnotavailable" in lowered
            or "decryptionnotavailable" in lowered
            or "not found" in str(exc).lower()
            or "404" in text
        ):
            return Refusal(RefusalKind.UNAVAILABLE, "this item is not available on Apple Music")
        return Refusal(RefusalKind.FAILURE, str(exc) or name)
