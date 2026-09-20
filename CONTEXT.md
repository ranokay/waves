# Waves

Waves is a native desktop app for saving music from the user's own accounts, search-first and art-forward.

## Language

**Provider**:
A music service Waves can search and save from (today TIDAL; Apple Music as the second).
_Avoid_: source, backend

**Provider descriptor**:
A provider's static identity as the surfaces that list providers need it — its
name, mark, one honest capability line, its card's own action words and the
Settings fields its card owns — composed by the bridge with live status into
what those surfaces render.
_Avoid_: provider config, provider metadata

**Engine**:
The component that performs a provider's fetching and decryption, possibly a wrapped external tool; each provider plugs into Waves through one.
_Avoid_: downloader, backend

**Download adapter**:
The surface a provider serves its download asks through: a click, a Chooser click, a retry, a standalone lyrics or art fetch, and a queued job's body. The bridge dispatches every download path through the adapter of the provider an id's namespace resolves to, so no path names a provider; a provider with no adapter keeps the TIDAL engine path.
_Avoid_: provider hook, download hook

**Chooser**:
The per-download control where the user picks provider, audio quality, audio type, and lyrics/art options; its defaults come from Settings, and one click uses those defaults.
_Avoid_: download dialog, picker

**Audio type**:
Which mix of a track is being saved: stereo or Dolby Atmos.
_Avoid_: mix, format, mode

**Audio quality**:
The fidelity tier a download is fetched at, stated on Waves' own four-rung ladder (LOW < HIGH < LOSSLESS < `HI_RES_LOSSLESS`), serialized as the ladder's tier strings. Audio type is orthogonal to it. Each provider maps its engine's codecs onto the rungs (e.g. AAC 320 → HIGH, ALAC 24/192 → `HI_RES_LOSSLESS`).
_Avoid_: bitrate, resolution

**Version**:
One saved instance of a track at a specific audio type; a track can be owned as several versions.
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
The home surface for the user's music: the Library first, then the saved shelves each enabled provider can fill, labelled by source only when more than one contributes.
_Avoid_: My Tidal, account home

**Saved vs Library**:
Two different collections. Saved means the files Waves itself downloaded, each carrying the provider it came from; Library means every audio file in the folder Waves scans, whoever put it there. A saved file is normally part of the library, but the two answer different questions: what Waves saved, and what is on disk.
_Avoid_: downloads (for Library), collection (for either)
