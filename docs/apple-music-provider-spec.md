# Waves × Apple Music: the second provider

**Status**: decision-complete. Every design decision needed before implementation ticketing is recorded here; nothing in this document is left open.
**Source**: synthesized from the [Wayfinder map](https://github.com/ranokay/waves/issues/1) and its sixteen resolved tickets. Where a section restates a ticket's resolution, the ticket is linked; the ticket bodies remain the detailed rationale, this document the ruling synthesis.
**Audience**: the implementation-ticketing effort that follows this map. This spec is its entire input; implementation work itself is out of this effort's scope.
**Research assets**: `docs/research/` on the `research/*` branches — [gamdl-eval](https://github.com/ranokay/waves/tree/research/gamdl-eval), [zhaarey-eval](https://github.com/ranokay/waves/tree/research/zhaarey-eval), [worldobs-eval](https://github.com/ranokay/waves/tree/research/worldobs-eval), [alac-verification](https://github.com/ranokay/waves/tree/research/alac-verification), [apple-catalog-surface](https://github.com/ranokay/waves/tree/research/apple-catalog-surface), [provider-seam-analysis](https://github.com/ranokay/waves/tree/research/provider-seam-analysis); UI prototype on [prototype/chooser-search-ui](https://github.com/ranokay/waves/tree/prototype/chooser-search-ui).
**Vocabulary**: per `CONTEXT.md` — Provider, Engine, Chooser, Audio type, Audio quality, Version, Dual-download, Quarantine, Ownership, Config-first. Used here in exactly those senses.

## Ground rules (inherited, non-negotiable)

1. **Don't break what works.** The TIDAL path's behavior is unchanged everywhere except where a section below explicitly states a ratified product change (one exists: the Atmos toggle's meaning, §5.1). Apple is additive.
2. **Config-first.** Anything possibly configurable is exposed in Settings rather than hardcoded. Every default named below is an initial value, user-tunable.
3. **Optional component.** Apple Music ships as a user-enabled component: off by default, explicit opt-in in Settings.
4. **Platform order**: macOS Apple silicon first, then Windows, then Linux.
5. **License discipline.** Waves is AGPL-3.0. Every bundled, vendored, or wrapped artifact must be license-compatible (§2, §11).
6. **One-time external setup is acceptable**; fully-in-app setup is a bonus, never a requirement.

---

## 1. The Engine

**Waves adopts [glomatico/gamdl](https://github.com/glomatico/gamdl) as the Apple Engine, embedded as a Python library — with [glomatico/wrapper-v2](https://github.com/glomatico/wrapper-v2) backing the ALAC path.** ([Ticket: Choose the Apple engine approach](https://github.com/ranokay/waves/issues/8))

- **Embedding, not vendoring, not CLI.** Waves uses gamdl's published embedding API (`AppleMusicApi` + its downloaders), pinned to a version line (3.8.x at spec time). Bumps ride Waves' updater (§10).
- **Catalog search is built in** (`get_search_results`) and needs only the auto-scraped dev token — no cookies, no user input. Apple search works before any setup exists.
- **ALAC path**: wrapper-v2, a Docker-based Android guest whose guest libs are **arm64** — on Apple silicon the linux/arm64 image runs **natively**, no emulation. This is the deciding platform fact: the x86-64 FairPlay guests of the other candidates are where the M-series crash reports live. wrapper-v2 publishes source only; **Waves builds and pins its own image artifacts**.
- **Download mode**: N_m3u8DL-RE (MIT; prebuilt binaries for macOS arm64/x64, Windows x64/arm64, Linux x64/arm64) is the default download mode. Its corruption class (yt-dlp-mode's malformed m4a) is avoided by mode choice; the remainder lands in the integrity gate (§6). N_m3u8DL-RE only changes the byte-download step; decryption is always local (Widevine-keyed license exchange, or wrapper FairPlay for ALAC).
- **Throttling**: gamdl has no license-exchange backoff; Waves adds its own (§4).
- **Fallback Engine**: [WorldObservationLog wrapper@lite](https://github.com/WorldObservationLog/wrapper) (MIT) + [AppleMusicDecrypt@v3](https://github.com/WorldObservationLog/AppleMusicDecrypt/tree/v3) (AGPL-3.0), kept viable behind the Provider seam — a swap means new `AppleProvider` method bodies, nothing else. Swap triggers: dev-token scraper breakage outpacing upstream releases; the wrapper/APK setup proving unacceptable in practice; word-timed lyrics becoming a hard requirement (v3 has syllable TTML today).
- **Ruled out**: [zhaarey/apple-music-downloader](https://github.com/zhaarey/apple-music-downloader) — **no license at all** (never vendored; external-CLI use only would be permitted, but its wrapper is Linux-x86_64-first against a macOS-first platform order and it ships no releases); an in-house thin client — FairPlay is only reachable through the Android-lib bridge every candidate wraps, and hi-res, exact-quality, and original-art facts ride undocumented extensions; a hybrid two-engine v1 — double integration surface, no v1 gain.

**License surface** (all compatible with AGPL-3.0): gamdl MIT; wrapper-v2 Unlicense; N_m3u8DL-RE MIT; fallback AppleMusicDecrypt v3 AGPL-3.0 + wrapper@lite MIT.

## 2. One-time setup: managed, degrading to two tiers

The setup wizard (§9.3) provisions what Waves can, **FFmpeg-manager style** — the user does only what only they can. Both tiers were proven end-to-end on macOS Apple silicon ([Ticket: Apple Music account + one-time decryption setup (human)](https://github.com/ranokay/waves/issues/14)); the run's record is the wizard's requirements doc.

| Step | Tier | Who |
|---|---|---|
| Managed runtime: wrapper-v2 image built/provisioned, N_m3u8DL-RE downloaded, checksum-verified, extracted, chmod'd | full | Waves, one click |
| Container runtime (Docker) present and running | full | detected; Waves attempts a gentle start (`open -a Docker`) and otherwise guides — **never silently installs a hypervisor product** |
| Apple ID login + 2FA | full | human, one time; wrapper tokens persist (session restore across a container restart was verified live) |
| Apple Music APK supply | full | human, one time (§10.2) |
| Cookies export from a logged-in music.apple.com browser session | fallback | human |

- **The two tiers**: **cookies alone** unlocks AAC 256 + Atmos (no runtime at all — Atmos needs no wrapper since gamdl 3.8.0); **ALAC (up to 24/192)** unlocks when the managed wrapper step completes. The wizard offers the cookies tier as the graceful fallback for anyone who won't run the runtime, upgradeable in place later.
- **Search needs nothing**: the dev token is auto-scraped; the Apple search group renders before any setup exists (§7.1).
- **Wizard fuel** (failure modes the wizard must design against, from the live run): Waves **owns its gamdl-library configuration surface entirely** — it never reads, inherits, or mutates a user-visible `~/.gamdl/config.ini` (a sticky config file silently rerouted and skipped tracks while reporting "0 errors"; a summary that skipped 100% of tracks is the failure mode this design bans). The N_m3u8DL-RE asset is a tar.gz — extract, verify, chmod (the lesson the FFmpeg manager already encodes). The wrapper HTTP API defaults to port 80, collision-prone on a desktop — Waves starts it on a free high port and passes it explicitly.

## 3. Apple session supervision

**An on-demand sidecar, held-not-failed recovery, honest breakage messaging, and no new queue states.** ([Ticket: Apple session supervision](https://github.com/ranokay/waves/issues/17))

- **Lifecycle**: search, browsing, and link resolution never start the wrapper. Waves starts it **lazily on the first Apple download**, health-probes its HTTP API, and **stops it after an idle period** (initial idle timeout: 5 minutes, Advanced-tunable) — an idle Docker VM must not burn memory and battery. The runtime is the setup wizard's artifact; supervision never re-provisions silently.
- **Failure classes and what the user sees**:

| Class | Presentation | Recovery |
|---|---|---|
| Runtime missing / dies mid-run | Apple downloads are **HELD, not failed** — one clear message, no wall of failures | Automatic when the runtime returns; manual via existing retry affordances |
| License-exchange 429 | Affected rows show **THROTTLED with a visible resume countdown** inside their normal downloading state | Automatic, in place |
| Dev-token scraper breakage | Search/catalog die with honest words: "Apple changed their web app — a Waves update is needed" | The updater ships the pinned-engine bump (§10.4) — no hot-patching, no silent hoping |
| Wrapper session / cookies expiry | Status light → needs attention; downloads pause at the next boundary | One click re-opens the wizard's login step; wrapper tokens refresh on their own between times |

- **Pacing**: **proactive** — Apple pacing fields in the Apple settings section, same shape as TIDAL's `api_rate_limit_*`: pause after N songs for N seconds; initial values **30 s every 25 songs**, tuned to the undocumented 429 threshold, fully tunable. **Reactive** — on a 429, honor `Retry-After` when present, else exponential backoff capped at a few minutes; resume the same job in place. Automatic recovery is never a failure and never a user task.
- **Queue vocabulary**: **HELD and THROTTLED are presentations, not new states.** A held row sits under Queued/Held with its reason; a throttled row stays in Downloading with its countdown. Both resume automatically and respect STOP; RETRY ALL covers anything manually stopped.
- **Errors**: Apple engine errors map into the existing refusal-vs-failure taxonomy through `classify_refusal` (§4.4) — a refusal ("this item is gone") is final and counted unavailable, exactly as TIDAL's; a failure is retryable. The queue never conflates them.

## 4. The Provider seam

**One fused `Provider` interface that both TIDAL and Apple implement now — TIDAL by thin delegation (no rewrites), Apple as the first green-field implementer.** ([Ticket: Design the Provider abstraction seam](https://github.com/ranokay/waves/issues/9); grounded in the [provider seam analysis](https://github.com/ranokay/waves/tree/research/provider-seam-analysis))

### 4.1 Shape

- New package `waves/providers/`: `base.py` (interface + neutral types), `tidal.py`, `apple.py`. TIDAL's implementation delegates to the existing `helper/tidal.py`, `config.py`, and `download.py` bodies **unchanged** — the refactor is call-routing with the existing test suite as the safety net.
- **The row-dict schema is the contract.** Each provider builds the exact plain dicts QML consumes today (search payload, result rows, queue rows) from its own engine objects; the field-name contract is documented in `base.py`. Zero QML work for Apple beyond tier words. The `_objs` id-bucket pattern stays per-provider.
- **Composition**: `Download` takes a `Provider`; stream resolution is `provider.resolve_stream(...)` returning a neutral `StreamInfo` (replacing `TrackStreamInfo`'s tidalapi payloads). The bridge holds `self.providers: dict[str, Provider]` keyed by provider id; `_JobSpec` carries `(provider_id, kind, namespaced_id)` and resolves via `get_object` at dispatch.
- **Capability flags** on the interface (`SEARCH OPEN_URL CATALOG DOWNLOAD LYRICS ART BROWSE FAVORITES MIXES VIDEOS` — plus `PREVIEW`, §7.4) keep My TIDAL, Browse, mixes, and videos TIDAL-only without `if`-branches.
- **The fence**: TIDAL's Atmos session-swap machinery stays inside `TidalProvider`, never generalized.
- **No Engine sub-abstraction in v1**: the fallback-engine swap happens behind the same `AppleProvider` methods.

### 4.2 Ids

**Namespaced string ids — `tidal:123`, `apple:456` — as the one format everywhere new**: ownership rows, on-disk tags, `_objs` buckets, queue rows, `_JobSpec`. The ownership store backfills existing rows as `tidal:`; legacy bare ids read as tidal. On disk a generic namespaced tag is written **alongside** the legacy `WAVES_TIDAL_*` tags (§8.1), so every existing library file stays recognized. Ownership gates become provider-scoped automatically: owning on TIDAL never satisfies an Apple gate.

### 4.3 One quality model

- The four rungs `LOW < HIGH < LOSSLESS < HI_RES_LOSSLESS` become a **Waves-owned enum** (no longer tidalapi's `Quality`); each provider maps its engine codecs onto it. Apple: AAC 256 → HIGH (Apple has no LOW), ALAC 16/44.1 → LOSSLESS, ALAC 24/96·192 → HI_RES_LOSSLESS. **Audio type (stereo/Atmos) stays orthogonal** to quality everywhere.
- The queue's pinned-quality string parses through the Waves enum, retiring the tidalapi `Quality(raw)` parse point (`backend.py:7586`). The three rank-comparison sites (ownership store, engine gate, bridge gate) keep their scale.
- The Chooser renders provider detail ("ALAC 24/192") as **label text, never as rank**.
- **Advertised vs delivered**: the Chooser shows what the catalog advertises (`advertised_deliveries` — Apple's `audioVariants` flags, with the exact tier available via one enhanced-HLS probe where it matters); after download, rows report the **delivered** quality in plain words (per the existing reporting), which ffprobe confirms (§6.1). 24/96 vs 24/192 is track-dependent; both are HI_RES_LOSSLESS.

### 4.4 Refusals

The TIDAL refusal taxonomy becomes a per-provider `classify_refusal(exc) -> Refusal` hook; Apple's engine errors join the shared refusal-vs-failure vocabulary (§3).

### 4.5 Interface sketch

The decision artifact from the seam ticket, extended by exactly one optional hook (`preview_url`, §7.4):

```python
class Provider(ABC):
    id: str                      # "tidal" / "apple"
    name: str                    # display name
    capabilities: frozenset      # SEARCH OPEN_URL CATALOG DOWNLOAD LYRICS ART BROWSE FAVORITES MIXES VIDEOS PREVIEW

    # session/auth
    def login_begin(self) -> str
    def login_complete(self, payload: str) -> bool
    def logout(self) -> None
    is_logged_in: bool
    def apply_quality(self, tier: QualityTier, audio_type: AudioType) -> None

    # catalog read — returns the app's row dicts; the schema is the contract
    def search(self, needle: str) -> dict
    def open_url(self, url: str) -> dict | None
    def get_object(self, kind: str, raw_id: str) -> object
    def collection_items(self, obj, include_videos: bool) -> list
    def user_collections(self) -> dict | None          # None when capability absent

    # quality — what the Chooser presents
    def advertised_tier(self, obj) -> QualityTier | None
    def advertised_deliveries(self, obj) -> list[tuple[QualityTier, AudioType]]
    def advertised_ceiling(self, obj) -> int | None

    # per-track delivery
    def resolve_stream(self, track, tier: QualityTier, audio_type: AudioType) -> StreamInfo
    def fetch_lyrics(self, track) -> tuple[str, str]   # (synced, plain)
    def cover_url(self, obj, dimension: int) -> str | None
    def track_facts(self, track) -> dict               # the fact schema metadata_write reads
    def preview_url(self, track) -> str | None         # optional; PREVIEW capability (§7.4)

    # refusals
    def classify_refusal(self, exc) -> Refusal

@dataclass
class StreamInfo:
    urls: list[str]
    file_extension: str
    codecs: str
    requires_flac_extraction: bool
    delivered: dict                    # {tier, audio_type, bit_depth, sample_rate}
    replay_gain: dict | None           # TIDAL-measured; None on Apple → tags left untagged (existing rule)
```

## 5. Dual-download: stereo + Dolby Atmos

**Decided semantics.** ([Ticket: Stereo + Atmos dual-download behavior](https://github.com/ranokay/waves/issues/12)) This is the map's **one ratified change to existing TIDAL-path behavior** (below).

1. **The toggle's meaning changes on its on-path only.** `download_dolby_atmos` keeps its default (off) and every existing user's off-path behavior byte-identical; its on-path meaning changes from "Atmos instead of stereo" to **"Atmos alongside stereo"** — one click queues both versions. Both providers. **Atmos-only tracks** (TIDAL lists some as their own ids) fetch Atmos alone — no stereo row to pair with, no hole left in an album.
2. **Queue: one row per version.** The Atmos row is badged ATMOS, sits adjacent to its stereo sibling, and carries its own progress, delivered-quality readout, cancel, retry, and file link. Album/artist roll-ups count both rows; MIXED-style reporting stays per version.
3. **Ownership and gates per version.** Ownership records gain an **explicit audio type**; the codec sniff (`_file_audio_mode_is_atmos`) retires to a legacy fallback (§8.1). `ownership_of` and the `_copy_is_current` gate become **mode-aware** — closing the documented second-path gap (a below-target stereo owner plus an Atmos-wanting job now settles correctly). **Skip/replace per version**: an Atmos copy on disk with stereo missing fetches stereo only, and vice versa. **Button coverage reflects enabled versions**: with both enabled and only stereo owned, the button still reads DOWNLOAD until every enabled version is owned. Redownload targets a specific version.
4. **Placement: a dedicated "Dolby Atmos files" path template**, default `{album_path}/Dolby Atmos`, reusing the existing token system, live per-field examples, and byte-fit length handling. Rationale: Apple's Atmos arrives as `.m4a` — the same extension as stereo — so a same-folder default guarantees collisions; a dedicated field makes the Plex-friendly separate-subfolder layout zero-config. A blank template places Atmos alongside stereo, where collisions fall to the existing numbered-copy machinery.
5. **The Chooser's audio-type control** offers **stereo / Atmos / both**, defaulting to the settings answer, overriding it for that click only; Atmos-only tracks collapse to Atmos.

## 6. Integrity: verification, retry, quarantine

**Always-on, pre-swap verification of every Apple audio delivery, with a two-class retry policy and a Quarantine the library can never mistake for owned music.** ([Ticket: ALAC verification & quarantine](https://github.com/ranokay/waves/issues/16); root cause and method: [alac-verification research](https://github.com/ranokay/waves/tree/research/alac-verification) — Apple's own ALAC encoder has emitted malformed packets since ~May 2025, still unfixed; gamdl ships no check at all.)

1. **Scope and timing.** Every Apple delivery — ALAC, AAC, Atmos EC-3 — is verified post-download, pre-swap: the `ffmpeg -v error … -f null` decode runs on the staged file during the existing finishing phase (~50 ms, no network). **Only a verified file ever reaches the library** through the atomic swap. TIDAL downloads are untouched. Verification is **always-on structural behavior, never a setting** — a toggle whose only function is writing known-corrupt files has no user. No conversion before verification passes; **no TYPE_END patching in v1** (patching masks a bad source as a decodable-but-lossy one).
2. **Retry policy with the outbreak pre-filter.** **2 automatic re-downloads** (3 attempts total, ~5 s pacing between; count tunable in Advanced). The **`Encoded date` ≥ 2025-05 pre-filter** sharpens it: an outbreak-era file quarantines after **1** retry — re-fetching known-bad Apple sources is pure waste. Never warn-and-save.
3. **Quarantine, skip-list, and the way back.** A **`Waves Quarantine` folder inside the library root** (location configurable), **excluded from the library scan** — a quarantined file can never badge as IN LIBRARY; files keep their intended names so a later verified copy replaces them. A provider-scoped **skip-list** (namespaced ids) marks quarantined tracks; **bulk runs auto-skip skip-listed tracks**, shown plainly like IN LIBRARY rows. **REDOWNLOAD is the explicit re-ask**: it re-attempts; if Apple has re-encoded (detectable via the Encoded date changing), the file verifies, adopts normally, and the skip-list entry clears. No background re-checking — no surprise bandwidth. A config toggle decides **keep vs delete** for quarantined files, default **keep**. Ownership stays honest by construction: a quarantined file was never swapped in, so nothing is owned that isn't on disk.
4. **Queue presentation.** Verification folds into the existing finishing phase — no new state; a mid-run integrity retry keeps the row's progress with a brief "retrying (integrity)" note. After the cap the row lands **FAILED with plain words: "failed integrity check — quarantined"**, counted in the album roll-up as failed, covered by RETRY ALL. Per §5.2, **each version verifies independently** — a corrupt Atmos source never blocks the stereo file, and vice versa.
5. **The honest limit**, documented in-app help and here: verification proves ffmpeg-decodability, **not bit-perfect fidelity** — the only complete check is cross-source comparison, which Waves cannot automate.
6. **QA fixtures**: the research's known-bad albums (TOGENASHI TOGEARI – Fragile Violet, Nate Sib – for us, JOLIN Tsai – Pleasure) anchor the verification path's tests.

## 7. Search, Chooser, and preview UX

**Variant A: provider groups + split-button Chooser** — chosen over two prototyped alternatives; the full three-variant prototype lives on [prototype/chooser-search-ui](https://github.com/ranokay/waves/tree/prototype/chooser-search-ui). ([Ticket: Per-download chooser & provider-sectioned search UI](https://github.com/ranokay/waves/issues/13))

### 7.1 Search results sectioned per provider

- Top-level **provider groups**: a TIDAL group header, then the familiar type sections (ARTISTS / ALBUMS / TRACKS / PLAYLISTS), then an APPLE MUSIC group with the same sections. **No per-row provider badges** — group membership carries the identity.
- **The Apple group renders when the Apple provider is enabled** — not when signed in. Search rides the dev token alone, so Apple search works **before any setup exists** (the engine decision's explicit intent, reconfirmed live in the setup run; this reconciles the prototype's enable+signed-in phrasing, which predates that run). Disabled = today's TIDAL-only page, unchanged.
- A download click on an Apple row before setup completes **routes into the setup wizard at the login step** (decided during spec synthesis) — the affordance stays live; it opens the path to making it work.

### 7.2 The Chooser gesture

Every download control is a **split button**: main face = one click with saved defaults (the queued toast confirms provider/tier/files); `▾` face (or right-click anywhere on the control) = the full Chooser as an **anchored popover** — never a dialog on every click. Chooser content: provider segmented control (fixed on collection rows — a collection belongs to its provider), the provider's quality tiers with detail text (Apple: "ALAC 24/192 · ALAC 16/44.1 · AAC 256"; TIDAL: its four rungs), audio type stereo/Atmos/both (collapsing to ATMOS ONLY on Atmos-only tracks), lyrics embed/.lrc/.ttml quick toggles, art sidecar/embed toggles, **SET AS DEFAULTS** (writes back to Settings) + DOWNLOAD. Choice applies to that click only.

### 7.3 Standalone lyrics/art actions

First-class buttons beside DOWNLOAD on album and artist pages ("LYRICS ONLY", "ART ONLY"); per-track as a compact hover affordance beside the track's split button. Both providers; they honor the embed/sidecar matrix (§9 of the [lyrics & art ticket](https://github.com/ranokay/waves/issues/10)) independently of audio, on found music and already-saved music alike.

### 7.4 Preview playback (decided during spec synthesis)

v1 includes Apple previews: the documented **30-second AAC preview URL** (a plain song attribute; no session, no wrapper, no setup) plays through the **existing shared preview player**. Full-track preview stays TIDAL-only, expressed as the `PREVIEW` capability with the optional `preview_url` hook (§4.5). Apple rows show the standard preview affordance; the asymmetry (30 s clip vs whole track) is accepted — it is what Apple documents.

## 8. Library recognition and badges

**One tag family, one library tree, two different badge questions, Atmos as a Version.** ([Ticket: Recognizing Apple files & provider-aware badges](https://github.com/ranokay/waves/issues/18))

### 8.1 The on-disk tag family

A generic `WAVES_*` family written by **both** providers going forward:

| Tag | Content |
|---|---|
| `WAVES_ITEM_ID` | the namespaced id (`tidal:…` / `apple:…`) |
| `WAVES_ARTIST_IDS` / `WAVES_ALBUM_ARTIST_ID` | the multi-credit id groundwork, now namespaced |
| `WAVES_AUDIO_TYPE` | `stereo` / `atmos` — recognition never depends on codec sniffing |

On MP4 (Apple ALAC/AAC/Atmos and TIDAL Atmos) these ride the existing freeform-atom mechanism (`----:com.apple.iTunes:…`); on FLAC, vorbis comments. TIDAL downloads keep writing the legacy `WAVES_TIDAL_*` tags alongside. The scan reads **generic-first, legacy-fallback**; the codec sniff retires to a legacy fallback only.

### 8.2 Path templates stay shared

Apple files land through the **same template system** as TIDAL — one `Artist/[Year] Album/…` tree, one Plex-readable library, provider-neutral tokens. The only special placement remains the **Dolby Atmos files** template (§5.4). Per-provider template variants are rejected for v1.

### 8.3 Badge semantics: two different questions

- **IN LIBRARY / PARTIALLY / MAYBE — scan-based, provider-blind.** They answer *"does this music exist on disk?"*; the scan matches by tags whoever saved it. Owning the TIDAL master **does** badge the Apple search result IN LIBRARY — the music is in your library. MAYBE-proof and the MusicBrainz arbiter work unchanged.
- **DOWNLOADED / HAVE / REDOWNLOAD — ownership-based, strictly per-provider.** They answer *"has Waves saved this provider's version?"*. Owning TIDAL's HI-RES never shows Apple's row as DOWNLOADED. The queue's HAVE marking is per-provider likewise.
- **Quality upgrades stay per-provider**: each provider's quality setting governs its own re-fetch ladder. No cross-provider upgrade interaction — wanting Apple's ALAC when TIDAL's copy exists is a deliberate choice, and both copies coexist as separate Versions.

### 8.4 Atmos files in the scan

An Atmos file is a **Version attached to its canonical track, never a duplicate**: the scan counts the non-Atmos files as the album's **canonical track set** (the "7 OF 10 IN LIBRARY" arithmetic and multi-disc folding run on it); Atmos copies attach by track, matched within the album folder and its Atmos subfolder, audio type read from `WAVES_AUDIO_TYPE` (codec sniff as fallback). Album cards earn a small **ATMOS TOO** micro-badge when Atmos versions exist. A fully Atmos-only track is its own canonical entry — no stereo twin to attach to.

## 9. Lyrics, album art, and Settings

### 9.1 The lyrics & album-art matrix

([Ticket: Lyrics & album-art policy matrix](https://github.com/ranokay/waves/issues/10)) TIDAL's current behavior stays byte-for-byte; the matrix extends it.

**Formats & sidecars** — sidecar toggles independent, one per format, all combinations valid, extensions never faked:

| Format | Providers | What it is |
|---|---|---|
| LRC (line-timed) | both | the interoperable standard, as today |
| Enhanced LRC (word-timed) | Apple | Waves converts syllable TTML → enhanced LRC in its own layer |
| **TTML (verbatim)** | Apple | **a first-class format choice**: saved exactly as Apple serves it, zero conversion loss |
| TXT (unsynced plain) | both | unchanged `.txt` rule, never a fake `.lrc` |

SRT is dropped for v1 (a conversion artifact, not something Apple provides).

**Embedding**: the existing embed toggle keeps its exact semantics — timed-when-available LRC in the primary lyrics field (FLAC `LYRICS`, MP4 `©lyr`, MP3 SYLT) plus the unsynced sibling. **TTML is sidecar-only** (a document format, not a tag format). All four embed × sidecar combinations stay valid, including "download but don't embed".

**Source precedence** (both providers, in order): 1. word-timed when the toggle is on (default **on**) — on Apple, syllable TTML **outranks a line-timed LRCLIB hit**; 2. LRCLIB-first (existing toggle, governs both providers); 3. provider-native fallback (Apple TTML → LRC conversion); 4. unsynced text last. **Syllable sourcing is direct**: Waves calls the `syllable-lyrics` relationship through the embedded AppleMusicApi client and converts in its own layer — not waiting on upstream glomatico/gamdl#345 — with graceful per-track fallback to line-timed.

**Defaults** (existing TIDAL defaults unchanged): `lyrics_embed` off, `lyrics_file` off, `synced_only` off, `prefer_lrclib` on; new toggles: word-timed **on**, .ttml sidecar **off**.

**Album art**: the existing `CoverDimensions` setting governs both providers; **ORIGIN maps per provider** — TIDAL keeps its exact current behavior (embedded cap included), Apple's ORIGIN is the true original-master image (URL-rewrite path), with the `{w}x{h}` template up to 5000×5000 otherwise. Sidecar format options: jpg (default) / png, plus raw-original on Apple; embedded format stays jpg for both. Animated artwork: post-v1 (§12).

## 9.2 Settings architecture

([Ticket: Config-first settings architecture](https://github.com/ranokay/waves/issues/11)) **Two axes — per-provider sections for what differs, shared sections for what doesn't — with a one-migration carry-over that no existing user feels.**

1. **A new Providers area** with a **TIDAL** section and an **Apple** section, each holding: enable/session state, the provider's quality default, and provider-specific runtime/pacing. Cross-provider behavior stays in the existing sections, now explicitly governing both providers (help-text updates only): lyrics/art toggles, path templates including the **Dolby Atmos files** template, library, queue, diagnostics. Per-provider duplication of shared toggles is rejected on purpose.
2. **Per-provider quality fields, one migration**: `quality_audio` (a serialized tidalapi enum today) splits into **`tidal_quality_audio` / `apple_quality_audio`, serialized as Waves tier strings** (§4.3). One migration converts the existing value into `tidal_quality_audio` — nobody's settings reset, no meaning changes. `quality_video` keeps its name and section (video is a TIDAL-only capability); `download_dolby_atmos` keeps its name and its shared both-provider meaning (§5.1).
3. **The Apple section**: always visible, behind an **enable switch (default off)** — the optional-component decision made concrete. Turning it on starts the **in-place setup wizard** (§2): managed runtime provisioning → Apple ID login + 2FA → APK supply, with the **cookies-only tier** in the same wizard as the graceful fallback. A **color-coded status light** — not set up / runtime ready / signed in / needs attention — mirrors the existing FFmpeg status light. The section also hosts Apple's pacing fields (§3) and runtime manage actions (update, remove).
4. **Pacing fields**: TIDAL's `api_rate_limit_*` keep their names, meaning, and section verbatim; Apple gains same-shape fields in the Apple section (§3).
5. **Chooser defaults fall out of Settings** exactly as the glossary says: per-provider quality, the shared audio-type toggle, the shared lyrics/art toggles. No separate chooser-defaults store.

## 10. Packaging and distribution constraints

(Decided during spec synthesis, resolving the map's packaging fog — grounded in the engine decision's build-and-pin ruling and the setup run's evidence.)

1. **Nothing Apple-engine ships inside Waves' own package.** Waves' signed/notarized application contains no Apple-engine artifacts; every engine piece is **provisioned at setup time** through the managed-runtime flow (§2) — downloaded, checksum-verified, extracted (tar.gz), chmod'd, version-pinned. This keeps Waves' installer free of Apple-adjacent material and follows the FFmpeg-manager precedent exactly.
2. **The Apple Music APK is user-supplied, never redistributed or proxied by Waves** — it is Apple's proprietary software; bundling, mirroring, or fetching it through Waves' infrastructure would be redistribution. The wizard guides the user to source the pinned version (from wrapper-v2's `LIBS_VERSION.json`), verifies it by SHA-256, and scripts the `.apkm` extraction — every step of which was proven in the setup run. **Automatic APK fetching is explicitly not v1** (legal exposure for zero real friction; the manual step took one download).
3. **Container runtime dependency**: the full tier presumes a container runtime (Docker). The wizard detects it, attempts a gentle start on macOS, and guides when absent (§2) — it never silently installs one.
4. **Engine bumps ride the updater**: Waves pins gamdl (version line), its own wrapper-v2 image build, and the N_m3u8DL-RE release; when upstream fixes scraper breakage, a pinned-version bump ships through Waves' normal update channel — the user updates Waves, the runtime refresh follows on next wizard/supervision pass.
5. **Platform order**: macOS Apple silicon ships first (arm64 image runs natively — the deciding fact). **Windows and Linux follow as later enablements**: both need the container-runtime path verified per platform (image architecture for x86-64 hosts among them) — an enablement-verification requirement of those milestones, not an open design decision.
6. **Notarization**: Waves' own signing/notarization pipeline is unchanged; the provisioning flow must keep downloaded executables inside the app's managed-runtime area with provenance recorded (source URL + checksum), the pattern the FFmpeg manager already uses.

## 11. What does *not* change

Worth stating plainly, since the spec touches everything:

- **TIDAL's engine, session, matching, metadata, lyrics, artwork behavior**: unchanged, except the §5.1 toggle-meaning change (ratified) and the mechanical call-routing through `TidalProvider` (tests pin behavior).
- **The library scan's provider-blindness** for IN LIBRARY-class badges: unchanged (§8.3 formalizes it).
- **Existing path templates, quality ranks, refusal taxonomy, queue states, ownership semantics**: extended (namespaced ids, explicit audio type, per-provider scoping), not replaced; existing data backfills, nothing resets.
- **AGPL-3.0**: no unlicensed or incompatible code enters the tree; the wrapper-v2 image is built from source (Unlicense) and never vendored into Waves.

## 12. Post-v1, explicitly deferred

Not decisions pending — decisions made to defer:

- **ISRC-deduped merged search results** across providers (v1 ships sections per provider). The documented ISRC batch lookup (`filter[isrc]`, 25 max) is the natural dedupe key, already identified.
- **Animated Apple artwork** (needs an ffmpeg-derived decode of `editorialVideo`).
- **Automatic APK fetching** (§10.2).
- **Windows and Linux enablement** (§10.5).
- **SRT lyrics sidecar** if ever wanted (config-first addition).
- **qobuz** — a separate future effort upstream; the Provider seam must not (and does not) preclude it. Better Lyrics as a lyrics source: likewise ruled out of this effort.

## 13. Handoff

This spec is the map's destination; **implementation ticketing is the next effort** and consumes this document as its complete input. A non-binding suggested sequencing, from the dependency structure of the decisions above:

1. Provider seam refactor — `waves/providers/`, TIDAL delegation, namespaced ids, quality enum, pinned tests (§4).
2. Apple Provider green-field: search + catalog + previews behind the enable flag (§1, §4, §7) — no setup required to ship this slice.
3. Download path: `_JobSpec` through providers, dual-download semantics, per-version ownership/gates (§5).
4. Integrity gate: verification, retry, quarantine, skip-list (§6).
5. Managed runtime + setup wizard + Settings architecture + migration (§2, §9.2, §10).
6. Session supervision + pacing (§3).
7. QML: provider groups, split-button Chooser, standalone actions (§7).
8. Library recognition: tag family, scan changes, badges (§8).

Each slice leaves the TIDAL path demonstrably unchanged; the test suite is the proof obligation throughout.

---

## Appendix: decision index

| Map ticket | Ruling | Spec sections |
|---|---|---|
| [Evaluate glomatico/gamdl](https://github.com/ranokay/waves/issues/2) | good fit; MIT; search built in; 429 + corruption + token-scrape risks | 1 |
| [Evaluate zhaarey/apple-music-downloader](https://github.com/ranokay/waves/issues/3) | functionally best, **unlicensed** — never vendored | 1, 11 |
| [Evaluate WorldObservationLog wrapper & AppleMusicDecrypt](https://github.com/ranokay/waves/issues/4) | most embeddable shape; M-series crash risk; **kept as fallback** | 1, 4.1 |
| [ALAC corruption: what Waves must do](https://github.com/ranokay/waves/issues/5) | engine-agnostic verify + retry + quarantine mandatory | 6 |
| [Apple catalog surface](https://github.com/ranokay/waves/issues/6) | documented search/`audioVariants`/`hasLyrics`/ISRC/art template; exact tiers + TTML + original art on undocumented extensions | 4.3, 7.4, 9.1, 12 |
| [Provider seam: where TIDAL assumptions live](https://github.com/ranokay/waves/issues/7) | ~15-method interface suffices; coupling surprises named | 4 |
| [Design the Provider abstraction seam](https://github.com/ranokay/waves/issues/9) | fused interface, both implement now; row-dict contract; namespaced ids; Waves quality enum; composition; Atmos fence; no Engine layer | 4 |
| [Lyrics & album-art policy matrix](https://github.com/ranokay/waves/issues/10) | per-format sidecar toggles; verbatim TTML first-class; direct syllable sourcing; ORIGIN per provider | 9.1 |
| [Stereo + Atmos dual-download behavior](https://github.com/ranokay/waves/issues/12) | alongside semantics; per-version rows/ownership/gates; Atmos path template | 5 |
| [Config-first settings architecture](https://github.com/ranokay/waves/issues/11) | two-axis layout; quality split + one migration; Apple section + wizard + status light | 9.2 |
| [Per-download chooser & provider-sectioned search UI](https://github.com/ranokay/waves/issues/13) | Variant A: provider groups, split button, standalone actions | 7 |
| [Apple Music account + one-time decryption setup (human)](https://github.com/ranokay/waves/issues/14) | both tiers proven; wizard fuel: config landmine, tar.gz, APK, port 80, search-needs-nothing | 2 |
| [Apple session supervision](https://github.com/ranokay/waves/issues/17) | on-demand sidecar; held-not-failed; throttled countdown; honest breakage messaging; no new queue states | 3 |
| [ALAC verification & quarantine](https://github.com/ranokay/waves/issues/16) | always-on pre-swap; 2 retries + outbreak pre-filter; Quarantine folder + skip-list; REDOWNLOAD re-ask | 6 |
| [Recognizing Apple files & badges](https://github.com/ranokay/waves/issues/18) | generic tag family; shared templates; two badge questions; Atmos as Version | 8 |
| [Choose the Apple engine approach](https://github.com/ranokay/waves/issues/8) | **gamdl embedded + wrapper-v2 for ALAC**; N_m3u8DL-RE mode; WorldObs-v3 fallback; two-tier setup | 1, 2 |

**Decisions made during spec synthesis** (not previously pinned as their own tickets; flagged for review):

- Apple search group gates on **enabled**; sign-in gates **downloading**; a pre-setup download click routes into the wizard (reconciles the prototype phrasing with the engine decision's search-before-setup intent, reconfirmed live) — §7.1.
- Apple previews in v1 via the documented 30-second preview URL — §7.4 (confirmed with the human during synthesis).
- APK sourcing: user-supplied, never redistributed by Waves; auto-fetch not v1 — §10.2.
- No Apple-engine artifacts inside Waves' signed package; all engine pieces provisioned at setup — §10.1.
- Initial values instantiated for tunables: pacing 30 s / 25 songs; 2 retries with ~5 s pacing; idle sidecar stop 5 min — §§2, 3, 6.
