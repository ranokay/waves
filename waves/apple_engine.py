"""Apple download engine: gamdl-backed fetch and local decrypt for the cookies tier.

The cookies tier (issue #28) needs no wrapper or runtime: a Netscape cookies
export from a logged-in music.apple.com session unlocks AAC 256 stereo and
Atmos E-AC-3. This module is the only place that speaks gamdl's download
stack; the provider calls in with plain arguments and gets back a decrypted
file, so a future engine swap stays behind the provider's methods (spec §4.1:
no Engine sub-abstraction in v1).

Per song the flow mirrors gamdl's own CLI wiring (cli/cli.py): catalog media
-> stream info (codec priority) -> encrypted fetch (N_m3u8DL-RE for m3u8,
yt-dlp for direct URLs) -> local decrypt and mux -> staged .m4a. Tagging,
placement, ownership and the queue stay Waves' own work above this module.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("waves.apple_engine")


class AppleCredentialsError(Exception):
    """The cookies export is missing, unreadable, or no longer signed in."""


class AppleDownloadError(Exception):
    """Fetching, decrypting or verifying one Apple song failed."""


class AppleHeld(RuntimeError):
    """The Apple runtime is missing or died: the job waits, it never fails."""


class AppleWrapperDown(AppleHeld, AppleDownloadError):
    """The wrapper sidecar is not answering (held-not-failed, issue #33).

    Subclasses AppleDownloadError so older catchers keep catching it; the
    supervision runner tests for this type first and holds the row with one
    clear message instead of failing it.
    """


class AppleIntegrityError(AppleDownloadError):
    """A staged Apple file failed verification (integrity gate, issue #30).

    Carries the rejected bytes' location so the download runner can retry,
    read the Encoded date and quarantine them: ``staged_path`` is the failed
    file, ``workdir`` its temp tree (ownership transfers to the catcher, which
    must remove it). Either may be empty when nothing was staged (a resolve
    that never produced bytes): the retry and skip-list still apply, just
    without bytes or a date.
    """

    def __init__(self, message: str, staged_path: str = "", workdir: str = "") -> None:
        super().__init__(message)
        self.staged_path = str(staged_path or "")
        self.workdir = str(workdir or "")


class AppleTrackUnavailable(Exception):
    """Apple knows the song but will not serve a stream for it."""


class _AppleSkipped(Exception):
    """An Apple track met the existing-file skip inside delivery."""


class _AppleAborted(Exception):
    """An Apple track noticed the job abort inside delivery."""


@dataclass
class AppleDelivery:
    """One decrypted song on disk, still inside its workdir."""

    staged_path: Path
    workdir: Path
    is_atmos: bool
    codec: str  # "mp4a.40.2" stereo or "ec-3" Atmos, as requested


def _require_cookies(cookies_path: str) -> str:
    path = str(cookies_path or "").strip()
    if not path or not Path(path).expanduser().is_file():
        raise AppleCredentialsError(  # noqa: TRY003 (user-facing words by design)
            "Apple downloads need a cookies export: set one in Settings under Providers, Apple Music."
        )
    return path


def ffprobe_for(ffmpeg_path: str = "") -> str:
    """An ffprobe binary to use: beside the resolved ffmpeg first (the
    manager installs both; neither is on PATH then), else PATH, else "".

    Managed-ffmpeg users have no ffprobe on PATH, so PATH-only lookup would
    silently disable every verification for exactly the users who installed
    ffmpeg the supported way.
    """
    if ffmpeg_path:
        sibling = Path(ffmpeg_path).parent / ("ffprobe.exe" if os.name == "nt" else "ffprobe")
        if sibling.is_file():
            return str(sibling)
    return shutil.which("ffprobe") or ""


def decode_check(staged: str | Path, ffmpeg_path: str = "") -> None:
    """Decode the whole staged file, rejecting corrupt/truncated payloads.

    A codec probe only reads stream metadata; the ffmpeg decode (~50 ms per
    the integrity research) actually walks the packets. Raises
    AppleIntegrityError on any decode error. Quarantine/retry policy stays
    the integrity ticket's scope; here a bad file fails its track.

    Pass means silence: ffmpeg can print a recoverable packet error and still
    exit 0 (the outbreak's malformed ALAC presents exactly so), so any
    stderr under ``-v error`` fails the file, not just a nonzero exit.
    """
    ffmpeg = ffmpeg_path if ffmpeg_path and Path(ffmpeg_path).is_file() else (shutil.which("ffmpeg") or "")
    if not ffmpeg:
        logger.debug("Apple decode check skipped (no ffmpeg)")
        return
    try:
        proc = subprocess.run(  # noqa: S603 (resolved binary, fixed argv)
            [ffmpeg, "-v", "error", "-i", str(staged), "-f", "null", "-"],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except Exception as exc:
        raise AppleDownloadError(f"Could not verify the Apple download: {exc}") from exc  # noqa: TRY003
    if proc.returncode != 0 or (proc.stderr or "").strip():
        raise AppleIntegrityError(  # noqa: TRY003
            "The Apple download failed its integrity check", staged_path=str(staged)
        )


def _require_binary(name: str, override: str = "") -> str:
    """A helper binary's path, or an AppleDownloadError naming it."""
    if override and Path(override).is_file():
        return override
    found = shutil.which(name)
    if found:
        return found
    raise AppleDownloadError(  # noqa: TRY003 (user-facing words by design)
        f"Apple downloads need {name}: set its path in Settings under Providers, Apple Music, "
        "or put it on PATH (the setup wizard provisions it later)."
    )


def _verify_delivery(
    *,
    staged: Path,
    song_id: str,
    atmos: bool,
    resolved_probe: str,
    ffmpeg_path: str,
) -> str:
    """Fail-fast verification of one fetched delivery, inside the engine fetch.

    A wrong delivery (an AAC file for an Atmos ask would otherwise be reported
    as E-AC-3 downstream) and an undecodable file both raise
    AppleIntegrityError carrying the staged path; the job runner verifies
    again per track. Stereo accepts AAC (cookies tier) and ALAC (wrapper
    tier). Returns the picked codec. The workdir is stamped by the caller.
    """
    probe = probe_audio_file(staged, resolved_probe)
    picked = str(probe.get("codec") or "")
    got = str(picked or "").lower().replace("-", "").replace("_", "")
    if got not in (("eac3", "ec3", "ac4") if atmos else ("aac", "alac")):
        want = "eac3" if atmos else "aac"
        raise AppleIntegrityError(  # noqa: TRY003 (user-facing words by design)
            f"Apple served {picked or 'an unknown codec'} for song {song_id}, expected {want}",
            staged_path=str(staged),
        )
    decode_check(staged, ffmpeg_path)
    return picked


async def _fetch_song_staged(*, interface, song_downloader, song_id: str) -> tuple[Path, str]:
    """The decrypted song file plus its stream-advertised codec, or a refusal.

    Raises AppleTrackUnavailable-shaped AppleDownloadError when Apple knows
    the song but will not serve a stream for it (kept out of the fail count
    upstream); every other fetch problem raises AppleDownloadError.
    """
    medias = [media async for media in interface._get_song_media(song_id)]
    media = medias[-1] if medias else None
    if media is None or getattr(media, "error", None) is not None:
        raise AppleDownloadError(  # noqa: TRY003 (user-facing words by design)
            f"Apple would not serve song {song_id}: {getattr(media, 'error', 'unknown error')}"
        )
    if getattr(media, "partial", False) or getattr(media, "stream_info", None) is None:
        raise AppleDownloadError(f"Apple served an incomplete stream for song {song_id}")  # noqa: TRY003
    item = await song_downloader.get_download_item(media)
    await song_downloader.download(item)
    staged = Path(str(item.staged_path))
    if not staged.is_file() or staged.stat().st_size == 0:
        raise AppleDownloadError(f"Apple download produced no file for song {song_id}")  # noqa: TRY003
    codec = str(getattr(getattr(media.stream_info, "audio_track", None), "codec", "") or "")
    return staged, codec


async def _download_song_async(
    *,
    song_id: str,
    atmos: bool,
    cookies_path: str,
    workdir: str,
    nm3u8dlre_path: str,
    ffmpeg_path: str,
) -> AppleDelivery:
    from gamdl.api.apple_music import AppleMusicApi
    from gamdl.downloader.base import AppleMusicBaseDownloader
    from gamdl.downloader.downloader import DownloadMode
    from gamdl.downloader.song import AppleMusicSongDownloader
    from gamdl.interface.base import AppleMusicBaseInterface
    from gamdl.interface.enums import SongCodec
    from gamdl.interface.interface import AppleMusicInterface
    from gamdl.interface.music_video import AppleMusicMusicVideoInterface
    from gamdl.interface.song import AppleMusicSongInterface
    from gamdl.interface.uploaded_video import AppleMusicUploadedVideoInterface

    api = None
    try:
        api = await AppleMusicApi.create_from_netscape_cookies(cookies_path)
    except (OSError, ValueError) as exc:
        # Missing file, unparsable jar, or no media-user-token cookie: the
        # export is absent or the browser session is signed out.
        raise AppleCredentialsError(  # noqa: TRY003 (user-facing words by design)
            "Apple downloads need a signed-in cookies export: set one in Settings under Providers, Apple Music."
        ) from exc
    try:
        base_interface = await AppleMusicBaseInterface.create(apple_music_api=api)
        song_interface = AppleMusicSongInterface(
            base=base_interface,
            codec_priority=[SongCodec.ATMOS] if atmos else [SongCodec.AAC_WEB, SongCodec.AAC],
        )
        interface = AppleMusicInterface(
            song=song_interface,
            music_video=AppleMusicMusicVideoInterface(base=base_interface),
            uploaded_video=AppleMusicUploadedVideoInterface(base=base_interface),
        )
        base_downloader = AppleMusicBaseDownloader(
            interface=interface,
            output_path=workdir,
            temp_path=workdir,
            nm3u8dlre_path=nm3u8dlre_path,
            ffmpeg_path=ffmpeg_path,
            download_mode=DownloadMode.NM3U8DLRE,
            silent=True,
        )
        song_downloader = AppleMusicSongDownloader(base=base_downloader)

        staged, picked = await _fetch_song_staged(interface=interface, song_downloader=song_downloader, song_id=song_id)
        resolved_probe = ffprobe_for(ffmpeg_path)
        if resolved_probe:
            # Fail fast on a wrong delivery; the job runner verifies again per
            # track. The rejected bytes stay for the caller (retry, date read,
            # quarantine): ownership of the workdir transfers outward.
            try:
                picked = _verify_delivery(
                    staged=staged,
                    song_id=str(song_id),
                    atmos=atmos,
                    resolved_probe=resolved_probe,
                    ffmpeg_path=ffmpeg_path,
                )
            except AppleIntegrityError as integrity_exc:
                if not integrity_exc.workdir:
                    integrity_exc.workdir = str(workdir)
                if not integrity_exc.staged_path:
                    integrity_exc.staged_path = str(staged)
                raise
        return AppleDelivery(staged_path=staged, workdir=Path(workdir), is_atmos=atmos, codec=picked)
    finally:
        close = getattr(getattr(api, "client", None), "aclose", None)
        if close is not None:
            try:
                await close()
            except Exception:
                logger.debug("Could not close the Apple API session", exc_info=True)


async def _open_wrapper_session(*, base_url: str, decrypt_host: str, decrypt_port: int):
    """A logged-in wrapper session, or AppleCredentialsError when logged out."""
    from gamdl.api.wrapper import WrapperApi

    try:
        return await WrapperApi.create(
            base_url=base_url,
            decrypt_host=str(decrypt_host or "127.0.0.1"),
            decrypt_port=int(decrypt_port or 10020),
        )
    except Exception as exc:
        text = f"{type(exc).__name__}: {exc}".lower()
        if "not authenticated" in text or "logged_out" in text or "login" in text:
            raise AppleCredentialsError(  # noqa: TRY003
                "The Apple wrapper is not signed in: re-open setup in Settings under Providers, Apple Music, and complete the login step."
            ) from exc
        raise AppleWrapperDown(f"Apple wrapper is unreachable at {base_url}: {exc}") from exc  # noqa: TRY003


async def _fetch_alac_staged(
    *, song_id: str, workdir: str, nm3u8dlre_path: str, ffmpeg_path: str, wrapper_api
) -> AppleDelivery:
    """One ALAC fetch through an open wrapper session, verified fail-fast."""
    from gamdl.api.apple_music import AppleMusicApi
    from gamdl.downloader.base import AppleMusicBaseDownloader
    from gamdl.downloader.downloader import DownloadMode
    from gamdl.downloader.song import AppleMusicSongDownloader
    from gamdl.interface.base import AppleMusicBaseInterface
    from gamdl.interface.enums import SongCodec
    from gamdl.interface.interface import AppleMusicInterface
    from gamdl.interface.music_video import AppleMusicMusicVideoInterface
    from gamdl.interface.song import AppleMusicSongInterface
    from gamdl.interface.uploaded_video import AppleMusicUploadedVideoInterface

    try:
        api = await AppleMusicApi.create_from_wrapper(wrapper_api=wrapper_api)
    except Exception as exc:
        raise AppleDownloadError(f"Apple wrapper session failed for song {song_id}: {exc}") from exc  # noqa: TRY003
    try:
        base_interface = await AppleMusicBaseInterface.create(apple_music_api=api, wrapper_api=wrapper_api)
        song_interface = AppleMusicSongInterface(base=base_interface, codec_priority=[SongCodec.ALAC])
        interface = AppleMusicInterface(
            song=song_interface,
            music_video=AppleMusicMusicVideoInterface(base=base_interface),
            uploaded_video=AppleMusicUploadedVideoInterface(base=base_interface),
        )
        base_downloader = AppleMusicBaseDownloader(
            interface=interface,
            output_path=workdir,
            temp_path=workdir,
            nm3u8dlre_path=nm3u8dlre_path,
            ffmpeg_path=ffmpeg_path,
            download_mode=DownloadMode.NM3U8DLRE,
            silent=True,
        )
        song_downloader = AppleMusicSongDownloader(base=base_downloader)
        staged, picked = await _fetch_song_staged(
            interface=interface, song_downloader=song_downloader, song_id=str(song_id)
        )
        resolved_probe = ffprobe_for(ffmpeg_path)
        if resolved_probe:
            try:
                picked = _verify_delivery(
                    staged=staged,
                    song_id=str(song_id),
                    atmos=False,
                    resolved_probe=resolved_probe,
                    ffmpeg_path=ffmpeg_path,
                )
            except AppleIntegrityError as integrity_exc:
                if not integrity_exc.workdir:
                    integrity_exc.workdir = str(workdir)
                if not integrity_exc.staged_path:
                    integrity_exc.staged_path = str(staged)
                raise
        return AppleDelivery(staged_path=staged, workdir=Path(workdir), is_atmos=False, codec=picked)
    finally:
        close = getattr(getattr(api, "client", None), "aclose", None)
        if close is not None:
            try:
                await close()
            except Exception:
                logger.debug("Could not close the Apple API session", exc_info=True)


async def _download_song_via_wrapper_async(
    *,
    song_id: str,
    wrapper_url: str,
    workdir: str,
    nm3u8dlre_path: str,
    ffmpeg_path: str,
    decrypt_host: str = "127.0.0.1",
    decrypt_port: int = 10020,
) -> AppleDelivery:
    """Fetch one ALAC song through the managed wrapper-v2 guest (issue #32).

    The wrapper holds the Apple ID session itself: its tokens persist across
    container restarts (verified live, spec §2), so this creates the session
    without credentials and succeeds whenever the guest is still signed in.
    A logged-out guest raises AppleCredentialsError with the wizard's login
    step as the fix; every other fetch problem raises AppleDownloadError.
    """
    base_url = str(wrapper_url or "").strip().rstrip("/")
    if not base_url:
        raise AppleCredentialsError(  # noqa: TRY003 (user-facing words by design)
            "Apple hi-res downloads need the managed wrapper: finish setup in Settings under Providers, Apple Music."
        )
    wrapper_api = await _open_wrapper_session(base_url=base_url, decrypt_host=decrypt_host, decrypt_port=decrypt_port)
    try:
        return await _fetch_alac_staged(
            song_id=str(song_id),
            workdir=str(workdir),
            nm3u8dlre_path=nm3u8dlre_path,
            ffmpeg_path=ffmpeg_path,
            wrapper_api=wrapper_api,
        )
    finally:
        close_wrapper = getattr(getattr(wrapper_api, "client", None), "aclose", None)
        if close_wrapper is not None:
            try:
                await close_wrapper()
            except Exception:
                logger.debug("Could not close the wrapper session", exc_info=True)


def download_song_alac_file(
    *,
    song_id: str,
    wrapper_url: str,
    nm3u8dlre_path: str = "",
    ffmpeg_path: str = "",
    decrypt_host: str = "127.0.0.1",
    decrypt_port: int = 10020,
) -> AppleDelivery:
    """Fetch one ALAC song through the managed wrapper into a fresh workdir.

    Session persistence is the wrapper's own property (tokens survive a
    container restart): a second call with the same URL needs no re-login.
    Raises AppleCredentialsError when the guest is logged out or unreachable
    as a login problem, AppleDownloadError otherwise.
    """
    url = str(wrapper_url or "").strip()
    if not url:
        raise AppleCredentialsError(  # noqa: TRY003 (user-facing words by design)
            "Apple hi-res downloads need the managed wrapper: finish setup in Settings under Providers, Apple Music."
        )
    nm3u8dlre = _require_binary("N_m3u8DL-RE", nm3u8dlre_path)
    ffmpeg = _require_binary("ffmpeg", ffmpeg_path)
    try:
        import yt_dlp  # noqa: F401  (direct-URL fallback shells through it)
    except ImportError as exc:
        raise AppleDownloadError("Apple downloads need the yt-dlp package installed.") from exc  # noqa: TRY003
    workdir = Path(tempfile.mkdtemp(prefix="waves-apple-alac-"))
    try:
        return asyncio.run(
            _download_song_via_wrapper_async(
                song_id=str(song_id),
                wrapper_url=url,
                workdir=str(workdir),
                nm3u8dlre_path=nm3u8dlre,
                ffmpeg_path=ffmpeg,
                decrypt_host=decrypt_host,
                decrypt_port=int(decrypt_port or 10020),
            )
        )
    except AppleIntegrityError:
        raise
    except (AppleCredentialsError, AppleDownloadError):
        shutil.rmtree(workdir, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(workdir, ignore_errors=True)
        raise AppleDownloadError(f"Apple ALAC download failed for song {song_id}: {exc}") from exc  # noqa: TRY003


def download_song_file(
    *,
    song_id: str,
    atmos: bool,
    cookies_path: str,
    nm3u8dlre_path: str = "",
    ffmpeg_path: str = "",
) -> AppleDelivery:
    """Fetch and locally decrypt one Apple song into a fresh workdir.

    Raises AppleCredentialsError when the cookies export cannot be used and
    AppleDownloadError for every fetch, decrypt or binary failure, so the
    caller can word rows and statuses without knowing gamdl.
    """
    cookies = _require_cookies(cookies_path)
    nm3u8dlre = _require_binary("N_m3u8DL-RE", nm3u8dlre_path)
    ffmpeg = _require_binary("ffmpeg", ffmpeg_path)
    try:
        import yt_dlp  # noqa: F401  (direct-URL fallback shells through it)
    except ImportError as exc:
        raise AppleDownloadError("Apple downloads need the yt-dlp package installed.") from exc  # noqa: TRY003
    workdir = Path(tempfile.mkdtemp(prefix="waves-apple-"))
    try:
        return asyncio.run(
            _download_song_async(
                song_id=str(song_id),
                atmos=bool(atmos),
                cookies_path=cookies,
                workdir=str(workdir),
                nm3u8dlre_path=nm3u8dlre,
                ffmpeg_path=ffmpeg,
            )
        )
    except AppleIntegrityError:
        # Verification rejected the delivery: the workdir (with the bad bytes)
        # transfers to the caller for the Encoded-date read and quarantine.
        # The caller owns cleanup from here.
        raise
    except (AppleCredentialsError, AppleDownloadError):
        shutil.rmtree(workdir, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(workdir, ignore_errors=True)
        raise AppleDownloadError(f"Apple download failed for song {song_id}: {exc}") from exc  # noqa: TRY003


def cleanup_delivery(delivery: AppleDelivery) -> None:
    """Remove a delivery's workdir after its file has been moved out."""
    shutil.rmtree(delivery.workdir, ignore_errors=True)


def probe_audio_file(path: str | Path, ffprobe_path: str = "") -> dict:
    """ffprobe's reading of one audio file's first stream.

    Returns {"codec": ..., "sample_rate": ..., "bit_depth": ...} with ""
    unknowns and None depth when ffprobe reports none (lossy AAC carries no
    bit depth). Raises AppleDownloadError when ffprobe is missing; a file
    with no audio stream raises AppleIntegrityError (a corrupt/truncated
    delivery, never an infra failure).
    """
    ffprobe = _require_binary("ffprobe", ffprobe_path)
    try:
        proc = subprocess.run(  # noqa: S603 (resolved binary, fixed argv)
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=codec_name,sample_rate,bits_per_sample,bits_per_raw_sample,sample_fmt",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except Exception as exc:
        raise AppleDownloadError(f"Could not probe the Apple download: {exc}") from exc  # noqa: TRY003
    try:
        streams = json.loads(proc.stdout or "{}").get("streams") or []
    except ValueError as exc:
        raise AppleDownloadError(f"Could not read the Apple download's probe output: {exc}") from exc  # noqa: TRY003
    if proc.returncode != 0 or not streams:
        raise AppleIntegrityError(  # noqa: TRY003
            "The Apple download has no playable audio stream", staged_path=str(path)
        )
    stream = streams[0]
    return {
        "codec": str(stream.get("codec_name") or ""),
        "sample_rate": str(stream.get("sample_rate") or ""),
        "bit_depth": _probe_bit_depth(stream),
    }


def _probe_bit_depth(stream: dict) -> int | None:
    """One ffprobe audio stream's bit depth, or None when it carries none.

    ALAC reports bits_per_sample (24 for hi-res, 16 for CD); lossy AAC
    reports none, which is itself the signal (no depth to claim). No
    sample_fmt guessing: a 24-bit payload in a 32-bit container must not
    read as 32, and a 16-bit payload in a padded container must not read
    as hi-res.
    """
    for key in ("bits_per_sample", "bits_per_raw_sample"):
        try:
            depth = int(str(stream.get(key) or "").strip())
        except (TypeError, ValueError):
            continue
        if depth > 0:
            return depth
    return None


def apple_tier_for_delivery(
    codec: str, bit_depth: int | None, sample_rate: int | str | None, fallback: str = "HIGH"
) -> str:
    """An Apple delivery's honest Waves tier value (spec §4.3, issue #32).

    AAC 256 -> HIGH (Apple has no LOW); ALAC 16-bit -> LOSSLESS; ALAC
    24-bit -> HI_RES_LOSSLESS (24/96 and 24/192 are both this rung; the
    "24/192" detail rides label text, never rank). A converted FLAC answers
    the same rungs as the ALAC it was converted from (issue #64). Bit depth alone decides
    hi-res: a rate without a depth never promotes (a 16-bit 48 kHz master
    stays LOSSLESS). Atmos E-AC-3 answers HIGH: the drawer words it ATMOS,
    never a rung. Unknown stays on the fallback, never invented.
    """
    from waves.constants import QualityTier

    norm = str(codec or "").lower().replace("-", "").replace("_", "")
    if norm in ("eac3", "ec3", "ac4"):
        return QualityTier.HIGH.value
    if norm in ("alac", "flac"):
        # FLAC is the converted ALAC container (issue #64): same lossless
        # ladder, decided by depth alone, never by rate.
        try:
            rate = int(str(sample_rate or "").strip())
        except (TypeError, ValueError):
            rate = 0
        depth = int(bit_depth) if isinstance(bit_depth, int) and bit_depth > 0 else 0
        if depth >= 24:
            return QualityTier.HI_RES_LOSSLESS.value
        if depth > 0:
            return QualityTier.LOSSLESS.value
        if rate > 0:
            return QualityTier.LOSSLESS.value
        return str(fallback or QualityTier.HIGH.value)
    if norm == "aac":
        return QualityTier.HIGH.value
    return str(fallback or QualityTier.HIGH.value)


def apple_delivery_detail(codec: str, bit_depth: int | None, sample_rate: int | str | None) -> str:
    """Label text for an Apple delivery ("ALAC 24/192"), never a rank.

    The Chooser and the queue's plain-words readout render this detail as
    text; the rank comparison reads only the tier (spec §4.3). Rates render
    in kHz (96000 -> "96", 44100 -> "44.1"), matching the documented
    "ALAC 24/192" shape. Empty when nothing is known.
    """
    norm = str(codec or "").lower().replace("-", "").replace("_", "")
    if norm == "alac":
        name = "ALAC"
    elif norm == "aac":
        name = "AAC"
    elif norm in ("eac3", "ec3", "ac4"):
        name = "E-AC-3"
    elif norm:
        name = str(codec or "").upper()
    else:
        return ""
    try:
        rate = int(str(sample_rate or "").strip())
    except (TypeError, ValueError):
        rate = 0
    depth = int(bit_depth) if isinstance(bit_depth, int) and bit_depth > 0 else 0
    khz = f"{rate / 1000:g}" if rate > 0 else ""
    if depth and khz:
        return f"{name} {depth}/{khz}"
    if depth:
        return f"{name} {depth}-bit"
    if khz:
        return f"{name} {khz} kHz"
    return name
