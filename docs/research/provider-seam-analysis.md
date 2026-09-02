# Provider seam analysis — every place Waves assumes a single TIDAL provider

Research for wayfinder ticket #7. Internal codebase survey, no code changed.
Goal: give the Provider-abstraction design a factual seam inventory, so the
interface is cut where the code actually couples, not where it looks coupled.

Scope surveyed: `waves/download.py`, `waves/matching.py`, `waves/metadata.py`,
`waves/lyrics.py`, `waves/config.py`, `waves/ownership.py`,
`waves/library_index.py`, `waves/worker.py`, `waves/model/*`,
`waves/helper/*`, `waves/waves_ui/backend.py`, `waves/waves_ui/bridge_library.py`,
`waves/waves_ui/qml/Main.qml`, `waves/waves_ui/qml/SettingsPage.qml`.
All citations are `file:line` at commit `d4c0a87`.

---

## Bottom line

### The minimum interface a second provider must implement

```python
class Provider:
    id: str                                  # stable slug, e.g. "tidal" / "apple_music"

    # --- session/auth ---
    def login_begin(self) -> str             # auth URL the GUI opens (backend.py:4479 flow)
    def login_complete(self, redirect_url: str) -> bool   # backend.py:4497 flow
    def logout(self) -> None                 # backend.py:4549 flow
    is_logged_in: bool                       # gates enqueue (backend.py:9996) and browse
    def apply_quality(self, tier: str) -> None            # config.py:467 settings_apply analogue
                                                          #   [superseded: ships as (tier, audio_type) —
                                                          #    spec §4.5; audio type stays orthogonal to the
                                                          #    ladder, and how a provider delivers Atmos is
                                                          #    that provider's fenced per-stream business]

    # --- catalog read (returns the app's plain dicts; see "Catalog metadata shapes") ---
    def search(self, needle: str) -> dict                 # backend.py:4826 payload shape
    def open_url(self, url: str) -> dict | None           # backend.py:4749 payload shape
    def get_object(self, kind: str, id_: str) -> object    # helper/tidal.py:312 instantiate_media analogue
    def collection_items(self, obj, include_videos: bool) -> list  # helper/tidal.py:198 items_results_all analogue
    def user_collections(self) -> dict                     # helper/tidal.py:265 user_media_lists analogue

    # --- quality ---
    def advertised_tier(self, obj) -> str | None           # helper/tidal.py:335 quality_audio_highest analogue
    def advertised_ceiling(self, obj) -> int | None        # backend.py:1100 _advertised_ceiling analogue

    # --- per-track delivery (the one really new seam) ---
    def resolve_stream(self, track, tier: str | None) -> StreamInfo
    #   StreamInfo replaces model/downloader.py TrackStreamInfo:
    #   urls: list[str] (segment/BTS), file_extension: str,
    #   requires_flac_extraction: bool, codecs: str,
    #   delivered: {tier, audio_mode, bit_depth, sample_rate}  (backend.py:1044 contract)
    def fetch_lyrics(self, track) -> tuple[str, str]       # (synced, plain); TIDAL-fallback seam, download.py:3727
    def cover_url(self, obj, dimension: int) -> str | None # download.py:3840 album.image analogue
    def track_facts(self, track) -> dict                   # fields metadata_write reads, download.py:3772
```

Everything else — file I/O, naming, tagging, ownership, matching, queue —
stays shared, provided two invariants hold:

1. **Ids are namespaced.** `ownership.py` keys rows on bare `track_id`
   (ownership.py:107-123) and files carry a single id tag
   (`metadata.py:73` `WAVES_TIDAL_ID`). TIDAL numeric ids and Apple Music
   numeric ids will eventually collide; either prefix stored ids
   (`tidal:123`, `am:456`) or add a provider column. Same for the on-disk tag
   (see Ownership seam below).
2. **Quality tiers reduce to one rank scale.** Both providers' tiers must map
   onto the existing `LOW < HIGH < LOSSLESS < HI_RES_LOSSLESS` integer scale
   (`ownership.py:33`) — or the scale generalizes — because that scale is
   compared in three independent places: the store, the engine gate, the
   bridge gate (see Quality seam).

### Reusability verdict (component by component)

| Component | Verdict | Why |
|---|---|---|
| `waves/matching.py` | **Reusable as-is** | Matches strings/dicts only; module docstring says so (matching.py:8-18) and no tidalapi import exists. Apple Music keys feed `presence_key`/`track_key` unchanged. |
| `waves/library_index.py` | **Reusable as-is** | Local tags only; "no Qt and no tidalapi" (library_index.py:20). |
| `waves/mb_arbiter.py` | **Reusable as-is** | MusicBrainz arbitration over strings/ints, "no Qt and no tidalapi" (mb_arbiter.py:32). |
| `waves/ownership.py` | **Reusable, small touch** | Pure sqlite (ownership.py:13). Touchpoint: `QUALITY_RANK` tier vocabulary (ownership.py:33) and track-id namespacing (ownership.py:107-123, 170-252). |
| `waves/lyrics.py` (LRCLIB) | **Reusable as-is** | Plain requests against lrclib.net; provider-independent (lyrics.py:24, 120-161). |
| `waves/metadata.py` (tag writer) | **Reusable as-is** | `Metadata` is a plain container (metadata.py:135-234); only its tag *names* encode TIDAL identity (see Ownership seam). |
| Segment/file pipeline: `_download_segment(s)`, `_segments_merge`, `_stage_and_swap`, `_move_file`, claims/ledgers, symlinks, m3u8 writer | **Reusable as-is** | Operates on URLs and paths, no provider types (download.py:822-1200, 3493-3636). The keep-alive pool `pooled_session` is generic (download.py:436-458). |
| ffmpeg post-processing (`_video_convert`, `_extract_flac`, `_faststart_remux`, `_downsample_audio`) | **Reusable as-is** | Container-level, no provider types (download.py:4629-4819). |
| `waves/progress.py`, `waves/poolgauge.py`, `waves/worker.py` | **Reusable as-is** | Generic infra. |
| `Download.item()`/`items()` orchestration | **Reusable after signature change** | Flow and fan-out are generic; the signatures and internals name tidalapi types and the `Tidal` singleton (download.py:1249-1264, 3999-4010, 513-543). |
| `waves/config.py` session layer | **TIDAL-specific** | `Tidal` class wraps a `tidalapi.Session`, PKCE, Atmos credential swap (config.py:424-695). Apple needs its own session/token class behind a shared `BaseConfig` persistence base (config.py:59-172, reusable). |
| `waves/helper/tidal.py`, `helper/folders.py`, `helper/path.py` | **TIDAL-specific** | The whole catalog-object adapter layer (helper/tidal.py:1-352); folder tree (helper/folders.py:1-34); `format_path_media` reads tidalapi attributes (helper/path.py:18-19). |
| Browse/editorial pages | **TIDAL-specific** | `tidalapi.page` (backend.py:39, 6052-6204); no Apple equivalent — becomes provider-optional. |
| `backend.py` dict builders & queue rows | **Shape already provider-neutral** | QML only ever sees plain dicts (backend.py:4311-4437, 7619-7704); tier words and labels are the residual coupling (see Queue/Settings seams). |
| QML `Main.qml` | **Nearly clean** | Hardcodes the four TIDAL tier words + ATMOS/VIDEO in the badge color/spec functions (Main.qml:1736-1748) and "My Tidal" labels (e.g. Main.qml:1785, 1957). |
| QML `SettingsPage.qml` | **Clean** | Fully schema-driven from Python (SettingsPage.qml:9-10); per-provider settings ride the schema for free. |

---

## Seam inventory

### 1. Session / auth

| Touchpoint | What it assumes |
|---|---|
| `waves/config.py:424-461` | `class Tidal` singleton owns a `tidalapi.Session`, PKCE client pairs, `stream_lock`, `is_atmos_session`; token persisted to `token.json` via `ModelToken` (`model/cfg.py:282-286`). |
| `waves/config.py:399-421` | `harden_api_session(session)` mounts the retry/timeout adapter on the tidalapi session's inner `requests.Session`. Policy constants `_API_RETRY_*` (config.py:259-286) are TIDAL-429-tuned. |
| `waves/config.py:467-475` | `settings_apply()` writes `tidalapi.Quality` / `VideoQuality` onto the session. |
| `waves/config.py:477-536` | `login_token` (`load_oauth_session`), `login_finalize`, `token_persist` (+0600 chmod). |
| `waves/config.py:569-650` | Atmos credential swap (`switch_to_atmos_session` / `restore_normal_session`) — deeply TIDAL-specific client-id machinery. |
| `waves/config.py:652-695` | `login` (PKCE prompt), `logout` (deletes session object), `is_authentication_error` (string sniffing). |
| `waves/config.py:292-322, 348-382` | Thread-local abort-event plumbing into the tidalapi retry ladder (`api_waits_wake_for`, `_ApiRetry.sleep`). Reusable pattern; mounted per provider session. |
| `waves/waves_ui/backend.py:4452-4477` | `_reset_tidal_session` rebuilds `tidalapi.Session`, re-hardens, restores Atmos state — the GUI knows the session's internals. |
| `waves/waves_ui/backend.py:4479-4496` | `beginLogin` slot → `session.pkce_login_url()`. |
| `waves/waves_ui/backend.py:4497-4547` | `completeLogin` slot → `pkce_get_auth_token`, `process_auth_token`, `login_finalize`. |
| `waves/waves_ui/backend.py:4549-4650` | `logout` slot: `stopAll()` → `tidal.logout()` → `_reset_tidal_session()` → wipe every per-account cache (`_lib_cache`, `_browse_pages`, `_fav_ids`, …). Cache wipe list is account-scoped, provider-neutral in shape. |
| `waves/waves_ui/session.py` | app-session glue (window state etc.), not provider-bound. |

### 2. Catalog metadata shapes (objects → strings)

The UI never sees tidalapi objects: every row is a plain dict. The conversion
layer is where a second provider plugs in.

| Touchpoint | What it assumes |
|---|---|
| `waves/waves_ui/backend.py:4311-4332` `_album_dict` | album attrs: `id`, title, album artist, `duration` seconds, `num_tracks`/`num_videos` (`backend.py:2183` `_track_count`), `explicit`, `popularity` (2187), `user_date_added` (2079). |
| `waves/waves_ui/backend.py:4334-4357` `_track_dict` | track attrs: `track_num`, `volume_num`, `duration`, album stub, `explicit`. |
| `waves/waves_ui/backend.py:4359-4382` `_video_dict` | video attrs + `(width,height)` stills (2001-2012). |
| `waves/waves_ui/backend.py:4384-4426` `_playlist_dict` / `_folder_dict` | playlist attrs + TIDAL playlist *folders* (kind "folder", `path`, `plCount`). |
| `waves/waves_ui/backend.py:4428-4437` `_mix_dict` | Mix: `sub_title`/`short_subtitle` — TIDAL-only concept. |
| `waves/waves_ui/backend.py:4995` `_top_hit_dict` | TIDAL search's single "top hit". |
| `waves/waves_ui/backend.py:1982-1998` `_image` | `obj.image(dimension)` contract; artist art limited to 160/320/480/750. |
| `waves/waves_ui/backend.py:2015-2032` `_artist_roles`, `_artist_popularity` | `roles` list; raw `artists/{id}` request for popularity. |
| `waves/waves_ui/backend.py:2035-2063` `_release_obj/_year/_release_date` | `release_date` + tidal-specific `tidal_release_date` fallback. |
| `waves/waves_ui/backend.py:2162-2212` `_quality_label`, `_track_count`, `_popularity`, `_artist_id` | `media_metadata_tags`, `audio_quality`, `num_tracks`, `artist.id`. |
| `waves/waves_ui/backend.py:2243-2320` `_all_playlist_items`, `_primary_artist_name` | playlist `.items()` paging; first-artist convention. |
| `waves/waves_ui/backend.py:3022` `_artists_list` | multi-credit list shape. |
| `waves/helper/tidal.py:16-105` | name builders over tidalapi `Track/Video/Album` (`artists`, `album.artists`, `Role.main` filter, `full_name` vs `title`). |
| `waves/helper/tidal.py:108-148` | `get_tidal_media_id/_type`, URL cleanup — TIDAL share-URL grammar. |
| `waves/helper/tidal.py:198-262` | `items_results_all` / `paginate_results` — collection enumeration incl. Mix `.items()`, artist `.get_albums/.get_ep_singles`. |
| `waves/helper/tidal.py:230-238` | `all_artist_album_ids` — discography scan. |
| `waves/helper/tidal.py:265-309` | `user_media_lists` — favorites playlists + playlist *folders* + mixes categories. |
| `waves/helper/tidal.py:312-332` | `instantiate_media(session, type, id)` — the id→object resolver the engine and `_open_url` both use. |
| `waves/helper/tidal.py:348-352` | `favorite_function_factory` + `constants.py:115-121 FAVORITES` (method names on `session.user.favorites`). |
| `waves/helper/folders.py:1-34` | TIDAL v2 playlist-folder tree sweep (`{folder_path}` template support). |
| `waves/download.py:3772-3925` `metadata_write` | the tag-writing fact pull: `track.copyright/.isrc/.explicit/.bpm/.key/.key_scale/.share_url/.volume_num/.track_num`, `album.available_release_date/.release_date/.num_tracks/.num_volumes/.upc/.type`, `album.image(int(dim))`, artists list. **This is the de-facto "track facts" schema.** |
| `waves/download.py:3891-3894` | ReplayGain values read off the tidalapi `Stream` object (`album_replay_gain` etc.). |
| `waves/download.py:3927-3997` `metadata_write_video` | video facts + `video.image(1080,720)`. |
| `waves/model/gui_data.py:23-35` | `ResultItem` (position/artist/title/album/duration/quality/explicit/dates) — legacy shape, provider-neutral. |

### 3. Search

| Touchpoint | What it assumes |
|---|---|
| `waves/helper/tidal.py:151-195` | `search_results_all`: `session.search(models=…)`, 300/page, accumulates `top_hit`. |
| `waves/waves_ui/backend.py:4826-4934` `search()` slot | one-page fetch (4871), bucket caps (artists 60/albums 40/tracks 60/videos 30/playlists 20/mixes 20), `searchResults.emit(payload)`; payload key set is the **provider-neutral contract** with QML. |
| `waves/waves_ui/backend.py:4749-4824` `_open_url` | pasted TIDAL share URL → `get_tidal_media_type/_id` → `instantiate_media` → same payload shape. |
| `waves/waves_ui/backend.py:11121` | secondary `session.search(models=[Track], limit=10)` (artist-credit resolution). |
| `waves/waves_ui/backend.py:3507-3511` | search generation + cache keyed on needle — reusable. |

### 4. Quality tiers

| Touchpoint | What it assumes |
|---|---|
| `waves/constants.py:4` | `Quality` imported from tidalapi; `constants.py:76-83` `QualityVideo` (360…1080). |
| `waves/model/cfg.py:50-52` | Settings store `quality_audio: Quality` (serialized enum) and `download_dolby_atmos`. |
| `waves/helper/tidal.py:335-345` | `quality_audio_highest`: `media_metadata_tags` (HIRES_LOSSLESS/LOSSLESS) → tier. |
| `waves/waves_ui/backend.py:2093-2105` | `_tier_word` folds tier spellings to the UI's four words. |
| `waves/waves_ui/backend.py:1044-1061` | `_stream_quality`: delivered snapshot `{tier, audio_mode, bit_depth, sample_rate, codecs}` from a `Stream`/`StreamManifest`. |
| `waves/waves_ui/backend.py:1100-1118` | `_advertised_ceiling`: `media_metadata_tags` → best rank now. |
| `waves/waves_ui/backend.py:1144-1248` | `_copy_is_current`: the whole upgrade-convergence gate on tier ranks + Atmos mode + `degraded_tries`. |
| `waves/waves_ui/backend.py:2162-2181, 2432-2457` | `_quality_label` / `_quality_rank` on catalog rows (merge edition ranking uses 2432). |
| `waves/waves_ui/backend.py:7575-7614` | `_queued_quality_value` / `_job_quality` / `_target_tier` — per-row quality pinning as a plain tier string. |
| `waves/waves_ui/backend.py:8016-8080` | `_target_quality_rank` (9081 variant) and `_would_refetch_atmos` for button/verdict agreement. |
| `waves/waves_ui/backend.py:332-338` | `_CHOICE_FIELDS` binds `quality_audio` to tidalapi `Quality` for the settings round-trip. |
| `waves/waves_ui/backend.py:14193-14205` | `applySettings`: quality change → `tidal.settings_apply()` + `ownershipChanged` (tier vocabulary change invalidates badges). |
| `waves/config.py:472, 640` | session quality apply (also 10777-10791: preview pins `Quality.low_96k` then restores). |
| `waves/download.py:1257-1258, 4007-4008, 3213-3242` | `item()`/`items()` take `Quality`/`QualityVideo`; `adjust_quality_audio/video` swap session tiers around a job. |
| `waves/download.py:2585-2599` | Atmos decision (`audio_modes`, `AudioMode.dolby_atmos`) inside stream resolution. |
| `waves/ownership.py:26-33` | `QUALITY_RANK` — the canonical rank scale every tier string must join. |
| `waves/waves_ui/qml/Main.qml:1736-1748` | QML hardcodes tier words + specs: `HI-RES`/`LOSSLESS`/`HIGH`/`LOW`/`ATMOS`/`VIDEO` → colors and "24-bit"/"16/44.1"/"AAC 320"/"AAC 96". |

### 5. Download pipeline

| Touchpoint | What it assumes |
|---|---|
| `waves/download.py:35-45` | engine imports tidalapi classes & exceptions wholesale. |
| `waves/download.py:513-543` | `Download.__init__(tidal_obj: Tidal, …)`; `self.session = tidal_obj.session`. |
| `waves/download.py:1249-1374` `item()` | per-track orchestration; params `media_type: MediaType`, `quality_audio: Quality`. |
| `waves/download.py:1376-1493` | `_validate_and_prepare_media` / `_resolve_media`: `instantiate_media`, `Track.album` re-fetch (1648-1675 `_track_with_album`), `allow_streaming` semantics (TIDAL-specific false-negative rule, 1461-1470). |
| `waves/download.py:130-173, 2540-2563` | TIDAL refusal taxonomy: `TooManyRequests/ObjectNotFound/StreamNotAvailable/AssetNotAvailable`, `subStatus` 11000-11999 auth family, `_tidal_refuses_asset` body sniffing. A second provider needs an equivalent "refusal vs failure" mapping. |
| `waves/download.py:2345-2447` | quality adjust + `_download_and_process_media` (extension correction, post-stream skip). Generic except stream fetch. |
| `waves/download.py:2449-2616` | `_get_stream_info` / `_get_track_stream_info`: `stream_lock` Atmos serialization, `track.get_stream()` → `StreamManifest` → extension/codecs/FLAC-extract decision, `is_bts`. **The core TIDAL seam.** |
| `waves/download.py:696-1200` | URL extraction + segment download/merge/gauge — generic given URLs. |
| `waves/download.py:1495-1640` | pace/rate-limit machinery keyed to TIDAL 429 behavior; settings `api_rate_limit_*` (`model/cfg.py:159-160`). |
| `waves/download.py:284-340` | `_waves_item_id` / `_artist_ids` / `_waves_owned_ids` — identity ids off tidalapi objects (incl. `waves_identity_id` merge convention). |
| `waves/download.py:3999-4220` `items()` | collection fan-out: `items_results_all(media)` enumeration, `isinstance(media, Album)` for the m3u sort, template build via `format_path_media`. |
| `waves/download.py:4221-4410` | `_execute_collection_downloads`/`_process_download_futures` — generic thread fan-out + tallies (`ok/fail/unavailable`, list size hook 4078). |
| `waves/download.py:4089-4129` | `_playlist_for_collection` → `playlist_populate` (4411+) m3u8 writer — generic. |
| `waves/model/downloader.py:5-24` | `TrackStreamInfo`/`DownloadSegmentResult` carry tidalapi `Stream`/`StreamManifest` types. |
| `waves/waves_ui/backend.py:1251-1440` `_TrackedDownload` | subclass overriding hooks (`_note_*`), per-thread skip override, ownership/claim injection, tallies — engine protocol is method overrides, provider-neutral in shape. |
| `waves/waves_ui/backend.py:9319-9345` `_build_download` | constructs the engine with `tidal_obj=self.tidal` and injects `ownership_of`/`target_rank`/`pinned_quality`/`library_claim`. |
| `waves/waves_ui/backend.py:10340-10368` | job dispatch: `dl.items(...)` / `dl.item(...)` with the cached tidalapi object. |
| `waves/waves_ui/backend.py:10520-10580` `_download_merge_plan` | best-of-both fan-out via `dl.item(keep_album=True, …)` + `_as_member_of` (3001) re-tagging — TIDAL-edition concept, but mechanical. |

### 6. Lyrics

| Touchpoint | What it assumes |
|---|---|
| `waves/lyrics.py:1-161` | LRCLIB client — **provider-agnostic**, reusable as-is. |
| `waves/download.py:3727-3770` `_retrieve_lyrics` | LRCLIB first (facts pulled off tidalapi track), then `track.lyrics()` TIDAL fallback — the one provider call. |
| `waves/model/cfg.py:21, 180-184` | `lyrics_prefer_lrclib` setting; help text names TIDAL as fallback. |

### 7. Artwork

| Touchpoint | What it assumes |
|---|---|
| `waves/download.py:3838-3849` | embedded cover via `album.image(int(dim))`, ORIGIN capped to 1280 for tag size. |
| `waves/download.py:3699-3725` | separate `cover.jpg` sizing (`CoverDimensions` resolution, `_album_cover_file_data` re-fetch at `track.album.image(...)`). |
| `waves/download.py:3638-3697` | `cover_data`/`cover_data_cached` — generic URL fetch + per-job LRU cache (569-572). |
| `waves/constants.py:92-98` | `CoverDimensions` = TIDAL's square sizes 80…1280/origin; `model/cfg.py:85-90` settings bound to it. |
| `waves/waves_ui/backend.py:1982-2012` | `_image(obj, dim)` / `_video_image(w,h)`; artist art size set (160/320/480/750). |
| `waves/download.py:3957-3962` | video thumbnail `video.image(1080, 720)`. |

### 8. Ownership / library detection

| Touchpoint | What it assumes |
|---|---|
| `waves/ownership.py:85-130` | store keyed `(track_id, path)`; collection membership table. Ids are provider-implicit. |
| `waves/ownership.py:26-33, 79-82` | tier→rank scale (`QUALITY_RANK`). |
| `waves/metadata.py:70-82, 85-132` | on-disk identity tags `WAVES_TIDAL_ID`, `WAVES_TIDAL_ARTIST_ID`, `WAVES_TIDAL_ALBUM_ARTIST_ID` + `read_item_id`. **The contract between downloads and ownership checks.** |
| `waves/download.py:1816-1898` `_existing_same_item_at` | skip/replace arbitration by reading id tags of occupants (incl. `_01.._99` variants). |
| `waves/download.py:1900-2034` | `_is_own_copy` / `_already_landed_here` / run-ledger twins. |
| `waves/download.py:343-369` | `_file_audio_mode_is_atmos` — Atmos vs stereo file discrimination (codec sniff). |
| `waves/waves_ui/backend.py:1144-1248` | `_copy_is_current` gate (tier ranks, ceilings, degraded tries). |
| `waves/waves_ui/backend.py:1580-1700` | `_TrackedDownload` ownership gate: `self._ownership_of(str(media_id))` → skip/upgrade decision; library tag claim (`_library_claim`) consulted after (1685-1690). |
| `waves/waves_ui/backend.py:1121-1133` | `_record_names_a_broken_copy` — historical path-format guard (TIDAL-era artifacts). |
| `waves/matching.py` | all presence matching — strings only, provider-agnostic (see verdict). |
| `waves/library_index.py` | local scan — reusable as-is. |
| `waves/waves_ui/bridge_library.py:264-341, 1018-1104, 1215-1289` | presence indexes built from scan; `libraryAlbumPresence`/`libraryTrackPresence` slots take plain strings; `_library_claims_album(album)` reads only names/counts off the tidalapi object — adapter-grade coupling. |
| `waves/mb_arbiter.py` | third-party arbitration for unproven matches — reusable as-is. |

### 9. Queue presentation

| Touchpoint | What it assumes |
|---|---|
| `waves/waves_ui/backend.py:2666-2683` | `_JobSpec` carries the raw catalog `obj` (a tidalapi object) until the job starts. |
| `waves/waves_ui/backend.py:7619-7704` `_enqueue` | row dict — provider-neutral fields; `quality`/`askQuality`/`expected` are tier strings, `art` a URL. |
| `waves/waves_ui/backend.py:7575-7614` | tier pinning read/written as plain strings (`Quality(raw)` only at job build). |
| `waves/waves_ui/backend.py:9969-10132` `_download` | funnel from any button: uses `_primary_artist_name(obj)`, `_track_count(obj)`, `_quality_label(obj)`, `_image(obj,160)` — the object-adapter quartet. |
| `waves/waves_ui/backend.py:10134-10222, 10340-10368` | pump/start/dispatch (calls `dl.items`/`dl.item`). |
| `waves/model/gui_data.py:44-50` | `QueueDownloadItem` carries tidalapi `Quality` + `QualityVideo` directly (legacy dataclass). |
| `waves/waves_ui/qml/Main.qml:1736-1748` | tier-word → color/spec mapping (see Quality seam). |
| `waves/waves_ui/qml/Main.qml:1785, 1957, 2012` | "My Tidal" nav labels — user-facing provider naming. |
| `waves/waves_ui/backend.py:7242+` | queue history trim / status machine (`queued/running/done/failed/stopped`) — provider-neutral. |

### 10. Settings

| Touchpoint | What it assumes |
|---|---|
| `waves/model/cfg.py:11-161` | `Settings` dataclass: TIDAL-bound fields `quality_audio` (tidalapi enum), `quality_video`, `download_dolby_atmos`; TIDAL-tuned `api_rate_limit_*`; templates whose tokens assume TIDAL semantics (`{folder_path}`, cfg.py:60-62; `{video_year_optional}` "when TIDAL has no release date", cfg.py:68-76). |
| `waves/config.py:181-247` | settings migrations — provider-neutral mechanism. |
| `waves/waves_ui/backend.py:305-358` | `_FLAG_FIELDS` (incl. `download_dolby_atmos`) / `_CHOICE_FIELDS` (incl. `("quality_audio", Quality)`) — the coercion registry a second provider's settings join. |
| `waves/waves_ui/backend.py:858-910` | labels/descriptions keyed by field name (quality_audio help text describes TIDAL tiers verbatim, `model/cfg.py:191-197`). |
| `waves/waves_ui/backend.py:13880-13960` | `settingsSchema()` sections; "Downloads" group lists `quality_audio`, `quality_video`, `download_dolby_atmos`. |
| `waves/waves_ui/backend.py:14193-14205` | quality change side-effects (`tidal.settings_apply()`, badge invalidation, queue not retargeted). |
| `waves/waves_ui/qml/SettingsPage.qml:9-10` | fully schema-driven rendering — **no provider knowledge in QML settings**. |
| `waves/constants.py:6` | `CTX_TIDAL` context string. |
| `waves/config.py:569-650` | Atmos flag's engine side (session swap) as consumed by settings apply. |

### 11. Browse / favorites (adjacent seam, for completeness)

| Touchpoint | What it assumes |
|---|---|
| `waves/waves_ui/backend.py:39, 6052-6204, 6422, 11749` | editorial browse via `tidalapi.page` (`Page`, `PageCategoryV2`, `PageLinks`). |
| `waves/waves_ui/backend.py:5357-5397, 5717-5729` | favorites id sets & listings via `session.user.favorites.*`. |
| `waves/constants.py:101-121` | `TidalLists` enum + `FAVORITES` function-name map. |
| `waves/waves_ui/qml/Main.qml:789-888` | Browse page cache keyed by TIDAL api paths. |

---

## What the design should take from this

1. **The dict boundary is the real seam.** Everything QML-facing is already
   plain dicts with string ids and URL strings (search payload, result-row
   dicts, queue rows). A provider that emits those dicts needs no QML work
   beyond the tier-word vocabulary (Main.qml:1736-1748) and label strings.
2. **The engine's `item()`/`items()` flow, file pipeline, ffmpeg steps,
   claims/ledgers, m3u writer, ownership store, matching brain and LRCLIB
   client are genuinely reusable.** The tidalapi coupling concentrates in:
   stream resolution (`_get_stream_info`), the `Tidal` session singleton, the
   catalog-attribute adapters (helper/tidal.py + backend dict builders +
   `metadata_write`'s fact pull), the tier vocabulary, and the refusal
   taxonomy.
3. **Three cross-cutting vocabularies must be shared or generalized:**
   item ids (ownership rows + WAVES_TIDAL_* tags + `_objs` buckets),
   quality tiers (`QUALITY_RANK` scale, threaded through 10+ sites),
   media types (`MediaType` enum — already shared, but `MIX`/video handling
   is TIDAL-shaped).
4. **Biggest coupling surprises found:**
   - `metadata_write` (download.py:3772) is the *implicit* provider fact
     schema — it reads ~15 tidalapi attributes inline rather than through any
     helper, so a second provider cannot reuse the tagging step without
     extracting that fact pull.
   - The Atmos machinery (credential swap in config.py, `stream_lock`
     tollbooth in download.py:2463-2485, mode-aware ownership gate in
     backend.py:1144-1248) is TIDAL-only and must be fenced behind the
     interface, not generalized away.
   - Quality pinning is stored as a *plain tier string* on queue rows
     (backend.py:7674-7679) and re-parsed to `Quality` at job build
     (backend.py:7586-7596) — a second provider's tiers must be parseable by
     the same row field or the field must become provider-qualified.
   - `harden_api_session` + the thread-local abort plumbing
     (config.py:292-421) are valuable and generic in concept but mounted
     directly on the tidalapi session's inner requests session; a shared
     "harden this requests session" helper would carry over.
