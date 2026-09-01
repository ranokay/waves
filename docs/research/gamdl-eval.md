# gamdl evaluation for Waves' Apple Music provider

Evaluated: 2026-09-01. Target: [glomatico/gamdl](https://github.com/glomatico/gamdl) v3.8.5 (last release 2026-08-03).

## Bottom line

**gamdl is a good fit for Waves.** It is a mature (v3.x, ~2.6k stars), MIT-licensed, actively maintained Python CLI/library that already satisfies our settled constraints: one-time external setup (cookies file; optional wrapper-v2 server), wrapping-an-existing-engine architecture (a clean async Python library API — `AppleMusicApi` + downloaders — plus a CLI), ALAC up to 24-bit/192 kHz, Atmos/AC3 as independent codec choices, LRC/SRT/TTML lyrics, original-resolution cover art, and even programmatic catalog search (library-level, not exposed in the CLI). Prebuilt wheels exist for macOS Apple silicon (universal2), Windows x64/ARM64, and Linux x64/ARM64. The main risks are Apple's rate-limiting of the Widevine license endpoint, a persistent class of corrupted-output bugs in the download layer, and a brittle dev-token scraper tied to Apple's web app.

Recommended integration style for Waves: **use gamdl as a Python library** (it publishes an embedding API, see [README §Embedding](https://github.com/glomatico/gamdl#-embedding)), or drive the CLI as a subprocess. Either way, no gamdl code is copied into Waves, so MIT/AGPL-3.0 coexistence is trivial (keep the MIT notice if we vendor; we won't).

## Auth + decryption requirements

**What the user must set up (one-time-ish):**

- **Active Apple Music subscription** ([README §Prerequisites](https://github.com/glomatico/gamdl#-prerequisites)). Subscription status is checked via the account-info endpoint (`active_subscription`, [gamdl/api/apple_music.py:57-65](https://github.com/glomatico/gamdl/blob/main/gamdl/api/apple_music.py)).
- **Cookies file** (Netscape format) exported from a browser logged into music.apple.com. The `media-user-token` cookie is mandatory; it's parsed in [`create_from_netscape_cookies`](https://github.com/glomatico/gamdl/blob/main/gamdl/api/apple_music.py) (`api/apple_music.py:218-248`). These cookies expire periodically, so it's a "refresh every so often" item, not per-session.
- **Dev token: nothing to do.** gamdl scrapes it automatically from the Apple Music web app's `index.js` ([`get_token`](https://github.com/glomatico/gamdl/blob/main/gamdl/api/apple_music.py), `api/apple_music.py:77-127`). This is the brittle part — see risks.
- **No device files or manual WVD needed.** A Widevine L3 `.wvd` (dumped from an Android 9 virtual device) is **bundled in the source** at [gamdl/interface/wvd.py](https://github.com/glomatico/gamdl/blob/main/gamdl/interface/wvd.py); users may override it with `--wvd-path`. Decryption keys are obtained from Apple's license-exchange endpoint with the user's own auth ([`get_license_exchange`](https://github.com/glomatico/gamdl/blob/main/gamdl/api/apple_music.py), `api/apple_music.py:748-789`), then decrypted locally via pywidevine ([`get_decryption_key`](https://github.com/glomatico/gamdl/blob/main/gamdl/interface/base.py), `interface/base.py:162-202`).

**Optional wrapper-v2 (needed for ALAC):** [glomatico/wrapper-v2](https://github.com/glomatico/wrapper-v2) is a separate local server (Unlicense-licensed). With `--use-wrapper`, gamdl sends it Apple ID username + password (+ 2FA code on first login) ([`WrapperApi.login`](https://github.com/glomatico/wrapper-v2/blob/main/README.md), mirrored in gamdl `api/wrapper.py:96-134`); the wrapper then serves account/playback requests and FairPlay decryption over a local TCP port (default `127.0.0.1:10020`). Cookies can be skipped when the wrapper is used ([README §Wrapper](https://github.com/glomatico/gamdl#optional-dependencies)). Once logged in, the wrapper persists auth — genuinely one-time setup. gamdl pins an exact wrapper API version (`0.0.2`, `api/wrapper.py:14`), so the two must be upgraded in lockstep.

**Platform support:** Pure-Python paths work anywhere Python 3.10+ runs. The v3.x native engine (`gamdl._ammuxer`, Rust/pyo3 with abi3-py310, [Cargo.toml](https://github.com/glomatico/gamdl/blob/main/gamdl/downloader/ammuxer/Cargo.toml)) ships prebuilt wheels for macOS universal2 (Apple silicon covered), Windows amd64 + arm64, and Linux x86_64 + aarch64 (PyPI files for [gamdl 3.8.5](https://pypi.org/project/gamdl/#files)). macOS Apple silicon first is fully supported; no FFmpeg/MP4Box/mp4decrypt needed since 3.6 (release notes, [3.6.0](https://github.com/glomatico/gamdl/releases/tag/3.6)).

## Audio quality

Codec selection is a priority list (`--song-codec-priority`, default `aac-web`); each entry matches a regex over the HLS master playlist ([`SONG_CODEC_REGEX_MAP`](https://github.com/glomatico/gamdl/blob/main/gamdl/interface/constants.py), `interface/constants.py:33-43`). From [README §Song Codecs](https://github.com/glomatico/gamdl#song-codecs) and the enum ([`SongCodec`](https://github.com/glomatico/gamdl/blob/main/gamdl/interface/enums.py), `interface/enums.py:48-63`):

- **Web (no wrapper, Widevine L3 path):** `aac-web` (AAC 256 kbps), `aac-he-web` (64 kbps).
- **Non-web:** `aac` (256 kbps up to 48 kHz), `aac-he`, `aac-binaural`, `aac-downmix`, `aac-he-binaural`, `aac-he-downmix`, **`atmos` (Dolby Atmos 768 kbps EAC-3)**, `ac3` (640 kbps), **`alac` (up to 24-bit/192 kHz)**, `ask` (interactive).
- Since 3.8.0, "all lossy codecs work consistently without wrapper" via the assets API; **ALAC still requires the wrapper** ("ALAC may still require wrapper due to API limitations" — [3.8.0 release notes](https://github.com/glomatico/gamdl/releases/tag/3.8); README: "ALAC can be attempted without wrapper, but it probably won't work"). Code confirms why: ALAC playlists only carry FairPlay keys, and without a wrapper there is no FairPlay decryptor, so `GamdlInterfaceDecryptionNotAvailableError` is raised ([interface/song.py:662-670](https://github.com/glomatico/gamdl/blob/main/gamdl/interface/song.py)).

**Dolby Atmos independently of stereo: yes.** Atmos is just another codec entry (`atmos` → `audio-atmos-.*`); setting `--song-codec-priority atmos` fetches only the Atmos rendition. Atmos works without the wrapper (Widevine path) per the 3.8.0 note. Caveat: a closed issue reported ALAC/Atmos duration-metadata mismatches ([#285](https://github.com/glomatico/gamdl/issues/285), closed 2026-04-20) and Atmos remux failures in the 2.x era ([#120](https://github.com/glomatico/gamdl/issues/120), closed).

## Lyrics

Synced lyrics are downloaded by default as a sidecar file; formats ([README §Synced Lyrics Format](https://github.com/glomatico/gamdl#synced-lyrics-format), enum at `interface/enums.py:13-16`):

- **LRC** (default) — line-level timing, parsed from Apple's TTML `<p begin=...>` elements ([`_get_lyrics`](https://github.com/glomatico/gamdl/blob/main/gamdl/interface/song.py), `interface/song.py:97-137`).
- **SRT** — line-level with end times ("more accurate timing" per README).
- **TTML** — dumps Apple's raw TTML pretty-printed (`minidom.parseString(...).toprettyxml()`), the native format.
- **Unsynced lyrics** are also extracted and embedded as a tag (patch to `get_tags_from_asset_info`, `interface/base.py:338-403`).

**Gaps:**

- **Word-by-word / syllable timing is not supported in mainline.** Apple exposes it under a separate `syllable-lyrics` relationship, not the default `lyrics` include. Open feature request [#309](https://github.com/glomatico/gamdl/issues/309) (9 comments) and open PR [#345](https://github.com/glomatico/gamdl/pull/345) ("feat: add syllable lyrics support") confirm the gap. Our constraint is "lyrics in all provided formats" — line-level LRC/SRT/TTML are covered; syllable-level would need #345 to land or a small post-345 upstream pull.
- Lyrics are **sidecar files, not embedded** — embedding synced LRC is a separate open request ([#318](https://github.com/glomatico/gamdl/issues/318)). Waves could embed them itself after download.
- Historical timing-offset bug ([#169](https://github.com/glomatico/gamdl/issues/169), closed).

## Cover art

- Default 1200×1200 JPG embedded + optional `--save-cover` sidecar; size and format configurable (`--cover-size`, `--cover-format jpg|png|raw`).
- **`raw` mode fetches the artist's original upload at full native resolution**: it strips the `image/thumb/` prefix and swaps the CDN host from the artwork template URL ([`_get_raw_cover_url`](https://github.com/glomatico/gamdl/blob/main/gamdl/interface/base.py), `interface/base.py:229-242`). Note raw covers are not embedded (only saved as files) per [README §Cover Format](https://github.com/glomatico/gamdl#cover-format). For embedding at high quality, a large `--cover-size` (e.g. 5000) via the `{w}x{h}` template works for jpg/png.
- Open PR [#321](https://github.com/glomatico/gamdl/pull/321) fixes raw-cover URLs for music videos (song path unaffected). Album-without-artwork handling was fixed in [#188](https://github.com/glomatico/gamdl/issues/188) (closed).

## Search

**Yes, programmatic catalog search exists** — [`AppleMusicApi.get_search_results(term, types, limit, offset)`](https://github.com/glomatico/gamdl/blob/main/gamdl/api/apple_music.py) (`api/apple_music.py:612-635`) against Apple's AMP API, supporting songs/albums/playlists/artists/music-videos with pagination. It is **library-only**: the CLI takes URLs/IDs only (no search flags in [gamdl/cli/cli.py](https://github.com/glomatico/gamdl/blob/main/gamdl/cli/cli.py)). For Waves this is actually ideal — we'd call the library method for in-app search. Additionally, artist URLs can be expanded to all albums/top songs with auto-select options ([README §Artist Auto-Select](https://github.com/glomatico/gamdl#artist-auto-select-options)).

## Maintenance health

- **Very active.** 61 commits in the last ~3 months (2026-06-01 → 2026-09-01); last push 2026-08-03. Fifteen releases between 2026-04-27 and 2026-08-03 (roughly weekly–biweekly), [releases list](https://github.com/glomatico/gamdl/releases).
- **Healthy issue flow:** 16 open / 191 closed issues, 6 open / 74 closed PRs (search API, 2026-09-01). Most open issues are recent and get responses.
- **Caveats:** the maintainer explicitly states only critical bug-fix PRs are reviewed — feature PRs are not accepted ([README §Contributing](https://github.com/glomatico/gamdl#-contributing)), so our Waves-specific needs would live in our wrapper layer, not upstream. Recent commits and PRs (e.g. #333, #334, Python 3.14 support) are authored by collaborators; wrapper-v2 itself is less active (last push 2026-07-10, 8 open issues) but small and stable.

## License

**MIT** ([LICENSE](https://github.com/glomatico/gamdl/blob/main/LICENSE), "Copyright (c) 2024 Glomatico"; also `license = "MIT"` in [pyproject.toml](https://github.com/glomatico/gamdl/blob/main/pyproject.toml)). MIT is one-way compatible with AGPL-3.0: Waves can depend on, wrap, or subprocess gamdl while staying AGPL-3.0. No license obstacle. Dependencies are permissive too (wrapper-v2 is Unlicense). Do **not** copy gamdl source into Waves (both for hygiene and to avoid turning MIT files into AGPL files unnecessarily).

## Notable issues/PRs on our dimensions

- **Corrupted ALAC/output:** [#344](https://github.com/glomatico/gamdl/issues/344) (open) "Corrupted m4a files" — ~1500/2400 files corrupted, intermittently, despite correct file sizes; linked to [#328](https://github.com/glomatico/gamdl/issues/328) (open; every 101st song silent). Release [3.8.4](https://github.com/glomatico/gamdl/releases/tag/3.8.4) fixed "corrupted song endings with wrapper decryption" but #344 says it persists. Root cause per community triage on [#337](https://github.com/glomatico/gamdl/issues/337) (open): yt-dlp download mode not ensuring all HLS segments arrive — **switching `--download-mode nm3u8dlre` is the workaround**.
- **Atmos handling:** [#285](https://github.com/glomatico/gamdl/issues/285) (closed) duration mismatch on ALAC/Atmos; [#120](https://github.com/glomatico/gamdl/issues/120) (closed) remux failures; [#319](https://github.com/glomatico/gamdl/issues/319) (open) failed alac/atmos downloads on some tracks; [#340](https://github.com/glomatico/gamdl/issues/340) (open) older MVs missing AAC 256.
- **Lyrics:** [#309](https://github.com/glomatico/gamdl/issues/309) (open) word-by-word request; PR [#345](https://github.com/glomatico/gamdl/pull/345) (open) syllable support; [#169](https://github.com/glomatico/gamdl/issues/169) (closed) +30 min offset; [#318](https://github.com/glomatico/gamdl/issues/318) (open) embed synced LRC.
- **Artwork:** PR [#321](https://github.com/glomatico/gamdl/pull/321) (open) raw-cover URL fix for music videos; [#188](https://github.com/glomatico/gamdl/issues/188) (closed) albums without covers.
- **Rate limiting:** [#306](https://github.com/glomatico/gamdl/issues/306) (open, 8 comments) HTTP 429 on the license-exchange endpoint when batch-downloading; no built-in throttle/cooldown yet.

## Risks for Waves (top three)

1. **Apple-side rate limiting / account flags (HTTP 429 on license exchange).** Batch downloads can trip per-account/IP limits with no built-in backoff or skip-if-exists logic ([#306](https://github.com/glomatico/gamdl/issues/306)). Waves must add its own throttling, retry-with-backoff, and skip-if-downloaded (gamdl's optional SQLite database helps) — and users bear some account risk inherent to any downloader of this kind.
2. **Corrupted output in the default download path.** The yt-dlp-based downloader intermittently produces truncated/silent files (#344, #328, #337); the N_m3u8DL-RE download mode is the mitigation but adds an external binary + FFmpeg dependency. Waves should default to the more robust mode and/or add integrity verification (duration/sample-count checks) after download.
3. **Upstream brittleness tied to Apple's web app.** The auto-scraped dev token ([`get_token`](https://github.com/glomatico/gamdl/blob/main/gamdl/api/apple_music.py)) breaks whenever Apple restructures its web app (fixed repeatedly, e.g. [3.7.4 "Fixed an issue when fetching access token"](https://github.com/glomatico/gamdl/releases/tag/3.7.4), 3.8.5 "Fix non-web song key extraction"). Combined with the wrapper-v2 API version pin (`0.0.2`) and the no-feature-PRs policy, Waves is exposed to breakage windows and must track upstream releases promptly. ALAC additionally depends on wrapper-v2, a second moving part with a smaller maintenance footprint.

Non-risk notes: licensing (MIT) is a non-issue; platform support (macOS Apple silicon → Windows/Linux) is covered by prebuilt wheels; search, Atmos-independence, and lyrics formats meet the settled constraints today, with syllable-level lyrics as the only spec-level gap (PR #345 pending).
