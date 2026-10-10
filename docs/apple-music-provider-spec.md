# Waves × Apple Music: the second provider

Accepted Apple Music integration contract, amended 2026-10-03. The existing
gamdl route, audio/asset rules and compatibility invariants below are the
maintained baseline. Multiple engines, offers/cross-provider fulfillment,
redesigned surfaces and managed-asset update extensions are **planned**, not
released or qualified by this document. The [architecture map](architecture.md)
names current owners; the [ADRs](adr/) own shared product decisions. Qualification
and delivery evidence stays in the owning issues/PRs and releases.

**Vocabulary**: per `GLOSSARY.md` — Provider, Engine, Runtime, catalog offer, Edition, Chooser, Audio type, Audio quality, Version, Dual-download, Quarantine, Ownership, Config-first. Used here in exactly those senses.

## Ground rules

1. **Preserve useful behavior.** Unrelated TIDAL execution/catalog functions and compatibility remain intact. Shared product changes follow the explicitly amended ADRs; symmetry never requires removing legitimate provider capabilities.
2. **Config-first.** Anything possibly configurable is exposed in Settings rather than hardcoded. Every default named below is an initial value, user-tunable.
3. **Optional component.** Apple Music ships as a user-enabled component: off by default, explicit opt-in in Settings.
4. **Platform parity.** New capabilities release across all eight builds together under [ADR 0010](adr/0010-provider-engine-runtime-boundary.md). Build success does not establish native runtime/account/delivery qualification (§10.5).
5. **License discipline.** Waves is AGPL-3.0. Every bundled, vendored, or wrapped artifact must be license-compatible (§2, §11).
6. **One-time external setup is acceptable**; fully-in-app setup is a bonus, never a requirement.

---

## 1. Apple engines

The maintained implementation embeds pinned [gamdl](https://github.com/glomatico/gamdl)
client APIs with wrapper-v2 for wrapper-dependent delivery, and separately
provisioned byte-download tools. Catalog search can work before download setup.
Waves owns its client configuration; it does not read or mutate a user's
`~/.gamdl/config.ini`. Existing integration is a comparison baseline, not proof
of the best route or packaged parity.

The accepted extension is several subordinate engines beneath one Apple
Provider, starting with gamdl and one qualified lite/Temari client. Selection,
operation readiness, shared failure boundaries, cancellation and fallback are
owned by [ADR 0010](adr/0010-provider-engine-runtime-boundary.md). Engine adapters
remain inside the Apple domain, not replacement Apple providers or QML branches.

No candidate is Recommended until equivalent-workload qualification establishes
its actual delivery, recovery, resource/setup costs, protocol compatibility,
credential/TLS handling and complete dependency distribution eligibility. An
engine's headline license is insufficient (§10.1). Neither another engine nor a
new downloader release is assumed to fix a transport/integrity failure without
exercising that route. Additional codecs/video/rich assets are exposed only as
implemented and qualified delivery capabilities.

## 2. One-time setup: managed and user-supplied

Apple remains an explicit optional provider, off by default. Activation opens
usable catalog/search/preview access immediately, without automatically starting
provisioning. Download setup is separate, on request or first need, and can be
cancelled/deferred without undoing catalog activation
([ADR 0006](adr/0006-onboarding-state-machine.md)).

The existing setup supports a cookies route and a wrapper-v2 route, with distinct
operation requirements. Cookies can serve supported AAC/Atmos operations;
wrapper-dependent ALAC requires its runtime/session. These are capability facts,
not a universal two-tier readiness light or an all-platform qualification claim.
Specific requests show missing setup; unused optional engines remain neutral.

Support both verified managed assets and user-supplied Apple assets/existing
endpoints (§10.2). Login/2FA or cookie export remains a user action. Engine sessions
must match the active account/storefront; do not assume sessions are interchangeable.
Keep private state isolated and preserve restoration without exposing credentials.
Waves configures its own managed tools and collision-free loopback endpoints;
external endpoints are checked for compatibility rather than modified.

A needed container runtime is detected and guided; host-tool installation is a
separate explicit action. Docker-compatible installations may include OrbStack.
Provisioning verifies artifact pins/provenance and keeps downloaded executables
outside the signed bundle. Setup/runtime ownership and truthful readiness follow
[ADR 0010](adr/0010-provider-engine-runtime-boundary.md).

## 3. Apple session supervision

The maintained wrapper supervision is lazy: catalog/link/preview operations do
not start it. Wrapper-dependent downloads may start a configured managed runtime;
idle supervision stops it after an initial five minutes. Supervision does not
silently re-provision. Existing Apple pacing starts at 30 seconds every 25 songs;
reactive 429 handling honors Retry-After or bounded backoff. Values remain tunable
and move under provider-owned Advanced settings (§9.2).

A fetch's download tool (N_m3u8DL-RE) dies with the fetch's job. Stopping the
job, signing out or disabling Apple cancels the fetch within a fifth of a
second while it waits on a request or the tool, and kills the tool. A
verification step already running finishes first, and a step running on a
thread (a decrypt, tagging, a name lookup) gets up to ten seconds before
Waves removes the fetch's temp folder.
The tool runs under a guard process that reads a pipe from Waves and
kills the tool when the pipe closes, so the tool also dies when Waves quits,
crashes or is killed. When a guard has not left five seconds after a stop,
Waves kills it. On macOS and Linux each of these kills reaches the tool's
whole process group, including anything the tool started, even after the
guard has died. On Windows the guard kills only the tool process, Waves kills
a stuck guard's process tree, and a tool whose guard died before the stop
keeps running. gamdl's yt-dlp route for a direct stream URL, which Waves'
catalog fetches do not take, dies with its job but not with Waves.

Each Waves process keeps its Apple temp folders in one `waves-apple-run-*`
folder under the system temp directory and holds an OS lock on that folder's
`.lease` file while it runs. After launch, Waves removes the run folders whose
lock no process holds. A run folder without a lease file, and the flat
`waves-apple-*` workdirs of builds without run folders, go once nothing in
them has changed for an hour. On a temp file system that refuses locks, run
folders stay.

The planned multi-engine lifecycle follows
[ADR 0010](adr/0010-provider-engine-runtime-boundary.md): distinguish account expiry,
engine/runtime-local failure, provider refusal, rate-limit scope and incompatible
protocol. Same-provider fallback preserves the requested item/delivery; another
client sharing the failed runtime is not independent recovery. Deliberate runtime
Stop never causes automatic restart. External services are disconnected, not killed.

HELD and THROTTLED remain presentations, not invented queue states. Account/setup
holds require action when appropriate; backoff remains visible and respects Cancel.
Provider disable/sign-out stops its work under [ADR 0002](adr/0002-disabled-provider-stops-its-queue.md).
Owner-classified events and actionable detail follow
[ADR 0013](adr/0013-redacted-event-lifecycle.md); do not promise every failure will
resume automatically or reduce every catalog change to a generic update message.

## 4. The Provider seam

**One fused `Provider` interface that both TIDAL and Apple implement now — TIDAL by thin delegation (no rewrites), Apple as the first green-field implementer.** ([Ticket: Design the Provider abstraction seam](https://github.com/ranokay/waves/issues/9))

### 4.1 Shape

- The `waves/providers/` package contains `base.py` (interface + neutral types), `tidal.py`, and `apple/`. TIDAL delegates to the existing session and engine; Apple owns its catalog and download adapter.
- **Plain row/presentation data is the contract.** Provider SDK objects stay in Python; only plain payloads cross the Qt boundary. `base.py` describes current rows, and `waves/desktop/BRIDGE.md` owns bridge slots/signals. Evolve shared presentations with their consumers; object caches remain provider-scoped.
- **Composition**: `Download` takes a `Provider`; stream resolution is `provider.resolve_stream(...)` returning a neutral `StreamInfo` (replacing `TrackStreamInfo`'s tidalapi payloads). The bridge holds `self.providers: dict[str, Provider]` keyed by provider id; `_JobSpec` carries `(provider_id, kind, namespaced_id)` and resolves via `get_object` at dispatch.
- **Capability flags** on the interface (`SEARCH OPEN_URL CATALOG DOWNLOAD LYRICS ART BROWSE FAVORITES MIXES VIDEOS` — plus `PREVIEW`, §7.4) gate My Music shelves, Browse, mixes, and videos on provider support.
- **The fence**: TIDAL Atmos/session switching remains in its provider and existing TIDAL download engine. `TidalProvider.resolve_stream` delegates through the job-bound engine resolver; shared provider-neutral consumers do not acquire that machinery.
- **Subordinate engines** use Apple's explicit request, readiness and classified-result contract. The registered gamdl adapter wraps the existing cookies/wrapper-v2 path. Engine preference order and request pins select beneath the provider; new queue entries capture the engine choice, and retries retain it. Bridge data carries safe engine/operation requirements. Additional adapters, complete persisted policy and recovery remain subject to [ADR 0010](adr/0010-provider-engine-runtime-boundary.md) and qualification.

### 4.2 Ids

**Namespaced string ids — `tidal:123`, `apple:456` — as the one format everywhere new**: ownership rows, on-disk tags, `_objs` buckets, queue rows, `_JobSpec`. The ownership store backfills existing rows as `tidal:`; legacy bare ids read as tidal. On disk a generic namespaced tag is written **alongside** the legacy `WAVES_TIDAL_*` tags (§8.1), so every existing library file stays recognized. Ownership gates become provider-scoped automatically: owning on TIDAL never satisfies an Apple gate.

### 4.3 One quality model

- The four rungs `LOW < HIGH < LOSSLESS < HI_RES_LOSSLESS` become a **Waves-owned enum** (no longer tidalapi's `Quality`); each provider maps its engine codecs onto it. Apple: AAC 256 → HIGH (Apple has no LOW); ALAC 16-bit at any rate and ALAC 24-bit at 44.1/48 kHz → LOSSLESS; ALAC 24-bit above 48 kHz (88.2–192) → HI_RES_LOSSLESS (Apple's own Lossless-vs-Hi-Res class boundary, so the rung never overstates the master). **Audio type (stereo/Atmos) stays orthogonal** to quality everywhere.
- The queue's pinned-quality string parses through the Waves enum. The three rank-comparison sites (ownership store, engine gate, bridge gate) keep their scale.
- Exact item evidence may provide codec/resolution detail; a theoretical "up to 24/192" maximum is never presented as the selected item's exact quality. Detail is not a tier rank.
- **Evidence:** [ADR 0001](adr/0001-one-quality-model.md) owns advertised/probed/selected/verified facts and constrained ranking. Apple catalog flags and enhanced-HLS manifests can supply different evidence; unknown/stale/checking states remain explicit. Verified delivered facts come from the staged file (§6). Rich offer evidence/probing is planned. Both 24/96 and 24/192 map to HI_RES_LOSSLESS; that does not make them equal resolution.

### 4.4 Refusals

The TIDAL refusal taxonomy becomes a per-provider `classify_refusal(exc) -> Refusal` hook; Apple's engine errors join the shared refusal-vs-failure vocabulary (§3).

### 4.5 Interface reference

[Provider and neutral types](../waves/providers/base.py) define the implemented
interface and row schemas; provider-specific contracts live with
[TIDAL](../waves/providers/tidal.py) and [Apple Music](../waves/providers/apple/provider.py).

## 5. Dual-download: stereo + Dolby Atmos

**One click can save stereo and Dolby Atmos as separate versions.**

1. **The audio-type setting chooses stereo or both.** `default_audio_type` defaults to `stereo`; `both` queues both versions. Both providers. **Atmos-only tracks** (TIDAL lists some as their own ids) fetch Atmos alone — no stereo row to pair with, no hole left in an album.
2. **Queue: one row per version.** The Atmos row is badged ATMOS, sits adjacent to its stereo sibling, and carries its own progress, delivered-quality readout, cancel, retry, and file link. Album/artist roll-ups count both rows; MIXED-style reporting stays per version.
3. **Ownership and gates per version.** Ownership records gain an **explicit audio type**; the codec sniff (`_file_audio_mode_is_atmos`) retires to a legacy fallback (§8.1). `ownership_of` and the `_copy_is_current` gate become **mode-aware** — closing the documented second-path gap (a below-target stereo owner plus an Atmos-wanting job now settles correctly). **Skip/replace per version**: an Atmos copy on disk with stereo missing fetches stereo only, and vice versa. **Button coverage reflects enabled versions**: with both enabled and only stereo owned, the button still reads DOWNLOAD until every enabled version is owned. Redownload targets a specific version.
4. **Placement: a dedicated "Dolby Atmos files" path template**, default `{album_path}/Dolby Atmos`, reusing the existing token system, live per-field examples, and byte-fit length handling. Rationale: Apple's Atmos arrives as `.m4a` — the same extension as stereo — so a same-folder default guarantees collisions; a dedicated field makes the Plex-friendly separate-subfolder layout zero-config. A blank template places Atmos alongside stereo, where collisions fall to the existing numbered-copy machinery.
5. **The Chooser's audio-type control** offers **stereo / Atmos / both**, defaulting to the settings answer, overriding it for that click only; Atmos-only tracks collapse to Atmos.

## 6. Integrity: verification, retry, quarantine

**Always-on, pre-swap verification of every Apple audio delivery, with a two-class retry policy and a Quarantine the library can never mistake for owned music.** ([Ticket: ALAC verification & quarantine](https://github.com/ranokay/waves/issues/16))

1. **Scope and timing.** Every Apple delivery — ALAC, AAC, Atmos EC-3 — is verified post-download, pre-swap: the `ffmpeg -v error … -f null` decode runs on the staged file during the existing finishing phase (full decode, no network; duration depends on the media). **Only a verified file ever reaches the library** through the atomic swap. TIDAL downloads are untouched. Verification is **always-on structural behavior, never a setting** — a toggle whose only function is writing known-corrupt files has no user. No conversion before verification passes; **no TYPE_END patching in v1** (patching masks a bad source as a decodable-but-lossy one).
2. **Retry policy with the outbreak pre-filter.** **2 automatic re-downloads** (3 attempts total, ~5 s pacing between; count tunable in Advanced). The **`Encoded date` ≥ 2025-05 pre-filter** sharpens it: an outbreak-era file quarantines after **1** retry — re-fetching known-bad Apple sources is pure waste. Never warn-and-save.
3. **Quarantine, skip-list, and the way back.** A **`Waves Quarantine` folder under the download root** by default (location configurable; the scanned Library root may be separate), **outside Library membership and excluded from scans** — a quarantined file can never badge as IN LIBRARY; files keep their intended names so a later verified copy replaces them. A provider-scoped **skip-list** (namespaced ids) marks quarantined tracks; **bulk runs auto-skip skip-listed tracks**, with a quarantine reason distinct from Library presence. **REDOWNLOAD is the explicit re-ask**: it re-attempts; if Apple has re-encoded (detectable via the Encoded date changing), the file verifies, adopts normally, and the skip-list entry clears. No background re-checking — no surprise bandwidth. A config toggle decides **keep vs delete** for quarantined files, default **keep**. Ownership stays honest by construction: a quarantined file was never swapped in, so nothing is owned that isn't on disk.
4. **Queue presentation.** Verification folds into the existing finishing phase — no new state; a mid-run integrity retry keeps the row's progress with a brief "retrying (integrity)" note. After the cap the row lands **FAILED with plain words: "failed integrity check — quarantined"**, counted in the album roll-up as failed, covered by RETRY ALL. Per §5.2, **each version verifies independently** — a corrupt Atmos source never blocks the stereo file, and vice versa.
5. **The honest limit**, documented in-app help and here: verification proves ffmpeg-decodability, **not bit-perfect fidelity** — the only complete check is cross-source comparison, which Waves cannot automate.

## 7. Search, Chooser and preview UX

### 7.1 Shared surfaces

[ADR 0012](adr/0012-composable-provider-surfaces.md) owns the All Providers
Search, progressive results, safe merged offers and compact source identity.
Search implements that surface: one unified section per media kind, source
marks and filter chips, and high-confidence equivalents merged into one row.
Apple catalog access remains possible before download setup. Missing requested
setup stays actionable; disabled providers belong to separate setup opportunities.

### 7.2 Download With

Keep the split-button/anchored Chooser gesture. Planned stacked offer rows allow
provider comparison and explicit selection, with delivery/asset options and useful
engine detail. Defaults come from Settings; enqueue captures the request.
[ADR 0011](adr/0011-captured-fulfillment-intent.md) owns matching confidence,
provider/engine pins and album/playlist/artist policies; the originating provider
is no longer a permanently fixed chip. Collection matching never silently changes
Editions or track lists. Quality claims follow ADR 0001.

### 7.3 Standalone lyrics/art actions

Keep standalone actions independent of audio on catalog and already-saved music,
honoring the existing embed/sidecar matrix (§9). The planned icon treatment uses
existing intentional lyrics/art icons, useful labels in menus/Chooser and
accessible tooltip-labelled compact controls, without hover reflow. Standalone
requests require the asset; optional/required download extras follow ADR 0011.

### 7.4 Preview playback

The existing Apple preview URL plays through the shared preview player without
account/wrapper/download setup. Apple uses the service-provided clip; TIDAL's
full-track preview remains a legitimate difference exposed through PREVIEW and
the optional preview_url hook (§4.5). Provider choice for download does not switch
preview identity or create an engine qualification claim.

## 8. Library recognition and badges

**One tag family, one library tree, two different badge questions, Atmos as a Version.** ([Ticket: Recognizing Apple files & provider-aware badges](https://github.com/ranokay/waves/issues/18))

### 8.1 The on-disk tag family

A generic `WAVES_*` family written by **both** providers going forward:

| Tag                                          | Content                                                          |
| -------------------------------------------- | ---------------------------------------------------------------- |
| `WAVES_ITEM_ID`                              | the namespaced id (`tidal:…` / `apple:…`)                        |
| `WAVES_ARTIST_IDS` / `WAVES_ALBUM_ARTIST_ID` | the multi-credit id groundwork, now namespaced                   |
| `WAVES_AUDIO_TYPE`                           | `stereo` / `atmos` — recognition never depends on codec sniffing |

On MP4 (Apple ALAC/AAC/Atmos and TIDAL Atmos) these ride the existing freeform-atom mechanism (`----:com.apple.iTunes:…`); on FLAC, vorbis comments. TIDAL downloads keep writing the legacy `WAVES_TIDAL_*` tags alongside. The scan reads **generic-first, legacy-fallback**; the codec sniff retires to a legacy fallback only.

### 8.2 Path templates stay shared

Apple files land through the **same template system** as TIDAL — one `Artist/[Year] Album/…` tree, one Plex-readable library, provider-neutral tokens. The **Dolby Atmos files** template (§5.4) remains. Planned optional provider/quality/audio-type tokens and mixed-collection organization follow [ADR 0011](adr/0011-captured-fulfillment-intent.md); no duplicate template system per provider is introduced.

### 8.3 Badge semantics: two different questions

- **IN LIBRARY / PARTIALLY / MAYBE — scan-based, provider-blind.** They answer _"does this music exist on disk?"_; the scan matches by tags whoever saved it. Owning the TIDAL master **does** badge the Apple search result IN LIBRARY — the music is in your library. MAYBE-proof and the MusicBrainz arbiter work unchanged.
- **DOWNLOADED / HAVE / REDOWNLOAD — ownership-based, strictly per-provider.** They answer _"has Waves saved this provider's version?"_. Owning TIDAL's HI-RES never shows Apple's row as DOWNLOADED. The queue's HAVE marking is per-provider likewise.
- **Ownership remains per provider and Version.** Planned cross-provider upgrades are a separate off-by-default policy under [ADR 0011](adr/0011-captured-fulfillment-intent.md), requiring trustworthy ownership and verified improvement. Initial provider selection does not authorize replacement. Equivalent Library presence never invents Apple ownership.

### 8.4 Atmos files in the scan

An Atmos file is a **Version attached to its canonical track, never a duplicate**: the scan counts the non-Atmos files as the album's **canonical track set** (the "7 OF 10 IN LIBRARY" arithmetic and multi-disc folding run on it); Atmos copies attach by track, matched within the album folder and its Atmos subfolder, audio type read from `WAVES_AUDIO_TYPE` (codec sniff as fallback). Album cards earn a small **ATMOS TOO** micro-badge when Atmos versions exist. A fully Atmos-only track is its own canonical entry — no stereo twin to attach to.

## 9. Lyrics, album art, and Settings

### 9.1 The lyrics & album-art matrix

([Ticket: Lyrics & album-art policy matrix](https://github.com/ranokay/waves/issues/10)) TIDAL's current behavior stays byte-for-byte; the matrix extends it.

**Formats & sidecars** — sidecar toggles independent, one per format, all combinations valid, extensions never faked:

| Format                    | Providers | What it is                                                                              |
| ------------------------- | --------- | --------------------------------------------------------------------------------------- |
| LRC (line-timed)          | both      | the interoperable standard, as today                                                    |
| Enhanced LRC (word-timed) | Apple     | Waves converts syllable TTML → enhanced LRC in its own layer                            |
| **TTML (verbatim)**       | Apple     | **a first-class format choice**: saved exactly as Apple serves it, zero conversion loss |
| TXT (unsynced plain)      | both      | unchanged `.txt` rule, never a fake `.lrc`                                              |

SRT is dropped for v1 (a conversion artifact, not something Apple provides).

**Embedding**: the existing embed toggle keeps its exact semantics — timed-when-available LRC in the primary lyrics field (FLAC `LYRICS`, MP4 `©lyr`, MP3 SYLT) plus the unsynced sibling. **TTML is sidecar-only** (a document format, not a tag format). All four embed × sidecar combinations stay valid, including "download but don't embed".

**Source precedence** (both providers, in order): 1. word-timed when the toggle is on (default **on**) — on Apple, syllable TTML **outranks a line-timed LRCLIB hit**; 2. LRCLIB-first (existing toggle, governs both providers); 3. provider-native fallback (Apple TTML → LRC conversion); 4. unsynced text last. **Syllable sourcing is direct**: Waves calls the `syllable-lyrics` relationship through the embedded AppleMusicApi client and converts in its own layer — not waiting on upstream glomatico/gamdl#345 — with graceful per-track fallback to line-timed.

**Defaults** (fresh installs; existing installs keep their stored values): `lyrics_embed` off, `lyrics_file` **on**, `synced_only` off, `prefer_lrclib` on, word-timed **on**, `.ttml` sidecar **on** (Apple only; inert where the provider's engine serves no TTML). Every lyrics/art key additionally has a per-provider mirror under the provider's card; the shared keys are one-time migration carriers (`provider_setting` reads the mirror first), and a fresh install starts every mirror at these values.

**Album art**: the existing `CoverDimensions` setting governs both providers; **ORIGIN maps per provider** — TIDAL keeps its exact current behavior (embedded cap included), Apple's ORIGIN is the true original-master image (URL-rewrite path), with the `{w}x{h}` template up to 5000×5000 otherwise. The separate cover file can carry its own size (`metadata_cover_file_dimension`: "follow" reuses the embedded size). Sidecar format options: **raw (default — the served bytes, Apple's true original master where available)** / jpg / png; embedded format stays jpg for both. Animated Apple artwork is not implemented. Planned cross-provider asset sourcing, required extras and optional translations/pronunciation follow [ADR 0011](adr/0011-captured-fulfillment-intent.md) and require capability qualification; this matrix does not certify an engine's rich-lyrics delivery.

### 9.2 Settings architecture

[ADR 0012](adr/0012-composable-provider-surfaces.md) owns the planned hierarchy and
normal/Advanced/Diagnostics boundaries. Accounts, provider download overrides,
engines and runtime stay under Apple; shared Downloads, Library and Lyrics &
Artwork behavior appears once. Keep one schema and staged Apply/Cancel. Enabling
Apple is catalog-first (§2); requested setup and one Providers attention surface
replace automatic provisioning and mandatory per-provider status lights.

Preserve serialized `tidal_quality_audio` / `apple_quality_audio` tier strings,
legacy `quality_audio` migration, shared `default_audio_type`, the retired
`download_dolby_atmos` carrier and independent lyrics/art mirrors (§9.1). Existing
video values survive the planned move to shared Downloads. Provider pacing names
and values survive their move under owner-grouped Advanced settings. Migration
completion/downgrade protection remains [ADR 0003](adr/0003-migration-sidecar.md).
Chooser defaults read Settings; no separate defaults store is introduced.

## 10. Packaging and distribution constraints

1. **Bundle boundary.** Cleared open-source clients/dependencies may ship as
   ordinary dependencies. Apple-derived/proprietary material, wrapper images and
   separately provisioned executables remain outside the signed app
   ([ADR 0004](adr/0004-apple-engine-bundling.md)). Whole-stack eligibility includes
   dependencies/platform wheels/assets/notices; no new candidate is cleared by
   its headline license. `tools/inspect_bundle.py` enforces the existing material
   boundary, not a complete license audit.
2. **Managed and user-supplied assets.** Support the fork-managed image and
   user-supplied Apple assets/existing endpoints. Managed artifacts require
   provenance, version/checksum/digest pins and isolated private session state;
   user-managed services receive compatibility guidance. The accepted public
   image policy is this fork's independent [ADR 0005](adr/0005-wrapper-image-distribution.md).
   Upstream product contributions do not require that image or its publishing
   policy. The [runbook](wrapper-image.md) owns current pins and publishing.
3. **Host tools.** Detect and guide required tools/container runtime. Host-tool
   installation is a separate explicit action; missing unused engines do not
   force setup. Runtime requirements vary by qualified engine/operation (§2).
4. **Updates.** Bundled client upgrades accompany Waves releases. Planned managed
   assets may receive separately approved, compatible version-pinned updates
   using the app's update-check preference. Manual installation is default;
   optional automatic installation runs idle with rollback. Preserve queued
   intent, compatibility and active attempts. User-managed services are not
   automatically modified. A fetched release is not qualification evidence.
5. **Platforms.** New capabilities satisfy [ADR 0010](adr/0010-provider-engine-runtime-boundary.md)
   across all eight builds together. Distinguish host client, guest architecture,
   packaged/native launch, account/session and verified delivery; successful
   container emulation or a build cannot substitute for native acceptance.
   Current build coverage is described in the [developer guide](../DEVELOPER.md).
6. **Signing/provenance.** Keep the app signing/notarization boundary. Downloaded
   executables stay in the managed-runtime area, with verified source/pins and
   recorded provenance, following the existing FFmpeg provisioning pattern.

## 11. Compatibility invariants

- **TIDAL's engine, session, matching, metadata, lyrics, artwork behavior**: unchanged, except the audio-type choice in §5.1 and the mechanical call-routing through `TidalProvider` (tests pin behavior).
- **The library scan's provider-blindness** for IN LIBRARY-class badges: unchanged (§8.3 formalizes it).
- **Existing path templates, quality ranks, refusal taxonomy, queue states, ownership semantics**: extended (namespaced ids, explicit audio type, per-provider scoping), not replaced; existing data backfills, nothing resets.
- **Distribution:** no unlicensed or incompatible code enters the tree. Whole-stack eligibility is reviewed under ADR 0004; the fork image's distinct residual risk is ADR 0005. It remains outside Waves' bundle.
