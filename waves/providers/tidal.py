"""The TIDAL Provider: the seam's first implementation, by thin delegation.

Every method hands the work to the body that has always done it --
``waves.helper.tidal``'s catalog adapters, ``waves.config``'s session, and the
engine's own normalizers in ``waves.download`` -- with no logic moved and no
behavior changed. The call-site routing that makes the bridge speak through
here is deliberately NOT part of this module's arrival (expand first, contract
later): until then the old paths keep running, and the tests pin that this
delegation returns what those paths return.

Where the provider adds code at all, it is vocabulary translation between the
engine's TIDAL-shaped facts and the seam's neutral types (quality rungs, audio
types, refusal classes) -- the drift-prone edges, each pinned in the test
suite to the backend normalizer it must agree with.
"""

from __future__ import annotations

import tidalapi
from requests import HTTPError
from tidalapi.exceptions import AssetNotAvailable, ObjectNotFound, StreamNotAvailable, TooManyRequests
from tidalapi.media import AudioMode

from waves.config import Tidal
from waves.constants import ATMOS_REQUEST_QUALITY, CTX_TIDAL, MediaType
from waves.download import _artist_ids, _tidal_refuses_asset, _waves_item_id
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
    Capability,
    Provider,
    QualityTier,
    Refusal,
    RefusalKind,
    StreamInfo,
    quality_rank,
)
from waves.waves_ui.manifest import overgenerated_tail_urls

# The Waves tier each TIDAL request rides: the rungs the UI's own spec lines
# name (LOW = AAC 96, HIGH = AAC 320, then lossless and hi-res lossless).
_TIDAL_QUALITY_BY_TIER: dict[QualityTier, tidalapi.Quality] = {
    QualityTier.LOW: tidalapi.Quality.low_96k,
    QualityTier.HIGH: tidalapi.Quality.low_320k,
    QualityTier.LOSSLESS: tidalapi.Quality.high_lossless,
    QualityTier.HI_RES_LOSSLESS: tidalapi.Quality.hi_res_lossless,
}

_ATMOS_MODE: str = str(AudioMode.dolby_atmos.value)


def _enum_value(value):
    """A provider enum to its plain string value, anything else unchanged."""
    return getattr(value, "value", value)


def _tidal_id(raw) -> str:
    """A TIDAL id in the seam's namespaced spelling (§4.2: namespaced string
    ids everywhere new), empty staying empty."""
    raw = str(raw or "")
    return f"{CTX_TIDAL}:{raw}" if raw else ""


def tier_from_tidal(quality: tidalapi.Quality | str) -> QualityTier:
    """A TIDAL quality spelling onto the Waves ladder.

    tidalapi 0.8's tier values are already the ladder's strings; the fall
    through handles the legacy spellings a delivered stream can carry
    (``low_320k`` etc.), folded exactly the way the backend's tier words fold
    them, so a row's badge and its rank can never disagree.
    """
    name = str(getattr(quality, "value", quality))
    try:
        return QualityTier(name)
    except ValueError:
        pass
    lowered = name.lower()
    if "hi_res" in lowered or "hires" in lowered:
        return QualityTier.HI_RES_LOSSLESS
    if "lossless" in lowered:
        return QualityTier.LOSSLESS
    if "320" in lowered or lowered == "high":
        return QualityTier.HIGH
    return QualityTier.LOW


class TidalProvider(Provider):
    """TIDAL, through the existing engine bodies.

    ``stream_resolver`` is the one collaborator the engine registers when the
    download pipeline routes through the seam (per-job state -- pacing,
    logging, tallies -- lives there, not here); without it the provider
    carries the contract but cannot resolve streams.
    """

    id = CTX_TIDAL
    name = "TIDAL"
    capabilities = frozenset(Capability)

    def __init__(self, tidal: Tidal, stream_resolver=None):
        self._tidal = tidal
        self._stream_resolver = stream_resolver

    def set_stream_resolver(self, resolver) -> None:
        """The engine registers its per-job resolver here.

        Per-job state -- pacing, quality pinning, delivered-quality capture --
        lives in the engine, not in this translation layer, so the provider
        carries the contract and the engine the behavior: a resolve_stream
        call hands the job straight back to whoever registered last. The GUI
        runs one download job at a time, so the latest registration is the
        live one.
        """
        self._stream_resolver = resolver

    # ----- session / auth

    def login_begin(self) -> str:
        return self._tidal.session.pkce_login_url()

    def login_complete(self, payload: str) -> bool:
        token = self._tidal.session.pkce_get_auth_token(payload)
        self._tidal.session.process_auth_token(token, is_pkce_token=True)
        return bool(self._tidal.login_finalize())

    def logout(self) -> None:
        self._tidal.logout()

    @property
    def is_logged_in(self) -> bool:
        return bool(self._tidal.session.check_login())

    def apply_quality(self, tier: QualityTier, audio_type: AudioType) -> None:
        # The session carries only the stereo tier, written exactly the way
        # settings_apply writes it (guard included: while the Atmos swap owns
        # the session, the stereo tier is held off it). TIDAL's Atmos delivery
        # is a per-stream decision inside the fenced swap machinery, never a
        # session property this call could set.
        self._tidal.settings.data.quality_audio = _TIDAL_QUALITY_BY_TIER[tier]
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
        return instantiate_media(self._tidal.session, MediaType(kind), raw_id)

    def collection_items(self, obj, include_videos: bool = True) -> list:
        return items_results_all(obj, videos_include=include_videos)

    def user_collections(self) -> dict:
        return user_media_lists(self._tidal.session)

    # ----- quality

    def advertised_tier(self, obj) -> QualityTier | None:
        try:
            quality = quality_audio_highest(obj)
        except Exception:
            return None
        return tier_from_tidal(quality)

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
            deliveries.append((tier_from_tidal(ATMOS_REQUEST_QUALITY), AudioType.ATMOS))
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
                "TidalProvider has no stream resolver registered; "
                "the download engine registers one when the pipeline routes through the seam"
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
        release_type = (
            str(album.type).lower() if album is not None and getattr(album, "type", None) else ""
        )

        return {
            # Identity rides the seam's namespaced spelling (§4.2) -- the new
            # schema never bares an id; the legacy tag writer strips when it
            # writes the WAVES_TIDAL_* tags it still owns.
            "item_id": _tidal_id(_waves_item_id(track)),
            "artist_ids": [_tidal_id(artist_id) for artist_id in _artist_ids(track)],
            "album_artist_ids": [_tidal_id(artist_id) for artist_id in get_album_artist_ids(track)],
            "artists": [
                (_tidal_id(artist.id), artist.name)
                for artist in getattr(track, "artists", None) or []
                if getattr(artist, "id", None)
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
