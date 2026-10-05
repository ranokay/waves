"""Persisted fulfillment rules and immutable, credential-free queued intent.

Existing quality, audio-default and lyrics/art fields remain authoritative.
The policy store adds shared rules and sparse provider overrides; capture folds
both stores into one request. Execution readiness and credentials are live.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from waves.model.cfg import Settings

type Scalar = str | bool | int | float
type JsonValue = Scalar | list[JsonValue] | dict[str, JsonValue] | None


@dataclass(frozen=True)
class FulfillmentPolicy:
    quality_strategy: str = "best_available"
    audio_type: str = ""
    required_codec: str = ""
    video_quality: str = ""
    video_codec: str = ""
    video_hdr: str = "sdr"
    video_max_fps: int = 0
    matching: str = "recording"
    metadata_source: str = "origin"
    organization_source: str = "origin"
    artwork_source: str = "origin"
    lyrics_source: str = "fulfillment"
    duplicates: str = ""
    require_extras: bool = False


# The same vocabulary validates disk/UI values and describes schema controls.
POLICY_CHOICES: dict[str, tuple[str, ...]] = {
    "quality_strategy": ("best_available", "minimum_required"),
    "audio_type": ("", "stereo", "atmos", "both"),
    "required_codec": ("", "flac", "alac", "aac", "eac3"),
    "video_quality": ("", "360", "480", "720", "1080"),
    "video_codec": ("", "h264", "hevc", "av1"),
    "video_hdr": ("sdr", "hdr", "any"),
    "matching": ("recording", "release"),
    "metadata_source": ("origin", "fulfillment"),
    "organization_source": ("origin", "fulfillment"),
    "artwork_source": ("origin", "fulfillment"),
    "lyrics_source": ("fulfillment", "origin"),
    "duplicates": ("", "keep_existing", "replace_owned", "keep_both"),
}
POLICY_LABELS = {
    "quality_strategy": "Quality strategy",
    "audio_type": "Audio type override",
    "required_codec": "Required audio codec",
    "video_quality": "Video quality override",
    "video_codec": "Required video codec",
    "video_hdr": "Video dynamic range",
    "video_max_fps": "Maximum video frame rate (0: unrestricted)",
    "matching": "Match recording or release",
    "metadata_source": "Descriptive metadata source",
    "organization_source": "File organization source",
    "artwork_source": "Artwork source",
    "lyrics_source": "Lyrics source",
    "duplicates": "Existing Version policy",
    "require_extras": "Require selected lyrics and artwork",
}
CROSS_PROVIDER_FIELDS = ("choose_best_provider", "recover_provider", "upgrade_provider", "enrich_provider")
CROSS_PROVIDER_LABELS = (
    "Automatically choose the best provider",
    "Recover failures through another provider",
    "Upgrade existing Waves-owned Versions through another provider",
    "Enrich lyrics and artwork through another provider",
)
ADVANCED_BOUNDS = {
    "attempt_limit": (1, 5),
    "retry_delay_sec": (0.0, 60.0),
    "request_timeout_sec": (1.0, 120.0),
}


@dataclass
class DownloadPolicies:
    shared: FulfillmentPolicy = field(default_factory=FulfillmentPolicy)
    providers: dict[str, dict[str, Scalar]] = field(default_factory=dict)
    provider_priority: tuple[str, ...] = ()
    engine_priority: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # Audio, lyrics and artwork can justify different engine orders.
    operation_priority: dict[str, dict[str, tuple[str, ...]]] = field(default_factory=dict)
    same_provider_fallback: bool = True
    choose_best_provider: bool = False
    recover_provider: bool = False
    upgrade_provider: bool = False
    enrich_provider: bool = False
    attempt_limit: int = 3
    retry_delay_sec: float = 5.0
    request_timeout_sec: float = 30.0

    def effective(self, provider_id: str) -> FulfillmentPolicy:
        return replace(self.shared, **self.providers.get(provider_id, {}))

    def engines(self, provider_id: str, operation: str = "audio") -> tuple[str, ...]:
        return self.operation_priority.get(provider_id, {}).get(operation) or self.engine_priority.get(provider_id, ())


def _order(value: JsonValue) -> tuple[str, ...]:
    words = value.split(",") if isinstance(value, str) else value if isinstance(value, list | tuple) else ()
    return tuple(dict.fromkeys(word.strip().lower() for word in words if isinstance(word, str) and word.strip()))


def _policy_values(raw: JsonValue) -> dict[str, Scalar]:
    if not isinstance(raw, dict):
        return {}
    result: dict[str, Scalar] = {}
    for key, value in raw.items():
        if (key in POLICY_CHOICES and isinstance(value, str) and value in POLICY_CHOICES[key]) or (
            key == "require_extras" and isinstance(value, bool)
        ):
            result[key] = value
        elif key == "video_max_fps" and isinstance(value, int) and not isinstance(value, bool):
            result[key] = max(0, min(value, 240))
    return result


def decode_policies(raw: JsonValue) -> DownloadPolicies:
    """Recover malformed policy fields independently, preserving other settings."""
    result = DownloadPolicies()
    if not isinstance(raw, dict):
        return result
    result.shared = replace(result.shared, **_policy_values(raw.get("shared")))
    providers = raw.get("providers")
    if isinstance(providers, dict):
        result.providers = {pid: _policy_values(values) for pid, values in providers.items()}
    result.provider_priority = _order(raw.get("provider_priority"))
    engines = raw.get("engine_priority")
    if isinstance(engines, dict):
        result.engine_priority = {pid: _order(values) for pid, values in engines.items()}
    operations = raw.get("operation_priority")
    if isinstance(operations, dict):
        result.operation_priority = {
            pid: {op: _order(values) for op, values in orders.items() if op in ("audio", "lyrics", "artwork")}
            for pid, orders in operations.items()
            if isinstance(orders, dict)
        }
    for key in (*CROSS_PROVIDER_FIELDS, "same_provider_fallback"):
        if isinstance(raw.get(key), bool):
            setattr(result, key, raw[key])
    for key, (minimum, maximum) in ADVANCED_BOUNDS.items():
        value = raw.get(key)
        if isinstance(value, int | float) and not isinstance(value, bool):
            value = max(minimum, min(value, maximum))
            setattr(result, key, int(value) if key == "attempt_limit" else float(value))
    return result


def encode_policies(policies: DownloadPolicies) -> dict:
    return dataclasses.asdict(policies)


def apply_policy_edit(policies: DownloadPolicies, key: str, value: JsonValue) -> DownloadPolicies:
    """Apply one schema edit to a copy; building/cancelling a page never writes."""
    parts = key.removeprefix("download_policies.").split(".")
    valid = (
        (len(parts) == 2 and parts[0] == "shared" and parts[1] in POLICY_LABELS)
        or (len(parts) == 3 and parts[0] == "providers" and bool(parts[1]) and parts[2] in POLICY_LABELS)
        or (len(parts) == 2 and parts[0] == "engine_priority" and bool(parts[1]))
        or (
            len(parts) == 3
            and parts[0] == "operation_priority"
            and bool(parts[1])
            and parts[2] in ("audio", "lyrics", "artwork")
        )
        or (
            len(parts) == 1
            and parts[0] in (*CROSS_PROVIDER_FIELDS, "same_provider_fallback", "provider_priority", *ADVANCED_BOUNDS)
        )
    )
    if not valid:
        return policies
    raw = encode_policies(policies)
    cursor = raw
    for part in parts[:-1]:
        cursor = cursor.setdefault(part, {})
    name = parts[-1]
    if parts[0] == "providers":
        if value == "__inherit__" or value == "inherit":
            cursor.pop(name, None)
            return decode_policies(raw)
        if name == "require_extras" and value in ("true", "false"):
            value = value == "true"
        if name == "video_max_fps" and isinstance(value, str):
            if not value.strip():
                cursor.pop(name, None)
                return decode_policies(raw)
            try:
                value = int(value)
            except ValueError:
                return policies
    cursor[name] = value
    return decode_policies(raw)


@dataclass(frozen=True)
class DownloadIntent:
    provider_id: str
    kind: str
    media_id: str
    policy: FulfillmentPolicy
    provider_pin: str
    engine_pin: str
    provider_priority: tuple[str, ...]
    engine_priority: tuple[str, ...]
    operation_priority: tuple[tuple[str, tuple[str, ...]], ...]
    same_provider_fallback: bool
    choose_best_provider: bool
    recover_provider: bool
    upgrade_provider: bool
    enrich_provider: bool
    attempt_limit: int
    retry_delay_sec: float
    request_timeout_sec: float
    clean_album_artist: bool
    library_bulk_skip: bool
    # JSON is immutable, detached from Settings, and contains no setup secrets.
    settings_json: str = field(repr=False)
    # Atmos-only fallback keeps the original stereo placement on Retry.
    base_template: str = ""

    def settings_data(self) -> Settings:
        from waves.model.cfg import Settings

        return Settings.from_json(self.settings_json)


# Setup is deliberately read live, never retained in a queue snapshot.
_LIVE_FIELDS = frozenset(
    {
        "network_mount_origins",
        "apple_cookies_path",
        "apple_enabled",
        "apple_wrapper_port",
        "path_binary_nm3u8dlre",
        "apple_wrapper_idle_sec",
        "path_binary_ffmpeg",
        "ffmpeg_source",
    }
)


def capture_intent(
    data: Settings,
    provider_id: str,
    kind: str,
    media_id: str,
    *,
    tier: str,
    audio_type: str | None,
    toggles: dict[str, bool],
    engine_pin: str = "",
    provider_pin: str = "",
    allow_fallback: bool = False,
    clean_album_artist: bool = False,
    library_bulk_skip: bool = True,
) -> DownloadIntent:
    rules = data.download_policies
    policy = rules.effective(provider_id)
    payload = json.loads(data.to_json())
    for key in _LIVE_FIELDS:
        payload.pop(key, None)
    payload[f"{provider_id}_quality_audio"] = tier
    payload["default_audio_type"] = audio_type or policy.audio_type or data.default_audio_type
    if policy.video_quality:
        payload["quality_video"] = policy.video_quality
    for key, value in toggles.items():
        payload[f"{provider_id}_{key}"] = value
    duplicates = policy.duplicates or ("keep_existing" if data.skip_existing else "keep_both")
    policy = replace(
        policy,
        audio_type=payload["default_audio_type"],
        video_quality=policy.video_quality or str(data.quality_video.value),
        duplicates=duplicates,
    )
    pin = "" if engine_pin in ("", "auto") else engine_pin
    return DownloadIntent(
        provider_id,
        kind,
        media_id,
        policy,
        provider_pin,
        pin,
        rules.provider_priority,
        rules.engines(provider_id),
        tuple(rules.operation_priority.get(provider_id, {}).items()),
        rules.same_provider_fallback and (not pin or allow_fallback),
        rules.choose_best_provider and (not provider_pin or allow_fallback),
        rules.recover_provider and (not provider_pin or allow_fallback),
        rules.upgrade_provider,
        rules.enrich_provider,
        rules.attempt_limit,
        rules.retry_delay_sec,
        rules.request_timeout_sec,
        clean_album_artist,
        library_bulk_skip,
        json.dumps(payload),
    )
