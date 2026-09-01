# Apple Music catalog surface (engine-independent)

Researched: 2026-09-01, for wayfinder ticket [#6](https://github.com/ranokay/waves/issues/6). Answers: "what does the Apple Music catalog actually expose, independent of engine choice?" Verified against Apple's own documentation (developer.apple.com) and the source code of the three candidate engines, shallow-cloned and inspected at: gamdl @ `478c3f2` (2026-08-03), zhaarey/apple-music-downloader @ `0d895e0` (2026-08-21), WorldObservationLog/AppleMusicDecrypt @ `d1a9a10` (2026-07-06), WorldObservationLog/wrapper @ `3e0ee61`. No code was copied from any external repo; all claims below are summaries with links.

## Bottom line

The Apple Music catalog is fully queryable by an independent client, and every dimension the per-download chooser needs is obtainable:

- **Search: yes** — one documented endpoint, `GET /v1/catalog/{storefront}/search`, covers songs/albums/artists/playlists/music-videos with paging. Auth = developer token only; no user token.
- **Quality: two layers.** The *catalog API* only flags *presence* of a tier (`audioVariants`: `lossy-stereo`, `lossless`, `hi-res-lossless`, `dolby-atmos`, `dolby-audio`). The *exact* resolution (24-bit/192 kHz, Atmos bitrate) is **not in the catalog API at all** — it lives in the enhanced-HLS master playlist (`extendedAssetUrls.enhancedHls`), whose per-variant `AUDIO` tags encode sample-rate/bit-depth (`audio-alac-stereo-192000-24`) and bitrates (`audio-atmos-2768`, `audio-stereo-256`). A chooser that wants "24/192 available?" must fetch one extra m3u8 per track (or read `audioVariants` and accept tier-level granularity).
- **Lyrics: yes, TTML is the single on-wire format** with three timing modes (`itunes:timing`: `None` / `Line` / `Word`), plus embedded translations/transliterations; availability is flagged by `hasLyrics` / `hasTimeSyncedLyrics`. Word-level content comes from a separate `syllable-lyrics` sub-resource. Lyrics requests want a `Media-User-Token`.
- **Cover art: a `{w}x{h}bb.jpg` URL template** with documented width/height maxima, plus an undocumented "raw" path that returns the original master asset (what all engines use for "original" quality). Animated artwork exists as `editorialVideo` clips.
- **ISRC: documented on Song** and, importantly, there is a **documented ISRC lookup endpoint** (`filter[isrc]`, batch of 25) — the natural key for future TIDAL↔Apple dedupe. Albums expose `upc`.

Per-engine: **gamdl and zhaarey expose nearly everything today** (gamdl is the only one with search in its library API; zhaarey has it too via its ampapi package); **AppleMusicDecrypt has no search** and no raw-tag surface, but its quality probe is the richest (channels, sample rate, bit depth per variant) and search would be a ~30-line addition to its `WebAPI`. Lyrics word-level: zhaarey and wrapper-lite fetch `syllable-lyrics`; AMD does line-level LRC only.

---

## 1. Search

**Documented endpoint:** `GET https://api.music.apple.com/v1/catalog/{storefront}/search` — "Search the catalog by using a query." [Apple: Search for Catalog Resources](https://developer.apple.com/documentation/applemusicapi/search-for-catalog-resources-(by-type)) (also under the [Search topic](https://developer.apple.com/documentation/applemusicapi/search)). Query params:

- `term` (required; `+` between words)
- `types` (required) — list of resource types; songs, albums, artists, playlists, music-videos are all valid catalog types
- `limit`, `offset` (paging), `l` (language tag), `with` (request modifications)

**Auth: developer token only.** Apple's rule: "A developer token is used to authorize all Apple Music API requests" via `Authorization: Bearer`, while the `Music-User-Token` header is required only "for data specific to an Apple Music subscriber, such as to fetch content from the user's library" (e.g. `/v1/me/library/...`). [Generating developer tokens](https://developer.apple.com/documentation/applemusicapi/generating-developer-tokens), [User Authentication for MusicKit](https://developer.apple.com/documentation/applemusicapi/user-authentication-for-musickit). Catalog search (and catalog song/album/playlist fetch) needs **no** user token. Developer tokens are JWTs (`{alg: ES256, kid}` header, `{iss: team-ID, iat, exp}` payload) signed with a MusicKit private key; Apple rate-limits requests per token with `429` responses ([Generating developer tokens](https://developer.apple.com/documentation/applemusicapi/generating-developer-tokens)).

**How engines actually get a developer token:** none of them own a MusicKit key. All three scrape the long-lived JWT embedded in the Apple Music web player's `index.js` (gamdl [`get_token`](https://github.com/glomatico/gamdl/blob/478c3f2/gamdl/api/apple_music.py), api/apple_music.py:77-127; zhaarey [`GetToken`](https://github.com/zhaarey/apple-music-downloader/blob/0d895e0/utils/ampapi/token.go), utils/ampapi/token.go:11-51; AppleMusicDecrypt `_set_token`, [src/api.py:63-68](https://github.com/WorldObservationLog/AppleMusicDecrypt/blob/d1a9a10/src/api.py)). `media-user-token` comes from browser cookies (gamdl `create_from_netscape_cookies`, api/apple_music.py:218-248) or config. Note the engines call `amp-api.music.apple.com` (the web player's host) rather than the documented `api.music.apple.com`; same JSON:API shape, stricter `Origin: https://music.apple.com` expectations.

**In the engines:**

- **gamdl**: full search API method, `types` default `"songs,music-videos,albums,playlists,artists"` ([`get_search_results`](https://github.com/glomatico/gamdl/blob/478c3f2/gamdl/api/apple_music.py), api/apple_music.py:612-635). Not surfaced in the CLI, but the library API exposes it.
- **zhaarey**: [`ampapi.Search`](https://github.com/zhaarey/apple-music-downloader/blob/0d895e0/utils/ampapi/search.go) (utils/ampapi/search.go:55-97) with dev token + `Origin` header, **no media-user-token** — proof by implementation that search needs only the dev token. The CLI's interactive search (`handleSearch`, main.go:549-683) offers album/song/artist, but the API function accepts any types string.
- **AppleMusicDecrypt**: no search anywhere in `src/api.py` (song/album/playlist/artist fetch only). Adding it is trivial — the request plumbing (`_request`, token handling) already exists.

## 2. Per-track quality metadata

**Layer 1 — catalog API (documented).** The [Song attributes dictionary](https://developer.apple.com/documentation/applemusicapi/songs/attributes-data.dictionary) lists `audioVariants` ("Indicates the specific audio variant for a song", an extended attribute) with allowed values:

| `audioVariants` value | Meaning |
|---|---|
| `lossy-stereo` | AAC 256 kbps stereo (the "High Quality" tier) |
| `lossless` | ALAC, up to 24-bit/48 kHz |
| `hi-res-lossless` | ALAC, up to 24-bit/192 kHz |
| `dolby-atmos` | Dolby Atmos (E-AC-3) spatial mix |
| `dolby-audio` | AC-3 Dolby Audio 5.1 |

Tier definitions per Apple: catalog is ALAC "16-bit/44.1 kHz (CD Quality) up to 24-bit/192 kHz"; "Lossless for a maximum resolution of 24-bit/48 kHz, Hi-Res Lossless for a maximum resolution of 24-bit/192 kHz" ([About lossless audio in Apple Music](https://support.apple.com/en-us/HT212183)). These flags say a tier *exists*, **not** which resolution a given track tops out at (a track flagged `hi-res-lossless` may only be 24/96).

The documented attributes also include `hasLyrics` (boolean), `isrc`, `contentRating` (`clean`/`explicit`), `previews` (30-second AAC preview URLs), `playParams`, `releaseDate`, `discNumber`/`trackNumber`, `genreNames`, `durationInMillis` ([Song attributes](https://developer.apple.com/documentation/applemusicapi/songs/attributes-data.dictionary)).

**Layer 2 — undocumented attributes the engines rely on.** All engines request `extend=extendedAssetUrls` on song/album fetch (`extend` itself is a [documented query param](https://developer.apple.com/documentation/applemusicapi/get-a-catalog-song): "A list of attribute extensions to apply"). The operative key today is **`enhancedHls`** — the enhanced-HLS master playlist URL (zhaarey's response struct: [`SongRespData`](https://github.com/zhaarey/apple-music-downloader/blob/0d895e0/utils/ampapi/song.go), utils/ampapi/song.go:91-96; AppleMusicDecrypt `_get_m3u8_url`, [src/rip.py:237-249](https://github.com/WorldObservationLog/AppleMusicDecrypt/blob/d1a9a10/src/rip.py)). The same structs show other undocumented returned attributes: **`hasTimeSyncedLyrics`** (bool), **`audioTraits`** (string array), **`audioLocale`**, and on albums **`upc`**. (The legacy per-codec asset-URL keys — `enhancedHires`, `plus`, `superJa` — that older community docs mention did not appear in any of the three engines' current code; `enhancedHls` has replaced them.)

**Layer 3 — the HLS master playlist (the real quality oracle).** `enhancedHls` is a master m3u8 whose variants carry `#EXT-X-STREAM-INF` `CODECS` + `AUDIO` tags that encode exact resolution and bitrate:

- `audio-alac-stereo-<sampleRate>-<bitDepth>` with `CODECS=alac` — e.g. `audio-alac-stereo-192000-24` = ALAC 24-bit/192 kHz (zhaarey parses bitDepth/sampleRate from exactly this, [main.go `extractMedia`](https://github.com/zhaarey/apple-music-downloader/blob/0d895e0/main.go), main.go:2590-2603; AMD's regex grammar `audio-alac-stereo-\d{5,6}-\d{2}`, [src/types.py:65-77](https://github.com/WorldObservationLog/AppleMusicDecrypt/blob/d1a9a10/src/types.py))
- `audio-atmos-<bitrateKbps>` with `CODECS=ec-3` — e.g. `audio-atmos-2768` = Atmos E-AC-3 ≈768 kbps (zhaarey main.go:2572-2589; AMD regex `audio-(atmos|ec3)-\d{4}`)
- `audio-ac3-<bitrate>` with `CODECS=ac-3` (Dolby Audio 640 kbps)
- `audio-stereo-<bitrate>` with `CODECS=mp4a.40.2` — `audio-stereo-256` = AAC 256 kbps; variants `-binaural` and `-downmix` exist (gamdl's [`SONG_CODEC_REGEX_MAP`](https://github.com/glomatico/gamdl/blob/478c3f2/gamdl/interface/constants.py), interface/constants.py:33-43, matches the same grammar)

AppleMusicDecrypt additionally reads `#EXT-X-MEDIA` entries for `channels` and embedded `sample_rate`/`bit_depth` per variant ([src/quality.py `get_available_audio_quality`](https://github.com/WorldObservationLog/AppleMusicDecrypt/blob/d1a9a10/src/quality.py)). Note the m3u8 itself is **not** auth-gated (plain HTTPS GET; no token needed to read the manifest — decryption is the hard part, which is the engines' DRM business and out of scope here).

**Bottom line for the chooser:** per-track "does 24/192 / Atmos / AAC-256 exist" = one catalog call with `audioVariants` (tier-level), or one extra m3u8 fetch (exact level). `isVocalAttenuationExtended`, an older Atmos flag from legacy docs, is absent from the current Song attributes and from all three engines.

## 3. Lyrics

**Single on-wire format: TTML**, carrying three timing modes tagged by the `itunes:timing` attribute on the root `tt` element — `"None"` (plain unsynced text), `"Line"` (line-synced `<p begin=…>`), `"Word"` (syllable/word-synced `<span begin=… end=…>` inside each line). TTML `head/metadata/iTunesMetadata` can also carry **`translations`** and **`transliterations`** keyed to each line's `itunes:key` (zhaarey's converter branches on all three modes and reads both metadata blocks: [`TtmlToLrc`](https://github.com/zhaarey/apple-music-downloader/blob/0d895e0/utils/lyrics/lyrics.go), utils/lyrics/lyrics.go:125-253; AMD's converter handles translations incl. `replacement` type and transliterations: [`ttml_convent`](https://github.com/WorldObservationLog/AppleMusicDecrypt/blob/d1a9a10/src/utils.py), src/utils.py:87-135; gamdl's TTML→LRC/SRT: [`_get_lyrics`](https://github.com/glomatico/gamdl/blob/478c3f2/gamdl/interface/song.py), interface/song.py:97-137).

**Availability flags.** `hasLyrics` is a documented, required Song attribute ("Indicates whether the song has lyrics available") ([Song attributes](https://developer.apple.com/documentation/applemusicapi/songs/attributes-data.dictionary)); `hasTimeSyncedLyrics` is the undocumented synced-specific variant both Go engines decode (zhaarey [song.go:84](https://github.com/zhaarey/apple-music-downloader/blob/0d895e0/utils/ampapi/song.go); AMD gates lyrics fetching on it, [src/rip.py:100-101](https://github.com/WorldObservationLog/AppleMusicDecrypt/blob/d1a9a10/src/rip.py)).

**Two fetch styles (both verified in engine code; neither is in Apple's public docs):**

1. **Relationship include:** `include=lyrics` on the song fetch → `relationships.lyrics.data[0].attributes.ttml` (gamdl's default `get_song` call, [api/apple_music.py:301-322](https://github.com/glomatico/gamdl/blob/478c3f2/gamdl/api/apple_music.py)).
2. **Dedicated sub-resource:** `GET /v1/catalog/{storefront}/songs/{id}/lyrics` (line-timed → `attributes.ttml`) and `GET /v1/catalog/{storefront}/songs/{id}/syllable-lyrics` (word-timed → `attributes.ttmlLocalizations`), with `extend=ttmlLocalizations` (zhaarey [`getSongLyrics`](https://github.com/zhaarey/apple-music-downloader/blob/0d895e0/utils/lyrics/lyrics.go), utils/lyrics/lyrics.go:53-79; wrapper-lite builds the same URLs, [lite/apple_api.cpp:224-239](https://github.com/WorldObservationLog/wrapper/blob/3e0ee61/lite/apple_api.cpp)).

**Auth:** lyrics want a **`media-user-token`**. zhaarey refuses to fetch without one (errors unless the token is ≥50 chars, lyrics.go:31-34) and sends it as a `media-user-token` cookie; wrapper-lite sends it as a header alongside `Authorization: Bearer` and `Origin: https://music.apple.com` ([lite/apple_api.cpp:252-254](https://github.com/WorldObservationLog/wrapper/blob/3e0ee61/lite/apple_api.cpp)); gamdl sends it as a cookie on all AMP requests when configured (api/apple_music.py:201-206). This fits Apple's documented model: the token identifies the subscriber ([User Authentication for MusicKit](https://developer.apple.com/documentation/applemusicapi/user-authentication-for-musickit)) — and in practice an **active Apple Music subscription** is required for lyrics (and for playback assets) to be returned.

**Conversion available off the shelf:** unsynced plain text, LRC (line-sync), enhanced LRC with word timestamps `<mm:ss.xx>` (zhaarey [`conventSyllableTTMLToLRC`](https://github.com/zhaarey/apple-music-downloader/blob/0d895e0/utils/lyrics/lyrics.go), lyrics.go:255-413), SRT and raw TTML passthrough (gamdl `SyncedLyricsFormat.LRC/SRT/TTML`).

## 4. Cover art

**Documented mechanics** ([Artwork object](https://developer.apple.com/documentation/applemusicapi/artwork)):

- `url` is a **template**: "`{w}x{h}` must precede image filename, as placeholders for the `width` and `height` values … For example, `{w}x{h}bb.jpeg`".
- `width`/`height` are "the maximum width/height available for the image" — i.e. the API tells you the native size. Substituting `{w}x{h}` (plus optional format suffix `.jpg`/`.png`) returns a resized variant from Apple's CDN.

**Maximum resolution:** the template can serve at least the native `width`×`height`, but the **original master asset** (typically 3000×3000 for recent albums, higher for some) is reachable via an undocumented URL rewrite that both mature engines implement:

- gamdl "raw" mode: strip the `image/thumb/` path segment, swap host `is1-ssl` → `a1`, and drop the `{w}x{h}bb.jpg` suffix ([`_get_raw_cover_url`](https://github.com/glomatico/gamdl/blob/478c3f2/gamdl/interface/base.py), interface/base.py:229-242); default size otherwise 1200 (interface/base.py:129).
- zhaarey "original" mode: rewrite `is1-ssl.mzstatic.com/image/thumb` → `a5.mzstatic.com/us/r1000/0` and cut the URL before the trailing segment, with a same-size fallback if it 404s ([main.go:380-452](https://github.com/zhaarey/apple-music-downloader/blob/0d895e0/main.go)).

Practical policy for Waves: request `ConfiguredSize×ConfiguredSize` from the template for embedding (engines default 1200×1200), and the raw path when the user wants "original". `jpg` and `png` are both servable (zhaarey swaps the extension to `.png`, main.go:395-399).

**Animated artwork:** albums can expose `attributes.editorialVideo` (undocumented extension) with `MotionSquare` / `MotionDetailSquare` / `MotionDetailTall` video URLs, which zhaarey saves as `square_animated_artwork.mp4` / `tall_animated_artwork.mp4` ([main.go:1528-1568](https://github.com/zhaarey/apple-music-downloader/blob/0d895e0/main.go)).

## 5. ISRC / identifiers (cross-provider matching)

What a future TIDAL↔Apple ISRC-dedupe can key on, all from the same catalog surface:

- **Song `isrc`** — documented attribute, "The International Standard Recording Code (ISRC) for the song" ([Song attributes](https://developer.apple.com/documentation/applemusicapi/songs/attributes-data.dictionary)); also decoded by zhaarey ([song.go:94](https://github.com/zhaarey/apple-music-downloader/blob/0d895e0/utils/ampapi/song.go)). TIDAL exposes the same ISRCs, so ISRC is the natural join key (fallback: name + artist + duration matching).
- **ISRC → song lookup is a documented endpoint:** `GET /v1/catalog/{storefront}/songs?filter[isrc]=…` — "You can substitute `filter[isrc]` for `ids`… one ISRC value may return more than one song. The maximum fetch limit is 25" ([Get Multiple Catalog Songs by ISRC](https://developer.apple.com/documentation/applemusicapi/get-multiple-catalog-songs-by-isrc)). Storefront-scoped, dev-token auth. This makes dedupe *and* reverse lookup cheap.
- **Album `upc`** — returned on album attributes (zhaarey's album struct, [song.go:149](https://github.com/zhaarey/apple-music-downloader/blob/0d895e0/utils/ampapi/song.go)) for album-level matching.
- **Native identifiers:** numeric catalog IDs (`adamId`), `playParams.id`, and storefront equivalence (`Get Equivalent IDs` on songs/albums, [Songs API topic](https://developer.apple.com/documentation/applemusicapi/songs-api)) — relevant since everything above is storefront-dependent.

## 6. Per-engine exposure

Legend: ✅ exposed today · 🟡 in engine code but not surfaced at the chosen API boundary · ❌ absent (but the engine's plumbing makes it a small addition). "Engine" boundaries chosen: gamdl's `AppleMusicApi`/interfaces, zhaarey's `ampapi` package + main.go, AppleMusicDecrypt's `WebAPI` + helpers.

| Dimension | gamdl | zhaarey (apple-music-downloader) | AppleMusicDecrypt (+ wrapper) |
|---|---|---|---|
| Catalog search (song/album/artist/playlist) | ✅ [`get_search_results`](https://github.com/glomatico/gamdl/blob/478c3f2/gamdl/api/apple_music.py), all 5 types | ✅ [`ampapi.Search`](https://github.com/zhaarey/apple-music-downloader/blob/0d895e0/utils/ampapi/search.go) (CLI exposes album/song/artist only) | ❌ no search method in `WebAPI`; add a GET to `/v1/catalog/{sf}/search` |
| Quality tier flags (`audioVariants`) | 🟡 present in raw song metadata it returns; engine itself selects via m3u8 regex | 🟡 present in raw metadata; engine uses m3u8 | 🟡 present in raw metadata; unused |
| Exact resolution (24/192, Atmos bitrate) | ✅ codec priority over m3u8 variants (`audio-alac-.*`, `audio-atmos-.*`), no per-variant bitrate in output | ✅ `extractMedia` parses bit-depth/sample-rate/bitrate per variant (debug table) | ✅ richest: [`quality.py`](https://github.com/WorldObservationLog/AppleMusicDecrypt/blob/d1a9a10/src/quality.py) yields codec, bitrate, avg bitrate, channels, sample rate, bit depth |
| `extendedAssetUrls.enhancedHls` | ✅ via `extend=extendedAssetUrls` (also `/v1/play/assets` + MZPlay webplayback paths) | ✅ same extend param | ✅ same extend param |
| Lyrics plain/line-synced | ✅ TTML→unsynced + LRC/SRT/TTML | ✅ `lrcType=lyrics`, LRC/TTML + translations/translits | ✅ via wrapper gRPC `lyrics()`; line-level LRC + translations/translits, TTML passthrough |
| Lyrics word/syllable | 🟡 raw TTML passthrough preserves word timing; no word-LRC converter | ✅ `lrcType=syllable-lyrics` → enhanced LRC with `<mm:ss.xx>` word stamps | 🟡 wrapper fetches syllable TTML; AMD's converter outputs line-level only |
| Lyrics availability flag | ✅ gates on `hasLyrics` | ✅ decodes `hasTimeSyncedLyrics` | ✅ gates on `hasTimeSyncedLyrics` |
| Cover art template + sizes | ✅ `{w}x{h}` substitution, jpg/png/raw(original) | ✅ size + png + original-mode rewrite | ✅ `get_cover(url, format, size)` ([src/api.py:148](https://github.com/WorldObservationLog/AppleMusicDecrypt/blob/d1a9a10/src/api.py)) |
| Original master artwork | ✅ raw-mode rewrite | ✅ original-mode rewrite | ❌ no raw/original mode (template only) |
| Animated artwork | ❌ | ✅ editorialVideo motion clips | ❌ |
| ISRC on song | 🟡 in raw metadata | ✅ decoded (`Isrc` field) | 🟡 in raw metadata |
| ISRC → song lookup (`filter[isrc]`) | ❌ (call it directly — one documented endpoint) | ❌ | ❌ |
| UPC on album | 🟡 in raw metadata | ✅ decoded | 🟡 in raw metadata |
| Auth model | dev token scraped from web player; `media-user-token` from cookies (sent as cookie) | same dev-token scrape; `media-user-token` from config (cookie for lyrics) | same dev-token scrape; user token lives in the wrapper service (gRPC) |

**Implications for Waves (feeds chooser UX, lyrics/art policy, engine choice — tickets #8, #10, #13):**

- The chooser can be built against the *catalog surface* (search + `audioVariants` + `hasLyrics` + artwork template + ISRC) without coupling to any engine, then mapped onto whichever engine executes the download.
- Exact "24/192?" verification costs one extra m3u8 GET per track; caching per-album (variants are usually album-wide) keeps this cheap.
- Word-level lyrics: only zhaarey's converter reaches enhanced LRC today; gamdl preserves the word-timed TTML raw. If word-level matters, plan on a small TTML→enhanced-LRC converter (or adopt zhaarey's approach conceptually — not its code, per license hygiene).
- ISRC dedupe needs no engine support at all: `filter[isrc]` is a documented Apple endpoint and TIDAL's metadata already provides the other half.
