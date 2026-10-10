"""Settings saves persist user preferences without touching runtime values.

Downloads share live FFmpeg settings, including a managed/PATH binary and
flags disabled when no binary exists. Saves serialize a sanitized snapshot;
runtime rebuilds resolve final values without clearing the path first.
Behavior tests park serialization and Settings application at their concurrent
read boundaries. The wiring guard fences new, unsanitized save sites.
"""

from __future__ import annotations

import inspect
import json
import logging
import re
import shutil
import threading
from threading import Lock
from types import SimpleNamespace
from typing import ClassVar

import pytest
from conftest import _InlineWriter
from support.bridge_stub import BridgeStub

from waves.config import Settings as SettingsSingleton
from waves.constants import CTX_APPLE, CTX_TIDAL
from waves.desktop.backend import WavesBridge
from waves.download import Download
from waves.model.cfg import Settings as CfgSettings
from waves.model.download_policy import capture_intent

# The managed binary sits under the account's own Application Support folder, so
# the path is identity-bearing. That is the whole reason it must never reach the
# settings file, which the bug template asks users to paste in public.
_MANAGED = "/Users/testuser/Library/Application Support/Waves/bin/ffmpeg"
_PATH_FFMPEG = "/usr/local/bin/ffmpeg"


class _Stub(BridgeStub):
    """Bare object the real methods get bound onto."""


def _bind(stub, name):
    return getattr(WavesBridge, name).__get__(stub, type(stub))


def _bridge():
    """A stub carrying the real snapshot/save methods over a real dataclass, in
    the exact state that triggers it: ffmpeg missing (flags forced off in memory,
    user's real preference remembered) and a managed path injected."""
    stub = _Stub()

    class _Cfg:
        data = CfgSettings()
        saved: ClassVar[list[dict]] = []

        def save(self):
            # Capture what would hit disk.
            self.saved.append(
                {
                    "extract_flac": self.data.extract_flac,
                    "video_convert_mp4": self.data.video_convert_mp4,
                    "path_binary_ffmpeg": self.data.path_binary_ffmpeg,
                }
            )

        def write_serialized(self, data_json):
            # The async path: capture what the SNAPSHOT would put on disk,
            # which is exactly what _submit_settings_write serialized.
            payload = json.loads(data_json)
            self.saved.append({k: payload[k] for k in ("extract_flac", "video_convert_mp4", "path_binary_ffmpeg")})

    stub.settings = _Cfg()

    # The user's real preferences: both features ON, no explicit ffmpeg path.
    stub._ffmpeg_flag_prefs = {"extract_flac": True, "video_convert_mp4": True}
    stub._ffmpeg_user_path = ""

    # What Download/_resolve_ffmpeg did to the live object in memory.
    stub.settings.data.extract_flac = False
    stub.settings.data.video_convert_mp4 = False
    stub.settings.data.path_binary_ffmpeg = _MANAGED

    stub._restore_ffmpeg_flags = _bind(stub, "_restore_ffmpeg_flags")
    stub._restore_ffmpeg_path = _bind(stub, "_restore_ffmpeg_path")
    stub._save_settings = _bind(stub, "_save_settings")
    stub._submit_settings_write = _bind(stub, "_submit_settings_write")
    stub._config_writer = _InlineWriter()
    stub._settings_save_lock = Lock()

    class _Signal:
        emits: ClassVar[list] = []

        def emit(self, *a):
            self.emits.append(a)

    # _save_settings tells the Settings page a backend path persisted values.
    stub.settingsPersistedExternally = _Signal()
    return stub


def _last_save(stub) -> dict:
    assert stub.settings.saved, "nothing was saved"
    return stub.settings.saved[-1]


def _running_download(stub):
    return Download(
        tidal_obj=SimpleNamespace(session=None),
        path_base=stub.settings.data.download_base_path,
        fn_logger=logging.getLogger(__name__),
        provider=object(),
        settings_data=stub.settings.data,
    )


def _park_saves_during_serialization(stub, monkeypatch):
    parked, release = threading.Event(), threading.Event()
    serialize = CfgSettings.to_json
    saver = threading.Thread(target=stub._save_settings)

    def serialize_then_park(data, **kwargs):
        if threading.current_thread() is saver:
            parked.set()
            assert release.wait(5), "the serialization was never released"
        return serialize(data, **kwargs)

    monkeypatch.setattr(CfgSettings, "to_json", serialize_then_park)
    return saver, parked, release


@pytest.mark.parametrize("path", [_MANAGED, _PATH_FFMPEG, None], ids=["managed", "system", "missing"])
def test_a_running_download_keeps_ffmpeg_values_during_serialization(path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    stub = _bridge()
    stub.settings.write_serialized = lambda payload: stub.settings.saved.append(json.loads(payload))
    data = stub.settings.data
    data.path_binary_ffmpeg = path
    data.extract_flac_all = False
    stub._ffmpeg_flag_prefs["extract_flac_all"] = True
    dl = _running_download(stub)
    saver, parked, release = _park_saves_during_serialization(stub, monkeypatch)
    saver.start()
    try:
        assert parked.wait(5), "the save never reached serialization"
        assert dl.settings.data.path_binary_ffmpeg == path
        assert dl.settings.data.extract_flac is False
        assert dl.settings.data.extract_flac_all is False
        assert dl.settings.data.video_convert_mp4 is False
    finally:
        release.set()
        saver.join(5)
    assert not saver.is_alive()
    written = _last_save(stub)
    assert written["path_binary_ffmpeg"] == ""
    assert written["extract_flac"] is True
    assert written["extract_flac_all"] is True
    assert written["video_convert_mp4"] is True


def test_a_running_download_keeps_ffmpeg_values_until_apply_rebuilds_it():
    stub = _apply_bridge()
    dl = _running_download(stub)
    parked, release = threading.Event(), threading.Event()
    stub._logged_in = True

    def rebuild():
        parked.set()
        assert release.wait(5), "the Download rebuild was never released"

    stub._init_download = rebuild
    apply = threading.Thread(target=lambda: stub.applySettings({}))
    apply.start()
    try:
        assert parked.wait(5), "applySettings never reached its Download rebuild"
        assert _last_save(stub)["path_binary_ffmpeg"] == ""
        assert dl.settings.data.path_binary_ffmpeg == _MANAGED
        assert dl.settings.data.extract_flac is False
        assert dl.settings.data.video_convert_mp4 is False
    finally:
        release.set()
        apply.join(5)
    assert not apply.is_alive()


def test_a_failed_serialization_preserves_running_download_settings(monkeypatch):
    stub = _bridge()
    dl = _running_download(stub)

    def fail(data, **kwargs):
        assert dl.settings.data.path_binary_ffmpeg == _MANAGED
        assert dl.settings.data.extract_flac is False
        raise ValueError("serialization failed")

    monkeypatch.setattr(CfgSettings, "to_json", fail)
    with pytest.raises(ValueError, match="serialization failed"):
        stub._save_settings()

    assert dl.settings.data.path_binary_ffmpeg == _MANAGED
    assert dl.settings.data.extract_flac is False
    assert not stub.settings.saved


@pytest.mark.parametrize(
    ("user_path", "installed", "on_path", "expected"),
    [
        ("", True, _PATH_FFMPEG, _MANAGED),
        ("/opt/custom/ffmpeg", True, _PATH_FFMPEG, "/opt/custom/ffmpeg"),
        ("", False, _PATH_FFMPEG, _PATH_FFMPEG),
        ("", False, None, ""),
    ],
    ids=["managed", "custom", "system", "missing"],
)
def test_rebuilding_a_download_resolves_binary_and_restores_usable_preferences(
    user_path, installed, on_path, expected, monkeypatch
):
    stub = _resolving_bridge()
    singleton = SettingsSingleton()
    monkeypatch.setattr(singleton, "data", stub.settings.data)
    stub.settings = singleton
    data = singleton.data
    # Runtime state from a previous Download must not be mistaken for the
    # user's override, or keep forced-off flags after FFmpeg becomes available.
    data.path_binary_ffmpeg = _PATH_FFMPEG
    for key in ("extract_flac", "extract_flac_all", "video_convert_mp4"):
        setattr(data, key, False)
        stub._ffmpeg_flag_prefs[key] = True
    stub._ffmpeg_user_path = user_path
    stub._ffmpeg = SimpleNamespace(is_installed=lambda: installed, binary_path=_MANAGED)
    stub.tidal = SimpleNamespace(session=None)
    stub.providers = {CTX_TIDAL: object()}
    stub._event_abort = threading.Event()
    stub._event_run = threading.Event()
    stub._warn_if_ffmpeg_missing = lambda dl: None

    def which(name):
        assert data.path_binary_ffmpeg == _PATH_FFMPEG, "resolution temporarily cleared the live path"
        return on_path

    monkeypatch.setattr(shutil, "which", which)
    # Download's own missing-binary check also asks PATH after final resolution.
    if not expected:
        monkeypatch.setattr(shutil, "which", lambda name: None)

    WavesBridge._init_download(stub)

    assert (stub._dl.settings.data.path_binary_ffmpeg or "") == expected
    assert stub._dl.ffmpeg_missing is (not expected)
    assert data.extract_flac is bool(expected)
    assert data.extract_flac_all is bool(expected)
    assert data.video_convert_mp4 is bool(expected)


def test_clearing_a_user_override_keeps_the_managed_binary_before_rebuild():
    stub = _apply_bridge()
    stub._ffmpeg_user_path = "/opt/custom/ffmpeg"
    stub.settings.data.path_binary_ffmpeg = stub._ffmpeg_user_path
    dl = _running_download(stub)
    handed = []
    stub._configure_apple_provider = lambda: handed.append(dl.settings.data.path_binary_ffmpeg)

    stub.applySettings({"path_binary_ffmpeg": ""})

    assert handed == [_MANAGED]
    assert dl.settings.data.path_binary_ffmpeg == _MANAGED
    assert _last_save(stub)["path_binary_ffmpeg"] == ""


@pytest.mark.parametrize("path_first", [False, True, None], ids=["flags-first", "path-first", "path-only"])
def test_a_signed_out_path_edit_restores_the_preferences_apple_captures(path_first, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    stub = _apply_bridge()
    stub._ffmpeg = SimpleNamespace(is_installed=lambda: False, binary_path=_MANAGED)
    stub.settings.data.path_binary_ffmpeg = None
    stub._configure_apple_provider = lambda: None
    entered = "/opt/custom/ffmpeg"
    values = {"extract_flac": True, "video_convert_mp4": True}
    if path_first is None:
        values = {}
    if path_first:
        values = {"path_binary_ffmpeg": entered, **values}
    else:
        values["path_binary_ffmpeg"] = entered

    stub.applySettings(values)
    intent = capture_intent(stub.settings.data, CTX_APPLE, "track", "apple:1", tier="HIGH", audio_type=None, toggles={})
    stub.providers = {CTX_APPLE: object()}
    hooks = WavesBridge._apple_job_hooks(stub, intent)

    assert hooks.settings().data.path_binary_ffmpeg == entered
    assert hooks.settings().data.extract_flac is True
    assert hooks.settings().data.video_convert_mp4 is True
    assert _last_save(stub)["extract_flac"] is True


def test_clearing_the_last_binary_disables_features_before_the_apply_save(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    stub = _apply_bridge()
    stub._ffmpeg = SimpleNamespace(is_installed=lambda: False, binary_path=_MANAGED)
    stub._ffmpeg_user_path = "/opt/custom/ffmpeg"
    stub.settings.data.path_binary_ffmpeg = stub._ffmpeg_user_path
    stub.settings.data.extract_flac = True
    stub.settings.data.video_convert_mp4 = True
    dl = _running_download(stub)
    observed = []

    def configure():
        data = dl.settings.data
        observed.append((data.path_binary_ffmpeg, data.extract_flac, data.video_convert_mp4))

    stub._configure_apple_provider = configure
    stub.applySettings({"path_binary_ffmpeg": ""})

    assert observed == [("", False, False)]
    assert _last_save(stub)["extract_flac"] is True
    assert _last_save(stub)["video_convert_mp4"] is True


def test_keep_download_folder_does_not_persist_transient_ffmpeg_flags():
    """Answering the folder nudge must not disable FLAC extraction on disk."""
    stub = _bridge()
    stub._run_pending_downloads = lambda: None

    _bind(stub, "keepDownloadFolder")()

    written = _last_save(stub)
    assert written["extract_flac"] is True, "answering the folder nudge disabled FLAC extraction on disk"
    assert written["video_convert_mp4"] is True
    assert written["path_binary_ffmpeg"] == "", "a machine path (with the username) was persisted"
    assert stub.settings.data.download_folder_prompted is True  # the decision still stuck


def test_mute_category_confirm_does_not_persist_transient_ffmpeg_flags():
    """'Don't ask again' on the bulk-download confirm shares the trap."""
    stub = _bridge()
    stub.confirmCategoryDlChanged = type("_S", (), {"emit": staticmethod(lambda: None)})()

    _bind(stub, "muteCategoryDlConfirm")()

    written = _last_save(stub)
    assert written["extract_flac"] is True
    assert written["video_convert_mp4"] is True
    assert written["path_binary_ffmpeg"] == ""
    assert stub.settings.data.confirm_category_download is False  # the opt-out still stuck


def test_save_settings_persists_user_ffmpeg_preferences():
    """The helper itself is the invariant; test it directly."""
    stub = _bridge()

    stub._save_settings()

    written = _last_save(stub)
    assert written == {
        "extract_flac": True,
        "video_convert_mp4": True,
        "path_binary_ffmpeg": "",
    }


def test_the_save_leaves_the_live_settings_alone():
    """A completed save preserves the object and values each track reads."""
    stub = _bridge()
    live = stub.settings.data

    stub._save_settings()

    assert _last_save(stub)["path_binary_ffmpeg"] == "", "the machine path must not reach disk"
    assert stub.settings.data is live, "the singleton's data object was swapped out and not put back"
    assert live.path_binary_ffmpeg == _MANAGED, "a running download just lost the ffmpeg binary it was built with"
    assert live.extract_flac is False, "the in-memory force-off was overwritten under a running download"
    assert live.video_convert_mp4 is False


def test_concurrent_saves_preserve_the_live_settings():
    """Concurrent worker/GUI saves each persist the user override and keep
    the shared runtime settings intact."""
    import threading

    stub = _bridge()
    live = stub.settings.data
    barrier = threading.Barrier(4)

    def _save():
        barrier.wait()
        stub._save_settings()

    threads = [threading.Thread(target=_save) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert stub.settings.data is live
    assert live.path_binary_ffmpeg == _MANAGED
    assert len(stub.settings.saved) == 4
    assert all(w["path_binary_ffmpeg"] == "" for w in stub.settings.saved)


def _resolving_bridge():
    """``_bridge`` with the managed ffmpeg installed and the real resolve
    bound: the managed path injected, both flags at the user's preference."""
    stub = _bridge()
    stub.settings.data.extract_flac = True
    stub.settings.data.video_convert_mp4 = True
    stub._ffmpeg = SimpleNamespace(is_installed=lambda: True, binary_path=_MANAGED)
    for name in ("_resolve_ffmpeg", "_resolve_ffmpeg_locked", "_ffmpeg_source_label", "_user_ffmpeg_path"):
        setattr(stub, name, _bind(stub, name))
    return stub


def _after_each_resolve(stub, then):
    """Run ``then`` each time a resolve returns. Both resolve names carry it,
    so it follows whichever one the caller uses."""

    def seam(resolve):
        def resolve_then():
            path = resolve()
            then()
            return path

        return resolve_then

    stub._resolve_ffmpeg = seam(stub._resolve_ffmpeg)
    stub._resolve_ffmpeg_locked = seam(stub._resolve_ffmpeg_locked)


def _a_save_starts(saver, parked):
    """Start ``saver`` once, then give it the time an unlocked caller would
    leave it to reach its write. A caller still holding the lock keeps the
    save out, and the wait runs out."""

    def start():
        if saver.ident is None:
            saver.start()
        parked.wait(0.3)

    return start


def test_a_resolve_during_a_save_keeps_the_managed_path_off_disk(monkeypatch):
    """Runtime resolution and a concurrent save keep the managed path
    available to downloads and absent from the persisted snapshot."""
    stub = _resolving_bridge()
    saver, parked, release = _park_saves_during_serialization(stub, monkeypatch)
    resolved: list[str] = []
    resolver = threading.Thread(target=lambda: resolved.append(stub._resolve_ffmpeg()))
    saver.start()
    assert parked.wait(5), "the save never reached its write"
    resolver.start()
    resolver.join(0.3)  # the time an unlocked resolve has to write
    release.set()
    saver.join(5)
    resolver.join(5)

    assert _last_save(stub)["path_binary_ffmpeg"] == "", "the managed path reached settings.json"
    assert resolved == [_MANAGED]
    assert stub.settings.data.path_binary_ffmpeg == _MANAGED


def _apple_provider_path(stub) -> str:
    provider = SimpleNamespace()
    stub.providers = {CTX_APPLE: provider}
    WavesBridge._configure_apple_provider(stub)
    return provider.ffmpeg_path


def _preview_path(stub) -> str | None:
    return WavesBridge._preview_ffmpeg_bin(stub)


@pytest.mark.parametrize("reader", [_apple_provider_path, _preview_path], ids=["apple-provider", "preview"])
def test_a_reader_keeps_the_resolved_path_through_a_save(reader, monkeypatch):
    """Provider configuration and previews retain the selected binary when
    a concurrent save serializes the user preferences."""
    monkeypatch.setattr(shutil, "which", lambda name: None)
    stub = _resolving_bridge()
    saver, parked, release = _park_saves_during_serialization(stub, monkeypatch)
    _after_each_resolve(stub, _a_save_starts(saver, parked))
    try:
        path = reader(stub)
    finally:
        release.set()
        if saver.ident is not None:
            saver.join(5)

    assert path == _MANAGED, "the reader took the user's value a save had restored for its write"
    assert _last_save(stub)["path_binary_ffmpeg"] == ""
    assert stub.settings.data.path_binary_ffmpeg == _MANAGED


def test_a_removal_during_a_configure_leaves_apple_off_the_deleted_binary(monkeypatch):
    """A configure on a worker (an Apple runtime install, a sign-out) can
    resolve the managed path just as removeFfmpeg deletes it on the GUI
    thread. Handed to the provider after the lock was released, that path
    landed after the removal's own configure and left Apple on a binary that
    no longer exists."""
    monkeypatch.setattr(shutil, "which", lambda name: None)
    stub = _resolving_bridge()
    installed = [True]
    stub._ffmpeg = SimpleNamespace(
        is_installed=lambda: installed[0],
        binary_path=_MANAGED,
        remove=lambda: installed.__setitem__(0, False),
    )
    provider = SimpleNamespace()
    stub.providers = {CTX_APPLE: provider}
    stub._logged_in = False
    stub._configure_apple_provider = _bind(stub, "_configure_apple_provider")
    removal = threading.Thread(target=_bind(stub, "removeFfmpeg"))
    worker = threading.current_thread()

    def a_removal_runs():
        # Only the worker's configure waits; the removal's own configure
        # resolves straight through.
        if threading.current_thread() is worker:
            if removal.ident is None:
                removal.start()
            removal.join(0.3)

    _after_each_resolve(stub, a_removal_runs)
    stub._configure_apple_provider()
    removal.join(5)

    assert not removal.is_alive()
    assert provider.ffmpeg_path == "", "the provider kept the managed binary the removal deleted"


def _build_init_download(stub):
    WavesBridge._init_download(stub)
    return stub._dl


def _build_job_download(stub, request_intent=None):
    signals = SimpleNamespace(item=None, item_name=None, list_item=None, list_name=None)
    return WavesBridge._build_download(stub, signals, request_intent=request_intent)


def _build_snapshot_job_download(stub):
    intent = capture_intent(stub.settings.data, CTX_TIDAL, "track", "t1", tier="LOSSLESS", audio_type=None, toggles={})
    return _build_job_download(stub, intent)


@pytest.mark.parametrize("on_path", [_PATH_FFMPEG, None], ids=["ffmpeg-on-path", "no-ffmpeg-on-path"])
@pytest.mark.parametrize(
    "build",
    [_build_init_download, _build_job_download, _build_snapshot_job_download],
    ids=["init-download", "job-download", "snapshot-job-download"],
)
def test_a_download_built_as_a_save_starts_sees_the_managed_path(build, on_path, monkeypatch):
    """Download construction and concurrent serialization preserve the
    managed binary for both shared and captured job settings."""
    monkeypatch.setattr(shutil, "which", lambda name: on_path)
    singleton = SettingsSingleton()
    data = CfgSettings()
    data.path_binary_ffmpeg = _MANAGED
    data.extract_flac = True
    data.video_convert_mp4 = True
    saved: list[dict] = []

    def write_serialized(data_json):
        payload = json.loads(data_json)
        saved.append({k: payload[k] for k in ("extract_flac", "video_convert_mp4", "path_binary_ffmpeg")})

    monkeypatch.setattr(singleton, "data", data)
    monkeypatch.setattr(singleton, "write_serialized", write_serialized)

    stub = _resolving_bridge()
    # Download.__init__ reads the singleton, so the bridge must hold the same one.
    stub.settings = singleton
    stub.tidal = SimpleNamespace(session=None)
    stub.providers = {CTX_TIDAL: object()}
    stub._event_abort = threading.Event()
    stub._event_run = threading.Event()
    stub._ownership = SimpleNamespace(ownership_of=None, stamp_ceiling=None)
    stub._target_quality_rank = lambda quality: 0
    stub._ffmpeg_missing_warned = False
    stub._warn_if_ffmpeg_missing = _bind(stub, "_warn_if_ffmpeg_missing")
    saver, parked, release = _park_saves_during_serialization(stub, monkeypatch)
    _after_each_resolve(stub, _a_save_starts(saver, parked))
    try:
        dl = build(stub)
    finally:
        release.set()
        if saver.ident is not None:
            saver.join(5)

    assert not saver.is_alive()
    assert dl.settings.data.path_binary_ffmpeg == _MANAGED, "the job runs without the managed binary"
    assert dl.ffmpeg_missing is False, "the Download read the user's value a save had restored for its write"
    assert saved == [{"extract_flac": True, "video_convert_mp4": True, "path_binary_ffmpeg": ""}], (
        "the save serialized what the Download wrote over the user's preferences"
    )
    assert data.path_binary_ffmpeg == _MANAGED
    assert data.extract_flac is True
    assert data.video_convert_mp4 is True


def test_an_apple_job_queued_during_a_save_keeps_the_managed_path(monkeypatch):
    """An Apple job captures the runtime binary while a save serializes
    only the user override."""
    stub = _resolving_bridge()
    stub.providers = {CTX_APPLE: object()}
    intent = capture_intent(stub.settings.data, CTX_APPLE, "track", "apple:1", tier="HIGH", audio_type=None, toggles={})
    saver, parked, release = _park_saves_during_serialization(stub, monkeypatch)
    hooks = []
    build = threading.Thread(target=lambda: hooks.append(WavesBridge._apple_job_hooks(stub, intent)))
    saver.start()
    assert parked.wait(5), "the save never reached its write"
    build.start()
    build.join(0.3)  # the time an unlocked copy has to read the save's restored value
    release.set()
    for t in (saver, build):
        t.join(5)
        assert not t.is_alive()

    assert hooks[0].settings().data.path_binary_ffmpeg == _MANAGED


def test_wiring_no_unsanitized_settings_save_after_startup():
    """Fence new save sites, whose absence cannot be driven behaviorally.

    The behavior of allowed post-startup writers is covered by the parked
    serialization and applySettings tests above. Startup saves precede
    FFmpeg snapshots and runtime injection, so they use the bare writer."""
    source = inspect.getsource(WavesBridge)
    bare = len(re.findall(r"self\.settings\.save\(\)", source))
    assert bare == 3, (
        f"found {bare} bare self.settings.save() calls, expected 3 "
        "(_apply_first_run_defaults, and __init__'s video-template migration + "
        "video_download force-off, all before ffmpeg is resolved). Route new "
        "saves through _save_settings, or this writes the transient ffmpeg "
        "flags and path to disk."
    )
    # Post-startup writers use the sanitized snapshot helper.
    submits = len(re.findall(r"self\._submit_settings_write\(\)", source))
    assert submits == 2, (
        f"found {submits} _submit_settings_write() calls, expected 2 "
        "(_save_settings and applySettings). A new caller must hold "
        "_settings_save_lock while serializing the sanitized copy."
    )

    for name in ("_apply_first_run_defaults", "__init__"):
        method_src = inspect.getsource(getattr(WavesBridge, name))
        assert "self.settings.save()" in method_src, f"{name} no longer saves; update this guard"
    for name in ("_save_settings", "applySettings"):
        method_src = inspect.getsource(getattr(WavesBridge, name))
        assert "self._submit_settings_write()" in method_src, f"{name} no longer saves; update this guard"


def _apply_bridge(save_hook=None):
    """Real Settings application and snapshot writers over a dataclass.

    ``save_hook`` parks the disk boundary when a test needs ordered writes.
    """
    stub = _Stub()

    class _Cfg:
        data = CfgSettings()
        saved: ClassVar[list[dict]] = []

        def save(self):
            if save_hook is not None:
                save_hook()
            self.saved.append(
                {
                    "extract_flac": self.data.extract_flac,
                    "video_convert_mp4": self.data.video_convert_mp4,
                    "path_binary_ffmpeg": self.data.path_binary_ffmpeg,
                }
            )

        def write_serialized(self, data_json):
            if save_hook is not None:
                save_hook()
            payload = json.loads(data_json)
            self.saved.append({k: payload[k] for k in ("extract_flac", "video_convert_mp4", "path_binary_ffmpeg")})

    stub.settings = _Cfg()
    stub._ffmpeg_flag_prefs = {"extract_flac": True, "video_convert_mp4": True}
    stub._ffmpeg_user_path = ""
    stub.settings.data.extract_flac = False
    stub.settings.data.video_convert_mp4 = False
    stub.settings.data.path_binary_ffmpeg = _MANAGED

    for name in (
        "_restore_ffmpeg_flags",
        "_restore_ffmpeg_path",
        "_resolve_ffmpeg_locked",
        "_ffmpeg_source_label",
        "_user_ffmpeg_path",
        "_waves_pref_bool",
        "_save_settings",
        "_submit_settings_write",
        "applySettings",
    ):
        setattr(stub, name, _bind(stub, name))
    stub._config_writer = _InlineWriter()
    stub._settings_save_lock = Lock()

    class _Signal:
        def __init__(self):
            self.emits: list = []

        def emit(self, *a):
            self.emits.append(a)

    stub.settingsPersistedExternally = _Signal()
    stub.librarySourceChanged = _Signal()
    stub.ownershipChanged = _Signal()
    stub.confirmCategoryDlChanged = _Signal()
    stub.ffmpegStatusChanged = _Signal()
    # applySettings reads these three to decide whether a library setting moved.
    stub._waves_prefs = {"library_enabled": False, "library_source": "", "library_folder": ""}
    stub._ffmpeg = SimpleNamespace(is_installed=lambda: True, binary_path=_MANAGED)
    stub._library_root = lambda: None
    stub._logged_in = False  # keeps _init_download out of it
    stub._set_status = lambda *a, **k: None
    return stub


def test_apply_settings_waits_for_a_worker_save_before_serializing():
    """The GUI save shares the snapshot lock with worker saves, keeping
    preference serialization and submission in order."""
    import threading

    wrote = threading.Event()
    stub = _apply_bridge(save_hook=wrote.set)

    stub._settings_save_lock.acquire()
    t = threading.Thread(target=lambda: stub.applySettings({}))
    t.start()
    try:
        assert not wrote.wait(0.3), (
            "applySettings wrote the settings file while _settings_save_lock was "
            "held: its snapshot region is not under the lock"
        )
    finally:
        stub._settings_save_lock.release()
    t.join(5)
    assert not t.is_alive(), "applySettings never finished after the lock was released"

    written = _last_save(stub)
    assert written["path_binary_ffmpeg"] == "", "a machine path (with the account name) was persisted"
    assert written["extract_flac"] is True
    assert written["video_convert_mp4"] is True


def test_worker_and_apply_saves_preserve_user_preferences_and_live_values(monkeypatch):
    stub = _apply_bridge()
    live = stub.settings.data
    saver, parked, release = _park_saves_during_serialization(stub, monkeypatch)
    apply = threading.Thread(target=lambda: stub.applySettings({}))
    saver.start()
    try:
        assert parked.wait(5), "the worker save never reached serialization"
        apply.start()
    finally:
        release.set()
        saver.join(5)
        if apply.ident is not None:
            apply.join(5)
    assert not saver.is_alive()
    assert not apply.is_alive()
    assert len(stub.settings.saved) == 2
    for written in stub.settings.saved:
        assert written["path_binary_ffmpeg"] == ""
        assert written["extract_flac"] is True
        assert written["video_convert_mp4"] is True
    assert live.path_binary_ffmpeg == _MANAGED
    assert live.extract_flac is False
    assert live.video_convert_mp4 is False


def test_a_path_entered_during_a_save_reaches_the_apple_provider(monkeypatch):
    """A concurrent snapshot must not overwrite a newly entered override
    before the Apple provider receives it."""
    stub = _apply_bridge()
    data = stub.settings.data
    saver, parked, release = _park_saves_during_serialization(stub, monkeypatch)
    handed: list[str] = []

    def configure():
        # The worker's save finishes first, as it would on its own thread.
        release.set()
        saver.join(5)
        handed.append(data.path_binary_ffmpeg)

    stub._configure_apple_provider = configure
    entered = "/opt/ffmpeg/bin/ffmpeg"
    saver.start()
    assert parked.wait(5), "the worker save never reached its write"
    apply = threading.Thread(target=lambda: stub.applySettings({"path_binary_ffmpeg": entered}))
    apply.start()
    apply.join(0.3)  # the time an unlocked edit has to land inside the save's write
    release.set()
    for t in (saver, apply):
        t.join(5)
        assert not t.is_alive(), "a writer deadlocked"

    assert handed == [entered], "the Apple provider was configured with the path the save put back"
    assert _last_save(stub)["path_binary_ffmpeg"] == entered
    assert data.path_binary_ffmpeg == entered
