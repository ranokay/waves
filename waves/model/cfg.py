from dataclasses import dataclass, field

from dataclasses_json import config, dataclass_json

from waves.constants import CoverDimensions, DownsampleTarget, InitialKey, MetadataTargetUPC, QualityVideo


@dataclass_json
@dataclass
class Settings:
    skip_existing: bool = True
    lyrics_embed: bool = False
    # Best-quality lyrics out of the box (issue #59): sidecars on, so a track
    # keeps its finest timed source next to it -- .lrc on both providers, plus
    # the verbatim .ttml on Apple (lyrics_ttml_file below). Embedding stays
    # opt-in per provider.
    lyrics_file: bool = True
    # When saving lyrics files: timed lyrics go to .lrc, untimed to .txt.
    # This switch skips the .txt entirely so only synced lyrics produce a file.
    lyrics_file_synced_only: bool = False
    # Try LRCLIB (lrclib.net, community-synced lyrics) before TIDAL's own
    # lyrics, which are machine-transcribed for tracks nobody has submitted
    # text for yet. TIDAL remains the fallback when LRCLIB has no match.
    lyrics_prefer_lrclib: bool = True
    # Word-timed source (issue #34, spec section 9.1): on Apple, syllable TTML
    # outranks a line-timed LRCLIB hit when on (default on). TIDAL has no
    # word-timed source, so this is a no-op there.
    lyrics_word_timed: bool = True
    # Verbatim Apple TTML sidecar (issue #34, spec section 9.1): saved exactly
    # as Apple serves it, zero conversion, sidecar-only (never embedded).
    # Apple only; default on (issue #59: best quality). TIDAL has no TTML source.
    lyrics_ttml_file: bool = True
    # Per-provider lyrics & artwork (issue #61): each provider keeps its own
    # options inside its Providers card, so what TIDAL embeds need not match
    # what Apple files. Fresh installs start both mirrors at the shared best
    # defaults; existing installs are migrated once (config._migrate_settings
    # copies the shared values into both mirrors). The word-timed and TTML
    # mirrors exist on TIDAL too for a uniform table, but stay inert there
    # (TIDAL has no word-timed or TTML source); raw cover bytes fall back to
    # jpg on TIDAL, which has no original-master sidecar.
    tidal_lyrics_embed: bool = False
    tidal_lyrics_file: bool = True
    tidal_lyrics_file_synced_only: bool = False
    tidal_lyrics_prefer_lrclib: bool = True
    tidal_lyrics_word_timed: bool = True
    tidal_lyrics_ttml_file: bool = True
    tidal_metadata_cover_dimension: CoverDimensions = CoverDimensions.PxORIGIN
    tidal_metadata_cover_file_dimension: str = "follow"
    tidal_metadata_cover_embed: bool = True
    tidal_cover_album_file: bool = True
    tidal_cover_single_track_file: bool = False
    tidal_cover_file_format: str = "raw"
    apple_lyrics_embed: bool = False
    apple_lyrics_file: bool = True
    apple_lyrics_file_synced_only: bool = False
    apple_lyrics_prefer_lrclib: bool = True
    apple_lyrics_word_timed: bool = True
    apple_lyrics_ttml_file: bool = True
    apple_metadata_cover_dimension: CoverDimensions = CoverDimensions.PxORIGIN
    apple_metadata_cover_file_dimension: str = "follow"
    apple_metadata_cover_embed: bool = True
    apple_cover_album_file: bool = True
    apple_cover_single_track_file: bool = False
    apple_cover_file_format: str = "raw"
    # One-time marker for the shared-to-mirror migration above. Once set, the
    # migration leaves both mirrors alone, so each provider's choices stand.
    lyrics_art_per_provider_migrated: bool = False
    # One tag template for every provider (issue #61): with the custom switch
    # off ("Provider default") every file carries what its provider supplies
    # (plus the long-standing gates below); with it on, the tag groups
    # switched off here are omitted. Lyrics and cover embedding are NOT
    # template tags: the per-provider embed toggles above are their single
    # source of truth, so no template tag duplicates them.
    metadata_custom: bool = False
    metadata_tag_composer: bool = True
    metadata_tag_copyright: bool = True
    metadata_tag_isrc: bool = True
    metadata_tag_bpm: bool = True
    metadata_tag_initial_key: bool = True
    metadata_tag_upc: bool = True
    use_primary_album_artist: bool = (
        False  # When True, uses first album artist instead of track artists for folder paths
    )
    # TODO: Implement API KEY selection.
    # api_key_index: bool = 0
    # TODO: Implement album info download to separate file.
    # album_info_save: bool = False
    video_download: bool = True
    # TODO: Implement multi threading for downloads.
    # multi_thread: bool = False
    download_delay: bool = True
    # No default download folder: the user must choose one explicitly. A fresh
    # install starts blank and the first download is gated until a folder is set
    # (so nobody silently downloads into a folder they can't find). Existing
    # installs keep whatever they persisted, including the old "~/download".
    download_base_path: str = ""
    # One-time flag for the soft "you're still on the old default folder" nudge
    # shown to existing users who never changed "~/download". Set once the nudge
    # is shown or dismissed so it never nags again.
    download_folder_prompted: bool = False
    # Where each network volume the download folder has lived on came from:
    # {"/Volumes/Media": "smb://user@nas/Media"}, recorded while the share is
    # healthy (statfs, see waves_ui/netmount.py). When macOS quietly ejects
    # the share, this is what lets the app mount it back the way Finder
    # would, instead of watching a path that cannot return by itself. Origin
    # URLs are identity (host, maybe user): internal only, never shown in the
    # settings UI, registered as diagnostics secrets on load and on record.
    network_mount_origins: dict[str, str] = field(default_factory=dict)
    # The audio-quality settings, one per provider (issue #24, spec §9.2),
    # each stored as a Waves tier string (waves.constants.QualityTier values:
    # "LOW", "HIGH", "LOSSLESS", "HI_RES_LOSSLESS") -- never an engine enum.
    # Both default to the highest rung (issue #59): anything the provider can
    # serve is fetched. Apple has no LOW rung (AAC 256 starts at HIGH).
    tidal_quality_audio: str = "HI_RES_LOSSLESS"
    apple_quality_audio: str = "HI_RES_LOSSLESS"
    # Apple Music ships as a user-enabled provider (spec ground rule 3), off
    # by default and opt-in from Settings. Search reads this now. Setup,
    # Chooser and download routing join it in their own rollout slices.
    apple_enabled: bool = False
    # Cookies-tier scaffolding (issue #28; superseded by the setup-wizard
    # ticket): path to a Netscape-format cookies export from a logged-in
    # music.apple.com session. Unlocks AAC 256 + Atmos downloads, no runtime.
    apple_cookies_path: str = ""
    # Same scaffolding shape as the FFmpeg override below: the N_m3u8DL-RE
    # binary Apple downloads fetch through. Empty means PATH; the wizard
    # provisions and pins it later.
    path_binary_nm3u8dlre: str = ""
    # Setup wizard (issue #31, spec section 2 and 10): the user-supplied Apple
    # Music APK the full tier's wrapper guest needs. Waves never fetches,
    # bundles, mirrors, or proxies it; the wizard verifies the pinned
    # version by SHA-256 and scripts the .apkm extraction.
    apple_apk_path: str = ""
    # Wrapper HTTP API port (spec section 2 wizard fuel): 0 means Waves picks
    # a free high port at setup time and passes it explicitly everywhere.
    # Never 80: that default is collision-prone on a desktop. A nonzero
    # value is a config-first override for a port the user knows is free.
    apple_wrapper_port: int = 0
    # Integrity gate (issue #30, spec §6): always-on Apple verification knobs.
    # Retries counts AUTOMATIC re-downloads after an integrity failure (2 means
    # 3 attempts total); the outbreak pre-filter (Encoded date >= 2025-05)
    # quarantines after 1 retry. Pacing between integrity retries.
    apple_integrity_retries: int = 2
    apple_integrity_retry_delay_sec: float = 5.0
    # Session supervision + pacing (issue #33, spec §3): proactive Apple
    # pacing, same shape as TIDAL's api_rate_limit_* (pause after N songs
    # for N seconds; initial 30 s every 25 songs, fully tunable), and the
    # idle timeout after which the supervised sidecar stops itself
    # (initial 5 minutes, Advanced-tunable).
    apple_pacing_batch_size: int = 25
    apple_pacing_delay_sec: float = 30.0
    apple_wrapper_idle_sec: float = 300.0
    # Quarantine: where persistently-bad Apple files land. Empty means the
    # default "Waves Quarantine" folder inside the download folder; a set value
    # is the full folder path. The folder is always excluded from the library
    # scan, so a quarantined file never badges IN LIBRARY.
    apple_quarantine_dir: str = ""
    # Keep vs delete for quarantined files, default keep. Delete still marks
    # the skip-list; it just keeps no bytes.
    apple_quarantine_keep: bool = True
    quality_video: QualityVideo = QualityVideo.P480
    # The Chooser one-click audio default (issue #66, spec §7.2): "stereo", or
    # "both" for stereo + Atmos side by side where a track offers the choice.
    # Replaces the old Download-Dolby-Atmos toggle one for one (on = both);
    # Atmos-alone has no Settings spelling and stays per-click only.
    default_audio_type: str = "stereo"
    # Artist > Album > Track, the shape a music library (and Plex) expects.
    # Playlists / mixes keep their own parent folder: they are platform
    # constructs a library manager can't model, but stay downloadable.
    # {provider_name} keeps each provider's files apart (issue #65: "Tidal",
    # "Apple Music"), so the same song saved from both coexists.
    format_album: str = (
        "{provider_name}/{artist_name}/[{album_year}] {album_title}{album_explicit}/{track_volume_num_optional}"
        "{album_track_num}. {artist_name} - {track_title}{track_explicit}"
    )
    # {folder_path} mirrors the playlist's TIDAL folder tree on disk (empty for
    # playlists not in a folder, so those land exactly where they always did).
    format_playlist: str = "Playlists/{folder_path}{playlist_name}/{list_pos}. {artist_name} - {track_title}"
    format_mix: str = "Mix/{mix_name}/{artist_name} - {track_title}"
    format_track: str = (
        "{provider_name}/{artist_name}/[{album_year}] {album_title}{album_explicit}/{track_volume_num_optional}"
        "{album_track_num}. {artist_name} - {track_title}{track_explicit}"
    )
    # Where Dolby Atmos Versions land (§5.4, issue #29): a folder fragment
    # rendered with the same tokens as the file templates, inserted between
    # the stereo file's folder and its name. Default "Dolby Atmos" gives the
    # Plex-friendly separate-subfolder layout zero-config; blank places Atmos
    # alongside stereo, where collisions fall to the numbered-copy machinery.
    format_atmos: str = "Dolby Atmos"
    # Videos keep their own top-level pool (Plex and friends do not model
    # music videos inside a music library's artist folders), organized per
    # artist with the release year leading the file name so a plain file
    # explorer sorts them chronologically. {video_year_optional} dresses
    # itself ("[2026] ", or nothing when TIDAL has no release date).
    # {artist_name_primary} keeps ONE folder per artist: the full join would
    # mint a fresh "A, B, C" folder for every collab. The full credit list
    # still lives in the file's metadata (and usually the title's feat.).
    format_video: str = "Videos/{artist_name_primary}/{video_year_optional}{track_title}{track_explicit}"
    video_convert_mp4: bool = True
    path_binary_ffmpeg: str = ""
    # Read-only diagnostic, written by the app, never edited in the Settings UI:
    # which ffmpeg a download would actually use, as a CATEGORY only (never a
    # path). "custom" (user override), "managed" (bundled copy), "system" (found
    # on PATH) or "none". Lets a pasted config reveal the ffmpeg situation, since
    # path_binary_ffmpeg stays "" for both the managed and the absent cases.
    ffmpeg_source: str = "unknown"
    # Original quality by default (issue #59): the true master image on both
    # providers (TIDAL's ORIGIN keeps its embedded cap; Apple's ORIGIN is the
    # original-master image). The separately-saved file follows this size.
    metadata_cover_dimension: CoverDimensions = CoverDimensions.PxORIGIN
    # Size of the separately-saved cover.jpg. The sentinel "follow" means "match
    # the embedded cover size above" (the historical behaviour); any other value
    # is a CoverDimensions member name (e.g. "Px640", "PxORIGIN") applied only to
    # the saved file, so the embedded art and the on-disk cover can differ.
    metadata_cover_file_dimension: str = "follow"
    metadata_cover_embed: bool = True
    # Sidecar cover format (issue #34, spec section 9.1): "raw" (default,
    # issue #59) is the true original-master bytes on Apple, and plain jpg on
    # TIDAL, which has no original-master sidecar (raw falls back to jpg
    # there). "jpg" or "png" force that container on both. Embedded art stays
    # jpg either way.
    cover_file_format: str = "raw"
    mark_explicit: bool = False
    cover_album_file: bool = True
    # Also write cover.jpg when a single track is downloaded on its own (not just
    # as part of a full album). Off by default: the historical behaviour only
    # saved cover.jpg for album/collection downloads.
    cover_single_track_file: bool = False
    extract_flac: bool = True
    # FLAC scope (issue #64): off (default) converts lossless sources only and
    # keeps lossy originals as *.m4a; on also converts lossy (AAC) sources to
    # FLAC by re-encoding them (bigger files, no quality gain). Dolby Atmos
    # always stays *.m4a either way. Needs FFmpeg like extract_flac.
    extract_flac_all: bool = False
    downsample_enabled: bool = False
    downsample_target: DownsampleTarget = DownsampleTarget.BIT16_48
    # Values above the shared HTTP pool size (10 connections) are clamped at
    # download time: extra workers can never hold a socket, they only cost
    # threads and memory.
    downloads_simultaneous_per_track_max: int = 10
    download_delay_sec_min: float = 3.0
    download_delay_sec_max: float = 5.0
    album_track_num_pad_min: int = 1
    downloads_concurrent_max: int = 3
    symlink_to_track: bool = False
    playlist_create: bool = False
    metadata_replay_gain: bool = True
    # Internal upgrade marker (not a user setting, not shown in the UI): records
    # the one-time flip that turned metadata_replay_gain on for configs created
    # before it became the default. Once set, the migration leaves the user's
    # own choice alone.
    replay_gain_default_migrated: bool = False
    # Internal upgrade marker (not a user setting): records the one-time
    # rewrite that added {folder_path} to format_playlist. Only a stored value
    # equal to the OLD default is rewritten; a customized template is left
    # exactly as the user wrote it.
    format_playlist_folder_migrated: bool = False
    # Internal upgrade marker (not a user setting): records the one-time
    # rewrite that prefixed format_album and format_track with the
    # {provider_name} segment (issue #65). Only stored values equal to the OLD
    # defaults are rewritten; customized templates are left exactly as the
    # user wrote them (the token is available for them to add by hand).
    format_provider_segment_migrated: bool = False
    # Internal upgrade marker (not a user setting): records the one-time reset
    # of the two api_rate_limit fields. They were editable in Advanced while
    # nothing read them, so any value on disk was a guess that never took
    # effect and never had a chance to be judged; now that they do take effect,
    # an old guess of, say, 60 seconds would silently add half an hour to a
    # long playlist. Set once, then the user's own choice stands.
    api_rate_limit_wired_migrated: bool = False
    # DOWNLOAD ALL on a Browse playlist category asks before queueing the
    # whole set; the dialog's "Don't ask again" flips this off.
    confirm_category_download: bool = True
    metadata_write_url: bool = True
    window_x: int = 50
    window_y: int = 50
    window_w: int = 1200
    window_h: int = 800
    filename_delimiter_artist: str = ", "
    filename_delimiter_album_artist: str = ", "
    # What to write where a character a filesystem rejects (/, :, ?, ...) is
    # removed from a name. "" (the default) removes it and tidies the spacing.
    # Applies to future downloads only: the engine keeps writing into folders
    # and files that already exist under an older spelling (see
    # Download._keep_existing_layout).
    filename_illegal_replacement: str = ""
    # Per-character stand-ins overriding the one above, {"?": "-", ":": " · "}.
    # A character named here uses its own text (empty means removed outright);
    # every other rejected character follows filename_illegal_replacement. Only
    # characters a file name cannot hold can be named (see
    # helper.path.safe_filename_replacement_map).
    # Empty by default on purpose: constants.DEFAULT_ILLEGAL_MAP holds the
    # recommended table, but an existing library was built under the spelling it
    # already has, so Waves offers that table on the settings page instead of
    # applying it. A brand-new install starts with it (_FIRST_RUN_OVERRIDES).
    filename_illegal_map: dict[str, str] = field(default_factory=dict)
    metadata_target_upc: MetadataTargetUPC = MetadataTargetUPC.UPC
    # Rate limiting for API calls (tweaking variables). See
    # Download._rate_limit_pause: the count is SONGS taken to the API, which is
    # where a long list earns its 429s. Either value at 0 turns the pause off.
    api_rate_limit_batch_size: int = 20  # Songs to download before pausing to stay under TIDAL's rate limit
    api_rate_limit_delay_sec: float = 3.0  # Length of that pause, in seconds
    initial_key_format: InitialKey = InitialKey.ALPHANUMERIC
    # Legacy carrier for the one migration that split quality_audio into the
    # per-provider settings above (issue #24). from_json reads the old key from
    # a pre-split config; _migrate_settings folds its value into
    # tidal_quality_audio and nulls it. The field is excluded from every
    # serialization, so the key leaves settings.json on the first save and the
    # migration is one-time by construction (nothing left to read).
    quality_audio: str | None = field(default=None, metadata=config(exclude=lambda v: True))
    # Legacy carrier for the toggle this replaced (issue #66). from_json reads
    # the old key from a pre-change config; _migrate_settings folds True into
    # default_audio_type "both" (False was the default already) and nulls it.
    # Excluded from every serialization like quality_audio above, so the key
    # leaves settings.json on the first save.
    download_dolby_atmos: bool | None = field(default=None, metadata=config(exclude=lambda v: True))


@dataclass_json
@dataclass
class HelpSettings:
    skip_existing: str = "Skip download if file already exists."
    confirm_category_download: str = (
        "Ask before queueing a whole Browse playlist category with DOWNLOAD ALL. "
        'Turning the dialog off with its "Don\'t ask again" box switches this off; '
        "switch it back on here."
    )
    album_cover_save: str = "Save cover to album folder."
    lyrics_embed: str = "Embed lyrics in audio file, if lyrics are available. Applies to every enabled provider."
    use_primary_album_artist: str = "Use only the primary album artist for folder paths instead of track artists."
    lyrics_file: str = (
        "Save lyrics next to the track: timed lyrics as a *.lrc file, untimed ones as "
        "*.txt. Applies to every enabled provider. Default on."
    )
    lyrics_file_synced_only: str = (
        "Only save a lyrics file when timed (synced) lyrics exist; untimed lyrics then produce no *.txt file."
    )
    lyrics_prefer_lrclib: str = (
        "Fetch lyrics from the community LRCLIB database first (the source behind LRCGet), "
        "falling back to the provider's own lyrics when it has no match. TIDAL's own lyrics are "
        "machine-transcribed for many newer track IDs and often wrong. Applies to every "
        "enabled provider."
    )
    lyrics_word_timed: str = (
        "Prefer word-timed lyrics when Apple serves syllable TTML: the enhanced LRC "
        "outranks a line-timed LRCLIB hit. Default on. No effect on TIDAL, which has "
        "no word-timed source."
    )
    lyrics_ttml_file: str = (
        "Save Apple's verbatim TTML beside the track (zero conversion, sidecar-only, "
        "never embedded). Apple only; default on."
    )
    # Per-provider mirrors (issue #61) share the wording above; the Providers
    # cards name the provider, so the help stays provider-neutral here.
    tidal_lyrics_embed: str = "Embed lyrics in the TIDAL audio file, if lyrics are available."
    tidal_lyrics_file: str = (
        "Save lyrics next to the TIDAL track: timed lyrics as a *.lrc file, untimed ones as *.txt. Default on."
    )
    tidal_lyrics_file_synced_only: str = (
        "Only save a lyrics file when timed (synced) lyrics exist; untimed lyrics then produce no *.txt file."
    )
    tidal_lyrics_prefer_lrclib: str = (
        "Fetch lyrics from the community LRCLIB database first, falling back to TIDAL's own lyrics "
        "when it has no match. TIDAL's own lyrics are machine-transcribed for many newer track IDs "
        "and often wrong."
    )
    tidal_lyrics_word_timed: str = (
        "Prefer word-timed lyrics when served. No effect on TIDAL, which has no word-timed source."
    )
    tidal_lyrics_ttml_file: str = (
        "Save the verbatim TTML beside the track. No effect on TIDAL, which has no TTML source."
    )
    tidal_metadata_cover_dimension: str = (
        "The square dimensions of the cover image embedded into the TIDAL track. Possible values: 80, 160, 320, 640, 1280, origin."
    )
    tidal_metadata_cover_file_dimension: str = (
        "Size of the saved 'cover.jpg' for TIDAL downloads. 'Same as embedded' matches the embedded "
        "cover size; otherwise pick an independent size (80, 160, 320, 640, 1280, origin)."
    )
    tidal_metadata_cover_embed: str = "Embed album cover into the TIDAL file."
    tidal_cover_album_file: str = "Save cover to 'cover.jpg', if a TIDAL album is downloaded."
    tidal_cover_single_track_file: str = "Also save cover.jpg when downloading a single TIDAL track on its own."
    tidal_cover_file_format: str = (
        "Sidecar cover format for TIDAL downloads: jpg or png (raw falls back to jpg, "
        "TIDAL has no original-master sidecar). Embedded art stays jpg."
    )
    apple_lyrics_embed: str = "Embed lyrics in the Apple Music audio file, if lyrics are available."
    apple_lyrics_file: str = (
        "Save lyrics next to the Apple Music track: timed lyrics as a *.lrc file, untimed ones as " "*.txt. Default on."
    )
    apple_lyrics_file_synced_only: str = (
        "Only save a lyrics file when timed (synced) lyrics exist; untimed lyrics then produce no *.txt file."
    )
    apple_lyrics_prefer_lrclib: str = (
        "Fetch lyrics from the community LRCLIB database first, falling back to Apple's own lyrics "
        "when it has no match."
    )
    apple_lyrics_word_timed: str = (
        "Prefer word-timed lyrics when Apple serves syllable TTML: the enhanced LRC outranks a "
        "line-timed LRCLIB hit. Default on."
    )
    apple_lyrics_ttml_file: str = (
        "Save Apple's verbatim TTML beside the track (zero conversion, sidecar-only, never " "embedded). Default on."
    )
    apple_metadata_cover_dimension: str = (
        "The square dimensions of the cover image embedded into the Apple Music track. Possible "
        "values: 80, 160, 320, 640, 1280, origin (the true original-master image)."
    )
    apple_metadata_cover_file_dimension: str = (
        "Size of the saved cover file for Apple Music downloads. 'Same as embedded' matches the "
        "embedded cover size; otherwise pick an independent size (80, 160, 320, 640, 1280, origin)."
    )
    apple_metadata_cover_embed: str = "Embed album cover into the Apple Music file."
    apple_cover_album_file: str = "Save cover beside the download, if an Apple Music album is downloaded."
    apple_cover_single_track_file: str = "Also save cover when downloading a single Apple Music track on its own."
    apple_cover_file_format: str = (
        "Sidecar cover format for Apple Music downloads: raw (default: the true original-master "
        "bytes), jpg, or png. Embedded art stays jpg."
    )
    metadata_custom: str = (
        "Custom tag template: with this off every file carries what its provider supplies "
        "('Provider default'); with it on, the tag groups switched off below are omitted. Lyrics "
        "and cover embedding are not template tags: the per-provider embed toggles decide those."
    )
    metadata_tag_composer: str = "Write the composer tag (Custom template only)."
    metadata_tag_copyright: str = "Write the copyright tag (Custom template only)."
    metadata_tag_isrc: str = "Write the ISRC tag (Custom template only)."
    metadata_tag_bpm: str = "Write the BPM tag (Custom template only)."
    metadata_tag_initial_key: str = "Write the initial-key tag (Custom template only)."
    metadata_tag_upc: str = "Write the UPC tag (Custom template only)."
    api_key_index: str = "Set the device API KEY."
    album_info_save: str = "Save album info to track?"
    video_download: str = "Allow download of videos."
    multi_thread: str = "Download several tracks in parallel."
    download_delay: str = "Activate randomized download delay to mimic human behaviour."
    download_base_path: str = "Where to store the downloaded media."
    tidal_quality_audio: str = (
        'TIDAL audio download quality as a Waves tier string: "LOW" (up to 96 Kbps), "HIGH" (up to '
        '320 Kbps), "LOSSLESS" (up to 16-bit, 44.1 kHz), "HI_RES_LOSSLESS" (up to 24-bit, 192 kHz). '
        "Default: the highest rung."
    )
    apple_quality_audio: str = (
        'Apple Music audio download quality as a Waves tier string: "HIGH" (up to 256 Kbps AAC, Apple '
        'has no LOW), "LOSSLESS" (up to 16-bit, 44.1 kHz ALAC), "HI_RES_LOSSLESS" (up to 24-bit, '
        "192 kHz ALAC). Default: the highest rung."
    )
    apple_cookies_path: str = (
        "Path to a cookies export (Netscape format) from a logged-in music.apple.com browser session. "
        "Unlocks Apple AAC 256 and Atmos downloads without any other setup; the setup wizard replaces "
        "this with a managed sign-in later."
    )
    path_binary_nm3u8dlre: str = (
        "Path to the N_m3u8DL-RE binary Apple downloads fetch through. Only necessary if it is not "
        "on $PATH; the setup wizard provisions it later."
    )
    apple_apk_path: str = (
        "Optional Apple Music APK path for custom wrapper image builds. The published image already "
        "carries the guest libraries, so the normal setup never asks for one; set this only when you "
        "build your own image and want Waves to verify the APK you used. Waves never downloads this "
        "file for you."
    )
    apple_wrapper_port: str = (
        "Port the Apple wrapper's HTTP API runs on. 0 (the default) means Waves picks a free high port "
        "at setup time; the port-80 default is never used because it collides on desktops."
    )
    apple_integrity_retries: str = (
        "How many times an Apple track that fails its integrity check is automatically re-downloaded "
        "before it is quarantined (2 means 3 attempts total). Outbreak-era files (Encoded date "
        "2025-05 or later) quarantine after 1 retry. Verification proves ffmpeg-decodability, "
        "not bit-perfect fidelity."
    )
    apple_integrity_retry_delay_sec: str = "How long to wait between Apple integrity retries, in seconds."
    apple_pacing_batch_size: str = (
        "How many Apple songs to download before pausing, so a long run does not ask Apple too much at once. "
        "0 never pauses."
    )
    apple_pacing_delay_sec: str = "How long that Apple pause lasts, in seconds. 0 never pauses."
    apple_wrapper_idle_sec: str = (
        "How long the Apple wrapper sidecar idles with no Apple download needing it before it stops itself, "
        "in seconds. 0 never stops it."
    )
    apple_quarantine_dir: str = (
        "Where Apple tracks that fail their integrity check are kept. Empty uses the default "
        "'Waves Quarantine' folder inside the download folder. The folder is excluded from the "
        "library scan, so a quarantined file never badges IN LIBRARY."
    )
    apple_quarantine_keep: str = (
        "Keep Apple tracks that fail their integrity check in the Quarantine folder (default on). "
        "Off deletes them instead; the skip-list still marks them either way."
    )
    quality_video: str = 'Desired video download quality: "360", "480", "720", "1080"'
    default_audio_type: str = (
        "The Chooser one-click audio default, on every enabled provider that offers Atmos: "
        "stereo, or both versions side by side where a track offers the choice. "
        "Atmos on its own stays a per-click choice in the Chooser."
    )
    # TODO: Describe possible variables.
    format_album: str = "Where to download albums and how to name the items."
    format_playlist: str = (
        "Where to download playlists and how to name the items. {folder_path} mirrors the "
        "playlist's folder tree on its provider (empty when the playlist is not in a folder)."
    )
    format_mix: str = "Where to download mixes and how to name the items."
    format_track: str = "Where to download tracks and how to name the items."
    format_atmos: str = (
        "Where Dolby Atmos versions land: a subfolder under the stereo file's folder "
        "(default Dolby Atmos). Blank places Atmos alongside stereo."
    )
    format_video: str = "Where to download videos and how to name the items."
    video_convert_mp4: str = (
        "Videos are downloaded as MPEG Transport Stream (TS) files. With this option each video "
        "will be converted to MP4. FFmpeg must be installed."
    )
    path_binary_ffmpeg: str = (
        "Path to FFmpeg binary file (executable). Only necessary if FFmpeg is not set in $PATH. Mandatory for Windows: "
        "The directory of `ffmpeg.exe` must be set in %PATH%."
    )
    metadata_cover_dimension: str = (
        "The square dimensions of the cover image embedded into the track. Possible values: 80, 160, 320, 640, 1280, origin."
    )
    metadata_cover_file_dimension: str = (
        "Size of the saved 'cover.jpg'. 'Same as embedded' matches the embedded cover size; "
        "otherwise pick an independent size (80, 160, 320, 640, 1280, origin)."
    )
    metadata_cover_embed: str = "Embed album cover into file."
    cover_file_format: str = (
        "Sidecar cover format: raw (default: the true original-master bytes on Apple, plain jpg on "
        "TIDAL, which has no original-master sidecar), jpg, or png. Embedded art stays jpg."
    )
    mark_explicit: str = "Mark explicit tracks with '🅴' in track title (only applies to metadata)."
    cover_album_file: str = "Save cover to 'cover.jpg', if an album is downloaded."
    cover_single_track_file: str = "Also save cover.jpg when downloading a single track on its own."
    extract_flac: str = "Extract FLAC audio tracks from MP4 containers and save them as `*.flac` (uses FFmpeg)."
    extract_flac_all: str = (
        "Also convert lossy tracks to FLAC, not just lossless ones. Lossless converts without quality loss "
        "(bit for bit identical); lossy sources are re-encoded, so the files grow with no quality gain. Off "
        "(default) converts lossless only and keeps lossy originals as `*.m4a`. Dolby Atmos always "
        "stays `*.m4a`. Uses FFmpeg."
    )
    downsample_enabled: str = (
        "Downsample FLAC files toward a fixed target rate/bit-depth using ffmpeg. "
        "Each dimension is reduced independently and never upsampled, a 24-bit/44.1 kHz "
        "source with a 16/48 target becomes 16-bit/44.1 kHz; a 16-bit/44.1 kHz source is "
        "left untouched. Useful for capping HI_RES_LOSSLESS downloads at a saner archive size."
    )
    downsample_target: str = (
        "Downsample target when downsample_enabled is true: '16_48' (16 bit / 48 kHz) or '24_48' (24 bit / 48 kHz)."
    )
    downloads_simultaneous_per_track_max: str = (
        "Maximum number of simultaneous chunk downloads per track (capped at 10, the connection pool size)."
    )
    download_delay_sec_min: str = "Lower boundary for the calculation of the download delay in seconds."
    download_delay_sec_max: str = "Upper boundary for the calculation of the download delay in seconds."
    album_track_num_pad_min: str = (
        "Minimum length of the album track count, will be padded with zeroes (0). To disable padding set this to 1."
    )
    downloads_concurrent_max: str = (
        "How many tracks of an album, playlist or mix download at the same time. "
        "Queued items themselves always run one after another, in order."
    )
    symlink_to_track: str = (
        "If enabled the tracks of albums, playlists and mixes will be downloaded to the track directory but symlinked "
        "accordingly."
    )
    playlist_create: str = "Creates a '_playlist.m3u8' file for downloaded albums, playlists and mixes."
    metadata_replay_gain: str = "Replay gain information will be written to metadata."
    metadata_write_url: str = "URL of the media file will be written to metadata."
    window_x: str = "X-Coordinate of saved window location."
    window_y: str = "Y-Coordinate of saved window location."
    window_w: str = "Width of saved window size."
    window_h: str = "Height of saved window size."
    filename_delimiter_artist: str = "Filename delimiter for multiple artists. Default: ', '"
    filename_delimiter_album_artist: str = "Filename delimiter for multiple album artists. Default: ', '"
    filename_illegal_replacement: str = (
        "Written where an illegal character (/ : ? *) is removed. Empty gives "
        "'ACDC', '-' gives 'AC-DC'. New downloads only."
    )
    filename_illegal_map: str = (
        "Give single characters their own stand-in, overriding the general one: "
        "' · ' for ':' keeps 'Rarities Edition · Live' readable. Characters left "
        "alone follow the general stand-in."
    )
    metadata_target_upc: str = (
        "Select the target metadata tag ('UPC', 'BARCODE', 'EAN') where to write the UPC information to. Default: 'UPC'."
    )
    api_rate_limit_batch_size: str = (
        "How many songs to download before pausing, so a long playlist does not ask TIDAL too much at once. 0 never pauses."
    )
    api_rate_limit_delay_sec: str = "How long that pause lasts, in seconds. 0 never pauses."
    initial_key_format: str = "Format for Initial Key metadata tag: 'alphanumeric' (default) or 'classic'."


@dataclass_json
@dataclass
class Token:
    token_type: str | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    expiry_time: float = 0.0


# Per-provider lyrics & artwork mirrors (issue #61): the shared key names
# each provider prefixes. The migration loop and the schema walk both read
# this table, so a new mirrored option lands in both by adding one word.
LYRICS_ART_KEYS: tuple[str, ...] = (
    "lyrics_embed",
    "lyrics_file",
    "lyrics_file_synced_only",
    "lyrics_prefer_lrclib",
    "lyrics_word_timed",
    "lyrics_ttml_file",
    "metadata_cover_dimension",
    "metadata_cover_file_dimension",
    "metadata_cover_embed",
    "cover_album_file",
    "cover_single_track_file",
    "cover_file_format",
)

PROVIDER_IDS: tuple[str, ...] = ("tidal", "apple")

# Custom-template tag groups (issue #61): the metadata tags a Custom
# template can omit, one toggle each (metadata_tag_<name>).
METADATA_TAG_FLAGS: tuple[str, ...] = (
    "composer",
    "copyright",
    "isrc",
    "bpm",
    "initial_key",
    "upc",
)

_MISSING = object()


def provider_setting(data, provider_id: str, key: str, default=None):
    """One lyrics/artwork option for one provider (issue #61).

    Reads the provider's mirror (``tidal_lyrics_embed``) with the shared key
    as legacy fallback, so configs and stubs that predate the split keep
    their meaning: an old install behaves exactly as configured until the
    one-time migration copies its values into both mirrors.
    """
    pid = str(provider_id or "").strip().lower() or "tidal"
    if data is None:
        return default
    namespaced = getattr(data, f"{pid}_{key}", _MISSING)
    if namespaced is not _MISSING:
        return namespaced
    return getattr(data, key, default)


def metadata_tag_write(data, tag: str) -> bool:
    """Whether the Custom template keeps one tag group (issue #61).

    Provider default (the custom switch off) writes everything; Custom
    omits the groups switched off. Unknown tags and unreadable configs
    write, never drop: omitting is always the user's explicit choice.
    """
    if data is None:
        return True
    try:
        custom = bool(getattr(data, "metadata_custom", False))
    except Exception:
        return True
    if not custom:
        return True
    try:
        return bool(getattr(data, f"metadata_tag_{tag}", True))
    except Exception:
        return True
