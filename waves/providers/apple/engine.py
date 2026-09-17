"""Apple download engine: gamdl-backed fetch and local decrypt for the cookies tier.

The cookies tier needs no wrapper or runtime: a Netscape cookies
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
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from waves.constants import quality_rank

logger = logging.getLogger("waves.providers.apple.engine")


class AppleCredential(StrEnum):
    """Which credential an Apple fetch needed.

    A credential failure names the one it needed, so the recovery hold can
    wait for that credential alone (AP-01: a wrapper-signed-in, cookies-broken
    job read the wrapper probe as recovery and re-ran the identical failing
    fetch forever).
    """

    COOKIES = "cookies"
    WRAPPER = "wrapper"

    @classmethod
    def of(cls, value) -> AppleCredential:
        """The member for a member or its plain word; an unknown name raises.

        One coercion for the error's constructor and the bridge's marker, so
        a typo cannot silently route a hold or a light to the other credential.
        """
        return cls(getattr(value, "value", value))


class AppleCredentialsError(Exception):
    """A credential the fetch needed is missing, unreadable, or signed out.

    ``credential`` names which one failed, so the recovery hold waits for proof
    about the credential the fetch actually needed. An unknown name is refused
    loudly: routing a hold off a typo would wait on the wrong credential again.
    """

    def __init__(self, message: str, *, credential: AppleCredential = AppleCredential.COOKIES) -> None:
        super().__init__(message)
        self.credential = AppleCredential.of(credential)


class AppleDownloadError(Exception):
    """Fetching, decrypting or verifying one Apple song failed."""


class AppleHeld(RuntimeError):
    """The Apple runtime is missing or died: the job waits, it never fails."""


class AppleWrapperDown(AppleHeld, AppleDownloadError):
    """The wrapper sidecar is not answering (held-not-failed).

    Subclasses AppleDownloadError so older catchers keep catching it; the
    supervision runner tests for this type first and holds the row with one
    clear message instead of failing it.
    """


class AppleIntegrityError(AppleDownloadError):
    """A staged Apple file failed verification (integrity gate).

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


class AppleVariantUnavailable(AppleDownloadError):
    """Apple holds no rendition at the requested quality (or none at all).

    The provider classifies this as an unavailable refusal, so the ceiling's
    fallback rules apply (AAC only when cookies exist; never a higher ALAC).
    """


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
    # The engine's fail-fast read of the staged bytes (codec/sample_rate/
    # bit_depth), empty when no ffprobe was available.
    probe: dict = field(default_factory=dict)
    # Whether the probe and the full decode both ran on exactly these
    # bytes. False means the caller still owns verification.
    verified: bool = False


def _require_cookies(cookies_path: str) -> str:
    path = str(cookies_path or "").strip()
    if not path or not Path(path).expanduser().is_file():
        raise AppleCredentialsError(  # noqa: TRY003 (user-facing words by design)
            "Apple downloads need a cookies export: set one in Settings under Providers, Apple Music.",
            credential=AppleCredential.COOKIES,
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


def _require_yt_dlp() -> None:
    """The direct-URL fallback shells through yt-dlp; fail with its name."""
    try:
        import yt_dlp  # noqa: F401  (direct-URL fallback shells through it)
    except ImportError as exc:
        raise AppleDownloadError("Apple downloads need the yt-dlp package installed.") from exc  # noqa: TRY003


def _verify_delivery(
    *,
    staged: Path,
    song_id: str,
    atmos: bool,
    resolved_probe: str,
    ffmpeg_path: str,
) -> dict:
    """Fail-fast verification of one fetched delivery, inside the engine fetch.

    A wrong delivery (an AAC file for an Atmos ask would otherwise be reported
    as E-AC-3 downstream) and an undecodable file both raise
    AppleIntegrityError carrying the staged path. Stereo accepts AAC (cookies
    tier) and ALAC (wrapper tier). Returns the probe (codec/sample_rate/
    bit_depth), which the caller carries onward as the verified read. The
    workdir is stamped by the caller.
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
    return probe


async def _fetch_song_staged(*, interface, song_downloader, song_id: str) -> tuple[Path, str]:
    """The decrypted song file plus its stream-advertised codec, or a refusal.

    A rendition Apple cannot serve for this ask raises AppleVariantUnavailable
    (gamdl parks its format/streamable refusals on ``media.error``; the
    provider's refusal vocabulary needs them typed, not as text). Every other
    fetch problem raises AppleDownloadError.
    """
    medias = [media async for media in interface._get_song_media(song_id)]
    media = medias[-1] if medias else None
    if media is None:
        raise AppleDownloadError(f"Apple would not serve song {song_id}: unknown error")  # noqa: TRY003
    error = getattr(media, "error", None)
    if error is not None:
        text = str(error).lower()
        if "format is not available" in text or "not streamable" in text:
            raise AppleVariantUnavailable(  # noqa: TRY003 (user-facing words by design)
                f"Apple holds no rendition at the requested quality for song {song_id}"
            )
        raise AppleDownloadError(  # noqa: TRY003 (user-facing words by design)
            f"Apple would not serve song {song_id}: {error}"
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


async def _close_client(owner, label: str = "Apple API session") -> None:
    """Best-effort close of an owner's aclose-able HTTP client, if any."""
    close = getattr(getattr(owner, "client", None), "aclose", None)
    if close is None:
        return
    try:
        await close()
    except Exception:
        logger.debug("Could not close the %s", label, exc_info=True)


async def _create_cookies_stack(cookies_path: str):
    """The cookies tier's API and base interface, built once per session."""
    from gamdl.api.apple_music import AppleMusicApi
    from gamdl.interface.base import AppleMusicBaseInterface

    try:
        api = await AppleMusicApi.create_from_netscape_cookies(cookies_path)
    except (OSError, ValueError) as exc:
        # Missing file, unparsable jar, or no media-user-token cookie: the
        # export is absent or the browser session is signed out.
        raise AppleCredentialsError(  # noqa: TRY003 (user-facing words by design)
            "Apple downloads need a signed-in cookies export: set one in Settings under Providers, Apple Music.",
            credential=AppleCredential.COOKIES,
        ) from exc
    try:
        base_interface = await AppleMusicBaseInterface.create(apple_music_api=api)
    except BaseException:
        await _close_client(api)
        raise
    return api, base_interface


async def _create_wrapper_stack(*, base_url: str, decrypt_host: str, decrypt_port: int):
    """The wrapper guest session, its API and base interface, once per session.

    A failure after either client opened closes what did open before
    raising, so a retried session never leaks a connection pool.
    """
    from gamdl.api.apple_music import AppleMusicApi
    from gamdl.interface.base import AppleMusicBaseInterface

    wrapper_api = await _open_wrapper_session(base_url=base_url, decrypt_host=decrypt_host, decrypt_port=decrypt_port)
    api = None
    try:
        api = await AppleMusicApi.create_from_wrapper(wrapper_api=wrapper_api)
        base_interface = await AppleMusicBaseInterface.create(apple_music_api=api, wrapper_api=wrapper_api)
    except BaseException:
        await _close_client(wrapper_api, "wrapper session")
        if api is not None:
            await _close_client(api)
        raise
    return wrapper_api, api, base_interface


_CONNECTION_FAILURE_TYPES = (
    "connecterror",
    "connecttimeout",
    "readtimeout",
    "readerror",
    "remoteprotocolerror",
    "networkerror",
    "timeout",
    "connectionreseterror",
)
_CONNECTION_FAILURE_PHRASES = (
    "connection refused",
    "all connection attempts failed",
    "server disconnected",
    "connection reset",
    "connection aborted",
    "network is unreachable",
)


def _is_connection_failure(exc: BaseException) -> bool:
    """Whether a failed wrapper fetch is the guest's connection dying.

    The session keeps one HTTP client across a job's tracks, so a sidecar
    that dies mid-job surfaces as that client's own connection error. The
    runner holds the row on a dead guest (never fails its track), so the
    session types the connection failure as AppleWrapperDown and the
    retry rebuilds the session.
    """
    text = f"{type(exc).__name__}: {exc}".lower()
    if any(token in text for token in _CONNECTION_FAILURE_TYPES):
        return True
    return any(phrase in text for phrase in _CONNECTION_FAILURE_PHRASES)


def _verify_fetched(
    *, staged: Path, song_id: str, atmos: bool, workdir: str, ffmpeg_path: str, picked: str
) -> tuple[dict, str, bool]:
    """The verified probe for one staged fetch, or an unverified answer.

    Verification needs an ffprobe; without one the bytes are handed on with
    ``verified`` False and the caller resolves the same binaries and checks
    them itself. Returns (probe, codec, verified); a rejected delivery
    carries its workdir and staged path on the raised integrity error.
    """
    resolved_probe = ffprobe_for(ffmpeg_path)
    if not resolved_probe:
        return {}, str(picked or ""), False
    try:
        probe = _verify_delivery(
            staged=staged,
            song_id=str(song_id),
            atmos=atmos,
            resolved_probe=resolved_probe,
            ffmpeg_path=ffmpeg_path,
        )
    except AppleIntegrityError as integrity_exc:
        # The rejected bytes stay for the caller (retry, date read,
        # quarantine): ownership of the workdir transfers outward.
        if not integrity_exc.workdir:
            integrity_exc.workdir = str(workdir)
        if not integrity_exc.staged_path:
            integrity_exc.staged_path = str(staged)
        raise
    return probe, str(probe.get("codec") or picked or ""), True


class AppleFetchSession:
    """One job's reused gamdl stack: one event loop, one API per tier.

    A job fetches its tracks sequentially. The cookies API (cookie parse,
    dev token, account info), the base interface (iTunes API, CDM) and the
    wrapper guest session (HTTP client, wrapper tokens) are job-scoped
    costs; building them per track repeats work no track boundary needs.
    The per-track song interface and downloader sit on top of the shared
    base, and the session's event loop serves the whole job. ``close``
    releases every client and the loop; a credential failure should close
    the session so the retry rebuilds it from the fresh export or guest.
    """

    def __init__(
        self,
        *,
        cookies_path: str = "",
        wrapper_url: str = "",
        nm3u8dlre_path: str = "",
        ffmpeg_path: str = "",
        decrypt_host: str = "127.0.0.1",
        decrypt_port: int = 10020,
    ) -> None:
        self.cookies_path = str(cookies_path or "")
        self.wrapper_url = str(wrapper_url or "").strip().rstrip("/")
        self.nm3u8dlre_path = str(nm3u8dlre_path or "")
        self.ffmpeg_path = str(ffmpeg_path or "")
        self.decrypt_host = str(decrypt_host or "127.0.0.1")
        self.decrypt_port = int(decrypt_port or 10020)
        self._loop = asyncio.new_event_loop()
        self._cookies: tuple | None = None
        self._wrapper: tuple | None = None
        self._closed = False

    def __enter__(self) -> AppleFetchSession:
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def close(self) -> None:
        """Release both stacks' clients and the session's event loop."""
        if self._closed:
            return
        self._closed = True
        try:
            self._loop.run_until_complete(self._aclose_stacks())
        except Exception:
            logger.debug("Could not close the Apple fetch session", exc_info=True)
        finally:
            self._loop.close()

    async def _aclose_stacks(self) -> None:
        if self._cookies is not None:
            await _close_client(self._cookies[0])
        if self._wrapper is not None:
            wrapper_api, api, _base = self._wrapper
            await _close_client(wrapper_api, "wrapper session")
            await _close_client(api)

    async def _cookies_stack(self):
        if self._cookies is None:
            self._cookies = await _create_cookies_stack(self.cookies_path)
        return self._cookies

    async def _wrapper_stack(self):
        if self._wrapper is None:
            self._wrapper = await _create_wrapper_stack(
                base_url=self.wrapper_url,
                decrypt_host=self.decrypt_host,
                decrypt_port=self.decrypt_port,
            )
        return self._wrapper

    def _require_tools(self) -> tuple[str, str]:
        """The resolved N_m3u8DL-RE and ffmpeg paths, or AppleDownloadError."""
        nm3u8dlre = _require_binary("N_m3u8DL-RE", self.nm3u8dlre_path)
        ffmpeg = _require_binary("ffmpeg", self.ffmpeg_path)
        _require_yt_dlp()
        return nm3u8dlre, ffmpeg

    def _run_staged(self, song_id: str, workdir: Path, make_awaitable, failure: str) -> AppleDelivery:
        """Run one fetch on the session loop; clean the workdir unless held.

        An integrity failure keeps the workdir for the caller (retry, date
        read, quarantine); every other failure removes it before re-raising,
        with ``failure`` naming the fetch in the generic message.
        """
        try:
            return self._loop.run_until_complete(make_awaitable())
        except AppleIntegrityError:
            raise
        except (AppleCredentialsError, AppleDownloadError):
            shutil.rmtree(workdir, ignore_errors=True)
            raise
        except Exception as exc:
            shutil.rmtree(workdir, ignore_errors=True)
            raise AppleDownloadError(f"{failure} for song {song_id}: {exc}") from exc  # noqa: TRY003

    def download_song(self, *, song_id: str, atmos: bool) -> AppleDelivery:
        """Fetch and locally decrypt one song on the shared cookies stack.

        Validation and the workdir are per fetch; the gamdl stack and the
        event loop persist for the session. An integrity failure keeps the
        workdir for the caller (retry, date read, quarantine).
        """
        _require_cookies(self.cookies_path)
        nm3u8dlre, ffmpeg = self._require_tools()
        workdir = Path(tempfile.mkdtemp(prefix="waves-apple-"))
        return self._run_staged(
            str(song_id),
            workdir,
            lambda: self._download_song_async(
                song_id=str(song_id),
                atmos=bool(atmos),
                workdir=str(workdir),
                nm3u8dlre_path=nm3u8dlre,
                ffmpeg_path=ffmpeg,
            ),
            "Apple download failed",
        )

    async def _download_song_async(
        self, *, song_id: str, atmos: bool, workdir: str, nm3u8dlre_path: str, ffmpeg_path: str
    ) -> AppleDelivery:
        from gamdl.downloader.base import AppleMusicBaseDownloader
        from gamdl.downloader.downloader import DownloadMode
        from gamdl.downloader.song import AppleMusicSongDownloader
        from gamdl.interface.enums import SongCodec
        from gamdl.interface.interface import AppleMusicInterface
        from gamdl.interface.music_video import AppleMusicMusicVideoInterface
        from gamdl.interface.song import AppleMusicSongInterface
        from gamdl.interface.uploaded_video import AppleMusicUploadedVideoInterface

        _api, base_interface = await self._cookies_stack()
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
        probe, codec, verified = _verify_fetched(
            staged=staged,
            song_id=song_id,
            atmos=atmos,
            workdir=workdir,
            ffmpeg_path=ffmpeg_path,
            picked=picked,
        )
        return AppleDelivery(
            staged_path=staged, workdir=Path(workdir), is_atmos=atmos, codec=codec, probe=probe, verified=verified
        )

    def download_alac(self, *, song_id: str, max_tier: str = "") -> AppleDelivery:
        """Fetch one ALAC song through the shared wrapper stack.

        The wrapper holds the Apple ID session itself: its tokens persist
        across container restarts, so this opens the guest session without
        credentials and succeeds while the guest is still signed in. A
        logged-out guest raises AppleCredentialsError with the wizard's
        login step as the fix; every other fetch problem raises
        AppleDownloadError.
        """
        if not self.wrapper_url:
            raise AppleCredentialsError(  # noqa: TRY003 (user-facing words by design)
                "Apple hi-res downloads need the managed wrapper: finish setup in Settings under Providers, Apple Music.",
                credential=AppleCredential.WRAPPER,
            )
        nm3u8dlre, ffmpeg = self._require_tools()
        workdir = Path(tempfile.mkdtemp(prefix="waves-apple-alac-"))
        return self._run_staged(
            str(song_id),
            workdir,
            lambda: self._fetch_alac_async(
                song_id=str(song_id),
                workdir=str(workdir),
                max_tier=str(max_tier or ""),
                nm3u8dlre_path=nm3u8dlre,
                ffmpeg_path=ffmpeg,
            ),
            "Apple ALAC download failed",
        )

    async def _fetch_alac_async(
        self, *, song_id: str, workdir: str, max_tier: str, nm3u8dlre_path: str, ffmpeg_path: str
    ) -> AppleDelivery:
        from gamdl.downloader.base import AppleMusicBaseDownloader
        from gamdl.downloader.downloader import DownloadMode
        from gamdl.downloader.song import AppleMusicSongDownloader
        from gamdl.interface.enums import SongCodec
        from gamdl.interface.interface import AppleMusicInterface
        from gamdl.interface.music_video import AppleMusicMusicVideoInterface
        from gamdl.interface.song import AppleMusicSongInterface
        from gamdl.interface.uploaded_video import AppleMusicUploadedVideoInterface

        from waves.constants import QualityTier

        try:
            _wrapper_api, _api, base_interface = await self._wrapper_stack()
        except (AppleCredentialsError, AppleWrapperDown):
            raise
        except Exception as exc:
            raise AppleDownloadError(f"Apple wrapper session failed for song {song_id}: {exc}") from exc  # noqa: TRY003
        # One chooser for both asks: a LOSSLESS ask caps at the LOSSLESS
        # rung (the same depth-and-rate map the delivery uses), a HI_RES ask
        # takes the best rendition the master holds. A 24-bit/48 kHz-only
        # master therefore satisfies a LOSSLESS ask instead of being refused
        # into the lossy fallback (issue #239).
        ceiling = QualityTier.LOSSLESS.value if str(max_tier) == QualityTier.LOSSLESS.value else None
        song_interface = AppleMusicSongInterface(
            base=base_interface,
            codec_priority=[SongCodec.ASK],
            ask_codec_function=lambda playlists: _choose_alac_playlist(playlists, ceiling),
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
        try:
            staged, picked = await _fetch_song_staged(
                interface=interface, song_downloader=song_downloader, song_id=str(song_id)
            )
        except (AppleCredentialsError, AppleVariantUnavailable, AppleIntegrityError, AppleDownloadError):
            raise
        except Exception as exc:
            if _is_connection_failure(exc):
                # The cached guest client outlived the sidecar: held, never
                # a failed track (the runner re-ensures and retries).
                raise AppleWrapperDown(  # noqa: TRY003 (user-facing words by design)
                    f"Apple wrapper is unreachable at {self.wrapper_url}: {exc}"
                ) from exc
            raise AppleDownloadError(f"Apple wrapper session failed for song {song_id}: {exc}") from exc  # noqa: TRY003
        probe, codec, verified = _verify_fetched(
            staged=staged,
            song_id=str(song_id),
            atmos=False,
            workdir=workdir,
            ffmpeg_path=ffmpeg_path,
            picked=picked,
        )
        return AppleDelivery(
            staged_path=staged, workdir=Path(workdir), is_atmos=False, codec=codec, probe=probe, verified=verified
        )


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
                "The Apple wrapper is not signed in: re-open setup in Settings under Providers, Apple Music, and complete the login step.",
                credential=AppleCredential.WRAPPER,
            ) from exc
        raise AppleWrapperDown(f"Apple wrapper is unreachable at {base_url}: {exc}") from exc  # noqa: TRY003


_ALAC_AUDIO_RE = re.compile(r"^audio-alac-.*?-(\d{4,6})-(\d{1,2})(?:-.*)?$")


def _choose_alac_playlist(playlists: list, max_tier: str | None) -> dict | None:
    """The best ALAC playlist at or below a rung ceiling, or None.

    Enhanced-HLS masters label each rendition's audio group
    ``audio-alac-stereo-<sampleRate>-<bitDepth>``. The ceiling is the Waves
    rung an ask may reach, decided by the same depth-and-rate map the
    delivery uses: a LOSSLESS ask takes the best LOSSLESS-class rendition
    (16-bit at any rate, or 24-bit at 44.1/48 kHz), a HI_RES ask the best the
    master holds. A master whose only lossless rendition is 24-bit/48 kHz
    therefore satisfies a LOSSLESS ask rather than being refused into the
    lossy fallback (issue #239). None means nothing qualified, which gamdl
    surfaces as a format refusal; ``_fetch_song_staged`` turns that into
    AppleVariantUnavailable, classified unavailable upstream so the ceiling's
    fallback rules still apply.
    """
    candidates: list[tuple[int, int, int, dict]] = []
    for playlist in playlists:
        if not isinstance(playlist, dict):
            continue
        stream_info = playlist.get("stream_info") or {}
        match = _ALAC_AUDIO_RE.fullmatch(str(stream_info.get("audio") or ""))
        if match is None:
            continue
        rate, depth = int(match.group(1)), int(match.group(2))
        if max_tier is not None and quality_rank(apple_tier_for_delivery("alac", depth, rate)) > quality_rank(max_tier):
            continue
        candidates.append((quality_rank(apple_tier_for_delivery("alac", depth, rate)), depth, rate, playlist))
    if not candidates:
        return None
    # Rung first, then depth and rate: the best on the rung the ask reaches
    # (a 24/192 beats a 24/96 on the same rung; an oddity labelled above the
    # ceiling's rung can never outrank a real one).
    return max(candidates, key=lambda candidate: (candidate[0], candidate[1], candidate[2]))[3]


def download_song_alac_file(
    *,
    song_id: str,
    wrapper_url: str,
    nm3u8dlre_path: str = "",
    ffmpeg_path: str = "",
    decrypt_host: str = "127.0.0.1",
    decrypt_port: int = 10020,
    max_tier: str = "",
) -> AppleDelivery:
    """Fetch one ALAC song through the managed wrapper into a fresh workdir.

    ``max_tier`` caps the rendition (a Waves tier value): LOSSLESS picks the
    best ALAC on that rung (16-bit at any rate, or 24-bit at 44.1/48 kHz),
    anything else the best the master holds. Session
    persistence is the wrapper's own property (tokens survive a container
    restart): a second call with the same URL needs no re-login. Raises
    AppleCredentialsError when the guest is logged out or unreachable as a
    login problem, AppleDownloadError otherwise. One call builds and closes
    its own stack; a job reusing a stack goes through AppleFetchSession.
    """
    with AppleFetchSession(
        wrapper_url=wrapper_url,
        nm3u8dlre_path=nm3u8dlre_path,
        ffmpeg_path=ffmpeg_path,
        decrypt_host=decrypt_host,
        decrypt_port=decrypt_port,
    ) as session:
        return session.download_alac(song_id=str(song_id), max_tier=str(max_tier or ""))


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
    caller can word rows and statuses without knowing gamdl. One call builds
    and closes its own stack; a job reusing a stack goes through
    AppleFetchSession.
    """
    with AppleFetchSession(
        cookies_path=cookies_path, nm3u8dlre_path=nm3u8dlre_path, ffmpeg_path=ffmpeg_path
    ) as session:
        return session.download_song(song_id=str(song_id), atmos=bool(atmos))


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
    """An Apple delivery's honest Waves tier value (spec §4.3).

    AAC 256 -> HIGH (Apple has no LOW). ALAC (or a FLAC converted from it):
    16-bit stays LOSSLESS whatever the rate; 24-bit (or deeper) is LOSSLESS
    at 44.1/48 kHz or an unreadable rate and HI_RES_LOSSLESS only above
    48 kHz (88.2 and up) -- Apple's own class boundary, so the rung never
    overstates what the master carries, and 24/96 and 24/192 stay the one
    rung whose numbers ride the label text, never rank (issue #239:
    24/48 used to promote on depth alone). A rate without a depth never
    promotes. Atmos E-AC-3 answers HIGH: the drawer words it ATMOS, never a
    rung. Unknown stays on the fallback, never invented.
    """
    from waves.constants import QualityTier

    norm = str(codec or "").lower().replace("-", "").replace("_", "")
    if norm in ("eac3", "ec3", "ac4"):
        return QualityTier.HIGH.value
    if norm in ("alac", "flac"):
        # FLAC is the converted ALAC container: same lossless ladder, the
        # same depth-and-rate map.
        try:
            rate = int(str(sample_rate or "").strip())
        except (TypeError, ValueError):
            rate = 0
        depth = int(bit_depth) if isinstance(bit_depth, int) and bit_depth > 0 else 0
        if depth >= 24:
            # Apple's classes: Lossless reaches 24/48; Hi-Res Lossless is the
            # 24-bit class above 48 kHz. An unreadable rate cannot promote.
            if rate > 48000:
                return QualityTier.HI_RES_LOSSLESS.value
            return QualityTier.LOSSLESS.value
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
