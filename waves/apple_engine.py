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
    AppleDownloadError on any decode error. Quarantine/retry policy stays
    the integrity ticket's scope; here a bad file fails its track.
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
    if proc.returncode != 0:
        raise AppleDownloadError("The Apple download failed its integrity check")  # noqa: TRY003


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
        picked = str(getattr(getattr(media.stream_info, "audio_track", None), "codec", "") or "")
        resolved_probe = ffprobe_for(ffmpeg_path)
        if resolved_probe:
            # Fail fast on a wrong delivery (an AAC file for an Atmos ask
            # would otherwise be reported as E-AC-3 downstream): the probe is
            # best-effort here, the job runner verifies again per track.
            # Stereo accepts AAC (cookies tier) and ALAC (wrapper tier).
            probe = probe_audio_file(staged, resolved_probe)
            picked = str(probe.get("codec") or picked)
            got = str(picked or "").lower().replace("-", "").replace("_", "")
            ok_delivery = got in ("eac3", "ec3", "ac4", "ac3") if atmos else got in ("aac", "alac")
            if not ok_delivery:
                want = "eac3" if atmos else "aac"
                raise AppleDownloadError(  # noqa: TRY003 (user-facing words by design)
                    f"Apple served {picked or 'an unknown codec'} for song {song_id}, expected {want}"
                )
            decode_check(staged, ffmpeg_path)
        return AppleDelivery(staged_path=staged, workdir=Path(workdir), is_atmos=atmos, codec=picked)
    finally:
        close = getattr(getattr(api, "client", None), "aclose", None)
        if close is not None:
            try:
                await close()
            except Exception:
                logger.debug("Could not close the Apple API session", exc_info=True)


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

    Returns {"codec": ..., "sample_rate": ...} with "" unknowns. Raises
    AppleDownloadError when ffprobe is missing or the file has no audio.
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
                "stream=codec_name,sample_rate",
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
        raise AppleDownloadError("The Apple download has no playable audio stream")  # noqa: TRY003
    stream = streams[0]
    return {"codec": str(stream.get("codec_name") or ""), "sample_rate": str(stream.get("sample_rate") or "")}
