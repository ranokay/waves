# Waves

Waves is a native desktop app for saving music from the user's own accounts, search-first and art-forward.

## Language

**Provider**:
A music service Waves can search and save from (today TIDAL; Apple Music as the second).
_Avoid_: source, backend

**Engine**:
The component that performs a provider's fetching and decryption, possibly a wrapped external tool; each provider plugs into Waves through one.
_Avoid_: downloader, backend

**Chooser**:
The per-download control where the user picks provider, audio quality, audio type, and lyrics/art options; its defaults come from Settings, and one click uses those defaults.
_Avoid_: download dialog, picker

**Audio type**:
Which mix of a track is being saved: stereo or Dolby Atmos.
_Avoid_: mix, format, mode

**Audio quality**:
The fidelity tier a download is fetched at (e.g. AAC 256, Lossless, Hi-Res Lossless).
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
