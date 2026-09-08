"""Apple Music catalog access through gamdl's embedded client."""

from __future__ import annotations

import asyncio
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


class AppleProvider(Provider):
    id = CTX_APPLE
    name = "Apple Music"
    capabilities = frozenset({Capability.SEARCH, Capability.CATALOG})

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
        if raw_id:
            self._objects[kind][raw_id] = item
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
        return None

    def get_object(self, kind: str, raw_id: str) -> object:
        raw_id = str(raw_id).removeprefix(f"{CTX_APPLE}:")
        return self._objects.get(kind, {})[raw_id]

    def collection_items(self, obj, include_videos: bool = True) -> list:
        raise NotImplementedError

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

    def fetch_lyrics(self, track) -> tuple[str, str]:
        return "", ""

    def cover_url(self, obj, dimension: int) -> str:
        return ""

    def track_facts(self, track) -> dict:
        return {}

    def classify_refusal(self, exc) -> Refusal:
        return Refusal(RefusalKind.FAILURE, str(exc) or type(exc).__name__)
