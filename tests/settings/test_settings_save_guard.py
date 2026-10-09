"""Every settings save must undo the transient ffmpeg injections first.

``Download`` force-disables ``video_convert_mp4`` and ``extract_flac`` **in
memory** when ffmpeg is absent, and ``_resolve_ffmpeg`` injects the managed
binary path into ``path_binary_ffmpeg``. ``Settings`` is a singleton and
``save()`` serialises the whole dataclass, so any bare ``settings.save()``
writes those transient values to disk.

``applySettings`` and ``setVideoQuality`` restore first. Three
other save sites do not: ``keepDownloadFolder`` (answering the
download-folder nudge with "keep it"), ``muteCategoryDlConfirm`` (a plain
"Don't ask again" click) and the download-folder auto-heal. Answering a nudge
about folders would then silently turn FLAC extraction and video conversion
off on disk, invisibly until the next launch (the settings page renders the
pre-damage snapshot), and with ffmpeg present it would also persist a machine
path containing the username into settings.json, the file the bug template
asks users to paste publicly.

Every save routes through ``_save_settings``, which restores both
before saving. This test fences the invariant at the helper AND at the slots
that regressed, so a newly added save site is caught by the guard below.
"""

from __future__ import annotations

import inspect
import json
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
    """A stub carrying the real save/restore methods over a real dataclass, in
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


def test_save_settings_restores_both_injections():
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
    """The restores must not run on the singleton itself, which
    every in-flight Download holds and re-reads on every track: putting the
    values back is the save's own job, and only _resolve_ffmpeg injects. So
    a "Don't ask again" tick during an album download would strip the managed
    ffmpeg path for the rest of that album. From that track on the m4a duration
    remux is skipped and a FLAC extraction runs with an empty executable.

    What goes to disk is the user's real preference; what stays in memory is
    what the running download was built with. Both, not one or the other."""
    stub = _bridge()
    live = stub.settings.data

    stub._save_settings()

    assert _last_save(stub)["path_binary_ffmpeg"] == "", "the machine path must not reach disk"
    assert stub.settings.data is live, "the singleton's data object was swapped out and not put back"
    assert live.path_binary_ffmpeg == _MANAGED, "a running download just lost the ffmpeg binary it was built with"
    assert live.extract_flac is False, "the in-memory force-off was overwritten under a running download"
    assert live.video_convert_mp4 is False


def test_two_saves_at_once_cannot_strand_a_copy():
    """Saves fire from the GUI thread, from download workers (a share's first
    landing) and from the keep-warm daemon. Two overlapping swaps that restored
    each other's copy would leave the singleton holding a sanitised one for
    good, which is the original bug by another route."""
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


def _park_saves_after_their_restore(stub):
    """Make the stub's saves park inside their write, after the restore and
    before serializing (the lock held, the user's values standing in the live
    settings), until released. Returns a save's thread (not started), the
    event set once a save parks, and the event that lets them finish."""
    parked, release = threading.Event(), threading.Event()
    restore = stub._restore_ffmpeg_path

    def restore_then_park():
        restore()
        parked.set()
        release.wait(5)

    stub._restore_ffmpeg_path = restore_then_park
    return threading.Thread(target=stub._save_settings), parked, release


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


def test_a_resolve_during_a_save_keeps_the_managed_path_off_disk():
    """Inside a save's write the user's "" stands in the live path, and the
    resolve injects the managed path whenever it finds that field empty.
    Unlocked, it wrote the path into the values that save then serialized: an
    absolute path carrying the account name, into settings.json."""
    stub = _resolving_bridge()
    saver, parked, release = _park_saves_after_their_restore(stub)
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
    """A save on another thread can start the moment a reader's resolve
    returns. A reader that re-read the live field then got the user's "": the
    Apple provider fell back to the PATH ffmpeg and ffprobe until its next
    configure, and a preview with no ffmpeg on PATH failed outright."""
    monkeypatch.setattr(shutil, "which", lambda name: None)
    stub = _resolving_bridge()
    saver, parked, release = _park_saves_after_their_restore(stub)
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


def test_a_removal_during_a_configure_leaves_apple_off_the_deleted_binary():
    """A configure on a worker (an Apple runtime install, a sign-out) can
    resolve the managed path just as removeFfmpeg deletes it on the GUI
    thread. Handed to the provider after the lock was released, that path
    landed after the removal's own configure and left Apple on a binary that
    no longer exists."""
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
    """Download.__init__ reads its settings and, finding the path empty,
    writes the PATH ffmpeg into them, or forces FLAC extraction and video
    conversion off. A save landing between the builder's resolve and that
    read showed it the user's "": the job ran without the managed binary,
    and where it shares the live settings, the save serialized what it wrote:
    the PATH location, or a null path and both features off, over the user's
    real preferences. The Download is built under the save lock, so the save
    waits for it."""
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
    saver, parked, release = _park_saves_after_their_restore(stub)
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
    assert data.extract_flac is True and data.video_convert_mp4 is True


def test_an_apple_job_queued_during_a_save_keeps_the_managed_path():
    """An Apple job copies the live ffmpeg path into its own settings when it
    is built. Copied inside a save's write, it took the user's "" and the job
    ran its FLAC conversion and decode check on the PATH ffmpeg, or on none."""
    stub = _resolving_bridge()
    stub.providers = {CTX_APPLE: object()}
    intent = capture_intent(stub.settings.data, CTX_APPLE, "track", "apple:1", tier="HIGH", audio_type=None, toggles={})
    saver, parked, release = _park_saves_after_their_restore(stub)
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


def test_no_bare_settings_save_outside_the_guarded_helper():
    """A newly added bare save silently re-opens this bug.

    Exactly five call sites of ``self.settings.save()`` are allowed: inside
    ``_save_settings`` itself; inside ``applySettings``, which does the restores
    explicitly because it must compute ``ffmpeg_source`` from the restored value
    before saving; inside ``_apply_first_run_defaults``, which runs from
    ``__init__`` before ffmpeg is resolved, so nothing is injected yet; and two
    more in ``__init__`` under the same nothing-injected-yet reasoning: the
    video-template migration, and the one-time video_download force-off.
    """
    source = inspect.getsource(WavesBridge)
    bare = len(re.findall(r"self\.settings\.save\(\)", source))
    assert bare == 3, (
        f"found {bare} bare self.settings.save() calls, expected 3 "
        "(_apply_first_run_defaults, and __init__'s video-template migration + "
        "video_download force-off, all before ffmpeg is resolved). Route new "
        "saves through _save_settings, or this writes the transient ffmpeg "
        "flags and path to disk."
    )
    # The guarded sites persist through the snapshot-then-background write
    # (_submit_settings_write): exactly its own body plus these two callers.
    submits = len(re.findall(r"self\._submit_settings_write\(\)", source))
    assert submits == 2, (
        f"found {submits} _submit_settings_write() calls, expected 2 "
        "(_save_settings and applySettings). A new caller must hold "
        "_settings_save_lock with the restores done, exactly as those two do."
    )

    for name in ("_apply_first_run_defaults", "__init__"):
        method_src = inspect.getsource(getattr(WavesBridge, name))
        assert "self.settings.save()" in method_src, f"{name} no longer saves; update this guard"
    for name in ("_save_settings", "applySettings"):
        method_src = inspect.getsource(getattr(WavesBridge, name))
        assert "self._submit_settings_write()" in method_src, f"{name} no longer saves; update this guard"


def _apply_bridge(save_hook=None):
    """A stub carrying the REAL ``applySettings`` (and ``_save_settings``) over a
    real dataclass, in the same ffmpeg-missing state ``_bridge`` builds: the
    user's real preferences remembered, both flags forced off in memory, and the
    managed path injected.

    ``save_hook`` runs at the top of every ``settings.save()``. That is the seam
    the two tests below use to place one writer inside the other's window.
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
    stub._ffmpeg = type("_F", (), {"is_installed": staticmethod(lambda: True)})()
    stub._library_root = lambda: None
    stub._logged_in = False  # keeps _init_download out of it
    stub._set_status = lambda *a, **k: None
    return stub


def test_apply_settings_waits_for_a_worker_save_before_it_restores():
    """applySettings does the ffmpeg restores explicitly rather than through
    _save_settings, so it has to take the same lock. Held elsewhere, it must
    wait: its restore and its write are separate statements, and a worker save
    completing between them re-borrows the managed path (its finally puts the
    borrowed value back), which this write would then serialise."""
    import threading

    wrote = threading.Event()
    stub = _apply_bridge(save_hook=wrote.set)

    stub._settings_save_lock.acquire()
    t = threading.Thread(target=lambda: stub.applySettings({}))
    t.start()
    try:
        assert not wrote.wait(0.3), (
            "applySettings wrote the settings file while _settings_save_lock was "
            "held: its restore-and-save region is not under the lock"
        )
    finally:
        stub._settings_save_lock.release()
    t.join(5)
    assert not t.is_alive(), "applySettings never finished after the lock was released"

    written = _last_save(stub)
    assert written["path_binary_ffmpeg"] == "", "a machine path (with the account name) was persisted"
    assert written["extract_flac"] is True
    assert written["video_convert_mp4"] is True


def test_a_worker_write_back_cannot_reach_the_apply_settings_write():
    """THE LEAK, forced end to end. _save_settings borrows the live values for
    the length of one write and puts them back in a finally. Order it worker
    borrow, worker write, GUI restore, worker put-back, GUI write and the GUI's
    save serialises the managed ffmpeg path: an absolute path carrying the
    account name, into the file a diagnostics bundle ships, with both ffmpeg
    flags written False against a real preference of True.

    Both writers are real. applySettings is a GUI-thread slot; _save_settings
    runs on download workers (a share's first landing, a folder auto-heal) and on
    the keep-warm daemon."""
    import threading

    worker_in_write = threading.Event()
    gui_restored = threading.Event()
    worker_wrote_back = threading.Event()

    def _park():
        # Only the worker's own write parks here; the GUI's write comes later.
        if not worker_in_write.is_set():
            worker_in_write.set()
            gui_restored.wait(0.12)

    stub = _apply_bridge(save_hook=_park)
    live = stub.settings.data

    def _worker():
        stub._save_settings()
        worker_wrote_back.set()

    def _label_seam():
        # The real applySettings calls _ffmpeg_source_label between the restore
        # and the save, so standing here is standing in the window.
        gui_restored.set()
        worker_wrote_back.wait(0.12)
        return "managed"

    stub._ffmpeg_source_label = _label_seam

    w = threading.Thread(target=_worker)
    w.start()
    assert worker_in_write.wait(5), "the worker save never reached its write"
    g = threading.Thread(target=lambda: stub.applySettings({}))
    g.start()
    for t in (w, g):
        t.join(10)
        assert not t.is_alive(), "a writer deadlocked"

    assert len(stub.settings.saved) == 2, "both writes should have happened"
    for written in stub.settings.saved:
        assert written["path_binary_ffmpeg"] == "", (
            "a worker's borrowed ffmpeg path reached the settings file: that path is "
            "absolute and carries the account name, and a diagnostics bundle ships it"
        )
        assert written["extract_flac"] is True, "the user's real FLAC preference was written False"
        assert written["video_convert_mp4"] is True
    # applySettings leaves the restored value in memory on purpose and re-injects
    # via _init_download when logged in (this stub is not), so the user's value is
    # what should be standing here. The managed path standing here instead would
    # mean the worker's put-back landed after the GUI's restore, which is the
    # ordering that produced the leak.
    assert live.path_binary_ffmpeg == "", "the worker's put-back landed inside the apply window"


def test_a_path_entered_during_a_save_reaches_the_apple_provider():
    """A save mid-write puts the path it borrowed back in its finally.
    applySettings wrote a newly entered path without the save lock, so the
    put-back could land over it before the Apple provider, configured right
    after the edit, read it: Apple kept the old binary until its next
    configure."""
    stub = _apply_bridge()
    data = stub.settings.data
    saver, parked, release = _park_saves_after_their_restore(stub)
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
