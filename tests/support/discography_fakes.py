"""Artist-discography download stand-ins shared by the discography tests.

``schema_stub`` arms a bare object for ``settingsSchema``, ``VideoArtist``
serves videos a window at a time the way the endpoint does, and ``DiscoStub``
carries the artist-download state with the real ``downloadArtist`` bound.
"""

from __future__ import annotations

from threading import Lock
from types import SimpleNamespace

from conftest import _Signal

from waves.model.cfg import HelpSettings
from waves.model.cfg import Settings as CfgSettings
from waves.waves_ui.backend import WavesBridge


class _Stub:
    """Bare object the real methods get bound onto."""


def bind(stub, name):
    return getattr(WavesBridge, name).__get__(stub, type(stub))


def schema_stub():
    stub = _Stub()

    class _Cfg:
        data = CfgSettings()

    stub.settings = _Cfg()
    stub._help = HelpSettings()
    stub._help_for = bind(stub, "_help_for")
    stub._default_waves_prefs = bind(stub, "_default_waves_prefs")
    stub._waves_prefs = stub._default_waves_prefs()
    stub._waves_pref_bool = bind(stub, "_waves_pref_bool")
    stub._ffmpeg_flag_prefs = {}
    stub.ffmpegState = lambda: {"status": "none", "source": "none", "path": ""}
    stub._user_ffmpeg_path = lambda: ""
    stub._ffmpeg_detected_path = lambda: ""
    return stub


class _InlinePool:
    @staticmethod
    def start(worker):
        worker.fn()


class VideoArtist:
    """Serves videos a window at a time, the way the endpoint does."""

    def __init__(self, videos, fail=False):
        self._videos = videos
        self._fail = fail
        self.video_calls = 0

    def get_videos(self, limit=None, offset=0):
        self.video_calls += 1
        if self._fail:
            raise RuntimeError("429")
        window = limit if limit is not None else len(self._videos)
        return list(self._videos[offset : offset + window])


class DiscoStub:
    downloadArtist = WavesBridge.downloadArtist

    def __init__(self, artist, video_download: bool):
        self._dl = object()
        # Stereo default on purpose: the sweep's Atmos filter runs
        # (and must pass a spatial-free release list through untouched).
        self.settings = SimpleNamespace(
            data=SimpleNamespace(video_download=video_download, default_audio_type="stereo")
        )
        self._artist = artist
        self._artist_groups: dict = {}
        self._artist_lock = Lock()
        self._merge_scanned: set = set()
        self._merge_plans: dict = {}
        self._scan_pool = _InlinePool()
        self._scan_gen = 0  # the generation STOP bumps; never bumped here
        self._scans_in_flight = 0
        self._scan_count_lock = Lock()
        self.scanningChanged = _Signal()
        self.downloadProgress = _Signal()
        self.downloadState = _Signal()
        self._albumsQueued = _Signal()
        self._tracksQueued = _Signal()
        self._videosQueued = _Signal()
        self.statuses: list = []
        self.remembered: list = []

    def _download_gate(self):
        return "ok"

    def _ffmpeg_gate_holds(self, media_id, retry):
        return False

    def _gate_reachability(self, retry, media_id):
        return True

    def _set_status(self, text):
        self.statuses.append(text)

    def _get_artist(self, artist_id):
        return self._artist

    def _artist_releases(self, artist):
        return [SimpleNamespace(id="al1")], [], True

    def _dedup_albums(self, albums):
        return list(albums)

    def _dedup_videos(self, videos):
        return list(videos)

    def _waves_pref_bool(self, key):
        return False

    def _merge_pref_on(self):
        # Edition handling off here: these stubs exercise the source toggles.
        return False

    def _library_bulk_skip_on(self):
        # The bulk claim gate is off here, like a library-less install; its
        # own filtering is covered by tests/library/test_library_bridge.py.
        return False

    def _remember(self, bucket, key, obj):
        self.remembered.append((bucket, key))
