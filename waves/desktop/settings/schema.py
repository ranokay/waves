"""Settings field vocabulary and QML schema construction.

The bridge supplies current values and the few live reads required by the
page. This module owns display fields, default values and coercion registries;
it never imports the bridge or mutates preferences. Qt slots remain on the
single WavesBridge QObject.
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Callable
from dataclasses import dataclass

from waves.constants import (
    CTX_APPLE,
    DEFAULT_ILLEGAL_MAP,
    CoverDimensions,
    DefaultAudio,
    DownsampleTarget,
    InitialKey,
    MetadataTargetUPC,
    QualityTier,
    QualityVideo,
)
from waves.desktop.providers.presentation import (
    apple_status,
    provider_card,
    provider_session_field,
)
from waves.model.cfg import Settings as SettingsData
from waves.paths import ILLEGAL_FILENAME_CHARS, safe_filename_replacement_map
from waves.providers import Provider, StatusKind

logger = logging.getLogger("waves.settings")

# Type registries, which coercion each settings key needs. settingsSchema()
# arranges these into task-based sections for the page; the lists below only
# decide how a value is read from / written back to the config.
FLAG_FIELDS = [
    "video_download",
    "video_convert_mp4",
    "lyrics_embed",
    "lyrics_file",
    "lyrics_file_synced_only",
    "lyrics_prefer_lrclib",
    # Lyrics & art matrix (spec section 9.1): word-timed source
    # toggle (default on) and the verbatim Apple TTML sidecar (default on,
    # the ratified best-quality fresh-install set).
    "lyrics_word_timed",
    "lyrics_ttml_file",
    # Per-provider mirrors: each provider's own lyrics/artwork
    # options, rendered inside its Providers card.
    "tidal_lyrics_embed",
    "tidal_lyrics_file",
    "tidal_lyrics_file_synced_only",
    "tidal_lyrics_prefer_lrclib",
    "tidal_lyrics_word_timed",
    "tidal_lyrics_ttml_file",
    "apple_lyrics_embed",
    "apple_lyrics_file",
    "apple_lyrics_file_synced_only",
    "apple_lyrics_prefer_lrclib",
    "apple_lyrics_word_timed",
    "apple_lyrics_ttml_file",
    "download_delay",
    "extract_flac",
    "extract_flac_all",
    "metadata_cover_embed",
    "cover_album_file",
    # Child of cover_album_file, carried inside its "cover_scope" composite rather
    # than as its own tile; listed here so applySettings persists it as a bool.
    "cover_single_track_file",
    "tidal_metadata_cover_embed",
    "tidal_cover_album_file",
    "tidal_cover_single_track_file",
    "apple_metadata_cover_embed",
    "apple_cover_album_file",
    "apple_cover_single_track_file",
    "skip_existing",
    "confirm_category_download",
    "symlink_to_track",
    "playlist_create",
    "mark_explicit",
    "use_primary_album_artist",
    # Custom tag template: the master switch plus one omit flag
    # per tag group, shown only while the switch is on.
    "metadata_custom",
    "metadata_tag_composer",
    "metadata_tag_copyright",
    "metadata_tag_isrc",
    "metadata_tag_bpm",
    "metadata_tag_initial_key",
    "metadata_tag_upc",
    # Providers area: the Apple component's enable switch. It is
    # never rendered as a flag tile: the Apple status row carries it as the
    # section's master switch, so it only needs the persistence coercion.
    "apple_enabled",
    # Integrity gate (spec §6): keep-vs-delete for quarantined
    # files, default keep. The quarantine folder itself is a path field below.
    "apple_quarantine_keep",
    # Advanced
    "downsample_enabled",
    "metadata_replay_gain",
    "metadata_write_url",
]

CHOICE_FIELDS = [
    ("tidal_quality_audio", QualityTier),
    ("apple_quality_audio", QualityTier),
    ("default_audio_type", DefaultAudio),
    ("quality_video", QualityVideo),
    ("metadata_cover_dimension", CoverDimensions),
    # Per-provider mirrors of the keys above.
    ("tidal_metadata_cover_dimension", CoverDimensions),
    ("apple_metadata_cover_dimension", CoverDimensions),
    # Advanced
    ("downsample_target", DownsampleTarget),
    ("metadata_target_upc", MetadataTargetUPC),
    ("initial_key_format", InitialKey),
]

NUMBER_FIELDS = [
    "album_track_num_pad_min",
    "downloads_concurrent_max",
    # Advanced
    "downloads_simultaneous_per_track_max",
    "api_rate_limit_batch_size",
    # Integrity gate: automatic re-downloads after an integrity
    # failure, tunable in Advanced. Default 2 (3 attempts total).
    "apple_integrity_retries",
    # Setup wizard: wrapper HTTP API port override. 0 means pick
    # a free high port; rendered as a plain number field in the Apple section.
    "apple_wrapper_port",
    # Session supervision (spec §3): proactive Apple pacing, same
    # shape as TIDAL's api_rate_limit_* (pause after N songs for N seconds).
    "apple_pacing_batch_size",
]

# Second-scale floats (Advanced), rendered as a decimal stepper.
FLOAT_FIELDS = [
    "download_delay_sec_min",
    "download_delay_sec_max",
    "api_rate_limit_delay_sec",
    "apple_integrity_retry_delay_sec",
    # Session supervision (spec §3): the proactive Apple pause
    # length, and the idle timeout after which the sidecar stops itself.
    "apple_pacing_delay_sec",
    "apple_wrapper_idle_sec",
]

# Waves' opinionated defaults layered over the engine's stock dataclass defaults.
# Applied once on a brand-new install (_apply_first_run_defaults) and restored
# by the Advanced-settings "reset all settings" action, so the two always agree
# on what "factory default" means.
FIRST_RUN_OVERRIDES = {
    "use_primary_album_artist": True,  # library-friendly Artist/Album folders
    "video_download": False,  # audio-first out of the box
    "quality_video": QualityVideo.P720,
    "mark_explicit": True,
    "metadata_write_url": False,
    # Recommended stand-ins for the rejected characters that carry meaning. Only
    # a fresh install gets them outright: an existing library is asked first
    # (_migrate_illegal_map_offer), because its folders already spell those
    # characters some other way. Copied, never the shared constant.
    "filename_illegal_map": dict(DEFAULT_ILLEGAL_MAP),
}

PATH_FIELDS = [
    "download_base_path",
    "format_track",
    "format_video",
    "format_album",
    "format_playlist",
    "format_mix",
    "format_atmos",
    "filename_delimiter_artist",
    "filename_delimiter_album_artist",
    # Surfaced under Advanced as a power-user override. The Settings "FFmpeg"
    # card normally manages the binary; an explicit path here wins over the
    # managed copy (see _resolve_ffmpeg).
    "path_binary_ffmpeg",
    # Cookies tier: a Netscape cookies export that unlocks Apple downloads,
    # browsed like the FFmpeg override above.
    "apple_engine",
    "apple_cookies_path",
    # Same override shape for the N_m3u8DL-RE binary Apple downloads fetch
    # through; the wizard provisions it later.
    "path_binary_nm3u8dlre",
    # Integrity gate: quarantine folder override, browsed like a
    # download folder. Empty means the default inside the download folder.
    "apple_quarantine_dir",
]

BROWSE_FIELDS = {
    "download_base_path": "dir",
    "path_binary_ffmpeg": "file",
    "apple_cookies_path": "file",
    "path_binary_nm3u8dlre": "file",
    "apple_quarantine_dir": "dir",
}

# String fields whose value is a character or two: they render as a compact
# row with a small box on the right (the Track-number padding shape) instead
# of a full-width text box under the help.
INLINE_STR_FIELDS = {
    "filename_delimiter_artist",
    "filename_delimiter_album_artist",
    "filename_illegal_replacement",
}

# Fields the engine launders before use: the page warns in red while the typed
# value would not survive it, and holds the save rather than storing text that
# would be silently dropped (see sanitizeFilenameReplacement). The per-
# character map is laundered the same way, value by value.
SANITIZED_FIELDS = {"filename_illegal_replacement"}

# Fields holding a character -> stand-in table rather than a single value.
MAP_FIELDS = {"filename_illegal_map"}

# How each rejected character is named on the settings page. The glyph alone
# is the label; the name is what a screen reader (and a puzzled user) gets.
ILLEGAL_CHAR_NAMES = {
    "/": "slash",
    "\\": "backslash",
    ":": "colon",
    "*": "asterisk",
    "?": "question mark",
    '"': "quote",
    "<": "less than",
    ">": "greater than",
    "|": "pipe",
}


def shipped_field_default(key: str):
    """The value a field has on a fresh install, or None if it has no useful one.

    Read straight off the ``Settings`` dataclass so it can never drift from
    what a new install actually gets. Feeds the per-field "Default" link on the
    settings page: a mistyped template is one click from the shipped one, with
    no need to reset every other setting to get there.
    """
    for f in dataclasses.fields(SettingsData):
        if f.name != key:
            continue
        default = f.default
        if default is dataclasses.MISSING or not isinstance(default, str) or default == "":
            return None
        return default
    return None


ENUM_BY_FIELD = dict(CHOICE_FIELDS)

# Flags that do nothing without FFmpeg, greyed out on the page when it's absent.
FFMPEG_DEPENDENT = {"video_convert_mp4", "extract_flac", "extract_flac_all"}

# Human field titles, overriding the auto-prettified key (e.g. "Api rate limit
# delay sec"). Anything not listed falls back to setting_label(key).
FIELD_LABELS = {
    # Downloads
    "download_base_path": "Download folder",
    "tidal_quality_audio": "Audio quality",
    "apple_quality_audio": "Audio quality (Apple)",
    "apple_engine": "Download engine",
    "apple_cookies_path": "Cookies file (Apple)",
    "path_binary_nm3u8dlre": "N_m3u8DL-RE binary path",
    "apple_wrapper_port": "Wrapper port (Apple)",
    "apple_quarantine_dir": "Quarantine folder (Apple)",
    "apple_quarantine_keep": "Keep quarantined files",
    "apple_integrity_retries": "Integrity retries (Apple)",
    "apple_integrity_retry_delay_sec": "Integrity retry delay (s)",
    "apple_pacing_batch_size": "Pause every N songs (Apple)",
    "apple_pacing_delay_sec": "Length of that pause (s, Apple)",
    "apple_wrapper_idle_sec": "Wrapper idle stop (s, Apple)",
    "quality_video": "Video quality",
    "downloads_concurrent_max": "Concurrent track downloads",
    "default_audio_type": "Default audio type",
    "confirm_category_download": "Confirm bulk downloads",
    # Discography & editions (a source toggle like the disco_* prefs)
    "video_download": "Music videos",
    # File organization
    "format_track": "Track path & name",
    "format_album": "Album path & name",
    "format_playlist": "Playlist path & name",
    "format_video": "Video path & name",
    "format_mix": "Mix path & name",
    "format_atmos": "Dolby Atmos files",
    "album_track_num_pad_min": "Track-number padding",
    "filename_delimiter_artist": "Artist separator",
    "filename_delimiter_album_artist": "Album-artist separator",
    "filename_illegal_replacement": "Illegal-character stand-in",
    "filename_illegal_map": "Per-character stand-ins",
    "use_primary_album_artist": "Primary album artist for folders",
    "symlink_to_track": "Symlink into track folder",
    "playlist_create": "Create .m3u8 playlist",
    # Metadata (the tag template; lyrics/cover embedding lives per provider)
    "metadata_cover_dimension": "Embedded cover size",
    "metadata_cover_embed": "Embed cover art",
    "cover_album_file": "Save cover.jpg",
    "lyrics_embed": "Embed lyrics",
    "lyrics_file": "Save lyrics file",
    "lyrics_file_synced_only": "Only synced lyrics files",
    "lyrics_prefer_lrclib": "Prefer LRCLIB lyrics",
    "lyrics_word_timed": "Prefer word-timed lyrics",
    "lyrics_ttml_file": "Save Apple TTML file",
    "cover_file_format": "Cover file format",
    "mark_explicit": "Mark explicit in title",
    # Per-provider mirrors: the Providers cards already name the
    # provider, so the labels stay provider-neutral.
    "tidal_lyrics_embed": "Embed lyrics",
    "tidal_lyrics_file": "Save lyrics file",
    "tidal_lyrics_file_synced_only": "Only synced lyrics files",
    "tidal_lyrics_prefer_lrclib": "Prefer LRCLIB lyrics",
    "tidal_lyrics_word_timed": "Prefer word-timed lyrics",
    "tidal_lyrics_ttml_file": "Save TTML file",
    "tidal_metadata_cover_dimension": "Embedded cover size",
    "tidal_metadata_cover_embed": "Embed cover art",
    "tidal_cover_album_file": "Save cover.jpg",
    "tidal_cover_file_format": "Cover file format",
    "apple_lyrics_embed": "Embed lyrics",
    "apple_lyrics_file": "Save lyrics file",
    "apple_lyrics_file_synced_only": "Only synced lyrics files",
    "apple_lyrics_prefer_lrclib": "Prefer LRCLIB lyrics",
    "apple_lyrics_word_timed": "Prefer word-timed lyrics",
    "apple_lyrics_ttml_file": "Save Apple TTML file",
    "apple_metadata_cover_dimension": "Embedded cover size",
    "apple_metadata_cover_embed": "Embed cover art",
    "apple_cover_album_file": "Save cover",
    "apple_cover_file_format": "Cover file format",
    # Custom tag template.
    "metadata_custom": "Custom tag template",
    "metadata_tag_composer": "Composer tag",
    "metadata_tag_copyright": "Copyright tag",
    "metadata_tag_isrc": "ISRC tag",
    "metadata_tag_bpm": "BPM tag",
    "metadata_tag_initial_key": "Initial-key tag",
    "metadata_tag_upc": "UPC tag",
    # Advanced
    "path_binary_ffmpeg": "FFmpeg binary path",
    "downsample_target": "Downsample target",
    "downloads_simultaneous_per_track_max": "Parallel chunks per track",
    "download_delay_sec_min": "Minimum download delay (s)",
    "download_delay_sec_max": "Maximum download delay (s)",
    "metadata_target_upc": "UPC tag field",
    "initial_key_format": "Initial-key tag format",
    "api_rate_limit_batch_size": "Pause every N songs",
    "api_rate_limit_delay_sec": "Length of that pause (s)",
    "downsample_enabled": "Downsample hi-res FLAC",
    "metadata_replay_gain": "Write ReplayGain tags",
    "metadata_write_url": "Write source URL tag",
}

# Human labels for enum dropdown values, keyed by field then by enum member
# name (the stored value). Unmapped members fall back to the raw name.
ENUM_LABELS = {
    # Per-provider audio quality: the Waves rungs, each provider
    # stating them in its own codecs with "Up to" ceilings, so the
    # dropdown reads as a fidelity promise: bitrate for lossy rungs, bit depth
    # and sample rate for lossless ones. Apple has no LOW rung (AAC 256 starts
    # at HIGH), so its list starts there.
    "tidal_quality_audio": {
        "LOW": "Low · Up to 96 Kbps",
        "HIGH": "High · Up to 320 Kbps",
        "LOSSLESS": "Lossless · Up to 16-bit / 44.1 kHz",
        "HI_RES_LOSSLESS": "Max · Hi-Res · Up to 24-bit / 192 kHz",
    },
    "apple_quality_audio": {
        "HIGH": "High · Up to 256 Kbps (AAC)",
        "LOSSLESS": "Lossless · Up to 24-bit / 48 kHz (ALAC)",
        "HI_RES_LOSSLESS": "Max · Hi-Res · Up to 24-bit / 192 kHz (ALAC)",
    },
    "quality_video": {"P360": "360p", "P480": "480p", "P720": "720p", "P1080": "1080p"},
    # Chooser one-click audio default: stereo, or both Versions
    # side by side where a track offers the choice.
    "default_audio_type": {"STEREO": "Stereo", "BOTH": "Stereo + Atmos"},
    "metadata_cover_dimension": {
        "Px80": "80×80",
        "Px160": "160×160",
        "Px320": "320×320",
        "Px640": "640×640",
        "Px1280": "1280×1280",
        "PxORIGIN": "Original",
    },
    # Per-provider mirrors: identical rungs, one list each so a
    # provider's wording can diverge later without touching the other.
    "tidal_metadata_cover_dimension": {
        "Px80": "80×80",
        "Px160": "160×160",
        "Px320": "320×320",
        "Px640": "640×640",
        "Px1280": "1280×1280",
        "PxORIGIN": "Original",
    },
    "apple_metadata_cover_dimension": {
        "Px80": "80×80",
        "Px160": "160×160",
        "Px320": "320×320",
        "Px640": "640×640",
        "Px1280": "1280×1280",
        "PxORIGIN": "Original",
    },
    "downsample_target": {"BIT16_48": "16-bit / 48 kHz", "BIT24_48": "24-bit / 48 kHz"},
    "metadata_target_upc": {"UPC": "UPC", "BARCODE": "Barcode", "EAN": "EAN"},
    "initial_key_format": {"ALPHANUMERIC": "Alphanumeric (Camelot)", "CLASSIC": "Classic"},
    "explicit_mode": {"explicit": "Explicit", "clean": "Clean", "both": "Both"},
    "edition_conflict": {
        "keep_both": "Keep both",
        "completeness": "Most complete",
        "quality": "Highest quality",
        "merge": "Best of both",
    },
    "update_cadence": {"launch": "Every launch", "daily": "Once a day"},
}


def enum_options(key: str, members) -> list:
    """Build [{value, label}] dropdown options for an enum field. ``members``
    may be an enum class (uses each member's ``name``) or a list of value
    strings (for the Waves prefs, which aren't backed by a Python enum)."""
    labels = ENUM_LABELS.get(key, {})
    out = []
    for m in members:
        v = getattr(m, "name", m)
        out.append({"value": v, "label": labels.get(v, v)})
    return out


def apple_status_actions(state: str) -> list[dict]:
    """The Apple status row's actions for a light state.

    One builder for the schema's baked value and the live mirror the page
    re-reads, so the two can never disagree about which pills exist: sign-out
    only while a session stands, the runtime management always.
    """
    actions = [
        {"label": "Setup wizard", "action": "apple_setup"},
        {"label": "Update runtime", "action": "apple_update_runtime"},
        {"label": "Remove runtime", "action": "apple_remove_runtime"},
    ]
    if state == "signed_in":
        actions.append({"label": "Sign out", "action": "apple_signout"})
    return actions


def setting_label(key: str) -> str:
    return key.replace("_", " ").capitalize()


@dataclass
class SettingsSchema:
    """A per-call view of settings; live reads remain bridge-owned callbacks."""

    data: SettingsData
    preferences: dict
    providers: list[Provider]
    help_for: Callable[[str], str]
    preference_bool: Callable[[str], bool]
    apple_flags: Callable[[], dict]
    quarantine_note: Callable[[], str]
    session_logged_in: Callable[[Provider], bool]
    ffmpeg_preferences: dict[str, bool]
    ffmpeg_path: Callable[[], str]
    ffmpeg_status: Callable[[str], dict]

    def build(self) -> list[dict]:  # noqa: C901 (declarative schema; branches describe controls)
        """Settings for the QML page, arranged into task-based, collapsible
        sections rather than raw engine field types.

        Each group carries ``id``/``open``/``desc`` for the collapsible UI, and
        ``card: "ffmpeg"`` injects the FFmpeg manager card at the top of that
        section. Per-field hints (``requires_ffmpeg``, ``depends_on`` +
        ``depends_on_value``) let the page grey-out or hide a control without
        hard-coding key names in QML.
        """
        d = self.data
        # The Providers area's status rows: live bridge state,
        # read at build time — the TIDAL session, and the Apple component's
        # light, through the same helper the appleStatus() slot serves the
        # page's live mirror from, so the two can never disagree.
        try:
            _flags = self.apple_flags()
        except Exception:
            _flags = {"enabled": bool(getattr(d, "apple_enabled", False))}
        apple_status_value = apple_status(
            bool(_flags.get("enabled", False)),
            runtime_ready=bool(_flags.get("runtime_ready", False)),
            signed_in=bool(_flags.get("signed_in", False)),
            needs_attention=bool(_flags.get("needs_attention", False)),
            cookies_ready=bool(_flags.get("cookies_ready", False)),
        )

        def field(key: str, ftype: str, value, extra: dict | None = None) -> dict:
            out = {
                "key": key,
                "label": FIELD_LABELS.get(key) or setting_label(key),
                "help": self.help_for(key),
                "type": ftype,
                "value": value,
            }
            if extra:
                out.update(extra)
            return out

        def auto_field(key: str) -> dict:
            """Build a field dict for an engine ``Settings`` key, choosing the
            control type from the registries above."""
            if key == "apple_engine":
                return field(
                    key,
                    "enum",
                    str(getattr(d, key, "auto")),
                    {
                        "options": [{"value": "auto", "label": "Auto"}, {"value": "gamdl", "label": "gamdl"}],
                    },
                )
            if key in ENUM_BY_FIELD:
                enum = ENUM_BY_FIELD[key]
                current = getattr(d, key)
                return field(key, "enum", getattr(current, "name", str(current)), {"options": enum_options(key, enum)})
            if key in FLOAT_FIELDS:
                # Most second-scale fields pause under a minute; the
                # supervision knobs run longer by design (idle
                # default 300 s), so they carry their own ceiling.
                maximum = {"apple_wrapper_idle_sec": 3600.0, "apple_pacing_delay_sec": 600.0}.get(key, 60)
                return field(
                    key,
                    "float",
                    float(getattr(d, key)),
                    {"minimum": 0, "maximum": maximum, "step": 0.5, "decimals": 1},
                )
            if key in NUMBER_FIELDS:
                return field(key, "int", int(getattr(d, key)))
            if key in FLAG_FIELDS:
                return field(key, "bool", bool(getattr(d, key)))
            if key in MAP_FIELDS:
                # A character -> stand-in table. The page renders one box per
                # rejected character, so it is handed the character list (with
                # names) rather than deriving one of its own. "default_value"
                # is the recommended table, behind the card's Default link;
                # "offer" additionally puts it on screen as a one-time strip,
                # for an install that predates it and has no stand-ins of its
                # own (see _migrate_illegal_map_offer).
                return field(
                    key,
                    "char_map",
                    safe_filename_replacement_map(getattr(d, key, None)),
                    {
                        "chars": [{"char": c, "name": ILLEGAL_CHAR_NAMES.get(c, c)} for c in ILLEGAL_FILENAME_CHARS],
                        "default_value": dict(DEFAULT_ILLEGAL_MAP),
                        "offer": not self.preferences.get("illegal_map_offer_done", False),
                    },
                )
            # "default" (when the field has a meaningful shipped value) drives
            # the page's per-field Default link, so a mangled template can be
            # restored without resetting every other setting.
            extra = {"browse": BROWSE_FIELDS.get(key, "")}
            shipped = shipped_field_default(key)
            if shipped is not None:
                extra["default_value"] = shipped
            if key in INLINE_STR_FIELDS:
                # Compact box beside the help, and a third of the row each, so
                # the three of them sit side by side on one line.
                extra["inline"] = True
                extra["third"] = True
            if key in SANITIZED_FIELDS:
                extra["sanitize"] = True
            return field(key, "str", str(getattr(d, key)), extra)

        # Waves-only prefs (stored in waves.json) keep their hand-written labels
        # and help; indexed by key so sections can pick them in any order.
        waves_fields = {
            f["key"]: f
            for f in [
                {
                    # Composite control (QML renders "library" specially): a
                    # master on/off toggle (off by default, the card below it
                    # greys out), a download-vs-separate source picker, the
                    # separate folder field, the live scan progress, and a
                    # Rescan button. The controls stage into the page's editMap
                    # and commit through SAVE CHANGES (applySettings), which
                    # also starts the first scan; only Rescan acts immediately,
                    # and only on the saved configuration.
                    "key": "library",
                    # The composite is a UI marker, not a pref; naming its
                    # backing prefs here lets _factory_default_values enumerate
                    # them, so RESET ALL SETTINGS restores the library switch,
                    # source, folder, bulk-skip and MusicBrainz toggles like
                    # every other field.
                    "enabled_key": "library_enabled",
                    "file_key": "library_source",
                    "child_key": "library_folder",
                    "bulk_key": "library_bulk_skip",
                    "mb_key": "library_mb_arbiter",
                    "label": "Music library",
                    "help": (
                        "Choose where your music library lives, then SAVE CHANGES to scan it. Waves matches "
                        "what you browse against it to badge what you already have, no matter which "
                        "provider saved the files. Scanning only ever "
                        "reads: it never writes, moves or renames anything it finds."
                    ),
                    "type": "library",
                    # The composite reads its state live from the bridge; this empty
                    # value only satisfies the generic str/enum delegates, which
                    # still instantiate (hidden) for every field and read f.value.
                    "value": "",
                },
                {
                    "key": "explicit_mode",
                    "label": "Explicit versions",
                    "help": (
                        "When an album or track exists as both explicit and clean: 'explicit' keeps the explicit "
                        "version, 'clean' keeps the censored one, 'both' keeps both. Applies to search results "
                        "and downloads."
                    ),
                    "type": "enum",
                    "value": self.preferences.get("explicit_mode", "explicit"),
                    "options": enum_options("explicit_mode", ["explicit", "clean", "both"]),
                },
                {
                    "key": "collapse_editions",
                    "label": "Most-complete edition only",
                    "help": (
                        "On 'Download discography' and a playlist's 'Download full albums', keep only the most "
                        "complete edition of each album (Deluxe, Complete). Remasters, re-releases, anniversary "
                        "editions and live or acoustic versions still count as their own album. Artist pages "
                        "hide the skipped editions too (see the next setting). "
                        "With this off, every edition is downloaded as it is."
                    ),
                    "type": "bool",
                    "value": self.preference_bool("collapse_editions"),
                },
                {
                    "key": "artist_page_all_editions",
                    "label": "Show every edition on artist pages",
                    "help": (
                        "With 'Most-complete edition only' on, artist pages hide the editions a discography "
                        "download would skip. Turn this on to list them all anyway, at a little loading time "
                        "per artist."
                    ),
                    "type": "bool",
                    "value": self.preference_bool("artist_page_all_editions"),
                },
                {
                    "key": "edition_conflict",
                    "label": "When an album has several editions",
                    "help": (
                        "'Best of both' builds one album from the most complete edition's track list, with each "
                        "shared song pulled from the highest-quality edition that has it (the exclusive bonus "
                        "tracks stay at the complete edition's quality). When you save a single album it runs on "
                        "its own. On 'Download discography' and a playlist's 'Download full albums' every "
                        "choice here, 'Best of both' included, only "
                        "takes effect when 'Most-complete edition only' is on; with that off, every edition is "
                        "downloaded as it is. The other three choices decide what happens when the most complete "
                        "edition is a lower audio quality than a smaller one: 'Keep both' downloads both, "
                        "'Most complete' keeps the most complete, 'Highest quality' keeps the highest quality."
                    ),
                    "type": "enum",
                    "value": self.preferences.get("edition_conflict", "keep_both"),
                    "options": enum_options("edition_conflict", ["keep_both", "completeness", "quality", "merge"]),
                },
                {
                    "key": "clean_album_artist",
                    "label": "Clean Album Artist",
                    "help": (
                        "Write only the primary artist to the album-artist tag, so Plex sorts "
                        "multi-artist albums correctly. Metadata only; folder names are unchanged."
                    ),
                    "type": "bool",
                    "value": self.preference_bool("clean_album_artist"),
                },
                {
                    "key": "disco_albums",
                    "label": "Albums",
                    "help": "Studio albums and the artist's own compilations (e.g. greatest-hits).",
                    "type": "bool",
                    "value": self.preference_bool("disco_albums"),
                },
                {
                    "key": "disco_eps",
                    "label": "EPs & singles",
                    "help": "The artist's own EPs and singles.",
                    "type": "bool",
                    "value": self.preference_bool("disco_eps"),
                },
                {
                    "key": "disco_featured",
                    "label": "Featured on",
                    "help": (
                        "Other artists' releases the artist is a featured guest on (e.g. a duet or a "
                        "guest verse); only the tracks the artist appears on are downloaded, not the "
                        "whole release."
                    ),
                    "type": "bool",
                    "value": self.preference_bool("disco_featured"),
                },
                {
                    "key": "disco_appears_on",
                    "label": "Appears on",
                    "help": (
                        "Various-artists compilations and soundtracks the artist appears on; only "
                        "the tracks the artist appears on are downloaded, not the whole release."
                    ),
                    "type": "bool",
                    "value": self.preference_bool("disco_appears_on"),
                },
                {
                    "key": "motion_background",
                    "label": "Motion background",
                    "help": (
                        "Show the slow ocean loop behind the interface. Turning it off stops video "
                        "playback entirely and keeps a flat background (saves a little battery)."
                    ),
                    "type": "bool",
                    "value": self.preference_bool("motion_background"),
                },
                {
                    "key": "hover_control_motion",
                    "label": "Hover controls slide in",
                    "help": (
                        "Preview and download controls rise up from the bottom of a cover with a "
                        "small bounce when you hover it, and roll their contents over when a "
                        "preview or a download starts. Download buttons ride the same roll "
                        "between their states (queued, progress, done, retry), with colours "
                        "fading along. Turn this off to have them simply fade in and out, and "
                        "change over instantly."
                    ),
                    "type": "bool",
                    "value": self.preference_bool("hover_control_motion"),
                },
                {
                    "key": "art_hover_tilt",
                    "label": "Cover art tilts on hover",
                    "help": (
                        "Album and artist artwork tilts toward your cursor and lifts slightly "
                        "once the pointer rests on it, springing back when you move away. Turn "
                        "this off to keep every cover flat and still."
                    ),
                    "type": "bool",
                    "value": self.preference_bool("art_hover_tilt"),
                },
                {
                    "key": "video_hover_peek",
                    "label": "Videos preview on hover",
                    "help": (
                        "Resting the pointer on a video thumbnail grows a small live preview "
                        "with sound. Turn this off to keep thumbnails still: videos then play "
                        "only when you click them."
                    ),
                    "type": "bool",
                    "value": self.preference_bool("video_hover_peek"),
                },
                {
                    "key": "verbose_diagnostics",
                    "label": "Verbose diagnostics",
                    "help": (
                        "Write a detailed activity log to help diagnose slowdowns, freezes and "
                        "crashes. Off by default: only warnings and errors are kept. Turn it on, "
                        "reproduce the problem, then export the report below."
                    ),
                    "type": "bool",
                    "value": self.preference_bool("verbose_diagnostics"),
                },
                {
                    "key": "diagnostics_redact_content",
                    "label": "Also hide titles and searches",
                    "help": (
                        "Exported reports always remove your username, file paths, network "
                        "addresses, account details and tokens. This additionally hides what you "
                        "searched for and the track, album and artist names; that can make some "
                        "bugs harder to reproduce."
                    ),
                    "type": "bool",
                    "value": self.preference_bool("diagnostics_redact_content"),
                },
                {
                    "key": "auto_update",
                    "label": "Check for updates automatically",
                    "help": (
                        "Off by default. When on, Waves checks the releases page for a newer version "
                        "(at launch or once a day) and only notifies you; nothing downloads until you "
                        "click Update. The check sends none of your data."
                    ),
                    "type": "bool",
                    "value": self.preference_bool("auto_update"),
                },
                {
                    "key": "update_cadence",
                    "label": "How often to check",
                    "help": "Run the automatic check on every launch, or at most once a day.",
                    "type": "enum",
                    "value": self.preferences.get("update_cadence", "daily"),
                    "options": enum_options("update_cadence", ["launch", "daily"]),
                },
                {
                    "key": "ffmpeg_auto_update",
                    "label": "Check for updates automatically",
                    "help": (
                        "Off by default. When on, Waves checks for a newer managed FFmpeg build "
                        "(at launch or once a day) and only notifies you; nothing downloads until "
                        "you click Update. The check sends none of your data."
                    ),
                    "type": "bool",
                    "value": self.preference_bool("ffmpeg_auto_update"),
                },
                {
                    "key": "ffmpeg_update_cadence",
                    "label": "How often to check",
                    "help": "Run the automatic check on every launch, or at most once a day.",
                    "type": "enum",
                    "value": self.preferences.get("ffmpeg_update_cadence", "daily"),
                    "options": enum_options("update_cadence", ["launch", "daily"]),
                },
                {
                    # The Apple section's master switch, status light and
                    # runtime-manage actions in one row (spec §9.2.3).
                    # apple_enabled rides as enabled_key: the switch
                    # stages into editMap like any toggle and SAVE CHANGES
                    # persists it, while enabled_key is what makes
                    # _factory_default_values enumerate it for RESET ALL
                    # SETTINGS. The actions drive the managed runtime's
                    # install/remove behind the setup wizard;
                    # "action" names the slot channel QML calls. "live" names
                    # the channel the page re-reads when a save moves the switch.
                    "key": "provider_apple_status",
                    "provider": CTX_APPLE,
                    "enabled_key": "apple_enabled",
                    "switch_value": bool(getattr(d, "apple_enabled", False)),
                    "live": "apple_status",
                    "label": "Enable Apple Music",
                    "help": (
                        "Apple Music ships off by default. Turn it on to add Apple Music "
                        "catalog results to search. Search needs no Apple account or runtime. "
                        "Downloads need setup below: a cookies export unlocks AAC 256 and Atmos "
                        "at once (no runtime), while the managed runtime plus the wrapper sign-in "
                        "unlock the full tier. Turning it off stops its queued downloads; RETRY "
                        "brings them back after it is switched on again."
                    ),
                    "type": "status",
                    "value": apple_status_value["state"],
                    "word": apple_status_value["word"],
                    "actions": apple_status_actions(apple_status_value["state"]),
                },
                {
                    # The in-place setup wizard steps (spec §2):
                    # a bridge-computed card, not a pref. QML renders the
                    # step list from the live appleSetupState() mirror
                    # ("live" names that channel, like apple_status above)
                    # and calls back the actions the steps name. It stages
                    # no edit and carries no factory default.
                    "key": "apple_setup_wizard",
                    "provider": CTX_APPLE,
                    "label": "Setup wizard",
                    "help": (
                        "Walks the setup in order: cookies unlock AAC 256 and Atmos at once, "
                        "then the managed runtime, container, wrapper image, and Apple ID sign-in "
                        "unlock the full tier. Steps refresh live as each lands."
                    ),
                    "type": "apple_setup",
                    "live": "apple_setup",
                    "value": "",
                },
                {
                    # A pure command row: re-opens the welcome surface as a
                    # page, where each provider is enabled and set up. It
                    # stages no edit and carries no value.
                    "key": "provider_setup_action",
                    "label": "Set up providers",
                    "help": (
                        "Re-opens the welcome surface: turn a provider on, sign in, or run its "
                        "one-time setup. The same cards the first run shows."
                    ),
                    "type": "action",
                    "action": "show_setup",
                    "value": "",
                },
            ]
        }
        # Session-kind provider cards get their status row here: one generic
        # row per provider, its state read from the bridge's session truth,
        # so a second session-kind provider needs no schema or QML branch.
        # (With no session the landing panel can be hidden by another
        # provider or a dismissed first-run picker, so the card's action is
        # the entry point that always exists; it starts the same flow the
        # panel and the top bar use.)
        for _provider in self.providers:
            _descriptor = _provider.descriptor()
            if _descriptor.status_kind != StatusKind.SESSION:
                continue
            waves_fields[f"provider_{_descriptor.id}_session"] = provider_session_field(
                _descriptor, self.session_logged_in(_provider)
            )

        def get_field(key: str) -> dict:  # noqa: C901 (field metadata varies by control type)
            f = dict(waves_fields[key]) if key in waves_fields else auto_field(key)

            def _provider_of(name: str) -> str:
                for prefix in ("tidal_", "apple_"):
                    if name.startswith(prefix):
                        return prefix[:-1]
                return ""

            def _base_key(name: str) -> str:
                provider = _provider_of(name)
                return name[len(provider) + 1 :] if provider else name

            def _prefixed(base: str, provider: str) -> str:
                return f"{provider}_{base}" if provider else base

            provider = _provider_of(key)
            base = _base_key(key)
            if base == "metadata_cover_dimension":
                # Composite control: the embedded-cover size (this field's enum)
                # plus an optional, progressively-disclosed size for the saved
                # cover file. Power users get a second size without a new row
                # appearing for everyone else. QML renders "cover_sizes" specially
                # and writes both keys back through applySettings. Per-provider
                # mirrors carry their own file size the same way.
                file_key = _prefixed("metadata_cover_file_dimension", provider)
                f["type"] = "cover_sizes"
                f["file_key"] = file_key
                f["file_value"] = getattr(d, file_key, "follow") or "follow"
                f["file_label"] = "Separate cover file size"
                f["file_options"] = [
                    {"value": "follow", "label": "Same as embedded"},
                    *enum_options("metadata_cover_dimension", ENUM_BY_FIELD["metadata_cover_dimension"]),
                ]
            if base == "cover_album_file":
                # Stays a normal on/off tile, but carries a nested child: a compact
                # checkbox for single-track downloads that appears under the
                # description while "Save cover" is on. The tile keeps its fixed
                # size, so the niche option adds no separate tile and the section
                # keeps its compact 2-column grid.
                child_key = _prefixed("cover_single_track_file", provider)
                f["child_key"] = child_key
                f["child_value"] = bool(getattr(d, child_key, False))
                f["child_label"] = "Also save for single tracks"
                f["child_help"] = "Write the cover file for a single track downloaded on its own, not just full albums."
            if base == "lyrics_file":
                # "Only synced" is meaningless while no lyrics file is saved, so
                # it rides inside this tile as a nested checkbox (same pattern
                # as cover_album_file) instead of a free-floating toggle.
                child_key = _prefixed("lyrics_file_synced_only", provider)
                f["child_key"] = child_key
                f["child_value"] = bool(getattr(d, child_key, False))
                f["child_label"] = "Only when lyrics are timed (skip the .txt)"
                f["child_help"] = self.help_for(child_key)
            if key == "apple_quarantine_dir":
                # The stored value and the used folder can differ (the resolver
                # refuses a folder that overlaps the download or library root);
                # the card must say which one is in use.
                note = self.quarantine_note()
                if note:
                    f["help"] = f"{f.get('help', '')} {note}".strip()
            if key == "video_download":
                # Lives with the other 'Download discography' sources; the
                # stock engine help ("Allow download of videos") no longer
                # describes what it does. Videos downloaded one at a time
                # never consult it.
                f["help"] = (
                    "The artist's music videos, saved with the video path template. "
                    "Downloading a single video yourself always works, with or without this."
                )
            if base == "lyrics_prefer_lrclib":
                # The source preference only matters while lyrics are fetched at
                # all; the tile greys out (live, unsaved toggles included) when
                # the provider's lyrics switches are all off.
                f["requires_any"] = {
                    _prefixed("lyrics_embed", provider): bool(getattr(d, _prefixed("lyrics_embed", provider), False)),
                    _prefixed("lyrics_file", provider): bool(getattr(d, _prefixed("lyrics_file", provider), False)),
                    _prefixed("lyrics_ttml_file", provider): bool(
                        getattr(d, _prefixed("lyrics_ttml_file", provider), False)
                    ),
                }
                f["requires_hint"] = "Turn on a lyrics option first"
            if base in ("lyrics_word_timed", "lyrics_ttml_file"):
                # Same gate as the LRCLIB preference: word-timed sourcing and
                # the verbatim TTML sidecar only matter while lyrics are
                # fetched at all.
                f["requires_any"] = {
                    _prefixed("lyrics_embed", provider): bool(getattr(d, _prefixed("lyrics_embed", provider), False)),
                    _prefixed("lyrics_file", provider): bool(getattr(d, _prefixed("lyrics_file", provider), False)),
                    _prefixed("lyrics_ttml_file", provider): bool(
                        getattr(d, _prefixed("lyrics_ttml_file", provider), False)
                    ),
                }
                f["requires_hint"] = "Turn on a lyrics option first"
            if base == "cover_file_format":
                # Small enum rendered as a dropdown: jpg/png everywhere, raw
                # as the original-master sidecar (Apple-only; TIDAL treats raw
                # as jpg, which the label says).
                raw_label = "Original (Apple only)" if provider != "tidal" else "Original (jpg on TIDAL)"
                f["type"] = "enum"
                f["value"] = str(getattr(d, key, "jpg") or "jpg")
                f["options"] = [
                    {"value": "jpg", "label": "JPG"},
                    {"value": "png", "label": "PNG"},
                    {"value": "raw", "label": raw_label},
                ]
            if base in (
                "metadata_tag_composer",
                "metadata_tag_copyright",
                "metadata_tag_isrc",
                "metadata_tag_bpm",
                "metadata_tag_initial_key",
                "metadata_tag_upc",
            ):
                # Custom-template omit flags: shown only while the
                # Custom template is on (the page hides depends_on fields).
                f["depends_on"] = "metadata_custom"
                f["depends_on_value"] = bool(getattr(d, "metadata_custom", False))
            if key in ("auto_update", "update_cadence", "ffmpeg_auto_update", "ffmpeg_update_cadence"):
                # Rendered inside the updater / FFmpeg cards (toggle + cadence
                # segment), not as the generic tile/row controls.
                f["embedded"] = True
            if key in ("verbose_diagnostics", "diagnostics_redact_content"):
                # Rendered inside the diagnostics card next to the export
                # action, not as generic tiles.
                f["embedded"] = True
            if key in FFMPEG_DEPENDENT:
                f["requires_ffmpeg"] = True
                # Report the user's *real* preference, not the in-memory value
                # Download force-disables while ffmpeg is missing, the page
                # greys the toggle (requires_ffmpeg) and animates it back to this
                # value once ffmpeg arrives, with no schema rebuild.
                f["value"] = bool(self.ffmpeg_preferences.get(key, f.get("value", False)))
            if key == "path_binary_ffmpeg":
                # Surface a genuine user override first. With none set, prefill
                # the binary detected on the system PATH so the box shows what
                # Waves is actually using (and Browse opens beside it); the box
                # is empty only when nothing is detected. The managed copy is
                # never shown here, it has its own card above, and this stays a
                # display prefill: nothing persists unless the user edits/saves.
                val = self.ffmpeg_path()
                if not val:
                    try:
                        st = self.ffmpeg_status(val)
                        if st.get("state") == "path":
                            val = str(st.get("path") or "")
                    except Exception:
                        logger.debug("Could not probe ffmpeg for the settings prefill", exc_info=True)
                f["value"] = val
                f["label"] = "Or link your own FFmpeg"
                f["help"] = (
                    "Point Waves at an FFmpeg binary you already have instead of the managed copy. "
                    "Leave empty to use the managed copy above, or one found on your system PATH."
                )
            # edition_conflict deliberately has NO depends_on: 'Best of both'
            # runs on its own for a single album, and hiding the control
            # behind another toggle is what let the merge sit silently off
            # with nothing on the page to say so. On the discography sweep it
            # follows 'Most-complete edition only', which the help
            # says in words instead.
            if key == "update_cadence":
                f["depends_on"] = "auto_update"
                f["depends_on_value"] = self.preference_bool("auto_update")
            elif key == "artist_page_all_editions":
                f["depends_on"] = "collapse_editions"
                f["depends_on_value"] = self.preference_bool("collapse_editions")
            elif key == "ffmpeg_update_cadence":
                f["depends_on"] = "ffmpeg_auto_update"
                f["depends_on_value"] = self.preference_bool("ffmpeg_auto_update")
            elif key == "downsample_target":
                f["depends_on"] = "downsample_enabled"
                f["depends_on_value"] = bool(d.downsample_enabled)
            return f

        sections: list[dict] = [
            {
                # The two-axis layout's first axis (spec §9.2): ONE
                # Providers section holding a distinctive card per provider
                # for what differs (session, quality, runtime/pacing/setup).
                # A third provider slots in as a third card; shared behavior
                # stays in the shared sections below. The QML renders each
                # entry with the provider's logo header and its fields, so a
                # card is never a flat mixed field list.
                "group": "Providers",
                "id": "providers",
                "desc": "Your music services. Each provider keeps its own session, quality default and setup.",
                # One card per registered provider, composed from its
                # descriptor: a provider contributes its identity, blurb
                # and field list; the live status data behind those keys
                # is built above. A new provider is a descriptor, not a
                # QML branch.
                "providers": [provider_card(p) for p in self.providers],
                # No loose fields except the re-open command: everything
                # provider-specific lives on the cards above.
                "fields": ["provider_setup_action"],
            },
            {
                "group": "Downloads",
                "id": "downloads",
                "desc": "Where your music is saved and how downloads run, for every enabled provider.",
                "fields": [
                    "download_base_path",
                    "quality_video",
                    "downloads_concurrent_max",
                    "default_audio_type",
                    "skip_existing",
                    "confirm_category_download",
                    "download_delay",
                ],
            },
            {
                "group": "Library",
                "id": "library",
                "desc": "Point Waves at your music library so it can badge what you already have.",
                "fields": [
                    "library",
                ],
            },
            {
                "group": "File organization",
                "id": "files",
                "desc": (
                    "Folder layout, file-name templates and how multiple artists are joined. The templates are shared by every enabled provider."
                ),
                "fields": [
                    "format_track",
                    "format_album",
                    "format_playlist",
                    "format_video",
                    "format_mix",
                    "format_atmos",
                    "album_track_num_pad_min",
                    "filename_illegal_replacement",
                    "filename_illegal_map",
                    "filename_delimiter_artist",
                    "filename_delimiter_album_artist",
                    "use_primary_album_artist",
                    "symlink_to_track",
                    "playlist_create",
                ],
            },
            {
                # One tag template for every provider: with the
                # Custom switch off each file carries what its provider
                # supplies; with it on, the tag groups switched off below are
                # omitted. Lyrics and cover embedding live only in the
                # Providers cards above, never as template tags.
                "group": "Metadata",
                "id": "metadata",
                "desc": "The tag template every download is written with, no matter which provider saved it.",
                "fields": [
                    "mark_explicit",
                    "clean_album_artist",
                    "metadata_replay_gain",
                    "metadata_write_url",
                    "metadata_target_upc",
                    "initial_key_format",
                    "metadata_custom",
                    "metadata_tag_composer",
                    "metadata_tag_copyright",
                    "metadata_tag_isrc",
                    "metadata_tag_bpm",
                    "metadata_tag_initial_key",
                    "metadata_tag_upc",
                ],
            },
            {
                "group": "Processing (FFmpeg)",
                "id": "processing",
                "card": "ffmpeg",
                "desc": "Post-processing that relies on the FFmpeg tool below.",
                # path_binary_ffmpeg is a str field → renders as a labelled box
                # with a Browse… button right under the card (before the bool
                # toggles), so linking your own binary lives beside its status.
                # The two ffmpeg_* auto-check fields are embedded in the card.
                "fields": [
                    "path_binary_ffmpeg",
                    "video_convert_mp4",
                    "extract_flac",
                    "extract_flac_all",
                    "ffmpeg_auto_update",
                    "ffmpeg_update_cadence",
                ],
            },
            {
                "group": "Discography & editions",
                "id": "discography",
                "desc": (
                    "What 'Download discography' pulls in, and how duplicate editions are "
                    "resolved (a playlist's 'Download full albums' follows the same edition rules)."
                ),
                "fields": [
                    "explicit_mode",
                    "edition_conflict",
                    "disco_albums",
                    "disco_eps",
                    "disco_featured",
                    "disco_appears_on",
                    "video_download",
                    "collapse_editions",
                    "artist_page_all_editions",
                ],
            },
            {
                "group": "Updates",
                "id": "updates",
                "card": "updates",
                "desc": "Keep Waves current. Checks are off by default and never send any of your data.",
                "fields": ["auto_update", "update_cadence"],
            },
            {
                "group": "Diagnostics",
                "id": "diagnostics",
                "card": "diagnostics",
                "desc": (
                    "Help fix bugs with a shareable report covering every enabled provider. "
                    "Personal details are always removed."
                ),
                "fields": ["verbose_diagnostics", "diagnostics_redact_content"],
            },
            {
                "group": "Advanced",
                "id": "advanced",
                "desc": "Power-user knobs. The defaults are right for almost everyone.",
                "fields": [
                    "motion_background",
                    "hover_control_motion",
                    "art_hover_tilt",
                    "video_hover_peek",
                    "downsample_target",
                    "downloads_simultaneous_per_track_max",
                    "download_delay_sec_min",
                    "download_delay_sec_max",
                    "api_rate_limit_batch_size",
                    "api_rate_limit_delay_sec",
                    "apple_integrity_retries",
                    "apple_integrity_retry_delay_sec",
                    "downsample_enabled",
                ],
            },
        ]
        for sec in sections:
            sec["fields"] = [get_field(k) for k in sec["fields"]]
            # Provider cards resolve their fields the same way:
            # one Providers section, one card per provider.
            for provider in sec.get("providers") or []:
                provider["fields"] = [get_field(k) for k in provider["fields"]]
        return sections
