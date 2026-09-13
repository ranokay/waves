"""The pinned clients the engine calls, checked without a network.

gamdl and N_m3u8DL-RE are pinned dependencies: a bump that removes or renames
a member the Apple engine calls must fail here, locally, instead of at fetch
time. The checks are structural (which members exist, what the pin tables
cover), not a fetch; a real-service run stays the opt-in account suite's job.
"""

from __future__ import annotations

import re

from waves.providers.apple.runtime import (
    NM3U8DLRE_RELEASES,
    NM3U8DLRE_SHA256,
    NM3U8DLRE_VERSION,
)


def test_the_engine_client_surface_still_exists():
    from gamdl.api.apple_music import AppleMusicApi
    from gamdl.api.wrapper import WrapperApi
    from gamdl.downloader.base import AppleMusicBaseDownloader
    from gamdl.downloader.downloader import DownloadMode
    from gamdl.downloader.song import AppleMusicSongDownloader
    from gamdl.interface.base import AppleMusicBaseInterface
    from gamdl.interface.enums import SongCodec
    from gamdl.interface.interface import AppleMusicInterface
    from gamdl.interface.music_video import AppleMusicMusicVideoInterface
    from gamdl.interface.song import AppleMusicSongInterface
    from gamdl.interface.uploaded_video import AppleMusicUploadedVideoInterface

    assert callable(AppleMusicApi.create_from_netscape_cookies)
    assert callable(AppleMusicApi.create_from_wrapper)
    assert callable(AppleMusicBaseInterface.create)
    assert callable(WrapperApi.create)
    # The engine reads the song's media list and drives the song downloader
    # through these members.
    assert callable(AppleMusicInterface._get_song_media)
    assert callable(AppleMusicSongDownloader.get_download_item)
    assert callable(AppleMusicSongDownloader.download)
    # The codecs and the download mode the engine's wiring names.
    assert {SongCodec.ATMOS, SongCodec.AAC_WEB, SongCodec.AAC, SongCodec.ASK} <= set(SongCodec)
    assert DownloadMode.NM3U8DLRE in set(DownloadMode)
    # The classes the engine instantiates (import success is the real check;
    # naming them here keeps the imports load-bearing).
    assert all(
        isinstance(cls, type)
        for cls in (
            AppleMusicBaseDownloader,
            AppleMusicMusicVideoInterface,
            AppleMusicSongInterface,
            AppleMusicUploadedVideoInterface,
        )
    )


def test_every_nm3u8dlre_asset_pin_is_versioned_and_hashed():
    assert NM3U8DLRE_RELEASES.keys() == NM3U8DLRE_SHA256.keys()
    assert NM3U8DLRE_RELEASES, "no pinned N_m3u8DL-RE assets"
    for key, url in NM3U8DLRE_RELEASES.items():
        assert url.startswith("https://github.com/nilaoda/N_m3u8DL-RE/releases/download/")
        assert NM3U8DLRE_VERSION in url, f"{key} asset is not from the pinned release"
        assert re.fullmatch(r"[0-9a-f]{64}", NM3U8DLRE_SHA256[key]), f"{key} has no real SHA-256 pin"
