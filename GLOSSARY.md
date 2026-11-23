# Waves

Waves is a native desktop app for saving music from the user's own accounts, search-first and art-forward.

This vocabulary covers the accepted product design. The [architecture map](docs/architecture.md)
describes current owners; the [ADRs](docs/adr/) distinguish implemented contracts
from planned extensions.

## Language

**Provider**:
A music service/account/catalog owner. It contributes only the operations it implements.
_Avoid_: source, backend

**Provider descriptor**:
A provider's static identity as the surfaces that list providers need it — its
name, mark, one honest capability line, its card's own action words and the
Settings fields its card owns — composed by the bridge with live status into
what those surfaces render.
_Avoid_: provider config, provider metadata

**Engine**:
An execution component subordinate to a Provider, possibly wrapping an external
tool. A provider can route supported operations through several engines.
_Avoid_: downloader, backend

**Runtime**:
The resources and lifecycle an engine uses: a built-in client, Waves-managed
external service, or user-managed endpoint. Engines sharing a runtime may share
an account or failure boundary.
_Avoid_: provider, engine (for the execution resource)

**Download adapter**:
A provider's own surface for serving download asks; providers without one use the shared engine path.
_Avoid_: provider hook, download hook

**Chooser**:
The per-download control (Download With) where the user compares catalog offers
and selects a provider, delivery and lyrics/art options. Defaults come from
Settings; explicit choices apply to the captured download request.
_Avoid_: download dialog, picker

**Catalog offer**:
A provider's identified representation of the requested media, with matching
evidence, delivery capability, ownership/presence and readiness. Match confidence
describes identity; it does not verify a delivered file.
_Avoid_: universal catalog, provider (for a matched item)

**Search source**:
One provider's participation in a search: its own result rows and its own
failure words. A merged search row exposes every source that returned a
high-confidence equivalent; unmerged rows keep their single source.
_Avoid_: group, provider section

**Audio type**:
Which mix of a track is being saved: stereo or Dolby Atmos.
_Avoid_: mix, format, mode

**Audio quality**:
The fidelity tier a download is fetched at, stated on Waves' own four-rung ladder (LOW < HIGH < LOSSLESS < `HI_RES_LOSSLESS`), serialized as the ladder's tier strings. Audio type is orthogonal to it. Each provider maps its engine's codecs onto the rungs (e.g. AAC 320 → HIGH, ALAC 24/192 → `HI_RES_LOSSLESS`).
_Avoid_: bitrate, resolution

**Version**:
One saved instance of a track from a particular provider at a specific audio
type, with its actual delivery facts and provenance. A track can have several
Versions.
_Avoid_: copy, duplicate

**Dual-download**:
Saving a track's stereo and Dolby Atmos versions in one click; each lands as its own Version, with its own ownership, badge, and placement.
_Avoid_: both-versions, Atmos-and-stereo

**Quarantine**:
Where Waves holds a download that failed its integrity check, kept outside the library until a verified copy replaces it.
_Avoid_: trash, failed files

**Ownership**:
Waves' record of which versions it has already saved, per provider.
_Avoid_: history, cache

**Config-first**:
The standing principle that anything possibly configurable is exposed in Settings rather than hardcoded.

**Onboarding**:
The first-run conversation that offers each provider and a skip, answered at most once per install; every step is cancellable and setup can be resumed later.
_Avoid_: first-run wizard, setup flow

**My Music**:
The composable home for local Library and provider account-saved shelves, with
source filters and configurable sections. Local Saved, All files and account
saves remain distinct collections.
_Avoid_: My Tidal, account home

**Saved vs Library**:
Two different collections. Saved means the files Waves itself downloaded, each carrying the provider it came from; Library means every audio file in the folder Waves scans, whoever put it there. A saved file is normally part of the library, but the two answer different questions: what Waves saved, and what is on disk.
_Avoid_: downloads (for Library), collection (for either)

**Capability**:
What a provider can do (search, download, lyrics, browse, and the rest).
_Avoid_: feature flag, permission

**Edition**:
One release among an album's releases — a reissue, remaster, anniversary, or regional pressing.
_Avoid_: version, release, variant

**Held**:
A queued download waiting its turn or paused at a recoverable boundary. Recovery
can resume it under its captured policy; intentionally stopping its pinned
engine requires explicit action and never restarts the runtime automatically.
Queue state, distinct from Stopped.
_Avoid_: pending, paused, waiting

**Twin**:
Files sharing one track's attach identity (title, artist, and play length) that count as a single track — an Atmos copy attaching to its stereo canonical entry, never counted twice.
_Avoid_: duplicate, match, copy

**Notification center**:
The application's product history of structured events: transient toasts for
new ones and retained, redacted entries bounded by count and age. Active issues
stay until resolved or dismissed.
_Avoid_: alerts panel, message log
