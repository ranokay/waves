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


@dataclass
class StreamInfo:
    """What a provider's stream resolution hands the download pipeline:
    everything the shared segment/file pipeline needs, no engine types."""

    urls: list[str] = field(default_factory=list)
    file_extension: str = ""
    codecs: str = ""
    requires_flac_extraction: bool = False
    # The delivered-quality snapshot: {tier, audio_mode, bit_depth,
    # sample_rate, codecs}, normalized to plain strings/ints for the
    # ownership record.
    delivered: dict = field(default_factory=dict)
    # ReplayGain measurements where the provider serves them; None leaves the
    # tags untagged (the existing rule for a stream without measurements).
    replay_gain: dict | None = None


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
        one. TIDAL's previews ride the engine's own pipeline and leave this
        unwired; the PREVIEW capability says whether to call it at all."""
        return None
