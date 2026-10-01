# Waves × Apple Music: the second provider

Current Apple Music behavior and integration requirements. The [architecture map](architecture.md) names source and test owners; the [ADRs](adr/) record the maintained decisions.

**Vocabulary**: per `CONTEXT.md` — Provider, Engine, Chooser, Audio type, Audio quality, Version, Dual-download, Quarantine, Ownership, Config-first. Used here in exactly those senses.

## Ground rules (inherited, non-negotiable)

1. **Don't break what works.** The TIDAL path's behavior is unchanged everywhere except where a section below explicitly states a ratified product change (one exists: the Atmos toggle's meaning, §5.1). Apple is additive.
2. **Config-first.** Anything possibly configurable is exposed in Settings rather than hardcoded. Every default named below is an initial value, user-tunable.
3. **Optional component.** Apple Music ships as a user-enabled component: off by default, explicit opt-in in Settings.
4. **Platform order**: macOS Apple silicon first, then Windows, then Linux. (Windows and Linux follow as later enablements — see §10.5.)
5. **License discipline.** Waves is AGPL-3.0. Every bundled, vendored, or wrapped artifact must be license-compatible (§2, §11).
6. **One-time external setup is acceptable**; fully-in-app setup is a bonus, never a requirement.

---

## 1. The Engine

**Waves adopts [glomatico/gamdl](https://github.com/glomatico/gamdl) as the Apple Engine, embedded as a Python library — with [glomatico/wrapper-v2](https://github.com/glomatico/wrapper-v2) backing the ALAC path.** ([Ticket: Choose the Apple engine approach](https://github.com/ranokay/waves/issues/8))

- **Embedding, not vendoring, not CLI.** Waves uses gamdl's published embedding API (`AppleMusicApi` + its downloaders), pinned to the 3.8.x version line. Bumps ride Waves' updater (§10).
- **Catalog search is built in** (`get_search_results`) and needs only the auto-scraped dev token — no cookies, no user input. Apple search works before any setup exists.
- **ALAC path**: wrapper-v2, a Docker-based Android guest whose guest libs are **arm64** — on Apple silicon the linux/arm64 image runs **natively**, no emulation. This is the deciding platform fact: the x86-64 FairPlay guests of the other candidates are where the M-series crash reports live. wrapper-v2 publishes source only; **Waves builds and pins its own image artifacts**.
- **Download mode**: N_m3u8DL-RE (MIT; prebuilt binaries for macOS arm64/x64, Windows x64/arm64, Linux x64/arm64) is the default download mode. Its corruption class (yt-dlp-mode's malformed m4a) is avoided by mode choice; the remainder lands in the integrity gate (§6). N_m3u8DL-RE only changes the byte-download step; decryption is always local (Widevine-keyed license exchange, or wrapper FairPlay for ALAC).
- **Throttling**: gamdl has no license-exchange backoff; Waves adds its own (§4).
- **Fallback Engine**: [WorldObservationLog wrapper@lite](https://github.com/WorldObservationLog/wrapper) (MIT) + [AppleMusicDecrypt@v3](https://github.com/WorldObservationLog/AppleMusicDecrypt/tree/v3) (AGPL-3.0), kept viable behind the Provider seam — a swap means new `AppleProvider` method bodies, nothing else. Swap triggers: dev-token scraper breakage outpacing upstream releases; the wrapper/APK setup proving unacceptable in practice; word-timed lyrics becoming a hard requirement (v3 has syllable TTML today).
- **Ruled out**: [zhaarey/apple-music-downloader](https://github.com/zhaarey/apple-music-downloader) — **no license at all** (never vendored; external-CLI use only would be permitted, but its wrapper is Linux-x86_64-first against a macOS-first platform order and it ships no releases); an in-house thin client — FairPlay is only reachable through the Android-lib bridge every candidate wraps, and hi-res, exact-quality, and original-art facts ride undocumented extensions; a hybrid two-engine v1 — double integration surface, no v1 gain.

**License surface** (all compatible with AGPL-3.0): gamdl MIT; wrapper-v2 Unlicense; N_m3u8DL-RE MIT; fallback AppleMusicDecrypt v3 AGPL-3.0 + wrapper@lite MIT.

## 2. One-time setup: managed, degrading to two tiers

The setup wizard (§9.2) provisions what Waves can, **FFmpeg-manager style** — the user does only what only they can. The cookies tier and full wrapper tier share the same wizard.

| Step                                                                                                               | Tier     | Who                                                                                                                                |
| ------------------------------------------------------------------------------------------------------------------ | -------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| Managed runtime: wrapper-v2 image built/provisioned, N_m3u8DL-RE downloaded, checksum-verified, extracted, chmod'd | full     | Waves, one click                                                                                                                   |
| Container runtime (Docker) present and running                                                                     | full     | detected; Waves attempts a gentle start (`open -a Docker`) and otherwise guides — **never silently installs a hypervisor product** |
| Apple ID login + 2FA                                                                                               | full     | human, one time; wrapper tokens persist across container restarts                                                                  |
| Cookies export from a logged-in music.apple.com browser session                                                    | fallback | human                                                                                                                              |

- **The two tiers**: **cookies alone** unlocks AAC 256 + Atmos (no runtime at all — Atmos needs no wrapper since gamdl 3.8.0); **ALAC (up to 24/192)** unlocks when the managed wrapper step completes. The wizard offers the cookies tier as the graceful fallback for anyone who won't run the runtime, upgradeable in place later.
- **Search needs nothing**: the dev token is auto-scraped; the Apple search group renders before any setup exists (§7.1).
- **Configuration isolation**: Waves **owns its gamdl-library configuration surface entirely** — it never reads, inherits, or mutates a user-visible `~/.gamdl/config.ini`. The N_m3u8DL-RE asset is a tar.gz — extract, verify, chmod (the lesson the FFmpeg manager already encodes). The wrapper HTTP API defaults to port 80, collision-prone on a desktop — Waves starts it on a free high port and passes it explicitly.

## 3. Apple session supervision

**An on-demand sidecar, held-not-failed recovery, honest breakage messaging, and no new queue states.** ([Ticket: Apple session supervision](https://github.com/ranokay/waves/issues/17))

- **Lifecycle**: search, browsing, and link resolution never start the wrapper. Waves starts it **lazily on the first Apple download**, health-probes its HTTP API, and **stops it after an idle period** (initial idle timeout: 5 minutes, Advanced-tunable) — an idle Docker VM must not burn memory and battery. The runtime is the setup wizard's artifact; supervision never re-provisions silently.
- **Failure classes and what the user sees**:

| Class                            | Presentation                                                                                           | Recovery                                                                                      |
| -------------------------------- | ------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------- |
| Runtime missing / dies mid-run   | Apple downloads are **HELD, not failed** — one clear message, no wall of failures                      | Automatic when the runtime returns; manual via existing retry affordances                     |
| License-exchange 429             | Affected rows show **THROTTLED with a visible resume countdown** inside their normal downloading state | Automatic, in place                                                                           |
| Dev-token scraper breakage       | Search/catalog die with honest words: "Apple changed their web app — a Waves update is needed"         | The updater ships the pinned-engine bump (§10.4) — no hot-patching, no silent hoping          |
| Wrapper session / cookies expiry | Status light → needs attention; downloads pause at the next boundary                                   | One click re-opens the wizard's login step; wrapper tokens refresh on their own between times |

- **Pacing**: **proactive** — Apple pacing fields in the Apple settings section, same shape as TIDAL's `api_rate_limit_*`: pause after N songs for N seconds; initial values **30 s every 25 songs**, tuned to the undocumented 429 threshold, fully tunable. **Reactive** — on a 429, honor `Retry-After` when present, else exponential backoff capped at a few minutes; resume the same job in place. Automatic recovery is never a failure and never a user task.
- **Queue vocabulary**: **HELD and THROTTLED are presentations, not new states.** A held row sits under Queued/Held with its reason; a throttled row stays in Downloading with its countdown. Both resume automatically and respect STOP; RETRY ALL covers anything manually stopped.
- **Errors**: Apple engine errors map into the existing refusal-vs-failure taxonomy through `classify_refusal` (§4.4) — a refusal ("this item is gone") is final and counted unavailable, exactly as TIDAL's; a failure is retryable. The queue never conflates them.

## 4. The Provider seam

**One fused `Provider` interface that both TIDAL and Apple implement now — TIDAL by thin delegation (no rewrites), Apple as the first green-field implementer.** ([Ticket: Design the Provider abstraction seam](https://github.com/ranokay/waves/issues/9))

### 4.1 Shape

- The `waves/providers/` package contains `base.py` (interface + neutral types), `tidal.py`, and `apple/`. TIDAL delegates to the existing session and engine; Apple owns its catalog and download adapter.
- **The row-dict schema is the contract.** Each provider builds the exact plain dicts QML consumes today (search payload, result rows, queue rows) from its own engine objects; the field-name contract is documented in `base.py`. Zero QML work for Apple beyond tier words. The `_objs` id-bucket pattern stays per-provider.
- **Composition**: `Download` takes a `Provider`; stream resolution is `provider.resolve_stream(...)` returning a neutral `StreamInfo` (replacing `TrackStreamInfo`'s tidalapi payloads). The bridge holds `self.providers: dict[str, Provider]` keyed by provider id; `_JobSpec` carries `(provider_id, kind, namespaced_id)` and resolves via `get_object` at dispatch.
- **Capability flags** on the interface (`SEARCH OPEN_URL CATALOG DOWNLOAD LYRICS ART BROWSE FAVORITES MIXES VIDEOS` — plus `PREVIEW`, §7.4) gate My Music shelves, Browse, mixes, and videos on provider support.
- **The fence**: TIDAL's Atmos session-swap machinery stays inside `TidalProvider`, never generalized.
- **No Engine sub-abstraction in v1**: the fallback-engine swap happens behind the same `AppleProvider` methods.

### 4.2 Ids

**Namespaced string ids — `tidal:123`, `apple:456` — as the one format everywhere new**: ownership rows, on-disk tags, `_objs` buckets, queue rows, `_JobSpec`. The ownership store backfills existing rows as `tidal:`; legacy bare ids read as tidal. On disk a generic namespaced tag is written **alongside** the legacy `WAVES_TIDAL_*` tags (§8.1), so every existing library file stays recognized. Ownership gates become provider-scoped automatically: owning on TIDAL never satisfies an Apple gate.

### 4.3 One quality model

- The four rungs `LOW < HIGH < LOSSLESS < HI_RES_LOSSLESS` become a **Waves-owned enum** (no longer tidalapi's `Quality`); each provider maps its engine codecs onto it. Apple: AAC 256 → HIGH (Apple has no LOW); ALAC 16-bit at any rate and ALAC 24-bit at 44.1/48 kHz → LOSSLESS; ALAC 24-bit above 48 kHz (88.2–192) → HI_RES_LOSSLESS (Apple's own Lossless-vs-Hi-Res class boundary, so the rung never overstates the master). **Audio type (stereo/Atmos) stays orthogonal** to quality everywhere.
- The queue's pinned-quality string parses through the Waves enum. The three rank-comparison sites (ownership store, engine gate, bridge gate) keep their scale.
- The Chooser renders provider detail ("ALAC 24/192") as **label text, never as rank**.
- **Advertised vs delivered**: the Chooser shows what the catalog advertises (`advertised_deliveries` — Apple's `audioVariants` flags, with the exact tier available via one enhanced-HLS probe where it matters); after download, rows report the **delivered** quality in plain words (per the existing reporting), which ffprobe confirms (§6.1). 24/96 vs 24/192 is track-dependent; both are HI_RES_LOSSLESS.

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

1. **Scope and timing.** Every Apple delivery — ALAC, AAC, Atmos EC-3 — is verified post-download, pre-swap: the `ffmpeg -v error … -f null` decode runs on the staged file during the existing finishing phase (~50 ms, no network). **Only a verified file ever reaches the library** through the atomic swap. TIDAL downloads are untouched. Verification is **always-on structural behavior, never a setting** — a toggle whose only function is writing known-corrupt files has no user. No conversion before verification passes; **no TYPE_END patching in v1** (patching masks a bad source as a decodable-but-lossy one).
2. **Retry policy with the outbreak pre-filter.** **2 automatic re-downloads** (3 attempts total, ~5 s pacing between; count tunable in Advanced). The **`Encoded date` ≥ 2025-05 pre-filter** sharpens it: an outbreak-era file quarantines after **1** retry — re-fetching known-bad Apple sources is pure waste. Never warn-and-save.
3. **Quarantine, skip-list, and the way back.** A **`Waves Quarantine` folder inside the library root** (location configurable), **excluded from the library scan** — a quarantined file can never badge as IN LIBRARY; files keep their intended names so a later verified copy replaces them. A provider-scoped **skip-list** (namespaced ids) marks quarantined tracks; **bulk runs auto-skip skip-listed tracks**, shown plainly like IN LIBRARY rows. **REDOWNLOAD is the explicit re-ask**: it re-attempts; if Apple has re-encoded (detectable via the Encoded date changing), the file verifies, adopts normally, and the skip-list entry clears. No background re-checking — no surprise bandwidth. A config toggle decides **keep vs delete** for quarantined files, default **keep**. Ownership stays honest by construction: a quarantined file was never swapped in, so nothing is owned that isn't on disk.
4. **Queue presentation.** Verification folds into the existing finishing phase — no new state; a mid-run integrity retry keeps the row's progress with a brief "retrying (integrity)" note. After the cap the row lands **FAILED with plain words: "failed integrity check — quarantined"**, counted in the album roll-up as failed, covered by RETRY ALL. Per §5.2, **each version verifies independently** — a corrupt Atmos source never blocks the stereo file, and vice versa.
5. **The honest limit**, documented in-app help and here: verification proves ffmpeg-decodability, **not bit-perfect fidelity** — the only complete check is cross-source comparison, which Waves cannot automate.

## 7. Search, Chooser, and preview UX

**Provider groups and a split-button Chooser** keep search and per-download options together.

### 7.1 Search results sectioned per provider

- Top-level **provider groups**: a TIDAL group header, then the familiar type sections (ARTISTS / ALBUMS / TRACKS / PLAYLISTS), then an APPLE MUSIC group with the same sections. **No per-row provider badges** — group membership carries the identity.
- **The Apple group renders when the Apple provider is enabled** — not when signed in. Search rides the dev token alone, so Apple search works **before any setup exists**. Disabled = today's TIDAL-only page, unchanged.
- A download click on an Apple row before setup completes **routes into the setup wizard at the login step** — the affordance stays live; it opens the path to making it work.

### 7.2 The Chooser gesture

Every download control is a **split button**: main face = one click with saved defaults (the queued toast confirms provider/tier/files); `▾` face (or right-click anywhere on the control) = the full Chooser as an **anchored popover** — never a dialog on every click. Chooser content: the row's provider as a **static chip** (a collection belongs to its provider), the provider's quality tiers with detail text (Apple: "ALAC 24/192 · ALAC 16/44.1 · AAC 256"; TIDAL: its four rungs), audio type stereo/Atmos/both (collapsing to ATMOS ONLY on Atmos-only tracks), lyrics embed/.lrc/.ttml quick toggles, art sidecar/embed toggles, **SET AS DEFAULTS** (writes back to Settings) + DOWNLOAD. Choice applies to that click only.

### 7.3 Standalone lyrics/art actions

First-class buttons beside DOWNLOAD on album and artist pages ("LYRICS", "COVER"); per-track as a compact always-visible pair beside the track's split button (always visible to avoid hover reflow). Both providers; they honor the embed/sidecar matrix (§9 of the [lyrics & art ticket](https://github.com/ranokay/waves/issues/10)) independently of audio, on found music and already-saved music alike.

### 7.4 Preview playback

v1 includes Apple previews: the documented **30-second AAC preview URL** (a plain song attribute; no session, no wrapper, no setup) plays through the **existing shared preview player**. Full-track preview stays TIDAL-only, expressed as the `PREVIEW` capability with the optional `preview_url` hook (§4.5). Apple rows show the standard preview affordance; the asymmetry (30 s clip vs whole track) is accepted — it is what Apple documents.

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

Apple files land through the **same template system** as TIDAL — one `Artist/[Year] Album/…` tree, one Plex-readable library, provider-neutral tokens. The only special placement remains the **Dolby Atmos files** template (§5.4). Per-provider template variants are rejected for v1.

### 8.3 Badge semantics: two different questions

- **IN LIBRARY / PARTIALLY / MAYBE — scan-based, provider-blind.** They answer _"does this music exist on disk?"_; the scan matches by tags whoever saved it. Owning the TIDAL master **does** badge the Apple search result IN LIBRARY — the music is in your library. MAYBE-proof and the MusicBrainz arbiter work unchanged.
- **DOWNLOADED / HAVE / REDOWNLOAD — ownership-based, strictly per-provider.** They answer _"has Waves saved this provider's version?"_. Owning TIDAL's HI-RES never shows Apple's row as DOWNLOADED. The queue's HAVE marking is per-provider likewise.
- **Quality upgrades stay per-provider**: each provider's quality setting governs its own re-fetch ladder. No cross-provider upgrade interaction — wanting Apple's ALAC when TIDAL's copy exists is a deliberate choice, and both copies coexist as separate Versions.

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

**Album art**: the existing `CoverDimensions` setting governs both providers; **ORIGIN maps per provider** — TIDAL keeps its exact current behavior (embedded cap included), Apple's ORIGIN is the true original-master image (URL-rewrite path), with the `{w}x{h}` template up to 5000×5000 otherwise. The separate cover file can carry its own size (`metadata_cover_file_dimension`: "follow" reuses the embedded size). Sidecar format options: **raw (default — the served bytes, Apple's true original master where available)** / jpg / png; embedded format stays jpg for both. Animated Apple artwork is not supported.

## 9.2 Settings architecture

([Ticket: Config-first settings architecture](https://github.com/ranokay/waves/issues/11)) **Two axes — per-provider sections for what differs, shared sections for what doesn't — with a one-migration carry-over that no existing user feels.**

1. **The Providers area** has a **TIDAL** section and an **Apple** section for session state, quality defaults, lyrics/art preferences and provider-specific runtime/pacing. Lyrics/art preferences have independent per-provider mirrors (§9.1); their shared keys are migration carriers. Path templates including **Dolby Atmos files**, library, queue and diagnostics remain shared.
2. **Per-provider quality fields**: **`tidal_quality_audio` / `apple_quality_audio`** serialize as Waves tier strings (§4.3). Migration converts legacy `quality_audio` into `tidal_quality_audio` without resetting settings. `quality_video` remains TIDAL-only. The shared `default_audio_type` chooses stereo or both; Atmos alone is a per-click Chooser option. Migration carries a legacy enabled `download_dolby_atmos` value into `both`.
3. **The Apple section**: always visible, behind an **enable switch (default off)** — the optional-component decision made concrete. Turning it on starts the **in-place setup wizard** (§2): managed runtime provisioning → Apple ID login + 2FA, with the **cookies-only tier** in the same wizard as the graceful fallback. A **color-coded status light** — not set up / runtime ready / signed in / needs attention — mirrors the existing FFmpeg status light. The section also hosts Apple's pacing fields (§3) and runtime manage actions (update, remove).
4. **Pacing fields**: TIDAL's `api_rate_limit_*` keep their names, meaning, and section verbatim; Apple gains same-shape fields in the Apple section (§3).
5. **Chooser defaults fall out of Settings** exactly as the glossary says: per-provider quality, the shared audio type and each provider's lyrics/art preferences. No separate chooser-defaults store.

## 10. Packaging and distribution constraints

1. **Bundle boundary.** Waves ships its open-source client libraries (gamdl,
   yt-dlp and their dependencies). Apple-derived/proprietary material, the
   wrapper image and separately provisioned executables remain outside the
   app bundle ([ADR 0004](adr/0004-apple-engine-bundling.md)).
   `tools/inspect_bundle.py` enforces this boundary.
2. **Published wrapper image.** The image build downloads the maintainer's
   pinned APK, extracts its arm64 libraries and packages them with notices
   and OCI provenance labels. End users pull the public image; they never
   supply or extract an APK. The app verifies its pinned digest at pull time.
   [ADR 0005](adr/0005-wrapper-image-distribution.md) records the accepted
   redistribution risk; [the runbook](wrapper-image.md) describes the pins
   and supported publishing workflow.
3. **Container runtime dependency**: the full tier presumes a container runtime (Docker). The wizard detects it, attempts a gentle start on macOS, and guides when absent (§2) — it never silently installs one.
4. **Engine bumps ride the updater**: Waves pins gamdl (version line), its own wrapper-v2 image build, and the N_m3u8DL-RE release; when upstream fixes scraper breakage, a pinned-version bump ships through Waves' normal update channel — the user updates Waves, the runtime refresh follows on next wizard/supervision pass.
5. **Platforms.** The wrapper image runs natively on macOS Apple silicon.
   Full-tier behavior on x86_64 hosts requires container emulation and live
   verification. The eight-leg release matrix includes Windows and Linux;
   build and smoke-launch coverage is described in the [developer guide](../DEVELOPER.md).
6. **Notarization**: Waves' own signing/notarization pipeline is unchanged; the provisioning flow must keep downloaded executables inside the app's managed-runtime area with provenance recorded (source URL + checksum), the pattern the FFmpeg manager already uses.

## 11. Compatibility invariants

- **TIDAL's engine, session, matching, metadata, lyrics, artwork behavior**: unchanged, except the audio-type choice in §5.1 and the mechanical call-routing through `TidalProvider` (tests pin behavior).
- **The library scan's provider-blindness** for IN LIBRARY-class badges: unchanged (§8.3 formalizes it).
- **Existing path templates, quality ranks, refusal taxonomy, queue states, ownership semantics**: extended (namespaced ids, explicit audio type, per-provider scoping), not replaced; existing data backfills, nothing resets.
- **AGPL-3.0**: no unlicensed or incompatible code enters the tree; the wrapper-v2 image is built from source (Unlicense) and never vendored into Waves.
