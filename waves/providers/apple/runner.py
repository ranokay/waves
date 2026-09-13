"""Apple job orchestration: queue entry, per-track delivery, settlement.

The bridge delegates Apple download jobs here. The runner owns the policy --
what to fetch, how to verify, place, tag and sidecar it, when to retry, hold
or quarantine -- while the bridge keeps the services it cannot give up: Qt
signals, the queue, live settings, ownership and the sidecar supervisor.
Those arrive as :class:`AppleJobHooks`, plain callables, so the same shape can
serve another provider's job path and tests can drive the runner with a
handful of lambdas.

Nothing here touches Qt: the module is orchestration over the provider seam
plus the Apple engine, files, integrity and supervision modules.
"""

from __future__ import annotations

import contextlib
import dataclasses
import logging
import os
import pathlib
import shutil
import tempfile
import time
from collections.abc import Callable, MutableMapping
from contextlib import AbstractContextManager
from typing import Any
from uuid import uuid4

from waves.constants import (
    CTX_APPLE,
    TIER_RANK,
    CoverDimensions,
    QualityTier,
    provider_folder_name,
    quality_rank,
    tier_from_word,
    tier_word,
)
from waves.helper.exceptions import DownloadIncomplete
from waves.lyrics import fetch_lrclib_lyrics, lyrics_sidecar_choices
from waves.metadata import sniff_image_format
from waves.model.cfg import cover_sidecar_format, wants_both_default
from waves.ownership import copy_is_current, record_names_a_broken_copy
from waves.providers.apple import engine as apple_engine
from waves.providers.apple.engine import (
    AppleCredentialsError,
    AppleDownloadError,
    AppleIntegrityError,
    AppleTrackUnavailable,
    _AppleAborted,
    _AppleSkipped,
)
from waves.providers.apple.files import (
    convert_image,
    format_apple_path,
    pick_destination,
    tag_apple_file,
    write_collection_playlist,
    write_cover_sidecar,
    write_text_sidecar,
)
from waves.providers.apple.integrity import (
    INTEGRITY_FAIL_MESSAGE,
    encoded_date_of,
    integrity_retries,
    integrity_retry_delay,
    is_outbreak_era,
    parse_encoded_date,
    quarantine_dest,
    resolve_quarantine_dir,
)
from waves.providers.apple.supervision import (
    HELD_POLL_SEC,
    HELD_START_FAILURES,
    SETUP_PATH,
    held_message,
    is_wrapper_down_error,
    pacing_due,
    pacing_message,
    parse_retry_after,
    throttled_message,
)
from waves.providers.apple.supervision import (
    pacing_policy as supervision_pacing_policy,
)
from waves.providers.apple.supervision import (
    throttle_delay as supervision_throttle_delay,
)
from waves.providers.base import AudioType, RefusalKind

logger = logging.getLogger("waves.providers.apple.runner")


class _AppleSetupRequired(Exception):
    """The wrapper tier cannot start without the user finishing setup.

    Raised by the sidecar ensure when repeated start attempts fail, so the
    job fails with the setup words and the wizard can open instead of a row
    holding forever with nowhere to go.
    """


class _JobOptions:
    """The lyrics/art options one job runs with: per-click pins over Settings.

    A Chooser click pins its quick toggles for that click only; every other
    job leaves the pins empty and reads the provider's stored options. The
    fallback is the job's per-provider option reader, so one reader serves
    both.
    """

    def __init__(self, fallback, provider_id: str, pinned: dict | None = None) -> None:
        self._fallback = fallback
        self._provider_id = str(provider_id or "")
        self._pinned = {str(key): value for key, value in dict(pinned or {}).items()}

    def option(self, key: str, default=None):
        if key in self._pinned:
            return self._pinned[key]
        return self._fallback(self._provider_id, key, default)


# --------------------------------------------------------------------------
# Hooks
# --------------------------------------------------------------------------


def _none() -> Any:
    return None


def _noop(*_args, **_kwargs) -> None:
    return None


def _false(*_args, **_kwargs) -> bool:
    return False


def _true(*_args, **_kwargs) -> bool:
    return True


def _default_two(_key: str, default: Any = None) -> Any:
    return default


def _default_three(_provider_id: str, _key: str, default: Any = None) -> Any:
    return default


def _quality_none(_qid: int) -> Any:
    return None


def _empty_dict() -> dict:
    return {}


def _empty_set() -> set:
    return set()


def _zero_port() -> int:
    return 0


def _zero_clock() -> float:
    return 0.0


@dataclasses.dataclass(slots=True)
class AppleJobHooks:
    """Bridge-owned services one Apple job reaches, as plain callables.

    The runner holds the job policy; everything here is state or a Qt/queue
    service the provider layer does not own: the live settings and provider
    registry, the queue and its settlement, the ownership store, the sidecar
    supervisor and the diagnostic relays. Defaults are inert, so a test can
    fill only what the path under test touches.
    """

    provider: Callable[[], Any] = _none
    settings: Callable[[], Any] = _none
    psetting: Callable[[str, str, Any], Any] = _default_three
    apple_setting: Callable[[str, Any], Any] = _default_two
    tag_write_flags: Callable[[], dict] = _empty_dict
    job_quality: Callable[[int], Any] = _quality_none
    job_audio_type: Callable[[int], Any] = _quality_none
    ownership: Callable[[], Any] = _none
    redownload_overrides: Callable[[], set] = _empty_set
    library_claim_overrides: Callable[[], set] = _empty_set
    quarantine_paths: Callable[[], MutableMapping[int, list[str]]] = _empty_dict

    status: Callable[[str], None] = _noop
    queue_status: Callable[..., None] = _noop
    queue_progress: Callable[..., None] = _noop
    queue_item: Callable[[int], Any] = _quality_none
    queue_mark_changed: Callable[[int], None] = _noop
    emit_queue: Callable[[], None] = _noop
    remove_row: Callable[[int], None] = _noop
    bump_groups: Callable[..., None] = _noop
    download_state: Callable[..., None] = _noop
    download_progress: Callable[..., None] = _noop
    setup_requested: Callable[..., None] = _noop
    finish_job: Callable[[int], None] = _noop

    gate_reachability: Callable[..., bool] = _true
    download_apple: Callable[..., bool] = _false
    download_failed_with_folder: Callable[..., bool] = _false

    supervisor: Callable[[], Any] = _none
    runtime: Callable[[], Any] = _none
    wrapper_port: Callable[[], int] = _zero_port
    sidecar_guard: Callable[[], AbstractContextManager] = contextlib.nullcontext
    note_activity: Callable[[], None] = _noop
    refresh_wrapper_auth: Callable[..., Any] = _none
    schedule_idle_stop: Callable[[], None] = _noop
    mark_session_expired: Callable[[], None] = _noop
    clear_session_expired: Callable[[], None] = _noop

    redact: Callable[[Any], str] = str
    devlog_event: Callable[..., None] = _noop
    devlog_done: Callable[..., None] = _noop
    devlog_clock: Callable[[], float] = _zero_clock


# --------------------------------------------------------------------------
# Shared readers and small helpers
# --------------------------------------------------------------------------


def _data(hooks: AppleJobHooks) -> Any:
    """The live settings data object, or None when settings is unreadable."""
    try:
        return getattr(hooks.settings(), "data", None)
    except AttributeError:
        return None


def _pooled_session():
    """The engine's shared keep-alive HTTP session (lazy: pulls no engine at
    import time)."""
    from waves.download import pooled_session

    return pooled_session()


def _apple_cookies_fingerprint(path: str) -> tuple:
    """(path, mtime_ns, size) for a cookies export, or a stable empty."""
    candidate = pathlib.Path(str(path or "").strip()).expanduser()
    try:
        stat = candidate.stat()
    except OSError:
        return ("", 0, 0)
    return (str(candidate), int(stat.st_mtime_ns), int(stat.st_size))


def _want_cover_file(save_cover: bool, collection: bool, single_track: bool) -> bool:
    """Whether a separate cover sidecar is filed: the master toggle must be
    on, then collections always qualify and a lone track only with its own
    opt-in (the engine's scope rule)."""
    return bool(save_cover) and (bool(collection) or bool(single_track))


def effective_version(provider, track_id: str, audio_type) -> str:
    """The Version a fetch will actually verify as: Atmos only when asked AND
    offered (spec §6.4: each Version verifies independently).

    An Atmos ask for a stereo-only track falls back to stereo (the provider's
    instead-of rule), so gating and clearing on the asked version would file
    the failure under Atmos while stereo runs keep refetching the same corrupt
    source. A track that cannot be read keeps the asked version: it will fail
    per-track below, never silently vanish.
    """
    try:
        want_atmos = str(getattr(audio_type, "value", audio_type) or "").strip().lower() == "atmos"
    except Exception:
        want_atmos = False
    if not want_atmos:
        return "stereo"
    try:
        raw = provider.get_object("track", str(track_id).removeprefix(f"{CTX_APPLE}:"))
    except Exception:
        return "atmos"
    try:
        return "atmos" if bool(provider.has_atmos(raw)) else "stereo"
    except Exception:
        return "atmos"


def needs_wrapper(requested_rank: int = -1) -> bool:
    """Whether this job's ask can need the wrapper sidecar at all.

    The cookies tier serves HIGH alone (AAC 256 + Atmos); only a
    LOSSLESS-or-better ask reaches for the wrapper's ALAC path.
    """
    try:
        want = int(requested_rank)
    except (TypeError, ValueError):
        return False
    try:
        return want >= int(quality_rank(QualityTier.LOSSLESS))
    except Exception:
        return False


def wants_atmos(hooks: AppleJobHooks) -> bool:
    """Whether the one-click default fetches the Atmos Version alongside
    stereo, read live per job."""
    try:
        return wants_both_default(hooks.settings())
    except Exception:
        return False


def fetch_audio_type(hooks: AppleJobHooks) -> AudioType:
    """The AudioType a job with no pinned Version fetches."""
    return AudioType.ATMOS if wants_atmos(hooks) else AudioType.STEREO


def setting_tier(hooks: AppleJobHooks):
    """The Apple quality setting folded onto the ladder, or None."""
    return tier_from_word(str(hooks.settings().data.apple_quality_audio))


def target_rank(hooks: AppleJobHooks, pinned=None) -> int:
    """Rank of the audio quality an Apple run targets: the row's pinned rung,
    else the Apple setting."""
    data = hooks.settings().data
    q = data.apple_quality_audio if pinned is None else pinned
    return quality_rank(str(getattr(q, "value", q) or ""))


def queue_expected_word(hooks: AppleJobHooks, job_atype, *, requested_rank: int, ceiling_rank: int) -> str:
    """The queue row's expected word: ATMOS for Atmos rows, else the
    requested tier capped by the servable ceiling.

    Cookies-tier ceiling HIGH keeps the old HIGH; the wrapper ceiling
    HI_RES lets a HI_RES ask read HI-RES. Detail ("ALAC 24/192") never
    rides this word, only the tier.
    """
    if job_atype == "atmos" or (job_atype is None and wants_atmos(hooks)):
        return "ATMOS"
    try:
        want = int(requested_rank)
        ceil = int(ceiling_rank)
    except (TypeError, ValueError):
        want, ceil = -1, -1
    rank = min(want, ceil) if want >= 0 and ceil >= 0 else (want if want >= 0 else ceil)
    for tier_value, tier_rank in TIER_RANK.items():
        if tier_rank == rank:
            return tier_word(tier_value)
    return tier_word(str(getattr(hooks.settings().data, "apple_quality_audio", "") or "")) or "HIGH"


def job_options(hooks: AppleJobHooks, pinned: dict | None = None) -> _JobOptions:
    """The lyrics/art options one Apple job runs with: per-click Chooser pins
    over the provider's stored options."""
    return _JobOptions(hooks.psetting, CTX_APPLE, pinned)


def emit_progress(signals, collection: bool, pos: int, total: int, media_id: str, qid: int) -> None:
    """Stepwise row progress: one tick per settled track."""
    pct = min(100.0, (pos / total) * 100.0) if total else 100.0
    (signals.list_item if collection else signals.item).emit(pct)


def sleep_abortable(seconds: float, job_abort) -> bool:
    """Sleep in slices so STOP lands promptly; False when aborted."""
    deadline = time.monotonic() + float(seconds)
    while True:
        if job_abort.is_set():
            return False
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return True
        time.sleep(min(0.2, remaining))


# --------------------------------------------------------------------------
# Destination paths
# --------------------------------------------------------------------------


def relative_path(
    hooks: AppleJobHooks,
    *,
    track: dict,
    album: dict | None,
    playlist: dict | None,
    file_template: str,
    list_pos: int = 0,
    list_total: int = 0,
    num_volumes: int = 1,
    isrc: str = "",
) -> str:
    """One Apple destination from the settings' template.

    The single formatter behind both the download job's relative path and
    the standalone actions' folder/stem split, so apart from playlist
    collections (which reconstruct the album template) both render the same
    vocabulary.
    """
    data = hooks.settings().data
    return format_apple_path(
        file_template,
        track=track,
        album=album,
        playlist=playlist,
        list_pos=list_pos,
        list_total=list_total,
        num_volumes=num_volumes,
        isrc=isrc,
        pad_min=int(getattr(data, "album_track_num_pad_min", 1) or 1),
        delimiter_artist=str(getattr(data, "filename_delimiter_artist", ", ") or ", "),
        delimiter_album_artist=str(getattr(data, "filename_delimiter_album_artist", ", ") or ", "),
        illegal_replacement=str(getattr(data, "filename_illegal_replacement", "") or ""),
        illegal_map=getattr(data, "filename_illegal_map", None),
        provider_name=provider_folder_name(CTX_APPLE),
    )


def track_relative(
    hooks: AppleJobHooks,
    row: dict,
    header: dict | None,
    type_media: str,
    file_template: str,
    list_pos: int,
    list_total: int,
    num_volumes: int,
    facts_isrc: str = "",
) -> str:
    """One Apple track's template path, without base dir or extension."""
    if type_media == "playlist":
        album = None
        playlist = header
    else:
        album = header
        playlist = None
    return relative_path(
        hooks,
        track=row,
        album=album,
        playlist=playlist,
        file_template=file_template,
        list_pos=list_pos if type_media == "playlist" else 0,
        list_total=list_total if type_media == "playlist" else 0,
        num_volumes=num_volumes,
        isrc=facts_isrc,
    )


# --------------------------------------------------------------------------
# Delivery helpers (fetch, FLAC, placement, verification)
# --------------------------------------------------------------------------


def cover_convert_ffmpeg(hooks: AppleJobHooks) -> str:
    """An ffmpeg binary for cover conversion, or "" (PATH fallback).

    The Apple provider's resolved path covers managed installs; the persisted
    setting covers TIDAL's standalone art action; the converter itself falls
    back to PATH.
    """
    provider = hooks.provider()
    path = str(getattr(provider, "ffmpeg_path", "") or "").strip()
    if not path:
        data = _data(hooks)
        path = str(getattr(data, "path_binary_ffmpeg", "") or "").strip()
    return path


def embed_cover_bytes(hooks: AppleJobHooks, cover: bytes | None) -> bytes | None:
    """Cover bytes for embedding: jpg per spec 9.1, converted when needed."""
    if not cover or sniff_image_format(cover) != "png":
        return cover
    return convert_image(cover, "jpg", cover_convert_ffmpeg(hooks)) or cover


def probe_binary(hooks: AppleJobHooks) -> str:
    """An ffprobe binary for Apple verification: beside the resolved ffmpeg
    first (managed installs), else PATH, else "" (trust)."""
    provider = hooks.provider()
    ffmpeg = str(getattr(provider, "ffmpeg_path", "") or "")
    try:
        return apple_engine.ffprobe_for(ffmpeg)
    except Exception:
        logger.debug("Apple ffprobe resolution failed", exc_info=True)
        return ""


def wants_flac(hooks: AppleJobHooks) -> bool:
    """Whether lossless Apple stereo should land as FLAC.

    The shared Processing toggle (``extract_flac``), off meaning the
    original .m4a is kept. A plain stub without settings reads as on, the
    shipped default.
    """
    try:
        return bool(getattr(_data(hooks), "extract_flac", True))
    except Exception:
        return True


def guess_ext(hooks: AppleJobHooks, provider, audio_type, requested_rank: int) -> str:
    """The destination extension guessed before the fetch.

    Stereo at a lossless-or-better ask with the wrapper tier up and the FLAC
    toggle on guesses .flac (scope "all" guesses .flac for stereo of any
    tier); everything else (Atmos, lossy asks under the lossless-only scope,
    cookies tier alone) guesses .m4a. The per-attempt correction in
    :func:`deliver_track` settles the truth off the delivery, so a wrong
    guess only costs the re-check, never a wrong file.
    """
    try:
        want_atmos = str(getattr(audio_type, "value", audio_type) or "").strip().lower() == "atmos"
    except Exception:
        want_atmos = False
    if want_atmos or not wants_flac(hooks):
        return ".m4a"
    if flac_scope_all(hooks):
        # Scope "all": stereo of any tier lands FLAC (lossy by re-encode);
        # only Atmos keeps its container.
        return ".flac"
    try:
        if int(requested_rank) < int(quality_rank(QualityTier.LOSSLESS)):
            return ".m4a"
    except (TypeError, ValueError):
        return ".m4a"
    try:
        if not bool(getattr(provider, "wrapper_available", False)):
            return ".m4a"
    except Exception:
        return ".m4a"
    return ".flac"


def flac_scope_all(hooks: AppleJobHooks) -> bool:
    """Whether lossy stereo also converts to FLAC.

    The scope toggle beside the shared FLAC switch (``extract_flac_all``,
    default off): on re-encodes AAC stereo into FLAC, off keeps lossy
    originals as .m4a. A plain stub without settings reads as off.
    """
    try:
        return bool(getattr(_data(hooks), "extract_flac_all", False))
    except Exception:
        return False


def flac_mode(hooks: AppleJobHooks, info, *, atmos: bool) -> str:
    """How this delivery becomes FLAC: "lossless", "lossy", or "".

    Stereo ALAC converts losslessly (the FLAC container cannot hold ALAC
    packets, so the engine decodes and FLAC-encodes them: still bit for bit
    identical, never a lossy step); with the scope toggle on, stereo AAC
    re-encodes instead. AAC under the lossless-only scope, Atmos, unknown
    codecs, and a switched-off FLAC toggle all answer "" (keep the original
    .m4a). The provider flags ALAC with ``requires_flac_extraction``; older
    fakes naming ``alac`` in codecs read the same way. Only the lossless mode
    re-derives its tier off the landed bytes; the lossy mode keeps its
    staged HIGH tier.
    """
    if atmos or not wants_flac(hooks):
        return ""
    with contextlib.suppress(Exception):
        if bool(getattr(info, "requires_flac_extraction", False)):
            return "lossless"
    try:
        delivered = getattr(info, "delivered", None) or {}
        codecs = str(getattr(info, "codecs", "") or delivered.get("codecs") or "")
        norm = codecs.lower().replace("-", "").replace("_", "")
    except Exception:
        return ""
    if "alac" in norm:
        return "lossless"
    if flac_scope_all(hooks) and ("aac" in norm or "mp4a" in norm):
        return "lossy"
    return ""


def flac_ffmpeg(hooks: AppleJobHooks) -> str:
    """An ffmpeg binary for the Apple FLAC conversion, or "" to keep .m4a.

    Precedence mirrors the probe: the provider's resolved path first, then
    the saved override, then PATH.
    """
    try:
        provider = hooks.provider()
        cand = str(getattr(provider, "ffmpeg_path", "") or "")
        if cand and pathlib.Path(cand).is_file():
            return cand
    except Exception:
        logger.debug("Apple FLAC ffmpeg resolve failed", exc_info=True)
    try:
        cand = str(getattr(_data(hooks), "path_binary_ffmpeg", "") or "")
        if cand and pathlib.Path(cand).is_file():
            return cand
    except Exception:
        logger.debug("Apple FLAC ffmpeg resolve failed", exc_info=True)
    try:
        return shutil.which("ffmpeg") or ""
    except Exception:
        return ""


def extract_flac(hooks: AppleJobHooks, staged: pathlib.Path) -> tuple[pathlib.Path, str]:
    """Convert staged audio into FLAC, losslessly where the source is.

    ALAC cannot stream-copy into a FLAC container (it holds FLAC packets
    only), so the engine decodes and FLAC-encodes with no resampling and no
    bit-depth change: out of ALAC the result is bit for bit identical
    (pinned test-side by a PCM comparison); lossy stereo converts only under
    the scope-"all" toggle. Runs only on bytes that already passed
    verification. Returns the converted path plus its temp dir; the caller
    removes the dir once the file is placed (or on failure). A converted file
    that will not decode fails the track as a conversion failure (plain
    AppleDownloadError), never as source corruption: the staged original
    verified clean, so there is nothing to quarantine.
    """
    ffmpeg = flac_ffmpeg(hooks)
    if not ffmpeg:
        raise AppleDownloadError("Apple FLAC extraction needs FFmpeg")
    tmpdir = tempfile.mkdtemp(prefix="waves-apple-flac-")
    out = pathlib.Path(tmpdir) / (staged.stem + ".flac")
    try:
        from ffmpeg import FFmpeg

        (
            FFmpeg(executable=ffmpeg)
            .option("hide_banner")
            .option("nostdin")
            .option("y")
            .input(url=staged)
            .output(url=out, map=0, acodec="flac", map_metadata="0:g", loglevel="quiet")
            .execute()
        )
    except Exception as exc:
        with contextlib.suppress(OSError):
            shutil.rmtree(tmpdir, ignore_errors=True)
        raise AppleDownloadError(f"Could not extract FLAC from the Apple download: {exc}") from exc
    if not out.is_file() or out.stat().st_size == 0:
        with contextlib.suppress(OSError):
            shutil.rmtree(tmpdir, ignore_errors=True)
        raise AppleDownloadError("Apple FLAC extraction produced no file")
    try:
        apple_engine.decode_check(out, ffmpeg)
    except AppleIntegrityError as exc:
        with contextlib.suppress(OSError):
            shutil.rmtree(tmpdir, ignore_errors=True)
        raise AppleDownloadError(f"Apple FLAC extraction failed its check: {exc}") from exc
    except AppleDownloadError:
        with contextlib.suppress(OSError):
            shutil.rmtree(tmpdir, ignore_errors=True)
        raise
    return out, tmpdir


def place_file(staged: pathlib.Path, dest: pathlib.Path) -> None:
    """Land one staged file on its final path, atomically.

    Staging lives on another filesystem (system temp vs library, typically a
    network share), so a direct move copies into the final name and a
    mid-copy failure (full disk, dropped share) leaves a partial .m4a that
    skip_existing would then treat as complete. Copy beside the target and
    rename over it instead: readers never see a half file, and forced
    overwrites never delete the good copy before its replacement is whole.
    """
    tmp = dest.with_name(f"{dest.name}.part-{uuid4().hex[:8]}")
    try:
        shutil.copyfile(staged, tmp)
        os.replace(tmp, dest)
    except Exception:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


def verify_staged(hooks: AppleJobHooks, staged: pathlib.Path, *, expect_atmos: bool) -> None:
    """Pre-swap verification of one Apple delivery (spec §6.1).

    Always-on structural behavior, never a setting; TIDAL downloads never
    reach here. Two checks on the staged file, before it is swapped into the
    library: the codec must be the asked family (stereo: AAC or ALAC; Atmos:
    E-AC-3), and the whole file must ffmpeg-decode cleanly (the decode-to-null
    check, ~50 ms, no network). Either failure raises AppleDownloadError with
    the integrity wording, so the retry policy and quarantine treat both
    identically. No conversion runs before this passes; there is no patching.

    No ffprobe/ffmpeg anywhere means trust (their absence already fails
    louder paths via the ffmpeg gate); a wrong codec or a decode error fails
    the track, never the job.
    """
    ffprobe = probe_binary(hooks)
    if ffprobe:
        probe = apple_engine.probe_audio_file(staged, ffprobe)
        codec = str(probe.get("codec") or "").lower().replace("-", "").replace("_", "")
        # Stereo is AAC on the cookies tier and ALAC once the wrapper
        # unlocks it; Atmos is E-AC-3 (AC-4 accepted as the same family).
        # Normalized (hyphens/underscores dropped): "e-ac-3" -> "eac3".
        if expect_atmos:
            if codec not in ("eac3", "ec3", "ac4"):
                raise AppleIntegrityError(
                    f"Apple served {codec or 'an unknown codec'}, expected eac3", staged_path=str(staged)
                )
        elif codec not in ("aac", "alac"):
            raise AppleIntegrityError(
                f"Apple served {codec or 'an unknown codec'}, expected aac", staged_path=str(staged)
            )
    else:
        logger.debug("Apple codec check skipped (no ffprobe): %s", staged)
    # The decode-to-null gate: the only check that catches the outbreak's
    # malformed ALAC packets (missing TYPE_END terminators). decode_check
    # skips itself when ffmpeg is absent; its AppleDownloadError already
    # carries the integrity wording.
    provider = hooks.provider()
    ffmpeg = str(getattr(provider, "ffmpeg_path", "") or "")
    if not ffmpeg:
        try:
            ffmpeg = str(getattr(_data(hooks), "path_binary_ffmpeg", "") or "")
        except Exception:
            ffmpeg = ""
    try:
        apple_engine.decode_check(staged, ffmpeg)
    except Exception as exc:
        if isinstance(exc, AppleDownloadError):
            raise
        raise AppleDownloadError(f"Could not verify the Apple download: {exc}") from exc


# --------------------------------------------------------------------------
# Integrity gate (spec §6): quarantine, skip-list
# --------------------------------------------------------------------------


def quarantine_root(hooks: AppleJobHooks) -> pathlib.Path:
    """The quarantine folder: custom override or the default inside the
    download folder. Created on use, never here. A custom location registers
    its full path for scan exclusion (basename matching would prune
    legitimate same-named folders)."""
    try:
        base = str(getattr(_data(hooks), "download_base_path", "") or "")
    except Exception:
        base = ""
    try:
        custom = str(getattr(_data(hooks), "apple_quarantine_dir", "") or "")
    except Exception:
        custom = ""
    root = resolve_quarantine_dir(base, custom or None)
    if custom:
        try:
            from waves import library_index as _lib_index

            _lib_index.register_quarantine_dir(str(root))
        except Exception:
            logger.debug("Could not register the quarantine dir for scan exclusion", exc_info=True)
    return root


def quarantine_keep(hooks: AppleJobHooks) -> bool:
    """Keep vs delete for quarantined files, default keep."""
    try:
        return bool(getattr(_data(hooks), "apple_quarantine_keep", True))
    except Exception:
        return True


def is_integrity_failure(exc: BaseException) -> bool:
    """Whether an Apple failure is an integrity verdict (retry + quarantine).

    Explicit first: AppleIntegrityError is the verifier's own verdict
    (decode failures, wrong codecs, files with no audio stream). The wording
    fallback covers the same verdicts built as plain AppleDownloadErrors
    (older callers, test doubles); transport, credential and refusal failures
    match neither and keep their existing handling.
    """
    if isinstance(exc, AppleIntegrityError):
        return True
    text = str(exc or "").lower()
    return (
        "integrity check" in text
        or "expected aac" in text
        or "expected eac3" in text
        or "no playable audio stream" in text
    )


def skiplist_get(hooks: AppleJobHooks, track_id: str, audio_type: str | None):
    """A skip-list entry for a track's version, or None (no store = none)."""
    store = hooks.ownership()
    if store is None or not hasattr(store, "is_quarantined"):
        return None
    try:
        want = str(audio_type or "").strip().lower() or None
        if want not in ("stereo", "atmos", None):
            want = None
        return store.is_quarantined(str(track_id), want)
    except Exception:
        logger.debug("Apple skip-list lookup failed; not gating", exc_info=True)
        return None


def skiplist_add(hooks: AppleJobHooks, track_id: str, audio_type: str | None, encoded_date: str | None = None) -> None:
    """Mark a track's version as quarantined (bulk runs auto-skip it)."""
    store = hooks.ownership()
    if store is None or not hasattr(store, "quarantine_add"):
        return
    try:
        store.quarantine_add(str(track_id), audio_type, encoded_date)
    except Exception:
        logger.debug("Could not mark the Apple skip-list", exc_info=True)


def skiplist_clear(hooks: AppleJobHooks, track_id: str, audio_type: str | None = None) -> None:
    """Clear a quarantine mark: a verified copy landed (REDOWNLOAD's way back)."""
    store = hooks.ownership()
    if store is None or not hasattr(store, "quarantine_remove"):
        return
    try:
        # A versioned clear removes only that version; the deliver path
        # passes its own version, so a fixed Atmos copy never leaves a
        # stale stereo mark (or vice versa).
        store.quarantine_remove(str(track_id), audio_type)
    except Exception:
        logger.debug("Could not clear the Apple skip-list", exc_info=True)


def quarantine_file(
    hooks: AppleJobHooks,
    staged: pathlib.Path,
    *,
    relative: str,
    track_id: str,
    audio_type: str | None = None,
    qid: int = 0,
) -> pathlib.Path | None:
    """Keep a persistently-bad staged file in Quarantine, or None.

    Honors the keep-vs-delete toggle (delete keeps no bytes but still marks
    the skip-list via the caller). Files keep their intended names under the
    quarantine root, so a later verified copy replaces them by name. A kept
    copy is recorded against the queue row that produced it, so the drawer
    can offer to reveal or delete it. Never raises: quarantine must not fail
    a download that already failed.
    """
    if not quarantine_keep(hooks):
        return None
    try:
        root = quarantine_root(hooks)
        dest = quarantine_dest(root, relative, ".m4a")
        shutil.copyfile(staged, dest)
    except Exception:
        logger.debug("Could not quarantine the Apple file for %s", track_id, exc_info=True)
        return None
    else:
        # A quarantined file was never swapped in, so ownership stays honest
        # by construction: nothing is owned that isn't on disk.
        record_quarantine(hooks, qid, dest)
        return dest


def record_quarantine(hooks: AppleJobHooks, qid: int, dest: pathlib.Path | str) -> None:
    """Remember one quarantined copy on its queue row (open/delete actions)."""
    text = str(dest or "")
    if not text:
        return
    try:
        qid = int(qid)
    except (TypeError, ValueError):
        return
    try:
        paths = hooks.quarantine_paths().setdefault(qid, [])
        if text in paths:
            return
        paths.append(text)
    except Exception:
        logger.debug("Could not record a quarantined copy for qid %s", qid, exc_info=True)
        return
    item = hooks.queue_item(qid)
    if item is not None:
        item["quarantineCount"] = len(paths)
        hooks.queue_mark_changed(qid)
        hooks.emit_queue()


def quarantine_folder(hooks: AppleJobHooks, qid: int) -> pathlib.Path | None:
    """The folder that holds one row's quarantined copies, or None."""
    try:
        paths = list(hooks.quarantine_paths().get(int(qid), []))
    except (TypeError, ValueError):
        return None
    for text in paths:
        if not text:
            continue
        parent = pathlib.Path(str(text)).expanduser().parent
        if parent.is_dir():
            return parent
    return None


def staged_encoded_date(hooks: AppleJobHooks, staged: pathlib.Path) -> str | None:
    """A staged file's Encoded date as "YYYY-MM-DD", or None when unknown."""
    try:
        ffprobe = probe_binary(hooks)
    except Exception:
        ffprobe = ""
    try:
        parsed = encoded_date_of(staged, ffprobe)
    except Exception:
        return None
    return parsed.isoformat() if parsed is not None else None


# --------------------------------------------------------------------------
# Lyrics, cover and sidecars
# --------------------------------------------------------------------------


def lyrics(
    hooks: AppleJobHooks, provider, row: dict, facts: dict, options: _JobOptions | None = None
) -> tuple[str, str]:
    """LRCLIB-first lyrics for one Apple track, or ("", "").

    The two-tuple form is kept for test stubs that override it; the job path
    reads :func:`lyrics_full` for the TTML verbatim. LRCLIB-only, so a
    stubbed override never reaches the catalog.
    """
    options = options or job_options(hooks)
    if not (
        options.option("lyrics_embed", False)
        or options.option("lyrics_file", False)
        or options.option("lyrics_ttml_file", False)
    ):
        return "", ""
    if not options.option("lyrics_prefer_lrclib", True):
        return "", ""
    try:
        session = _pooled_session()
        return fetch_lrclib_lyrics(
            session,
            artist=str(row.get("artist") or ""),
            title=str(row.get("title") or ""),
            album=str(row.get("album") or ""),
            duration=int(row.get("duration_sec") or 0),
        )
    except Exception:
        logger.debug("Apple LRCLIB lookup failed", exc_info=True)
        return "", ""


def lyrics_full(
    hooks: AppleJobHooks, provider, row: dict, facts: dict, options: _JobOptions | None = None
) -> tuple[str, str, str]:
    """Lyrics for one Apple track as (synced, plain, ttml_verbatim).

    Source precedence (spec section 9.1), both providers in spirit, Apple in
    full:

    1. word-timed when the toggle is on (default on): syllable TTML
       sourced directly through the embedded catalog client and
       converted in Waves' layer (enhanced LRC). It outranks a
       line-timed LRCLIB hit.
    2. LRCLIB-first (existing toggle, governs both providers).
    3. provider-native fallback (Apple TTML to LRC conversion).
    4. unsynced text last.

    Syllable fetching degrades per track: a missing or unreadable
    syllable document falls back to line-timed sources, never failing
    the download. The verbatim TTML is returned alongside for the
    sidecar-only save (zero conversion); embedding keeps its exact
    TIDAL semantics (timed LRC in the primary field, TTML never
    embedded).
    """
    options = options or job_options(hooks)
    if not (
        options.option("lyrics_embed", False)
        or options.option("lyrics_file", False)
        or options.option("lyrics_ttml_file", False)
    ):
        return "", "", ""
    word_on = bool(options.option("lyrics_word_timed", True))
    prefer_lrclib = bool(options.option("lyrics_prefer_lrclib", True))

    track_obj = None
    try:
        track_obj = provider.get_object("track", str(row.get("id") or ""))
    except Exception:
        track_obj = None

    # 1. Word-timed: syllable TTML outranks a line-timed LRCLIB hit.
    # The verbatim sidecar is independent of this toggle (spec: sidecar
    # toggles independent, all combinations valid), so the syllable
    # document is fetched when either the word-timed source or the TTML
    # file is on.
    word_lrc = ""
    syllable_ttml = ""
    ttml_on = bool(options.option("lyrics_ttml_file", False))
    if (word_on or ttml_on) and track_obj is not None:
        try:
            syllable_ttml = provider.fetch_syllable_ttml(track_obj) or ""
        except Exception:
            logger.debug("Apple syllable-TTML fetch failed", exc_info=True)
            syllable_ttml = ""
        if syllable_ttml and word_on:
            try:
                from waves.ttml_lyrics import ttml_timing_mode, ttml_to_enhanced_lrc

                if ttml_timing_mode(syllable_ttml) == "word":
                    word_lrc = ttml_to_enhanced_lrc(syllable_ttml) or ""
            except Exception:
                logger.debug("Apple enhanced-LRC conversion failed", exc_info=True)
                word_lrc = ""

    # 2. LRCLIB-first (existing toggle, both providers).
    lrclib_synced = ""
    lrclib_plain = ""
    if prefer_lrclib:
        try:
            session = _pooled_session()
            lrclib_synced, lrclib_plain = fetch_lrclib_lyrics(
                session,
                artist=str(row.get("artist") or ""),
                title=str(row.get("title") or ""),
                album=str(row.get("album") or ""),
                duration=int(row.get("duration_sec") or 0),
            )
        except Exception:
            logger.debug("Apple LRCLIB lookup failed", exc_info=True)
            lrclib_synced, lrclib_plain = "", ""

    if word_lrc:
        # Word-timed wins for the synced slot; the plain sibling still
        # prefers LRCLIB's text, then the syllable document's own text.
        plain = lrclib_plain
        if not plain and syllable_ttml:
            try:
                from waves.ttml_lyrics import ttml_to_text

                plain = ttml_to_text(syllable_ttml) or ""
            except Exception:
                plain = ""
        verbatim = syllable_ttml
        if not verbatim and track_obj is not None:
            try:
                verbatim = provider.fetch_line_ttml(track_obj) or ""
            except Exception:
                verbatim = ""
        return word_lrc, plain, verbatim

    if lrclib_synced:
        # A timed LRCLIB hit wins outright; native is never spent on it.
        verbatim = ""
        if track_obj is not None:
            try:
                verbatim = provider.fetch_line_ttml(track_obj) or ""
                if not verbatim and syllable_ttml:
                    verbatim = syllable_ttml
            except Exception:
                verbatim = syllable_ttml or ""
        return lrclib_synced, lrclib_plain, verbatim

    # 3. Provider-native fallback (Apple TTML to LRC conversion). Tried
    # on a plain-only LRCLIB hit too: unsynced text is the last resort,
    # not something that hides available native timing.
    native_synced = ""
    native_plain = ""
    if track_obj is not None:
        try:
            native_synced, native_plain = provider.fetch_lyrics(track_obj)
        except Exception:
            logger.debug("Apple native lyrics fetch failed", exc_info=True)
            native_synced, native_plain = "", ""
        if native_synced or native_plain:
            verbatim = ""
            try:
                verbatim = provider.fetch_line_ttml(track_obj) or syllable_ttml or ""
            except Exception:
                verbatim = syllable_ttml or ""
            # The timed native document owns the synced slot; LRCLIB's
            # text still owns the plain slot when it has one.
            return native_synced, lrclib_plain or native_plain, verbatim

    # 4. Unsynced text last: LRCLIB's plain text, then the syllable
    # document's own text when nothing else exists.
    if lrclib_plain:
        verbatim = ""
        if track_obj is not None:
            try:
                verbatim = provider.fetch_line_ttml(track_obj) or syllable_ttml or ""
            except Exception:
                verbatim = syllable_ttml or ""
        return "", lrclib_plain, verbatim
    if syllable_ttml:
        try:
            from waves.ttml_lyrics import ttml_to_text

            plain = ttml_to_text(syllable_ttml) or ""
        except Exception:
            plain = ""
        if plain:
            return "", plain, syllable_ttml

    return "", "", syllable_ttml


def wants_cover(hooks: AppleJobHooks, collection: bool, options: _JobOptions | None = None) -> bool:
    """Whether this job fetches cover art at all: embedded, or filed per
    the engine's own cover.jpg rule (collections always qualify; a lone
    track only with the single-track opt-in)."""
    options = options or job_options(hooks)
    if options.option("metadata_cover_embed", True):
        return True
    return _want_cover_file(
        bool(options.option("cover_album_file", True)),
        bool(collection),
        bool(options.option("cover_single_track_file", False)),
    )


def cover_bytes(hooks: AppleJobHooks, provider, raw: dict) -> bytes | None:
    """The collection cover at the embedded size, or None.

    ORIGIN maps per provider (spec section 9.1): TIDAL keeps
    its exact current behavior (embedded cap included); Apple's ORIGIN
    is the true original-master image via the raw URL-rewrite path, with
    the ``{w}x{h}`` template up to 5000x5000 otherwise. The requested
    sidecar/embedded formats are the writers' job: sidecars convert the
    served bytes to the selected format (or keep their true extension),
    and embedding normalizes to jpg.
    """
    dimension = hooks.psetting(CTX_APPLE, "metadata_cover_dimension", CoverDimensions.Px320)
    is_origin = str(getattr(dimension, "value", dimension)) == "origin"
    if is_origin:
        try:
            url = provider.cover_raw_url(raw)
        except Exception:
            url = ""
        if not url:
            # Same-size fallback: the template at its largest before
            # giving up, mirroring the engine's original-mode fallback.
            try:
                url = provider.cover_url(raw, 5000)
            except Exception:
                url = ""
    else:
        try:
            size = int(dimension)
        except (TypeError, ValueError):
            size = 320
        try:
            url = provider.cover_url(raw, size)
        except Exception:
            url = ""
    if not url:
        return None
    try:
        response = _pooled_session().get(url, timeout=30)
        response.raise_for_status()
    except Exception:
        logger.debug("Apple cover fetch failed", exc_info=True)
        return None
    else:
        return response.content or None


def write_sidecars(
    hooks: AppleJobHooks,
    dest: pathlib.Path,
    lyrics_synced: str,
    lyrics_unsynced: str,
    cover_data: bytes | None,
    collection: bool,
    ttml_verbatim: str = "",
    options: _JobOptions | None = None,
) -> None:
    """Lyrics and cover sidecars per the shared toggles.

    The per-format matrix (spec section 9.1): independent sidecar toggles
    (.lrc; .ttml on Apple; .txt under the existing unsynced rule;
    extensions never faked; all embed x sidecar combinations valid). SRT
    is not shipped.
    """
    options = options or job_options(hooks)
    for text, suffix in lyrics_sidecar_choices(
        synced=lyrics_synced,
        plain=lyrics_unsynced,
        ttml=ttml_verbatim,
        lyrics_file=bool(options.option("lyrics_file", False)),
        synced_only=bool(options.option("lyrics_file_synced_only", False)),
        ttml_file=bool(options.option("lyrics_ttml_file", False)),
        is_apple=True,
    ):
        write_text_sidecar(dest.parent, dest.stem, suffix, text)
    # Same gate as the fetch decision above: a lone track files its cover
    # only with the single-track opt-in.
    want_cover_file = _want_cover_file(
        bool(options.option("cover_album_file", True)),
        bool(collection),
        bool(options.option("cover_single_track_file", False)),
    )
    if want_cover_file and cover_data:
        write_cover_sidecar(
            dest.parent,
            cover_data,
            cover_sidecar_format(_data(hooks), "apple_cover_file_format"),
            ffmpeg_path=cover_convert_ffmpeg(hooks),
        )


# --------------------------------------------------------------------------
# Ownership gate
# --------------------------------------------------------------------------


def gate_track(
    hooks: AppleJobHooks, provider, track_id: str, requested_rank: int, force: bool, audio_type: str | None = None
) -> tuple[str | None, dict | None]:
    """Ownership verdict plus the record it was read from: 'skip' when an
    owned copy is current, 'force' when owned but stale, (None, None)
    when nothing is owned. Ranked on the servable ceiling: cookies tier
    HIGH settles whatever was asked; wrapper tier uses the track's own
    ceiling (an AAC-only master caps at HIGH, never HI_RES).

    Dual-download rows (§5.3) ask per Version (audio_type stereo/atmos),
    so owning stereo leaves the Atmos half fetching and vice versa.
    Legacy single rows (None) keep the whole-track query.
    """
    if force:
        return "force", None
    store = hooks.ownership()
    if store is None:
        return None, None
    want_type = str(audio_type or "").strip().lower() or None
    if want_type not in ("stereo", "atmos"):
        want_type = None
    try:
        if want_type in ("stereo", "atmos"):
            rec = store.ownership_of(str(track_id), audio_type=want_type)
        else:
            rec = store.ownership_of(str(track_id))
    except TypeError:
        try:
            rec = store.ownership_of(str(track_id))
        except Exception:
            logger.debug("Apple ownership lookup failed; not gating", exc_info=True)
            return None, None
    except Exception:
        logger.debug("Apple ownership lookup failed; not gating", exc_info=True)
        return None, None
    if not rec or record_names_a_broken_copy(rec):
        return None, None
    if want_type == "stereo":
        wants = False
    elif want_type == "atmos":
        wants = True
    else:
        try:
            raw = provider.get_object("track", str(track_id).removeprefix(f"{CTX_APPLE}:"))
            wants = wants_atmos(hooks) and bool(provider.has_atmos(raw))
        except Exception:
            wants = False
    try:
        raw_for_ceiling = provider.get_object("track", str(track_id).removeprefix(f"{CTX_APPLE}:"))
    except Exception:
        raw_for_ceiling = None
    try:
        ceiling = provider.advertised_ceiling(raw_for_ceiling)
    except Exception:
        ceiling = None
    try:
        # Plain test doubles implement advertised_ceiling(None-only);
        # a TypeError there means "no per-track ceiling", not a gate.
        if ceiling is None:
            try:
                ceiling = provider.advertised_ceiling(None)
            except Exception:
                ceiling = None
    except Exception:
        ceiling = None
    current = copy_is_current(rec, requested_rank, wants, ceiling)
    return ("skip", rec) if current else ("force", rec)


# --------------------------------------------------------------------------
# Supervision glue (pacing, throttling, sidecar ensure, session waits)
# --------------------------------------------------------------------------


def pacing_policy(hooks: AppleJobHooks) -> tuple[int, float]:
    """Proactive Apple pacing: pause after N songs for N seconds.

    Same shape as TIDAL's api_rate_limit_*. Read on every track (a
    settings change takes effect on the next download, never the next
    restart) and best-effort: a value that cannot be read means no
    pause, never a download that will not start. An old stub without
    the fields reads as (0, 0.0) so it never pauses.
    """
    try:
        return supervision_pacing_policy(
            hooks.apple_setting("pacing_batch_size", 0),
            hooks.apple_setting("pacing_delay_sec", 0.0),
        )
    except Exception:
        return 0, 0.0


def pace_if_due(hooks: AppleJobHooks, pos_1based: int, job_abort, qid: int = 0) -> bool:
    """Stand back when this 1-based track opens a new Apple pacing batch.

    Returns False only when STOP lands mid-pause (the caller aborts the
    job). The pause is a deliberate stall, logged at INFO like TIDAL's
    so a support bundle names it instead of showing a silent gap.
    """
    every, seconds = pacing_policy(hooks)
    if not every or seconds <= 0:
        return True
    try:
        due = pacing_due(int(pos_1based), int(every))
    except Exception:
        due = False
    if not due:
        return True
    logger.info(pacing_message(seconds, every))
    with contextlib.suppress(Exception):
        hooks.status(f"Pausing Apple downloads for {float(seconds):g}s…")
    return bool(sleep_abortable(float(seconds), job_abort))


def throttle_delay(attempt: int, exc) -> float:
    """Reactive 429 wait: Retry-After wins, else exponential, capped."""
    try:
        retry_after = parse_retry_after(exc)
    except Exception:
        retry_after = None
    try:
        return float(supervision_throttle_delay(int(attempt), retry_after))
    except Exception:
        return 5.0


def throttle_wait(hooks: AppleJobHooks, qid: int, wait: float, job_abort, track_id: str = "") -> bool:
    """Wait out a license-exchange 429 with a visible resume countdown.

    The row stays in Downloading with its countdown (a presentation, not
    a new state); STOP lands promptly and returns False. RETRY ALL covers
    anything manually stopped because a stop settles the row cancelled.
    Ticks the countdown about once a second so the drawer visibly counts
    down instead of stalling silently.
    """
    try:
        total = max(0.0, float(wait))
    except (TypeError, ValueError):
        total = 0.0
    deadline = time.monotonic() + total
    with contextlib.suppress(Exception):
        hooks.status(throttled_message(total))
    with contextlib.suppress(Exception):
        hooks.queue_status(int(qid), "running", throttled_message(total))
    last_shown = -1
    while True:
        if job_abort.is_set():
            return False
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return True
        shown = round(remaining)
        if shown != last_shown and shown >= 0:
            last_shown = shown
            with contextlib.suppress(Exception):
                hooks.status(throttled_message(remaining))
            with contextlib.suppress(Exception):
                hooks.queue_status(int(qid), "running", throttled_message(remaining))
        time.sleep(min(0.25, remaining))


def set_held(hooks: AppleJobHooks, qid: int, detail: str = "") -> None:
    """Hold an Apple row with one clear message (presentation, not a state).

    The row sits under Queued with its reason; it resumes automatically
    when the runtime returns and respects STOP while it waits.
    """
    try:
        message = held_message(detail)
    except Exception:
        message = "Held: the Apple runtime is not running. Waiting for it to return."
    with contextlib.suppress(Exception):
        hooks.queue_status(int(qid), "queued", message)
    with contextlib.suppress(Exception):
        hooks.status(message)


def wait_for_session(hooks: AppleJobHooks, provider, job_abort) -> bool:
    """Wait (abortably) until the Apple session can serve again.

    The wrapper guest refreshes its own tokens, so a cheap /me probe
    finds it; a cookies export cannot be probed server-side, so the wait
    watches the file the provider names and retries once it changes.
    False when STOP lands.
    """
    cookies_before = _apple_cookies_fingerprint(str(getattr(provider, "cookies_path", "") or ""))
    while not job_abort.is_set():
        if str(getattr(provider, "wrapper_url", "") or "").strip():
            try:
                state = hooks.refresh_wrapper_auth(timeout=5) or {}
                if bool(state.get("logged_in")):
                    return True
            except Exception:
                logger.debug("Apple wrapper recovery probe failed", exc_info=True)
        cookies_now = _apple_cookies_fingerprint(str(getattr(provider, "cookies_path", "") or ""))
        if cookies_now != cookies_before:
            # A fresh export landed (in place or at a new path): the
            # retried fetch is the proof.
            return True
        if not sleep_abortable(HELD_POLL_SEC, job_abort):
            return False
    return False


def ensure_sidecar(hooks: AppleJobHooks, qid: int, job_abort, *, need_wrapper: bool) -> bool:
    """Lazily start the sidecar when this job needs it; hold until ready.

    Search, browsing and link resolution never call here (they ride the
    dev token alone). Returns True when the job may proceed, False when
    STOP landed while held. One failed start is a blip the next poll may
    heal, so the row is HELD with the setup words and re-probed; a runtime
    that fails to start repeatedly cannot come back on its own, so the
    row stops waiting, setup opens, and the job fails with those words
    (RETRY is the way back once the runtime works). Never re-provisions:
    the runtime is the setup wizard's artifact.
    """
    if not need_wrapper:
        return True
    if job_abort.is_set():
        return False
    # No manager and no wrapper URL on a plain stub means there is no
    # sidecar to supervise: proceed so old tests keep fetching.
    manager = hooks.runtime()
    provider = hooks.provider()
    wrapper_url = ""
    try:
        wrapper_url = str(getattr(provider, "wrapper_url", "") or "").strip()
    except Exception:
        wrapper_url = ""
    if manager is None and not wrapper_url:
        return True
    sup = hooks.supervisor()
    # The wrapper tier was never set up (no URL and no persisted port):
    # the cookies path serves alone. Only a configured tier that stops
    # answering holds.
    port_probe = hooks.wrapper_port()
    if not wrapper_url and not port_probe:
        return True
    # Poll until the supervised port exists and answers, or STOP lands.
    # The wizard may pick the port concurrently; ensure_started probes
    # first, so a healthy sidecar returns without sleeping, and it also
    # migrates a sidecar still publishing on a wildcard host address.
    failures = 0
    while not job_abort.is_set():
        port = hooks.wrapper_port()
        if sup is not None and port:
            try:
                # The idle stop decides under the same guard: a start in
                # flight is never stopped out from under itself.
                with hooks.sidecar_guard():
                    started = sup.ensure_started(http_port=port)
            except Exception:
                logger.debug("Wrapper ensure-start failed", exc_info=True)
                started = False
            if started:
                with contextlib.suppress(Exception):
                    hooks.note_activity()
                # A row held on an earlier poll resumes visibly.
                with contextlib.suppress(Exception):
                    hooks.queue_status(int(qid), "running", "")
                return True
            # Still down: hold with the setup words rather than fail a
            # blip, but bounded: a start that keeps failing needs the
            # wizard, and a held row cannot wait forever.
            set_held(hooks, qid)
            terminal_message = f"Apple's runtime did not start. Finish setup in {SETUP_PATH}, then retry."
            failures += 1
        else:
            # Configured for the wrapper tier but no supervised port yet:
            # the wizard has not picked one. Hold with the setup words
            # instead of failing the wall.
            set_held(hooks, qid, "The wrapper tier has no port yet.")
            terminal_message = f"Apple's wrapper tier is not set up. Finish setup in {SETUP_PATH}, then retry."
            failures += 1
        if failures >= max(1, int(HELD_START_FAILURES)):
            with contextlib.suppress(Exception):
                hooks.setup_requested("setup")
            with contextlib.suppress(Exception):
                hooks.status(terminal_message)
            raise _AppleSetupRequired(terminal_message)
        if not sleep_abortable(HELD_POLL_SEC, job_abort):
            return False
    return False


# --------------------------------------------------------------------------
# Per-track delivery
# --------------------------------------------------------------------------


def deliver_track(
    hooks: AppleJobHooks,
    provider,
    row: dict,
    header: dict | None,
    *,
    type_media: str,
    file_template: str,
    collection: bool,
    list_pos: int,
    list_total: int,
    num_volumes: int,
    audio_type,
    requested_rank: int,
    requested_tier: QualityTier | None,
    ceiling_rank: int,
    force: bool,
    owned_path: str | None,
    job_abort,
    signals=None,
    options: _JobOptions | None = None,
    qid: int = 0,
) -> dict:
    """Fetch, verify, place, tag and sidecar one Apple track.

    Verification is always-on pre-swap (spec §6.1): the ffmpeg
    decode-to-null check runs on the staged file during the finishing
    phase, never a setting. Integrity failures retry automatically (2
    re-downloads, 1 for outbreak-era Encoded date >= 2025-05, with brief
    pacing); persistent failures land in Quarantine plus the skip-list and
    raise with the plain-words verdict. Each Version verifies
    independently; no conversion runs before verification passes; no
    patching.

    Returns {"path", "quality"} for the done event. Raises
    AppleTrackUnavailable when Apple withholds the song and
    AppleDownloadError (or anything gamdl raises) otherwise.
    """
    options = options or job_options(hooks)
    track_id = str(row.get("id"))
    raw_id = track_id.removeprefix(f"{CTX_APPLE}:")
    raw = provider.get_object("track", raw_id)
    facts = provider.track_facts(raw)
    relative = track_relative(
        hooks,
        row,
        header,
        type_media,
        file_template,
        list_pos,
        list_total,
        num_volumes,
        facts_isrc=str(facts.get("isrc") or ""),
    )
    data = hooks.settings().data
    base = pathlib.Path(str(data.download_base_path)).expanduser()
    # Lossless stereo lands as FLAC; the true extension is
    # only known after the fetch, so guess here and correct per attempt
    # below (the TIDAL pipeline's guess-then-correct shape).
    guess_ext_value = guess_ext(hooks, provider, audio_type, requested_rank)
    # The skip check reads the REQUESTED destination: pick_destination
    # loops until it finds a free name, so asking it first would make the
    # exists check below permanently false and duplicate owned files.
    exact = base / f"{relative}{guess_ext_value}"
    exact.parent.mkdir(parents=True, exist_ok=True)
    if force:
        # Overwrite the copy THIS track owns, not the template path: two
        # distinct tracks can render to one relative name (the second owns
        # the _01 suffixed file), and the template path would overwrite
        # the sibling's audio while its record goes stale.
        dest = pathlib.Path(owned_path) if owned_path else exact
        dest.parent.mkdir(parents=True, exist_ok=True)
    elif data.skip_existing and exact.exists():
        raise _AppleSkipped()
    else:
        dest = pick_destination(base, relative, guess_ext_value)
    # The Version this fetch verifies as, for the per-version skip-list.
    # resolve_stream decides Atmos from the raw + ask; the delivered word
    # confirms it per attempt below.
    version_hint = str(getattr(audio_type, "value", audio_type) or "").strip().lower() or None
    if version_hint not in ("stereo", "atmos"):
        version_hint = None
    attempt = 0
    last_encoded: str | None = None
    last_staged: pathlib.Path | None = None
    outbreak_seen = False

    def _drop_hold() -> None:
        """Delete the superseded retry hold, if any, and forget it."""
        nonlocal last_staged
        if last_staged is not None:
            with contextlib.suppress(OSError):
                if "quarantine-" in str(last_staged.parent):
                    shutil.rmtree(last_staged.parent, ignore_errors=True)
            last_staged = None

    # Every attempt fetches at the row's pinned ask, never the live setting.
    while True:
        info = None
        flac_tmpdir: str | None = None
        try:
            try:
                info = provider.resolve_stream(raw, requested_tier, audio_type)
            except Exception as resolve_exc:
                # A refusal is TIDAL-vocabulary for "gone": kept out of the fail
                # count so one delisted track cannot fail its whole album.
                if provider.classify_refusal(resolve_exc).kind is RefusalKind.UNAVAILABLE:
                    raise AppleTrackUnavailable(str(resolve_exc) or "not available on Apple Music") from resolve_exc
                # The engine verifies inside its own fetch (decode-to-null
                # before resolve_stream returns), so a corrupt delivery can
                # raise here with no staged file to hold: it still enters
                # the integrity retry/quarantine path below (without bytes
                # for the quarantine copy or the Encoded-date read).
                raise
            staged = pathlib.Path(str(info.local_file))
            if not staged.is_file():
                raise AppleDownloadError("Apple download produced no file")  # noqa: TRY301
            atmos = str((info.delivered or {}).get("audio_type") or "") == str(AudioType.ATMOS)
            # The true extension off the delivery: ALAC stereo becomes
            # .flac when the FLAC toggle is on (and an ffmpeg binary is
            # at hand); scope "all" additionally converts lossy stereo
            # by re-encoding it. AAC (lossless-only scope) and Atmos
            # always stay .m4a. A HI_RES ask can fall back to AAC on an
            # AAC-only master, so this is decided per attempt, never
            # from the ask alone.
            mode = flac_mode(hooks, info, atmos=atmos)  # "lossless", "lossy", or ""
            if mode and not flac_ffmpeg(hooks):
                # "Continue anyway" past the ffmpeg gate (or a binary
                # that went away mid-job): keep the original .m4a rather
                # than fail a fetchable track.
                logger.debug("Apple FLAC extraction skipped (no ffmpeg); keeping the original file")
                mode = ""
            want_ext = ".flac" if mode else ".m4a"
            if dest.suffix != want_ext:
                if force and owned_path:
                    owned = pathlib.Path(owned_path)
                    dest = owned.with_suffix(want_ext) if owned.suffix != want_ext else owned
                    dest.parent.mkdir(parents=True, exist_ok=True)
                else:
                    exact_true = base / f"{relative}{want_ext}"
                    if not force and data.skip_existing and exact_true.exists():
                        raise _AppleSkipped()  # noqa: TRY301
                    dest = pick_destination(base, relative, want_ext)
            verify_staged(hooks, staged, expect_atmos=atmos)
            if job_abort.is_set():
                raise _AppleAborted()  # noqa: TRY301
            if mode:
                # Verified above, so conversion runs on known-good bytes
                # (spec §6: no conversion before verification passes).
                # The converted file lands outside the provider's workdir,
                # which discard_delivery removes below.
                staged, flac_tmpdir = extract_flac(hooks, staged)
            try:
                place_file(staged, dest)
            finally:
                if flac_tmpdir is not None:
                    with contextlib.suppress(OSError):
                        shutil.rmtree(flac_tmpdir, ignore_errors=True)
        except _AppleAborted:
            if info is not None:
                try:
                    provider.discard_delivery(str(info.local_file))
                except Exception:
                    logger.debug("Could not discard the Apple staging area", exc_info=True)
            if flac_tmpdir is not None:
                with contextlib.suppress(OSError):
                    shutil.rmtree(flac_tmpdir, ignore_errors=True)
            _drop_hold()
            raise
        except Exception as exc:
            # The staged bytes still exist here (discard runs below), so
            # read the Encoded date and hold quarantine bytes FIRST: after
            # discard the workdir is gone and both reads would miss. A
            # resolve-stage integrity failure carries its rejected bytes on
            # the exception itself (the engine transfers workdir ownership
            # outward instead of deleting it); without them it still
            # retries and marks the skip-list, just without bytes or a date.
            failed_staged: pathlib.Path | None = None
            preserved_workdir = ""
            if info is not None:
                try:
                    candidate = pathlib.Path(str(info.local_file))
                    failed_staged = candidate if candidate.is_file() else None
                except Exception:
                    failed_staged = None
            else:
                try:
                    exc_staged = str(getattr(exc, "staged_path", "") or "")
                    preserved_workdir = str(getattr(exc, "workdir", "") or "")
                    candidate = pathlib.Path(exc_staged)
                    failed_staged = candidate if exc_staged and candidate.is_file() else None
                except Exception:
                    failed_staged = None
            is_integrity = is_integrity_failure(exc)
            if not is_integrity:
                if info is not None:
                    try:
                        provider.discard_delivery(str(info.local_file))
                    except Exception:
                        logger.debug("Could not discard the Apple staging area", exc_info=True)
                if flac_tmpdir is not None:
                    with contextlib.suppress(OSError):
                        shutil.rmtree(flac_tmpdir, ignore_errors=True)
                _drop_hold()
                raise
            # Integrity failure: sharpen the budget on outbreak-era bytes.
            # The Encoded date rides the failed file itself; unknown stays
            # on the normal budget (never the sharpened one).
            try:
                encoded_text = staged_encoded_date(hooks, failed_staged) if failed_staged else None
            except Exception:
                encoded_text = None
            if encoded_text:
                last_encoded = encoded_text
            with contextlib.suppress(Exception):
                outbreak_seen = outbreak_seen or is_outbreak_era(parse_encoded_date(encoded_text))
            hold_path: pathlib.Path | None = None
            if failed_staged is not None:
                try:
                    hold = pathlib.Path(tempfile.mkdtemp(prefix="waves-apple-quarantine-")) / "failed.m4a"
                    shutil.copyfile(failed_staged, hold)
                    hold_path = hold
                except Exception:
                    hold_path = None
            if info is not None:
                try:
                    provider.discard_delivery(str(info.local_file))
                except Exception:
                    logger.debug("Could not discard the Apple staging area", exc_info=True)
            if preserved_workdir:
                # The engine's rejected bytes were copied into the hold
                # above (or there was nothing to hold): either way the
                # preserved workdir is spent and must not leak.
                with contextlib.suppress(OSError):
                    shutil.rmtree(preserved_workdir, ignore_errors=True)
            if hold_path is not None:
                # A superseded hold is deleted with its temp dir: only the
                # latest failure's bytes are quarantined, the earlier
                # copies are retry debris, never keepsakes.
                previous = last_staged
                last_staged = hold_path
                if previous is not None and previous != hold_path:
                    with contextlib.suppress(OSError):
                        if "quarantine-" in str(previous.parent):
                            shutil.rmtree(previous.parent, ignore_errors=True)
            try:
                budget = integrity_retries(_data(hooks), outbreak=outbreak_seen)
            except Exception:
                budget = 1 if outbreak_seen else 2
            if attempt >= budget:
                # Persistent failure: quarantine (keep-by-default) plus the
                # provider-scoped skip-list. Filed under the DELIVERED
                # Version: an Atmos ask for a stereo-only track falls back,
                # so its corrupt bytes belong to stereo (the effective
                # version the gate and the clear both read). A resolve-stage
                # failure never produced a delivered word, but the effective
                # Version is still knowable (asked AND offered); only a
                # probe that fails too falls back to the ask.
                if info is not None:
                    version = "atmos" if locals().get("atmos", False) else "stereo"
                else:
                    try:
                        version = effective_version(provider, track_id, audio_type)
                    except Exception:
                        version = ""
                    if version not in ("stereo", "atmos"):
                        if version_hint in ("stereo", "atmos"):
                            version = version_hint
                        else:
                            try:
                                version = str(getattr(audio_type, "value", audio_type) or "").strip().lower()
                            except Exception:
                                version = ""
                            version = version if version in ("stereo", "atmos") else "stereo"
                if last_staged is not None and last_staged.is_file():
                    try:
                        quarantine_file(
                            hooks, last_staged, relative=relative, track_id=track_id, audio_type=version, qid=qid
                        )
                    except Exception:
                        logger.debug("Could not quarantine the Apple file", exc_info=True)
                    _drop_hold()
                try:
                    skiplist_add(hooks, track_id, version, last_encoded)
                except Exception:
                    logger.debug("Could not mark the Apple skip-list", exc_info=True)
                raise AppleDownloadError(INTEGRITY_FAIL_MESSAGE) from exc
            attempt += 1
            # Mid-run integrity retry keeps the row's progress (the caller
            # ticks per settled track, so nothing moves) with a brief note.
            try:
                if signals is not None:
                    signals.track_event.emit({"id": track_id, "status": "running"})
            except Exception:
                logger.debug("Could not emit the Apple integrity-retry event", exc_info=True)
            with contextlib.suppress(Exception):
                hooks.status(f"Retrying {row.get('title') or track_id} (integrity)…")
            logger.warning(
                "Apple integrity check failed for %s (attempt %s); retrying",
                hooks.redact(track_id),
                attempt + 1,
            )
            try:
                delay = integrity_retry_delay(_data(hooks))
            except Exception:
                delay = 5.0
            sleep_ok = sleep_abortable(delay, job_abort) if delay > 0 else True
            if delay > 0 and not sleep_ok:
                _drop_hold()
                raise _AppleAborted() from exc
            if job_abort.is_set():
                _drop_hold()
                raise _AppleAborted() from exc
            continue
        else:
            try:
                provider.discard_delivery(str(info.local_file))
            except Exception:
                logger.debug("Could not discard the Apple staging area", exc_info=True)
            _drop_hold()
            break
    lyrics_synced, lyrics_unsynced, lyrics_ttml = lyrics_full(hooks, provider, row, facts, options=options)
    cover_data = cover_bytes(hooks, provider, raw) if wants_cover(hooks, collection, options=options) else None
    # Embedded art stays jpg (spec 9.1): an original-master PNG is
    # converted for the tag while the sidecar keeps the master bytes.
    embed_cover = embed_cover_bytes(hooks, cover_data) if options.option("metadata_cover_embed", True) else None
    # The embed toggle is the single source for embedding; the sidecars
    # below still receive the fetched text.
    embed_lyrics = bool(options.option("lyrics_embed", False))
    if not tag_apple_file(
        dest,
        title=str(row.get("title") or ""),
        facts=facts,
        lyrics_synced=lyrics_synced if embed_lyrics else "",
        lyrics_unsynced=lyrics_unsynced if embed_lyrics else "",
        cover_data=embed_cover,
        mark_explicit=bool(data.mark_explicit),
        metadata_target_upc=str(getattr(data, "metadata_target_upc", "UPC") or "UPC"),
        audio_type="atmos" if atmos else "stereo",
        **hooks.tag_write_flags(),
    ):
        logger.debug("Apple tagging reported failure for %s", hooks.redact(track_id))
    write_sidecars(
        hooks,
        dest,
        lyrics_synced,
        lyrics_unsynced,
        cover_data,
        collection,
        ttml_verbatim=lyrics_ttml,
        options=options,
    )
    # Honest delivered tier: the provider probed the staged
    # bytes (ALAC 24/96 where the master tops out stays 24/96 in the
    # record); the landed file re-probes for depth/rate so the ownership
    # row carries reality, not the ask. Detail rides bit_depth/
    # sample_rate/codecs label text, never rank.
    try:
        landed_probe = apple_engine.probe_audio_file(dest, probe_binary(hooks)) or {}
    except Exception:
        landed_probe = {}
    try:
        delivered = dict(getattr(info, "delivered", None) or {})
    except Exception:
        delivered = {}
    tier = str(delivered.get("tier") or QualityTier.HIGH.value)
    try:
        probe_depth = landed_probe.get("bit_depth")
        depth = int(probe_depth) if isinstance(probe_depth, int) and probe_depth > 0 else None
        if depth is None and delivered.get("bit_depth") is not None:
            depth = int(delivered.get("bit_depth"))
    except (TypeError, ValueError):
        depth = None
    try:
        raw_rate = landed_probe.get("sample_rate") or delivered.get("sample_rate")
        rate = int(str(raw_rate or "").strip()) if str(raw_rate or "").strip().isdigit() else None
    except (TypeError, ValueError):
        rate = None
    # A landed ALAC file re-derives its tier off its own bytes (a 24/96
    # master asked as HI_RES stays HI_RES with rate 96000; a 16/44.1
    # master asked as HI_RES lands LOSSLESS, honestly). A converted
    # FLAC probes as "flac" and answers the same rungs.
    # Source-gated, never container-gated: a transcoded AAC also probes
    # as FLAC, but it keeps its staged HIGH tier and must never promote
    # off its new container.
    try:
        codecs_landed = str(landed_probe.get("codec") or delivered.get("codecs") or info.codecs or "")
        source_codecs = str(getattr(info, "codecs", "") or delivered.get("codecs") or "")
        if not atmos and "alac" in source_codecs.lower().replace("-", "").replace("_", ""):
            tier = apple_engine.apple_tier_for_delivery(codecs_landed, depth, rate or "", fallback=tier)
    except Exception:
        logger.debug("Apple honest-tier re-probe failed; keeping the staged tier", exc_info=True)
    # Per-track ceiling for the ownership record: an AAC-only
    # master caps at HIGH even when the job asked HI_RES, so the copy
    # settles instead of reopening an upgrade that is not coming. Falls
    # back to the job's ceiling when the track cannot be read.
    try:
        per_track_ceiling = provider.advertised_ceiling(raw)
    except Exception:
        per_track_ceiling = None
    try:
        ceiling_for_record = int(per_track_ceiling) if per_track_ceiling is not None else int(ceiling_rank)
    except (TypeError, ValueError):
        ceiling_for_record = int(ceiling_rank)
    return {
        "path": str(dest),
        "quality": {
            "tier": tier,
            "audio_mode": "DOLBY_ATMOS" if atmos else "STEREO",
            "bit_depth": depth,
            "sample_rate": rate,
            "codecs": str(info.codecs or ""),
            "requested_rank": int(requested_rank),
            "ceiling_rank": int(ceiling_for_record),
        },
    }


# --------------------------------------------------------------------------
# Job orchestration
# --------------------------------------------------------------------------


def run_apple_job(hooks: AppleJobHooks, qid, spec, obj, *, signals, job_abort, file_template) -> str:
    """Download one Apple track or collection, emitting the shared
    lifecycle events so queue rows, delivered words, ownership and badges
    behave exactly like TIDAL jobs.

    Returns "" on a clean run; raises DownloadIncomplete naming the
    shortfall when tracks failed (the settlement's row reason), like the
    collection path it mirrors. Sequential per track: gamdl's stack runs
    one song at a time, and serial fetches stay under Apple's
    undocumented license-exchange rate limit.
    """
    provider = hooks.provider()
    type_media, collection, media_id = spec.kind, spec.collection, spec.media_id
    # Dual-download Version (§5.2): explicit stereo/atmos rows pin their
    # Version; legacy single rows (None, toggle off) keep the existing
    # instead-of behavior (ATMOS when toggled, else stereo).
    job_atype = (
        str(getattr(spec, "audio_type", None) or (hooks.job_audio_type(qid) or "") or "").strip().lower() or None
    )
    if job_atype not in ("stereo", "atmos"):
        job_atype = None
    if job_atype == "atmos":
        audio_type = AudioType.ATMOS
    elif job_atype == "stereo":
        audio_type = AudioType.STEREO
    else:
        audio_type = fetch_audio_type(hooks)
    # The Version this job fetches as, for the per-version skip-list.
    # Legacy single rows (None) resolve to the concrete fetch (stereo on
    # the stereo default, Atmos on "both"): an Atmos quarantine never
    # skips a stereo fetch, and vice versa. Ownership keeps its own legacy
    # whole-track query above; the skip-list is always per-version.
    try:
        job_version = str(getattr(audio_type, "value", audio_type) or "").strip().lower()
    except Exception:
        job_version = ""
    if job_version not in ("stereo", "atmos"):
        job_version = "stereo"
    ask_tier = hooks.job_quality(qid)
    requested_rank = target_rank(hooks, ask_tier)
    if ask_tier is None:
        # A row that pinned nothing (legacy or unreadable) fetches at the
        # setting, read once so the whole run shares one request.
        ask_tier = setting_tier(hooks)
    try:
        ceiling_probe = provider.advertised_ceiling(None)
    except Exception:
        ceiling_probe = None
    try:
        if ceiling_probe is None and bool(getattr(provider, "wrapper_available", False)):
            # Wrapper up but object unknown: predict the ask (the per-track
            # gate and the deliver record still read the track's own
            # ceiling, so AAC-only masters settle honestly after one fetch).
            ceiling_rank = int(requested_rank)
        elif ceiling_probe is None:
            ceiling_rank = quality_rank(QualityTier.HIGH)
        else:
            ceiling_rank = int(ceiling_probe)
    except Exception:
        ceiling_rank = quality_rank(QualityTier.HIGH)
    force = media_id in hooks.redownload_overrides()
    if collection:
        header = provider.row_for(type_media, obj)
        rows = provider.collection_items(obj)
    else:
        header = None
        rows = [provider.row_for("track", obj)]
    rows = [row for row in rows if isinstance(row, dict) and row.get("id")]
    total = len(rows)
    if not total:
        raise DownloadIncomplete("Apple served an empty track list")
    # Empty-dual withdrawal (§5.2): an Atmos row with nothing to fetch
    # (all tracks stereo-only) leaves no row, not a done row with no
    # files. Runs on the worker (may fetch track raws), never the GUI.
    if job_atype == "atmos":
        atmos_capable = 0
        for row in rows:
            try:
                raw = provider.get_object("track", str(row.get("id")).removeprefix(f"{CTX_APPLE}:"))
                if bool(provider.has_atmos(raw)):
                    atmos_capable += 1
                    break
            except Exception:
                # A track that cannot be read cannot prove it has no
                # Atmos: keep the row (it will fail/skip per-track below,
                # never silently vanish).
                atmos_capable += 1
                break
        if not atmos_capable:
            # Withdraw: remove the queue row so the click leaves one row
            # (stereo), not a done row with no files. The bypass permit is
            # released by the job body's finally, the one place that runs
            # however this job ends, so one release covers every exit here.
            hooks.remove_row(qid)
            hooks.emit_queue()
            return " (already downloaded)"
    num_volumes = max([int(row.get("vol") or 1) for row in rows] + [1])
    ok = fail = skipped = unavailable = quarantined = 0
    failed_names: list[str] = []
    landed: list = []
    # The lyrics/art options this job runs with: the row's per-click
    # Chooser pins when it has any, the provider's stored options otherwise.
    options = job_options(hooks, getattr(spec, "chooser_toggles", None))
    # Session supervision (spec §3): the sidecar starts lazily
    # on the first Apple download that needs it. Cookies-tier asks (HIGH)
    # never touch it; only a LOSSLESS-or-better ask waits here.
    try:
        need_wrapper = bool(needs_wrapper(requested_rank))
    except Exception:
        need_wrapper = False
    if need_wrapper:
        try:
            ensured = ensure_sidecar(hooks, qid, job_abort, need_wrapper=True)
        except _AppleSetupRequired as exc:
            # The runtime cannot come back on its own: fail with the setup
            # words so the row is retryable once setup works, never a
            # forever hold.
            raise DownloadIncomplete(str(exc)) from exc
        except Exception:
            logger.debug("Apple sidecar ensure failed; proceeding to fetch", exc_info=True)
            ensured = True
        if not ensured:
            raise _AppleAborted()
    for pos, row in enumerate(rows, start=1):
        if job_abort.is_set():
            break
        # Proactive pacing (spec §3): pause after N songs for
        # N seconds, same shape as TIDAL's. STOP lands promptly.
        try:
            pace_ok = pace_if_due(hooks, pos, job_abort, qid)
        except Exception:
            pace_ok = True
        if pace_ok is False:
            raise _AppleAborted()
        track_id = str(row.get("id"))
        # Atmos rows skip stereo-only tracks (no Atmos to fetch); stereo
        # rows fetch stereo for every track (every Apple song has stereo).
        # Legacy single rows keep the existing behavior (fetch what the
        # toggle names, falling back to stereo).
        if job_atype == "atmos":
            try:
                raw_probe = provider.get_object("track", track_id.removeprefix(f"{CTX_APPLE}:"))
                has_at = bool(provider.has_atmos(raw_probe))
            except Exception:
                has_at = True
            if not has_at:
                skipped += 1
                signals.track_event.emit({"id": track_id, "status": "skipped"})
                emit_progress(signals, collection, pos, total, media_id, qid)
                continue
        expected_word = queue_expected_word(hooks, job_atype, requested_rank=requested_rank, ceiling_rank=ceiling_rank)
        signals.track_event.emit(
            {
                "id": track_id,
                "title": str(row.get("title") or ""),
                "num": int(row.get("num") or pos),
                "vol": int(row.get("vol") or 1),
                "duration": str(row.get("duration") or ""),
                "status": "running",
                "expected": expected_word,
            }
        )
        verdict, gate_rec = gate_track(hooks, provider, track_id, requested_rank, force, audio_type=job_atype)
        if verdict == "skip":
            skipped += 1
            signals.track_event.emit({"id": track_id, "status": "skipped", "owned": "own"})
            emit_progress(signals, collection, pos, total, media_id, qid)
            continue
        # Integrity skip-list (spec §6.3): bulk runs auto-skip quarantined
        # tracks, shown plainly like IN LIBRARY rows. REDOWNLOAD (force)
        # and an explicit RETRY (single or RETRY ALL, spec §6.4) are the
        # re-asks that bypass it: the row's own spec carries is_retry, so
        # each retried row (each Version of a dual pair included) bypasses
        # on its own, nothing is counted or released, and a dispatch that
        # never runs a job leaks nothing. Per-version: an Atmos quarantine
        # never skips its stereo sibling. Fresh clicks (even
        # single-track) also skip: otherwise the mark would be bypassable
        # by re-clicking and REDOWNLOAD would not be the way back.
        bypass = bool(force) or bool(getattr(spec, "is_retry", False))
        # The Version the fetch will verify as (not the bare ask): an
        # Atmos ask for a stereo-only track falls back, and its failure is
        # filed under stereo. Computed for every track; the gate below and
        # the success-clear both read it.
        try:
            check_version = effective_version(provider, track_id, audio_type)
        except Exception:
            check_version = job_version
            logger.debug("Apple effective-version probe failed; gating on the ask", exc_info=True)
        if not bypass:
            # Gate on the fetched Version (check_version above).
            try:
                skip_mark = skiplist_get(hooks, track_id, check_version)
            except Exception:
                skip_mark = None
            if skip_mark is not None:
                skipped += 1
                signals.track_event.emit({"id": track_id, "status": "skipped", "quarantined": True})
                emit_progress(signals, collection, pos, total, media_id, qid)
                continue
        # An upgrade run overwrites the stale copy in place; without the
        # per-track verdict an upgrade would land beside it as a numbered
        # copy and the old file would stay behind.
        track_force = force or verdict == "force"
        owned_path = str((gate_rec or {}).get("path") or "") or None
        attempts = 0
        try:
            while True:
                try:
                    delivered = deliver_track(
                        hooks,
                        provider,
                        row,
                        header,
                        type_media=type_media,
                        file_template=file_template,
                        collection=collection,
                        list_pos=pos,
                        list_total=total,
                        num_volumes=num_volumes,
                        audio_type=audio_type,
                        requested_rank=requested_rank,
                        requested_tier=ask_tier,
                        ceiling_rank=ceiling_rank,
                        force=track_force,
                        owned_path=owned_path,
                        job_abort=job_abort,
                        signals=signals,
                        options=options,
                        qid=qid,
                    )
                    break
                except Exception as exc:
                    if isinstance(exc, AppleCredentialsError):
                        # The saved session no longer works: tell the
                        # light, hold the row with the sign-in message,
                        # and wait in place for recovery instead of
                        # failing the run (spec §3). The wrapper guest
                        # refreshes its tokens on its own; a cookies
                        # export recovers when its file or path changes.
                        # STOP lands promptly and settles the row
                        # cancelled. The retry re-runs THIS track.
                        hooks.mark_session_expired()
                        with contextlib.suppress(Exception):
                            set_held(hooks, qid, "Sign in again in Settings under Providers, Apple Music.")
                        if not wait_for_session(hooks, provider, job_abort):
                            raise _AppleAborted() from exc
                        continue
                    # A dead sidecar holds the row while a return is
                    # plausible: one clear message, automatic resume. A
                    # runtime that will not start ends the run through
                    # the ensure's setup verdict instead of holding on.
                    try:
                        down = bool(is_wrapper_down_error(exc))
                    except Exception:
                        down = False
                    if down:
                        logger.warning("Apple runtime down mid-run; holding %s", hooks.redact(track_id))
                        with contextlib.suppress(Exception):
                            set_held(hooks, qid)
                        try:
                            ensured = ensure_sidecar(hooks, qid, job_abort, need_wrapper=True)
                        except _AppleSetupRequired:
                            # The runtime cannot come back on its own: the
                            # track handler below ends the run with the
                            # setup words instead of holding again.
                            raise
                        except Exception:
                            logger.debug("Apple sidecar re-ensure failed", exc_info=True)
                            ensured = False
                        if not ensured or job_abort.is_set():
                            raise _AppleAborted() from exc
                        continue
                    try:
                        throttled = provider.classify_refusal(exc).kind is RefusalKind.THROTTLED
                    except Exception:
                        throttled = False
                    if not throttled:
                        raise
                    try:
                        wait = float(throttle_delay(attempts, exc))
                    except Exception:
                        wait = 5.0
                    attempts += 1
                    logger.warning(
                        "Apple rate-limited this job; retrying %s in %ss",
                        hooks.redact(track_id),
                        round(wait, 1),
                    )
                    try:
                        waited = throttle_wait(hooks, qid, wait, job_abort, track_id)
                    except Exception:
                        # A countdown helper that cannot run keeps the
                        # previous abortable sleep there.
                        with contextlib.suppress(Exception):
                            hooks.status(f"Apple is rate-limiting; retrying in {int(wait)}s…")
                        waited = sleep_abortable(wait, job_abort)
                    if not waited:
                        raise _AppleAborted() from exc
        except AppleTrackUnavailable as exc:
            unavailable += 1
            signals.track_event.emit({"id": track_id, "status": "unavailable"})
            logger.info("Apple track unavailable: %s", exc)
            emit_progress(signals, collection, pos, total, media_id, qid)
            continue
        except _AppleSkipped:
            skipped += 1
            signals.track_event.emit({"id": track_id, "status": "skipped"})
            emit_progress(signals, collection, pos, total, media_id, qid)
            continue
        except _AppleAborted:
            break
        except _AppleSetupRequired as exc:
            # The runtime cannot come back on its own: end the whole run
            # with the setup words rather than failing track after track.
            raise DownloadIncomplete(str(exc)) from exc
        except Exception as exc:
            fail += 1
            failed_names.append(str(row.get("title") or track_id))
            # Integrity quarantines end FAILED in plain words (spec §6.4);
            # other failures keep the existing failed row without a reason.
            try:
                is_integrity = is_integrity_failure(exc)
            except Exception:
                is_integrity = False
            if is_integrity:
                quarantined += 1
            try:
                if is_integrity:
                    signals.track_event.emit({"id": track_id, "status": "failed", "reason": INTEGRITY_FAIL_MESSAGE})
                else:
                    signals.track_event.emit({"id": track_id, "status": "failed"})
            except Exception:
                with contextlib.suppress(Exception):
                    signals.track_event.emit({"id": track_id, "status": "failed"})
            logger.exception("Apple track failed for %s", hooks.redact(track_id))
            emit_progress(signals, collection, pos, total, media_id, qid)
            continue
        ok += 1
        landed.append(pathlib.Path(delivered["path"]))
        # A landed track proves the session works: lift the expiry marker
        # even when recovery was never observed by a probe (spec §3).
        with contextlib.suppress(Exception):
            hooks.clear_session_expired()
        # Wrapper work stamps the idle clock so an in-flight run never
        # looks idle to the sidecar stop.
        with contextlib.suppress(Exception):
            hooks.note_activity()
        # A verified copy landing clears the skip-list (REDOWNLOAD's way
        # back; also clears a stale mark when Apple re-encoded). The
        # fetched Version clears its own mark (check_version above).
        try:
            skiplist_clear(hooks, track_id, check_version)
        except Exception:
            logger.debug("Could not clear the Apple skip-list", exc_info=True)
        signals.track_event.emit(
            {
                "id": track_id,
                "status": "done",
                "path": delivered["path"],
                "quality": delivered["quality"],
            }
        )
        emit_progress(signals, collection, pos, total, media_id, qid)
    if collection and landed and hooks.settings().data.playlist_create and not job_abort.is_set():
        # The _Name.m3u8 the playlist_create setting promises, in landed
        # order (mirrors the engine's playlist_populate scope).
        header_title = ""
        try:
            header_title = str(provider.row_for(type_media, obj).get("title") or "")
        except Exception:
            logger.debug("Apple playlist title unreadable", exc_info=True)
        data = hooks.settings().data
        write_collection_playlist(
            landed,
            header_title or spec.name,
            is_album=type_media == "album",
            illegal_replacement=str(getattr(data, "filename_illegal_replacement", "") or ""),
            illegal_map=getattr(data, "filename_illegal_map", None),
        )
    # Settlement: the job body's finally drops the job's abort token and
    # relay exactly once.
    if total == 1 and not collection:
        if ok or skipped:
            return "" if ok else " (already downloaded)"
        if unavailable:
            raise DownloadIncomplete("not available on Apple Music anymore")
        if quarantined:
            raise DownloadIncomplete(INTEGRITY_FAIL_MESSAGE)
        raise DownloadIncomplete("Apple download produced no file")
    short = fail + unavailable
    if short:
        done_word = f"{ok} of {total} tracks" if ok else f"0 of {total} tracks"
        if quarantined and quarantined == fail and not unavailable:
            # Every failure is a quarantine: the row's plain-words verdict.
            raise DownloadIncomplete(f"{done_word} downloaded ({INTEGRITY_FAIL_MESSAGE})")
        raise DownloadIncomplete(f"{done_word} downloaded ({short} failed)")
    if skipped and not ok:
        return " (already downloaded)"
    return ""


def run_job_body(hooks: AppleJobHooks, qid, spec, obj, *, signals, job_abort, row_ask, name) -> None:
    """An Apple job's worker body: probe, run, settle. Mirrors the TIDAL
    body's three outcomes (cancelled / done / failed) without its engine."""
    type_media, file_template, collection, media_id = (
        spec.kind,
        spec.file_template,
        spec.collection,
        spec.media_id,
    )
    provider = hooks.provider()
    try:
        replay_row = provider.row_for(type_media, obj) if provider is not None else {}
    except Exception:
        replay_row = {}
    replay_collection = replay_row if collection else None
    if job_abort.is_set():
        hooks.queue_status(qid, "cancelled")
        hooks.download_state(media_id, "")
        hooks.bump_groups(media_id, None, "failed")
        hooks.finish_job(qid)
        return

    def replay() -> bool:
        return hooks.download_apple(
            type_media,
            replay_row,
            replay_collection,
            file_template,
            collection,
            media_id,
            # The replay keeps the row's pinned ask either way, but only a
            # retried row replays as a retry (its skip-list bypass rides
            # the spec flag); a fresh row replays fresh, so quarantined
            # tracks skip again instead of fetching on a folder hiccup.
            keep_ask=row_ask,
            is_retry=bool(getattr(spec, "is_retry", False)),
            chooser_toggles=getattr(spec, "chooser_toggles", None),
        )

    if not hooks.gate_reachability(replay, media_id):
        hooks.download_state(media_id, "")
        hooks.finish_job(qid)
        hooks.remove_row(qid)
        hooks.emit_queue()
        return
    if job_abort.is_set():
        hooks.queue_status(qid, "cancelled")
        hooks.download_state(media_id, "")
        hooks.bump_groups(media_id, None, "failed")
        hooks.finish_job(qid)
        return
    hooks.queue_status(qid, "running")
    hooks.download_progress(media_id, 0.0)
    hooks.download_state(media_id, "running")
    hooks.status(f"Downloading {name}…")
    hooks.devlog_event("download", "start", type=type_media, id=media_id, qid=qid)
    started_at = hooks.devlog_clock()
    try:
        summary = run_apple_job(
            hooks, qid, spec, obj, signals=signals, job_abort=job_abort, file_template=file_template
        )
        if job_abort.is_set():
            hooks.download_state(media_id, "")
            hooks.queue_status(qid, "cancelled")
            hooks.bump_groups(media_id, None, "failed")
            hooks.status(f"Cancelled {name}")
        else:
            hooks.redownload_overrides().discard(media_id)
            hooks.library_claim_overrides().discard(media_id)
            hooks.download_progress(media_id, 100.0)
            hooks.queue_progress(qid, 100.0)
            hooks.download_state(media_id, "done")
            hooks.queue_status(qid, "done")
            hooks.bump_groups(media_id, 100.0, "done")
            hooks.status(f"Finished {name}{summary}")
            hooks.devlog_done("download", f"done {type_media} id={media_id}", hooks.devlog_clock() - started_at)
    except Exception as exc:
        if job_abort.is_set():
            hooks.download_state(media_id, "")
            hooks.queue_status(qid, "cancelled")
            hooks.bump_groups(media_id, None, "failed")
            hooks.status(f"Cancelled {name}")
        elif hooks.download_failed_with_folder(replay, media_id, qid, name, job_abort):
            pass
        else:
            logger.exception("Apple download failed for %s", hooks.redact(name))
            reason = str(exc) if isinstance(exc, (DownloadIncomplete, AppleCredentialsError)) else ""
            hooks.download_state(media_id, "failed")
            hooks.queue_status(qid, "failed", reason)
            hooks.bump_groups(media_id, None, "failed")
            hooks.status(f"Failed {name}{': ' + reason if reason else ''}")
            hooks.devlog_done("download", f"FAILED {type_media} id={media_id}", hooks.devlog_clock() - started_at)
    finally:
        hooks.finish_job(qid)
        # Session supervision: an Apple job ending restarts the idle
        # clock's countdown; the sidecar stops itself when no download has
        # needed it for the tuned timeout.
        try:
            hooks.schedule_idle_stop()
        except Exception:
            logger.debug("Apple idle-stop schedule failed", exc_info=True)
