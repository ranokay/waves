"""The Provider seam's neutral half: the interface every music provider plugs
into, and the Waves-owned vocabulary it speaks.

Deliberately import-light (standard library only -- no tidalapi, no Qt): the
neutral types are consumable by the engine, the bridge, the tests, and the
second provider without dragging anyone else along.

The design is the wayfinder map's Provider-seam decision (spec §4): one fused
interface that TIDAL and Apple Music both implement, the row-dict schema as
the contract with QML, namespaced string ids everywhere new, and one
Waves-owned quality scale with the audio type (stereo / Dolby Atmos)
orthogonal to it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import NamedTuple

# ============================================================================
# The row-dict schema (the catalog contract with QML)
# ============================================================================
#
# Every provider serves the SAME plain dicts the QML consumes today; the
# field names below are the contract, spelled exactly as the bridge's dict
# builders write them. ``id`` is always the ENGINE's own id as a string (the
# key the bridge remembers the live object under in its ``_objs`` buckets);
# namespacing happens above this layer. A missing fact is "", 0, -1 or None
# exactly as noted -- rows are never partial-keyed (a QML ListModel freezes
# its roles on the first row appended).
#
# Result rows (search payload, library pages, artist pages, browse cards):
#   artist row:   {id, name, art, roles, popularity}
#                   art: cover URL at 320px, best-effort "" when absent.
#                   roles: display words for the artist's credits ("Artist"
#                   when none). popularity: 0-100, or -1 until enriched.
#   album row:    {id, title, artist, artist_id, artists, art, year, date,
#                  tracks, duration_sec, quality, popularity, explicit, added}
#                   artist: the album-artist line; artist_id: its single id;
#                   artists: the full credited list [{id, name, roles}];
#                   tracks: track count (0 unknown); duration_sec: release
#                   length in raw seconds (0 unknown) -- the presence
#                   matcher's duration witness; quality: the advertised tier
#                   word ("" unknown); date: "YYYY-MM-DD" or ""; added: the
#                   user's date-added "YYYY-MM-DDTHH:MM:SS" or "".
#   track row:    {id, title, artist, artist_id, artists, album, album_id,
#                  num, vol, art, year, date, duration, duration_sec,
#                  quality, popularity, explicit, added}
#                   duration: "M:SS"; num/vol: track and volume numbers
#                   (0/1 defaults); art: 160px thumb.
#   video row:    {id, title, artist, artists, art, art_big, duration,
#                  explicit, added, date, quality}
#                   art/art_big: 160x107 / 750x500 stills (videos are sized
#                   as a width-height PAIR, not a square); quality: the
#                   resolution label ("1080p", "" unknown).
#   playlist row: {id, title, art, tracks, creator, added, kind, sub, path,
#                  plCount}
#                   kind: "playlist"; sub/path/plCount: "" / "" / 0 here,
#                   filled by the bridge for playlist FOLDER rows, which
#                   share this exact key set (kind: "folder") so a QML
#                   ListModel never sees a new role mid-list.
#   mix row:      {id, title, art, subtitle, added}
#
# Payloads built from those rows:
#   search payload:
#     {artists, albums, tracks, videos, playlists, mixes: [row...], top}
#     top: the provider's best match as a row dict tagged with its kind
#     ("album"/"track"/"video"/"playlist" -- an artist top hit is dropped,
#     the artist strip already leads with it), or None.
#   album expansion rows:  {id, num, title, duration, popularity, explicit}
#     num: 1-based position in the album.
#   playlist expansion rows:
#     {id, kind, num, title, artist, duration, popularity, explicit}
#     kind: "track" or "video" (the row routes its own download).
#   artist page payload:
#     {id, name, art, bio, albums: [album row], eps: [album row],
#      tracks: [track row]}
#     plus the bridge's context flags (refresh, libraryScoped).
#   My Tidal home payload:
#     sections: [{rowKind: "cards"|"tracks", title, target, items: [row]}]
#     items additionally tagged with their row kind ("album"/"track").
#
# Until the dict builders move into the providers (the second provider's
# arrival), the bridge builds these rows FROM the engine objects the reads
# below return: the reads are the seam, the builders are the rendering, and
# the schema above is what both must agree on. Object-method calls on an
# already-resolved object (an album's .tracks(), an artist's .get_albums())
# are the bridge's page-building policy, not session reaches -- they move
# behind the interface when the dict builders do.

# The one delivered-quality ladder, lowest to highest. Its strings are the
# keys of the ownership store's QUALITY_RANK scale (and, as it happens,
# tidalapi's own tier values): a caller asks "is a better tier available than
# what is on disk" with a plain integer comparison. Bit depth and sample rate
# are deliberately not used for ranking.


class QualityTier(StrEnum):
    """A rung on Waves' own quality ladder, provider-independent."""

    LOW = "LOW"
    HIGH = "HIGH"
    LOSSLESS = "LOSSLESS"
    HI_RES_LOSSLESS = "HI_RES_LOSSLESS"


def quality_rank(tier: QualityTier | str) -> int:
    """The integer rank of a tier on the shared ladder (LOW = 0)."""
    return TIER_RANK[str(getattr(tier, "value", tier))]


TIER_RANK: dict[str, int] = {tier.value: rank for rank, tier in enumerate(QualityTier)}


class AudioType(StrEnum):
    """Which mix of a track a delivery carries (CONTEXT.md: audio type) --
    orthogonal to the quality tier, never a rung on its ladder."""

    STEREO = "stereo"
    ATMOS = "atmos"


class Capability(StrEnum):
    """What a provider can do. The bridge consults these instead of
    branching on provider identity, so Browse / My TIDAL / mixes / videos
    stay TIDAL-only without if-branches."""

    SEARCH = "search"
    OPEN_URL = "open_url"
    CATALOG = "catalog"
    DOWNLOAD = "download"
    LYRICS = "lyrics"
    ART = "art"
    BROWSE = "browse"
    FAVORITES = "favorites"
    MIXES = "mixes"
    VIDEOS = "videos"
    PREVIEW = "preview"


class RefusalKind(StrEnum):
    """How to read an engine error, shared across providers.

    UNAVAILABLE is final: the provider will not serve this item (counted
    unavailable, never retried). THROTTLED is the provider rate-limiting:
    retry after a wait. FAILURE is everything else: retryable.
    """

    UNAVAILABLE = "unavailable"
    THROTTLED = "throttled"
    FAILURE = "failure"


@dataclass(frozen=True)
class Refusal:
    """A classified engine error: the shared refusal-vs-failure verdict plus
    the provider's own user-facing words when it refused the item itself."""

    kind: RefusalKind
    message: str = ""


class FavoritesUnavailable(Exception):
    """A favorite-id read failed partway; ``ids`` carries what was collected.

    The bridge serves the partial set (or its stale cache) but never caches
    it, so the caller's badges read as much truth as the failed read gathered
    -- exactly the old path's rule: a partial set stamped fresh would read as
    "you have nothing by this artist" until the TTL expired.
    """

    def __init__(self, ids: set[str]):
        super().__init__("favourite pagination failed")
        self.ids = ids


class BrowseWindow(NamedTuple):
    """One paged window of an editorial category: the parsed category, the
    RAW item count the window returned (a parse may drop items; the caller's
    offset must advance by what the endpoint actually sent, or it rewinds),
    and the collection total."""

    category: object
    n: int
    total: int


@dataclass
class StreamInfo:
    """What a provider's stream resolution hands the download pipeline:
    everything the shared segment/file pipeline needs, no engine types.

    The no-stream answer is the all-default instance: an empty ``urls`` means
    the provider could not resolve a streamable delivery (the pipeline treats
    it exactly like a failed fetch).
    """

    urls: list[str] = field(default_factory=list)
    file_extension: str = ""
    codecs: str = ""
    requires_flac_extraction: bool = False
    # The delivered-quality snapshot: {tier, audio_type, bit_depth,
    # sample_rate, codecs}, normalized to plain strings/ints for the
    # ownership record.
    delivered: dict = field(default_factory=dict)
    # ReplayGain measurements where the provider serves them; None leaves the
    # tags untagged (the existing rule for a stream without measurements).
    # Keys, where measured: album_replay_gain, album_peak_amplitude,
    # track_replay_gain, track_peak_amplitude.
    replay_gain: dict | None = None
    # The provider refuses to serve an encrypted delivery as audio: the
    # pipeline must fail the item rather than write an unplayable file.
    encrypted: bool = False
    # Provider-proven count of over-generated trailing URLs (padding whose
    # failure is harmless); None when nothing is proven and the pipeline
    # keeps its legacy last-segment leniency.
    tail_spurious: int | None = None
    # The delivery arrived as one complete file (no fragmented-segment merge),
    # so its container is already whole and needs no duration-repairing remux.
    single_file: bool = False
    # The HLS master playlist URL when the delivery is HLS-shaped (TIDAL's
    # non-BTS streams): the preview pipeline reads it, the download pipeline
    # does not. Empty when the delivery is not HLS.
    hls_url: str = ""


class Provider(ABC):
    """One music service Waves can search and save from (CONTEXT.md).

    Implementations return the app's plain dicts and neutral types; the
    row-dict schema QML already consumes IS the catalog contract, and the
    catalog objects stay inside the provider (the bridge resolves ids back to
    objects through :meth:`get_object`).
    """

    id: str
    name: str
    capabilities: frozenset[Capability]

    # ----- session / auth

    @abstractmethod
    def login_begin(self) -> str:
        """Start the login flow; returns the URL (or flow entry) for the GUI."""

    @abstractmethod
    def login_complete(self, payload: str) -> bool:
        """Complete the login with the user's payload (pasted URL / code)."""

    @abstractmethod
    def logout(self) -> None:
        """Forget the account's credentials."""

    @abstractmethod
    def login_resume(self) -> bool:
        """Reopen the session from the credentials stored on disk (the app's
        launch path). False when there is nothing usable stored, or the
        provider refused them."""

    @abstractmethod
    def reset_session(self) -> None:
        """Rebuild a clean session after a sign-out, so the user can sign
        back in without restarting the app. A long-lived GUI cannot share the
        CLI's assumption that the process exits right after logging out."""

    @abstractmethod
    def account_id(self) -> str:
        """The signed-in account's id, as a plain string ("" unknown). The
        key cached page snapshots are stamped with, so one account's
        personalized pages never render for another."""

    @abstractmethod
    def credential_facts(self) -> dict[str, str]:
        """The session's secret-bearing facts, keyed by what they are (e.g.
        ``access_token``, ``session_id``, ``account_id``, ``username``). The
        caller registers each value with the log redactor at the moment it
        exists; the mapping to redactor tags stays with the caller."""

    @property
    @abstractmethod
    def is_logged_in(self) -> bool:
        """Whether the provider currently holds a working session."""

    @abstractmethod
    def apply_quality(self, tier: QualityTier, audio_type: AudioType) -> None:
        """Make the provider request the given tier for subsequent streams.

        The audio type is carried for interface symmetry: how a provider
        delivers Atmos (TIDAL's per-stream session swap, Apple's own codec) is
        that provider's fenced business, decided per stream -- never by this
        call.
        """

    # ----- catalog read (returns the app's row dicts; the schema is the contract)

    @abstractmethod
    def search(self, needle: str) -> dict:
        """Search the catalog; returns the provider's share of the search
        payload (per-type buckets of engine objects plus ``top_hit``), which
        the bridge caps and renders. Needs no user setup beyond the
        provider's own session rules."""

    @abstractmethod
    def open_url(self, url: str) -> object | None:
        """Resolve a pasted share URL to the catalog object it names, or None
        when the URL is not this provider's grammar / the item is gone. The
        bridge builds the page payload from the resolved object."""

    @abstractmethod
    def get_object(self, kind: str, raw_id: str) -> object:
        """The id -> engine object resolver every dispatch goes through."""

    @abstractmethod
    def collection_items(self, obj, include_videos: bool = True) -> list:
        """Enumerate a collection's items (tracks/videos/albums), honoring
        the music-videos switch."""

    @abstractmethod
    def user_collections(self) -> dict | None:
        """The signed-in user's collections (playlists/mixes), or None when
        the provider has no such capability."""

    @abstractmethod
    def folder_tree(self, root_folders: list | None = None) -> object | None:
        """The user's playlist-folder tree (every level's folders, each
        folder's playlists, and the playlist-id -> folder-path map), or None
        when the provider has no folders.

        ``root_folders`` are already-fetched root folders to reuse (a caller
        mid-sweep has them in hand); fetched fresh when None."""

    @abstractmethod
    def search_tracks(self, needle: str, limit: int = 10) -> list:
        """A lightweight, track-only search: the first ``limit`` track matches
        for ``needle``, as engine objects. The video player's title-link
        fallback lives on this shape -- a full search payload would pay for
        buckets the heuristic never reads."""

    @abstractmethod
    def browse_page(self, title: str, api_path: str) -> object | None:
        """One editorial (Browse) page, read and parsed: the engine's page
        object for ``api_path``, ``title``-labelled. None when the page
        cannot be read. The bridge renders the parsed categories; where the
        bytes come from stays the provider's business."""

    @abstractmethod
    def browse_home(self) -> object | None:
        """The personalized home feed as a parsed page object, or None when
        the provider has no such feed."""

    @abstractmethod
    def browse_window(
        self, title: str, data_path: str, mod_type: str, offset: int, limit: int = 50
    ) -> BrowseWindow:
        """One paged window of an editorial category: the parsed category,
        the RAW item count the window returned (the paging arithmetic's
        input -- a parse may drop items, the offset may not rewind), and the
        collection total."""

    @abstractmethod
    def favorites_page(
        self, kind: str, offset: int, limit: int, order: tuple[str, str] | None = None
    ) -> tuple[list, bool]:
        """One window ``[offset, offset+limit)`` of the signed-in user's
        favorites of ``kind`` (e.g. "tracks", "albums"), as engine objects,
        paired with whether more exist beyond the window.

        ``order`` is the neutral sort spec ``(key, direction)`` -- keys from
        the UI's vocabulary ("date", "name", "release", "artist"; direction
        "asc"/"desc"), mapped onto the engine's own order enums inside the
        provider. None asks for the engine's default order.

        The "more" verdict must come from the provider's total count when it
        has one: a limit-N window can return fewer than N rows (unavailable
        items dropped inside the window), so a short window alone would
        silently truncate the set.
        """

    @abstractmethod
    def favorite_ids(self, kind: str) -> set[str]:
        """Every id in the signed-in user's favorites of ``kind``, paged to
        exhaustion, as plain strings. The bridge filters catalog rows against
        these, so the ids are the engine's own (bare, not namespaced) -- the
        same spelling a row's ``id`` field carries.

        A failure raises :class:`FavoritesUnavailable` carrying the ids
        collected before it; it must never raise a bare error and lose them,
        and must never swallow the failure and serve a partial set as fresh.
        """

    # ----- quality -- what the Chooser presents

    @abstractmethod
    def advertised_tier(self, obj) -> QualityTier | None:
        """The best tier the provider advertises for this object, on the
        Waves ladder; None when unknown."""

    @abstractmethod
    def advertised_deliveries(self, obj) -> list[tuple[QualityTier, AudioType]]:
        """Every (tier, audio type) delivery the provider advertises for this
        object -- the Chooser's option list."""

    @abstractmethod
    def advertised_ceiling(self, obj) -> int | None:
        """Best advertised quality rank, or None when unknown. Feeds the
        upgrade-convergence gate, so it must trust only explicit signals."""

    # ----- per-track delivery

    @abstractmethod
    def resolve_stream(self, track, tier: QualityTier, audio_type: AudioType) -> StreamInfo:
        """Resolve a track to a streamable delivery at the requested tier and
        audio type."""

    @abstractmethod
    def fetch_lyrics(self, track) -> tuple[str, str]:
        """The provider's NATIVE lyrics for a track as (synced, plain). The
        LRCLIB-first precedence lives above this, shared by both providers."""

    @abstractmethod
    def cover_url(self, obj, dimension: int) -> str:
        """Best-effort cover URL at the requested square dimension ('' when
        the object carries no image), the app's existing convention."""

    @abstractmethod
    def track_facts(self, track) -> dict:
        """The fact schema the tag writer reads (copyright, ISRC, album
        block, credited artists and their ids...), extracted from the engine
        objects so tagging stays provider-neutral."""

    @abstractmethod
    def classify_refusal(self, exc) -> Refusal:
        """Classify an engine error into the shared refusal vocabulary."""

    # ----- optional hooks

    def preview_url(self, track) -> str | None:
        """A directly-streamable preview URL, when the provider documents
        one; None (the inherited default) when it does not. The PREVIEW
        capability says whether to call the hook at all."""
        return None

    def resolve_preview(self, track) -> StreamInfo:
        """A full preview STREAM resolution for providers whose previews need
        their own session machinery (TIDAL's full-track preview: the stream
        lock, the session normalisation, the LOW-tier pin and its restore are
        fenced provider business, never the caller's).

        The all-default StreamInfo (the inherited default) is "could not
        resolve": the caller reports the preview failed rather than crashing.
        A provider answering through :meth:`preview_url` alone never needs
        this hook."""
        return StreamInfo()
