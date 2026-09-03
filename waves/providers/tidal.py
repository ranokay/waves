"""The TIDAL Provider: the seam's first implementation, by thin delegation.

Every method hands the work to the body that has always done it --
``waves.helper.tidal``'s catalog adapters, ``waves.config``'s session, and the
engine's own normalizers in ``waves.download``. The bridge routes every TIDAL
session, catalog and editorial read through this module (the seam's contract
half, ticket #22); the only tidal-object touches left in the bridge are the
engine hand-off and the config layer's credential-event wiring.

Where the provider adds code at all, it is vocabulary translation between the
engine's TIDAL-shaped facts and the seam's neutral types (quality rungs, audio
types, refusal classes) -- the drift-prone edges, each pinned in the test
suite to the backend normalizer it must agree with.
"""

from __future__ import annotations

import contextlib
import logging
import threading

import tidalapi
from requests import HTTPError
from tidalapi import page as tidal_page
from tidalapi.exceptions import AssetNotAvailable, ObjectNotFound, StreamNotAvailable, TooManyRequests
from tidalapi.media import AudioMode, Track
from tidalapi.mix import Mix

from waves.config import ATMOS_REQUEST_QUALITY, Tidal, harden_api_session, tidal_quality_for_tier
from waves.constants import CTX_TIDAL, LIBRARY_PAGE, MediaType, QualityTier, quality_rank, tier_from_word
from waves.download import _artist_ids, _tidal_refuses_asset, _waves_item_id
from waves.helper.folders import walk_playlist_tree
from waves.helper.tidal import (
    get_album_artist_ids,
    get_album_artists,
    get_tidal_media_id,
    get_tidal_media_type,
    instantiate_media,
    items_results_all,
    quality_audio_highest,
    search_results_all,
    user_media_lists,
)
from waves.providers.base import (
    AudioType,
    BrowseWindow,
    Capability,
    FavoritesUnavailable,
    Provider,
    Refusal,
    RefusalKind,
    StreamInfo,
)
from waves.waves_ui.manifest import overgenerated_tail_urls

logger = logging.getLogger("waves.providers.tidal")

_ATMOS_MODE: str = str(AudioMode.dolby_atmos.value)

# My Tidal sort: the order keys the UI speaks, mapped onto the per-category
# tidalapi order enums (moved here from the bridge so the mapping rides the
# seam with the favorites reads it serves). Direction is applied separately.
# Built only when the enums are importable; an empty map means "no
# server-side sort" (older tidalapi) and every category falls back to the API's
# default date-added order.
try:
    from tidalapi.types import AlbumOrder, ArtistOrder, ItemOrder, OrderDirection, VideoOrder

    _FAVORITES_ORDER: dict[str, dict[str, object]] = {
        "albums": {
            "date": AlbumOrder.DateAdded,
            "name": AlbumOrder.Name,
            "release": AlbumOrder.ReleaseDate,
            "artist": AlbumOrder.Artist,
        },
        "artists": {"date": ArtistOrder.DateAdded, "name": ArtistOrder.Name},
        "tracks": {"date": ItemOrder.Date, "name": ItemOrder.Name, "artist": ItemOrder.Artist},
        "videos": {"date": VideoOrder.DateAdded, "name": VideoOrder.Name, "artist": VideoOrder.Artist},
    }
except Exception:  # pragma: no cover - depends on installed tidalapi version
    _FAVORITES_ORDER = {}


def _favorites_order_kwargs(kind: str, order: tuple[str, str] | None) -> dict:
    """tidalapi favorites kwargs for a My Tidal sort, or ``{}`` for the
    default order (an absent spec, an order key the category doesn't offer,
    or an older tidalapi without ordered favourites)."""
    if not _FAVORITES_ORDER or not order:
        return {}
    order_key, direction = order
    enum = _FAVORITES_ORDER.get(kind, {}).get(order_key)
    if enum is None:
        return {}
    direction_enum = OrderDirection.Ascending if direction == "asc" else OrderDirection.Descending
    return {"order": enum, "order_direction": direction_enum}


def _enum_value(value):
    """A provider enum to its plain string value, anything else unchanged."""
    return getattr(value, "value", value)


def _tidal_id(raw) -> str:
    """A TIDAL id in the seam's namespaced spelling (§4.2: namespaced string
    ids everywhere new), empty staying empty."""
    raw = str(raw or "")
    return f"{CTX_TIDAL}:{raw}" if raw else ""


class TidalProvider(Provider):
    """TIDAL, through the existing engine bodies.

    ``stream_resolver`` is the one collaborator the engine binds when the
    download pipeline resolves through the seam (per-job state -- pacing,
    logging, tallies -- lives there, not here); without a bound resolver the
    provider carries the contract but cannot resolve streams. The binding is
    the engine's own act (:meth:`stream_resolver_bound`), scoped to each
    resolve, never a construction-time registration.
    """

    id = CTX_TIDAL
    name = "TIDAL"
    capabilities = frozenset(Capability)

    def __init__(self, tidal: Tidal, stream_resolver=None):
        self._tidal = tidal
        self._stream_resolver = stream_resolver
        # The editorial (Browse) reads serialize behind their own lock: they
        # parse through the session's SHARED page parser, which mutates itself
        # on every parse and is not thread-safe. The lock lives here because
        # the shared parser does -- every read that parses a page takes it,
        # whoever calls.
        self._browse_lock = threading.Lock()

    @contextlib.contextmanager
    def stream_resolver_bound(self, resolver):
        """Bind this caller's engine resolver for the binding's duration.

        Per-job state -- pacing, quality pinning, delivered-quality capture --
        lives in the engine, not in this translation layer, so a resolve_stream
        call crosses the seam and comes straight back to the engine that ASKED.
        The engine therefore binds its own fetch around each resolve and the
        binding is restored after it: one shared provider serves many engines
        (the GUI rebuilds its idle ``Download`` on every settings save while a
        job is running), and a construction-time registration would let the
        newest engine steal a running job's resolves -- silently dropping the
        job's pinned quality and delivered-quality capture mid-album.
        """
        previous = self._stream_resolver
        self._stream_resolver = resolver
        try:
            yield
        finally:
            self._stream_resolver = previous

    # ----- session / auth

    def login_begin(self) -> str:
        # A prior sign-out tears the session down (the engine's logout deletes
        # it outright); rebuild one so a fresh PKCE login can start -- the
        # self-heal the bridge's login slot used to carry, now where the
        # session actually lives.
        if getattr(self._tidal, "session", None) is None:
            self.reset_session()
        return self._tidal.session.pkce_login_url()

    def login_complete(self, payload: str) -> bool:
        token = self._tidal.session.pkce_get_auth_token(payload)
        self._tidal.session.process_auth_token(token, is_pkce_token=True)
        return bool(self._tidal.login_finalize())

    def logout(self) -> None:
        self._tidal.logout()

    def login_resume(self) -> bool:
        """Reopen the session from the credentials stored on disk.

        The WavesTidal wrapper the GUI passes in owns the resilience policy
        (a dead network must not cost the user their saved sign-in); the
        provider only forwards the ask."""
        return bool(self._tidal.login_token())

    def reset_session(self) -> None:
        """Rebuild the underlying tidalapi session after a sign-out.

        The engine's ``Tidal.logout()`` deletes the session object outright (a
        CLI assumption, the process exits right after logging out). The GUI is
        long-running and lets the user sign back in, so a clean session is
        rebuilt, mirroring ``Tidal.__init__``, and the configured quality is
        reapplied. Without this, a sign-out leaves the wrapper with no
        ``session`` and the next login, or any session call, raises
        ``AttributeError``.
        """
        self._tidal.session = tidalapi.Session(tidalapi.Config(item_limit=10000))
        # The rebuilt session is a fresh requests.Session too, so it needs the
        # catalog retry/timeout policy re-mounted or every call after a
        # sign-out goes back to being a single un-retried attempt.
        harden_api_session(self._tidal.session)
        self._tidal.original_client_id = self._tidal.session.config.client_id
        self._tidal.original_client_secret = self._tidal.session.config.client_secret
        # Both pairs, the same four the constructor captures: the Atmos swap
        # moves the PKCE pair too, and these are what it restores to.
        self._tidal.original_client_id_pkce = self._tidal.session.config.client_id_pkce
        self._tidal.original_client_secret_pkce = self._tidal.session.config.client_secret_pkce
        self._tidal.is_atmos_session = False
        self._tidal.settings_apply()

    @property
    def is_logged_in(self) -> bool:
        # A sign-out deletes the session object outright (the engine's CLI
        # assumption); a status refresh that lands after one reads as signed
        # out, never an AttributeError.
        session = getattr(self._tidal, "session", None)
        return bool(session and session.check_login())

    def account_id(self) -> str:
        try:
            return str(getattr(self._tidal.session.user, "id", "") or "")
        except Exception:
            return ""

    def credential_facts(self) -> dict[str, str]:
        """The session's secret-bearing facts for the caller's redactor.

        A missing session or a missing attribute answers empty rather than
        raising: this is called on every credential mint and every redactor
        refresh, and a failure must never take a login or a quality switch
        down with it.
        """
        facts: dict[str, str] = {}
        try:
            session = self._tidal.session
            for key in ("access_token", "refresh_token", "session_id"):
                facts[key] = str(getattr(session, key, "") or "")
            user = getattr(session, "user", None)
            facts["account_id"] = str(getattr(user, "id", "") or "")
            facts["username"] = str(getattr(user, "username", "") or "")
        except Exception:
            logger.debug("Could not collect the session's credential facts", exc_info=True)
        return facts

    def apply_quality(self, tier: QualityTier, audio_type: AudioType) -> None:
        # The session carries only the stereo tier, written exactly the way
        # settings_apply writes it (guard included: while the Atmos swap owns
        # the session, the stereo tier is held off it). The provider stores
        # the Waves rung as its tier string on the engine's settings; the
        # engine maps it onto its own codec vocabulary (spec §4.3). TIDAL's
        # Atmos delivery is a per-stream decision inside the fenced swap
        # machinery, never a session property this call could set.
        self._tidal.settings.data.tidal_quality_audio = str(tier.value)
        self._tidal.settings_apply()

    # ----- catalog read

    def search(self, needle: str) -> dict:
        # One page: the GUI keeps a bounded head of each bucket, so the
        # pager's serial follow-ups only ever fetched rows it discarded.
        return search_results_all(self._tidal.session, needle, single_page=True)

    def open_url(self, url: str) -> object | None:
        """Resolve a pasted share URL to the engine object it names.

        None covers every "cannot show this" case for now -- not this
        provider's grammar, an item that is gone, or a failed lookup (the
        bridge's own handler reports them identically today). Telling those
        apart to the user is the routing ticket's to decide.
        """
        media_type = get_tidal_media_type(url)
        if media_type is False:
            return None
        try:
            return instantiate_media(self._tidal.session, media_type, get_tidal_media_id(url))
        except Exception:
            return None

    def get_object(self, kind: str, raw_id: str) -> object:
        # Under the browse lock: a Mix construction parses through the SHARED
        # session.page instance (the same non-thread-safe parser the editorial
        # reads guard against); the other fetchers don't need it but holding
        # it uniformly is harmless -- and it closes the dispatch path's
        # unguarded Mix parse (a queued job resolving its object raced any
        # concurrent Browse parse).
        with self._browse_lock:
            return instantiate_media(self._tidal.session, MediaType(kind), raw_id)

    def collection_items(self, obj, include_videos: bool = True) -> list:
        # Under the browse lock: a mix's lazy items() parse runs through the
        # SHARED session.page instance (the same non-thread-safe parser the
        # editorial reads serialize), and a parse racing a browse parse
        # corrupts both. The other collections page through typed endpoints
        # that do not touch that parser; holding it uniformly was judged
        # harmless, but a long album pagination has no business blocking a
        # browse parse, so only the mix branch takes it.
        if isinstance(obj, Mix):
            with self._browse_lock:
                return items_results_all(obj, videos_include=include_videos)
        return items_results_all(obj, videos_include=include_videos)

    def user_collections(self) -> dict:
        return user_media_lists(self._tidal.session)

    def folder_tree(self, root_folders: list | None = None):
        return walk_playlist_tree(self._tidal.session, root_folders=root_folders)

    def search_tracks(self, needle: str, limit: int = 10) -> list:
        try:
            res = self._tidal.session.search(needle, models=[Track], limit=limit)
        except Exception:
            logger.debug("Track search failed for %r", needle, exc_info=True)
            return []
        return list(res.get("tracks") or [])

    # ----- editorial reads (Browse) ---------------------------------------

    def browse_page(self, title: str, api_path: str):
        """One editorial page, read and parsed. The parse is the only part
        that needs the lock (the shared session.page parser mutates itself on
        every parse), so the request is issued BEFORE the lock: an untimed
        request held under it meant one wedged peer blocked every other
        acquirer. The V2 home-feed shape degrades to the stock parser rather
        than misreading the payload, an unparseable module is dropped and
        logged, and every parsed category carries the raw paging handle
        (``_waves_pl``: dataApiPath + totals) endless scroll pages from
        later."""
        with self._browse_lock:
            page = tidal_page.Page(self._tidal.session, title)
        json_obj = page.request.request("GET", api_path, params={"deviceType": "BROWSER"}).json()
        if "rows" not in json_obj:
            # V2 home-feed shape, Browse never requests it, but degrade
            # to the stock parser rather than misreading the payload.
            with self._browse_lock:
                return page.parse(json_obj)
        page.title = str(json_obj.get("title") or "") or title
        categories = []
        for row in json_obj.get("rows") or []:
            try:
                with self._browse_lock:
                    modules = row.get("modules") or []
                    if not modules:
                        continue
                    cat = page.page_category.parse(modules[0])
                # Stash the module's raw paging handle on the parsed
                # category: dataApiPath + totals let a row load further
                # pages later (endless scroll), tidalapi's own objects
                # drop this information.
                pl = modules[0].get("pagedList") or {}
                cat._waves_pl = {
                    "data": str(pl.get("dataApiPath") or ""),
                    "total": int(pl.get("totalNumberOfItems") or 0),
                    "n": len(pl.get("items") or []),
                    "modType": str(modules[0].get("type") or ""),
                }
                categories.append(cat)
            except Exception:
                logger.debug("Skipped an unparseable browse module", exc_info=True)
        page.categories = categories
        return page

    def browse_home(self):
        """The V2 home feed as a parsed page ("Home"), each module parsed
        tolerantly: one module type tidalapi doesn't know is dropped and
        logged, the rest of the feed lives. The request runs before the
        lock (see browse_page); the parse holds it."""
        session = self._tidal.session
        json_obj = session.request.request(
            "GET",
            "home/feed/static",
            base_url=session.config.api_v2_location,
            params={"deviceType": "BROWSER", "locale": session.locale, "platform": "WEB"},
        ).json()
        # A private parser instance for the same reason as browse_page:
        # the shared session.page mutates itself on every parse.
        with self._browse_lock:
            parser = tidal_page.PageCategoryV2(session)
            page = tidal_page.Page(session, "Home")
            categories = []
            for item in json_obj.get("items") or []:
                try:
                    categories.append(parser.parse_item(item))
                except Exception:
                    logger.debug("Skipped an unparseable home module", exc_info=True)
            page.categories = categories
            return page

    def browse_window(self, title: str, data_path: str, mod_type: str, offset: int, limit: int = 50) -> BrowseWindow:
        """One paged window of an editorial category, with the RAW item count
        (the offset must advance by what the endpoint sent, never by what
        survived the parse) and the collection total. The request is issued
        before the lock; the parse holds it (see browse_page)."""
        with self._browse_lock:
            page = tidal_page.Page(self._tidal.session, title)
        j = page.request.request(
            "GET",
            data_path,
            params={"deviceType": "BROWSER", "locale": "en_US", "offset": offset, "limit": limit},
        ).json()
        raw = j.get("items") or []
        with self._browse_lock:
            cat = page.page_category.parse({"type": mod_type, "title": title, "pagedList": {"items": raw}})
        return BrowseWindow(category=cat, n=len(raw), total=int(j.get("totalNumberOfItems") or 0))

    def _favorites_parts(self, kind: str) -> tuple:
        """The favorites accessor for ``kind`` plus its total-count answer
        (``None`` when the engine offers no count) -- the shared front of
        both favorites reads."""
        favorites = self._tidal.session.user.favorites
        method = getattr(favorites, kind)
        try:
            total = int(getattr(favorites, f"get_{kind}_count")())
        except Exception:
            total = None  # no count available: fall back to the short-window stop
        return method, total

    def favorites_page(
        self, kind: str, offset: int, limit: int, order: tuple[str, str] | None = None
    ) -> tuple[list, bool]:
        # One window of the user's favorites, verbatim the bridge's ladder:
        # the order kwargs first, dropped for older tidalapi, then the
        # limit/offset kwargs, then one unpaged call sliced locally.
        method, total = self._favorites_parts(kind)
        order_kwargs = _favorites_order_kwargs(kind, order)
        try:
            raw = method(limit=limit, offset=offset, **order_kwargs) or []
        except TypeError:
            try:
                raw = method(limit=limit, offset=offset) or []
            except TypeError:
                raw = (method() or [])[offset : offset + limit]
        # A limit-N window can return FEWER than N rows (tidalapi drops
        # unavailable items inside the window), so "more" must come from the
        # total count, not the returned length; without a count, keep paging
        # until a window comes back empty.
        more = offset + limit < total if total is not None else len(raw) > 0
        return list(raw), more

    def favorite_ids(self, kind: str) -> set[str]:
        """The user's favourite ids of ``kind``, paged to exhaustion.

        The window is the engine's own 100-row favorites page
        (:data:`waves.constants.LIBRARY_PAGE`, the My Tidal page size -- one
        size so the id sweep and the paged windows can never drift apart),
        and "done" comes from the total count where one exists -- a short
        window alone would silently truncate the set for the same reason it
        would in :meth:`favorites_page`. A failure raises
        :class:`FavoritesUnavailable` carrying the ids collected so far; the
        bridge decides what a partial set is worth (it serves the stale one
        when it has it and caches nothing).
        """
        method, total = self._favorites_parts(kind)
        ids: set[str] = set()
        offset = 0
        try:
            while True:
                try:
                    batch = method(limit=LIBRARY_PAGE, offset=offset) or []
                    paged = True
                except TypeError:
                    batch = method() or []  # older tidalapi: one unpaged call
                    paged = False
                for obj in batch:
                    ids.add(str(getattr(obj, "id", "")))
                offset += LIBRARY_PAGE
                if not paged:
                    break
                if total is not None:
                    if offset >= total or not batch:  # empty guards a lying count
                        break
                elif len(batch) < LIBRARY_PAGE:
                    break
        except Exception as exc:
            raise FavoritesUnavailable(ids) from exc
        return ids

    # ----- quality

    def advertised_tier(self, obj) -> QualityTier | None:
        try:
            quality = quality_audio_highest(obj)
        except Exception:
            return None
        if quality is None:
            # No answer at all (no tags, no fallback quality): unknown stays
            # unknown. The shared fold below answers None for an unrecognized
            # spelling too, so a catalog oddity can never read as a real rung.
            return None
        return tier_from_word(quality)

    def advertised_deliveries(self, obj) -> list[tuple[QualityTier, AudioType]]:
        modes = getattr(obj, "audio_modes", None) or []
        deliveries: list[tuple[QualityTier, AudioType]] = []
        tier = self.advertised_tier(obj)
        if tier is not None and (not modes or not all(str(mode) == _ATMOS_MODE for mode in modes)):
            # A stereo master exists and its tier is known: advertise exactly
            # what the catalog states, nothing more.
            deliveries.append((tier, AudioType.STEREO))
        if _ATMOS_MODE in {str(mode) for mode in modes}:
            # Atmos rides ONE fixed request tier the quality setting cannot
            # raise; the UI words an Atmos delivery ATMOS, never a rung.
            deliveries.append((tier_from_word(ATMOS_REQUEST_QUALITY), AudioType.ATMOS))
        return deliveries

    def advertised_ceiling(self, obj) -> int | None:
        # Mirrors the backend gate's input: only the explicit metadata tags
        # are trusted; tags below the lossless line never cap.
        try:
            tags = {str(getattr(tag, "value", tag)) for tag in getattr(obj, "media_metadata_tags", None) or []}
        except Exception:
            return None
        if "HIRES_LOSSLESS" in tags:
            return quality_rank(QualityTier.HI_RES_LOSSLESS)
        if "LOSSLESS" in tags:
            return quality_rank(QualityTier.LOSSLESS)
        return None

    # ----- per-track delivery

    def resolve_stream(self, track, tier: QualityTier, audio_type: AudioType) -> StreamInfo:
        if self._stream_resolver is None:
            raise RuntimeError(  # noqa: TRY003
                "TidalProvider has no stream resolver bound; "
                "the engine binds its own fetch around each resolve "
                "(stream_resolver_bound) before calling through the seam"
            )
        return self._as_stream_info(self._stream_resolver(track, tier, audio_type))

    @staticmethod
    def _as_stream_info(info) -> StreamInfo:
        """The engine's stream answer into the neutral shape.

        The delivered snapshot carries the same facts as the backend's own
        normalizer, in the seam's vocabulary (``audio_type``, the neutral
        word, where the backend snapshot says ``audio_mode``); the suite pins
        the translation of the two together. The URL list is the stream
        itself: the engine's no-stream answer (no manifest behind it)
        translates to the all-default StreamInfo, which is the seam's "could
        not resolve". The byte-pipeline steering facts -- the DASH tail
        arithmetic, the encrypted-stream verdict, the single-file shape --
        come off the same engine answer, so the pipeline never touches the
        manifest again.
        """
        stream = getattr(info, "media_stream", None)
        manifest = getattr(info, "stream_manifest", None)

        if manifest is None:
            return StreamInfo()

        urls: list = []
        try:
            urls = list(manifest.get_urls() or [])
        except Exception:
            urls = []

        audio_mode = _enum_value(getattr(stream, "audio_mode", None))
        replay_gain = None
        if stream is not None:
            replay_gain = {
                "album_replay_gain": getattr(stream, "album_replay_gain", None),
                "album_peak_amplitude": getattr(stream, "album_peak_amplitude", None),
                "track_replay_gain": getattr(stream, "track_replay_gain", None),
                "track_peak_amplitude": getattr(stream, "track_peak_amplitude", None),
            }
        codecs = getattr(manifest, "codecs", None)
        return StreamInfo(
            urls=urls,
            file_extension=getattr(info, "file_extension", "") or "",
            codecs=codecs or "",
            requires_flac_extraction=bool(getattr(info, "requires_flac_extraction", False)),
            delivered={
                "tier": _enum_value(getattr(stream, "audio_quality", None)),
                "audio_type": str(AudioType.ATMOS if str(audio_mode) == _ATMOS_MODE else AudioType.STEREO),
                "bit_depth": getattr(stream, "bit_depth", None),
                "sample_rate": getattr(stream, "sample_rate", None),
                "codecs": codecs,
            },
            replay_gain=replay_gain,
            encrypted=bool(getattr(manifest, "is_encrypted", False)),
            tail_spurious=overgenerated_tail_urls(manifest),
            single_file=bool(getattr(stream, "is_bts", False)),
        )

    def resolve_preview(self, track) -> StreamInfo:
        """The full-track preview's stream resolution.

        The caller's preview pipeline (HLS localisation, the ffmpeg remux)
        stays app-side; what moved behind the seam is the session work the
        resolve needs: it holds the stream lock (a concurrent or subsequent
        download is never silently downgraded), normalises the session out of
        Atmos mode, pins LOW for its own fetch and restores the configured
        tier in ``finally`` (``restore_normal_session`` early-returns without
        touching quality in normal mode, per config.py). An encrypted stream
        answers ``encrypted`` -- Waves does not process encrypted streams, so
        there is nothing here to preview. A failed normalisation answers the
        all-default StreamInfo: the caller reports the preview failed.
        """
        with self._tidal.stream_lock:
            try:
                if not self._tidal.restore_normal_session():
                    return StreamInfo()
                self._tidal.session.audio_quality = tidalapi.Quality.low_96k
            except Exception:
                logger.debug("Could not normalise the session for preview", exc_info=True)
                return StreamInfo()
            try:
                stream = track.get_stream()
                manifest = stream.get_stream_manifest()
                if manifest.is_encrypted:
                    return StreamInfo(encrypted=True)
                is_bts = bool(stream.is_bts)
                return StreamInfo(
                    urls=list(manifest.get_urls() or []),
                    codecs=getattr(manifest, "codecs", "") or "",
                    encrypted=False,
                    single_file=is_bts,
                    # Only an MPD manifest has an HLS answer; a BTS one raises.
                    hls_url=("" if is_bts else self._hls_url(manifest)),
                )
            finally:
                # Canonical resting quality, NOT restore_normal_session(),
                # which leaves quality untouched in normal mode (config.py).
                # The settings hold Waves tier strings; the engine maps the
                # rung onto its own codec vocabulary (issue #24).
                with contextlib.suppress(Exception):
                    tier = tier_from_word(self._tidal.settings.data.tidal_quality_audio)
                    if tier is not None:
                        self._tidal.session.audio_quality = tidal_quality_for_tier(tier)

    @staticmethod
    def _hls_url(manifest) -> str:
        try:
            return str(manifest.get_hls() or "")
        except Exception:
            return ""

    def fetch_lyrics(self, track) -> tuple[str, str]:
        # TIDAL's native lyrics only: the LRCLIB-first precedence is shared
        # policy above the seam, and the engine keeps calling it until routed.
        try:
            lyrics = track.lyrics()
        except Exception:
            return "", ""
        return lyrics.subtitles or "", lyrics.text or ""

    def cover_url(self, obj, dimension: int) -> str:
        # Best-effort, mirroring the backend's image helper: fall back to the
        # engine object's own default size when the requested one is rejected
        # (artist art allows only 160/320/480/750), and answer "" rather than
        # raising -- an unavailable cover is no cover, never a failure.
        target = obj if hasattr(obj, "image") else getattr(obj, "album", None)
        if target is None or not hasattr(target, "image"):
            return ""
        for call in (lambda: target.image(int(dimension)), lambda: target.image()):
            try:
                url = call()
            except Exception:
                url = ""
            if url:
                return url
        return ""

    def track_facts(self, track) -> dict:
        """The fact schema the tag writer reads, pulled once, here.

        Mirrors the engine's inline fact pull field for field -- the engine's
        metadata_write consumes this dict instead of reaching into the engine
        objects, so tagging stays provider-neutral. The suite pins the schema.
        """
        album = getattr(track, "album", None)

        def _date(value) -> str:
            try:
                return value.strftime("%Y-%m-%d") if value else ""
            except Exception:
                return ""

        if album is not None:
            release_date = _date(getattr(album, "available_release_date", None)) or _date(
                getattr(album, "release_date", None)
            )
        else:
            release_date = ""
        release_type = str(album.type).lower() if album is not None and getattr(album, "type", None) else ""

        return {
            # Identity rides the seam's namespaced spelling (§4.2) -- the new
            # schema never bares an id; the legacy tag writer strips when it
            # writes the WAVES_TIDAL_* tags it still owns.
            "item_id": _tidal_id(_waves_item_id(track)),
            "artist_ids": [_tidal_id(artist_id) for artist_id in _artist_ids(track)],
            "album_artist_ids": [_tidal_id(artist_id) for artist_id in get_album_artist_ids(track)],
            # Every credited artist keeps its name, exactly the old tag pull
            # (`a.name for a in track.artists`): a credit whose id never
            # arrived still belongs on the ARTIST tag (the id lists below
            # filter separately). Dropping the whole pair would silently
            # shrink the tag.
            "artists": [
                (_tidal_id(getattr(artist, "id", None)), artist.name)
                for artist in getattr(track, "artists", None) or []
            ],
            "album_artists": get_album_artists(track),
            "copyright": track.copyright if getattr(track, "copyright", None) else "",
            "isrc": track.isrc if getattr(track, "isrc", None) else "",
            "explicit": bool(getattr(track, "explicit", False)),
            "bpm": track.bpm if getattr(track, "bpm", None) else 0,
            "key": getattr(track, "key", None),
            "key_scale": getattr(track, "key_scale", None),
            "share_url": getattr(track, "share_url", None) or "",
            "volume_num": track.volume_num,
            "track_num": track.track_num,
            "release_date": release_date,
            "release_type": release_type,
            "album": {
                "name": album.name if album is not None else "",
                "num_tracks": album.num_tracks if album is not None else None,
                "num_volumes": album.num_volumes if album is not None else None,
                "upc": album.upc if album is not None else "",
                "type": album.type if album is not None else "",
            },
        }

    # ----- refusals

    def classify_refusal(self, exc) -> Refusal:
        """The engine's refusal decision, restated in the shared vocabulary.

        Agreement with the engine's stream-info failure handling is pinned
        test-side: unavailable exactly when the engine would mark it so.
        """
        if isinstance(exc, TooManyRequests):
            return Refusal(RefusalKind.THROTTLED, "TIDAL is rate-limiting; back off and retry")
        message = None
        if isinstance(exc, HTTPError):
            message = _tidal_refuses_asset(exc)
        if message is not None or isinstance(exc, StreamNotAvailable | ObjectNotFound | AssetNotAvailable):
            return Refusal(RefusalKind.UNAVAILABLE, message or "this item is not available on TIDAL")
        return Refusal(RefusalKind.FAILURE, str(exc) or type(exc).__name__)
