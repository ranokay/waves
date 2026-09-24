"""Behavioral coverage for the bridge slots and signals no test named.

Source: AUDIT.md TEST-03 (28 slots, 13 signals). Each test below binds the
real ``WavesBridge``/``_ProgressSignals`` method onto a minimal stub (the
``tests/conftest.py`` ``_Signal``/``_InlinePool`` pattern) and asserts the
method's observable contract: return value, emitted signal payload, or state
change. No test here reads source text. The ``# Slots:`` / ``# Signals:``
comment above each test lists the names it covers, so the static scan
(``rg '\\b<name>\\b' tests/`` against ``waves/desktop/backend.py``) resolves
to a behavioral test.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

from conftest import _InlinePool, _Signal

from waves.desktop import backend as bk
from waves.desktop.backend import WavesBridge, _ProgressSignals


def _bind(stub, name, owner=WavesBridge):
    return getattr(owner, name).__get__(stub, type(stub))


class _Stub:
    pass


def _stub(**kw):
    s = _Stub()
    for k, v in kw.items():
        setattr(s, k, v)
    return s


# ---------------------------------------------------------------------------
# Progress relay (_ProgressSignals): _on_pct, _on_track_event, item_name
# ---------------------------------------------------------------------------


# Slots: _on_pct. Signals: (relay item -> bridge._report_pct).
def test_on_pct_forwards_scaled_value_to_bridge():
    seen = []
    relay = _stub(_bridge=_stub(_report_pct=lambda mid, qid, pct: seen.append((mid, qid, pct))), _media_id="m1", _qid=7)
    relay._on_pct = _bind(relay, "_on_pct", _ProgressSignals)
    relay._on_pct(42.5)
    assert seen == [("m1", 7, 42.5)], "the pct relay must reach the bridge with media, row and value"


# Slots: _on_track_event. Signals: (relay track_event -> bridge._track_lifecycle).
def test_on_track_event_forwards_lifecycle_dict_to_bridge():
    seen = []
    relay = _stub(_bridge=_stub(_track_lifecycle=lambda qid, ev: seen.append((qid, ev))), _qid=9)
    relay._on_track_event = _bind(relay, "_on_track_event", _ProgressSignals)
    relay._on_track_event({"id": "t1", "status": "running"})
    assert seen == [(9, {"id": "t1", "status": "running"})], "the lifecycle event must reach the bridge as a dict"


# Signals: item_name (emission contract: emits what a listener receives).
def test_progress_item_name_signal_carries_the_title():
    relay = _ProgressSignals(None, 1, "m1", False)
    try:
        seen = []
        relay.item_name.connect(seen.append)
        relay.item_name.emit("Song Title")
        assert seen == ["Song Title"], "item_name must deliver the emitted title to listeners"
    finally:
        relay.deleteLater()


# ---------------------------------------------------------------------------
# Ownership announcements: _own_announce_arm, ownershipGeneration,
# collectionOwnershipMany
# ---------------------------------------------------------------------------


# Slots: _own_announce_arm.
def test_own_announce_arm_starts_an_idle_timer():
    started = []
    timer = SimpleNamespace(isActive=lambda: False, start=lambda: started.append(True))
    s = _stub(_own_announce_timer=timer)
    s._own_announce_arm = _bind(s, "_own_announce_arm")
    s._own_announce_arm()
    assert started == [True], "arming must start the idle announce timer"


def test_own_announce_arm_leaves_a_running_timer_alone():
    started = []
    timer = SimpleNamespace(isActive=lambda: True, start=lambda: started.append(True))
    s = _stub(_own_announce_timer=timer)
    s._own_announce_arm = _bind(s, "_own_announce_arm")
    s._own_announce_arm()
    assert started == [], "arming must not restart a timer that is already running"


# Slots: ownershipGeneration.
def test_ownershipGeneration_returns_the_forget_counter():
    s = _stub(_own_generation=3)
    s.ownershipGeneration = _bind(s, "ownershipGeneration")
    assert s.ownershipGeneration() == 3
    s2 = _stub()
    s2.ownershipGeneration = _bind(s2, "ownershipGeneration")
    assert s2.ownershipGeneration() == 0, "a fresh bridge has forgotten nothing"


# Slots: collectionOwnershipMany.
def test_collectionOwnershipMany_batches_member_lookups_in_one_call():
    members = {"c1": ["t1", "t2"], "c2": []}
    s = _stub(
        _ownership=SimpleNamespace(members_of=lambda cid: members[cid]),
        _rollup_detail=lambda ids: {"verdict": "owned" if ids else "no", "ids": ids},
    )
    s.collectionOwnershipMany = _bind(s, "collectionOwnershipMany")
    out = s.collectionOwnershipMany(["c1", "c2"])
    assert out == {"c1": {"ids": ["t1", "t2"], "verdict": "owned"}, "c2": {"ids": [], "verdict": "no"}}, (
        "one crossing must answer every card on the page"
    )


# ---------------------------------------------------------------------------
# Catalog / home: loadHome, homeLoaded, providerSignInSteps,
# bootIncubationBusy
# ---------------------------------------------------------------------------


def _home_stub(*, providers, cache=None, loading=None, page=None):
    s = _stub(
        providers=providers,
        _home_cache=dict(cache or {}),
        _home_loading=set(loading or ()),
        _home_reval_ts={},
        _browse_gen=1,
        threadpool=_InlinePool(),
        homeLoaded=_Signal(),
        _logged_in=False,
        _save_page_cache=lambda: None,
    )
    s._library_page = lambda source, cat, *a, **k: (list(page.get(cat, []) if page else []), False)
    s.loadHome = _bind(s, "loadHome")
    return s


# Slots: loadHome. Signals: homeLoaded.
def test_loadHome_unknown_source_emits_empty_landing():
    s = _home_stub(providers={})
    s.loadHome("ghost")
    assert s.homeLoaded.emits == [("ghost", [])], "a closed source must answer empty, never another source's rows"


# Slots: loadHome. Signals: homeLoaded.
def test_loadHome_emits_cached_shelves_then_revalidates():
    cached = [
        {
            "rowKind": "cards",
            "title": "Recent albums",
            "target": "albums",
            "source": "tidal",
            "items": [{"id": "a1", "kind": "album"}],
        }
    ]
    s = _home_stub(
        providers={"tidal": object()}, cache={"tidal": cached}, page={"albums": [{"id": "a1"}], "tracks": []}
    )
    s.loadHome("tidal")
    assert s.homeLoaded.emits[0] == ("tidal", cached), "the cached landing must paint instantly"
    assert s._home_cache["tidal"] == cached, "identical shelves must not rewrite the cache"


# Slots: providerSignInSteps.
def test_providerSignInSteps_lists_only_registered_step_providers():
    s = _stub(_sign_in_step_providers=("tidal", "apple", "ghost"), providers={"tidal": object(), "apple": object()})
    s.providerSignInSteps = _bind(s, "providerSignInSteps")
    assert s.providerSignInSteps() == ["tidal", "apple"], "steps open for shipped providers only"


# Slots: bootIncubationBusy.
def test_bootIncubationBusy_reads_the_live_reader_first():
    s = _stub(_incubation_reader=lambda: 2, _incubation_count=0)
    s.bootIncubationBusy = _bind(s, "bootIncubationBusy")
    assert s.bootIncubationBusy() is True
    s._incubation_reader = lambda: 0
    assert s.bootIncubationBusy() is False, "a released controller must read idle"


# Slots: bootIncubationBusy.
def test_bootIncubationBusy_falls_back_to_the_latched_count():
    s = _stub(_incubation_reader=None, _incubation_count=1)
    s.bootIncubationBusy = _bind(s, "bootIncubationBusy")
    assert s.bootIncubationBusy() is True
    s._incubation_count = 0
    assert s.bootIncubationBusy() is False


# ---------------------------------------------------------------------------
# Busy / setup / folder gate signals via their real emitters:
# busyChanged (_set_busy), setupRequested (showSetup),
# downloadFolderMissing / downloadFolderDefault (_download_gate),
# motionBgChanged (setWavesPref)
# ---------------------------------------------------------------------------


# Signals: busyChanged (via _set_busy).
def test_set_busy_announces_transitions_only():
    s = _stub(_busy=False, busyChanged=_Signal())
    s._set_busy = _bind(s, "_set_busy")
    s._set_busy(True)
    assert s._busy is True and len(s.busyChanged.emits) == 1
    s._set_busy(True)
    assert len(s.busyChanged.emits) == 1, "re-setting the same value must not re-emit"


# Signals: setupRequested (via showSetup).
def test_showSetup_forwards_to_the_welcome_surface():
    s = _stub(setupRequested=_Signal())
    s.showSetup = _bind(s, "showSetup")
    s.showSetup()
    assert s.setupRequested.emits == [()], "the bridge only forwards; QML owns the surface"


# Signals: downloadFolderMissing, downloadFolderDefault (via _download_gate).
def test_download_gate_blocks_when_no_folder_is_set():
    s = _stub(
        settings=SimpleNamespace(data=SimpleNamespace(download_base_path="", download_folder_prompted=False)),
        downloadFolderMissing=_Signal(),
        downloadFolderDefault=_Signal(),
        statusChanged=_Signal(),
        _status="",
    )
    s._set_status = _bind(s, "_set_status")
    s._folder_gate_action = WavesBridge._folder_gate_action  # static: no binding
    s._download_gate = _bind(s, "_download_gate")
    assert s._download_gate() == "block"
    assert len(s.downloadFolderMissing.emits) == 1
    assert s.downloadFolderDefault.emits == []


# Signals: downloadFolderMissing, downloadFolderDefault (via _download_gate).
def test_download_gate_nudges_once_on_the_legacy_default():
    s = _stub(
        settings=SimpleNamespace(data=SimpleNamespace(download_base_path="~/download", download_folder_prompted=False)),
        downloadFolderMissing=_Signal(),
        downloadFolderDefault=_Signal(),
        statusChanged=_Signal(),
        _status="",
    )
    s._set_status = _bind(s, "_set_status")
    s._folder_gate_action = WavesBridge._folder_gate_action  # static: no binding
    s._download_gate = _bind(s, "_download_gate")
    assert s._download_gate() == "nudge"
    assert len(s.downloadFolderDefault.emits) == 1
    assert s.downloadFolderMissing.emits == []


# Signals: motionBgChanged (via setWavesPref).
def test_setWavesPref_motion_background_notifies_the_scene():
    s = _stub(
        _waves_prefs={"motion_background": False},
        _save_waves_prefs=lambda: None,
        motionBgChanged=_Signal(),
        hoverMotionChanged=_Signal(),
        artHoverTiltChanged=_Signal(),
        videoHoverPeekChanged=_Signal(),
    )
    s.setWavesPref = _bind(s, "setWavesPref")
    s.setWavesPref("motion_background", True)
    assert s._waves_prefs["motion_background"] is True
    assert len(s.motionBgChanged.emits) == 1, "the scene re-reads the pref on this signal"


# ---------------------------------------------------------------------------
# Held downloads: bypassFfmpegGate, retryDownloadFolder
# ---------------------------------------------------------------------------


# Slots: bypassFfmpegGate.
def test_bypassFfmpegGate_remembers_and_runs_held_downloads():
    ran = []
    s = _stub(_ffmpeg_gate_bypassed=False, _run_pending_downloads=lambda: ran.append(True))
    s.bypassFfmpegGate = _bind(s, "bypassFfmpegGate")
    s.bypassFfmpegGate()
    assert s._ffmpeg_gate_bypassed is True
    assert ran == [True], "Continue anyway must run the held downloads degraded"


# Slots: retryDownloadFolder.
def test_retryDownloadFolder_reruns_every_held_download():
    ran = []
    s = _stub(_run_pending_downloads=lambda: ran.append(True))
    s.retryDownloadFolder = _bind(s, "retryDownloadFolder")
    s.retryDownloadFolder()
    assert ran == [True], "Try again must re-enter the full gate for every held download"


# ---------------------------------------------------------------------------
# FFmpeg / app update: ffmpegStatus, checkFfmpegUpdate, ffmpegUpdateChecked,
# cancelFfmpeg, removeFfmpeg, resumePendingUpdate, appUpdatePending,
# startupFfmpegUpdateCheck, cancelAppUpdate, restartForUpdate,
# openReleasesPage
# ---------------------------------------------------------------------------


# Slots: ffmpegStatus.
def test_ffmpegStatus_passes_the_explicit_override_through():
    s = _stub(
        _ffmpeg=SimpleNamespace(status=lambda path: {"state": "managed", "path": path}),
        _user_ffmpeg_path=lambda: "/custom/ffmpeg",
    )
    s.ffmpegStatus = _bind(s, "ffmpegStatus")
    assert s.ffmpegStatus() == {"state": "managed", "path": "/custom/ffmpeg"}


# Slots: checkFfmpegUpdate. Signals: ffmpegUpdateChecked.
def test_checkFfmpegUpdate_emits_the_available_triple():
    s = _stub(
        _ffmpeg=SimpleNamespace(update_available=lambda: (True, "1.0", "1.1")),
        threadpool=_InlinePool(),
        ffmpegUpdateChecked=_Signal(),
    )
    s.checkFfmpegUpdate = _bind(s, "checkFfmpegUpdate")
    s.checkFfmpegUpdate()
    assert s.ffmpegUpdateChecked.emits == [(True, "1.0", "1.1")]


# Slots: checkFfmpegUpdate. Signals: ffmpegUpdateChecked.
def test_checkFfmpegUpdate_failure_emits_blank():
    def boom():
        raise RuntimeError("offline")

    s = _stub(_ffmpeg=SimpleNamespace(update_available=boom), threadpool=_InlinePool(), ffmpegUpdateChecked=_Signal())
    s.checkFfmpegUpdate = _bind(s, "checkFfmpegUpdate")
    s.checkFfmpegUpdate()
    assert s.ffmpegUpdateChecked.emits == [(False, "", "")], "a failed check must read as none available"


# Slots: cancelFfmpeg.
def test_cancelFfmpeg_trips_the_abort():
    abort = threading.Event()
    s = _stub(_ffmpeg_abort=abort)
    s.cancelFfmpeg = _bind(s, "cancelFfmpeg")
    s.cancelFfmpeg()
    assert abort.is_set(), "cancel must stop the in-flight ffmpeg work"


# Slots: removeFfmpeg. Signals: ffmpegStatusChanged.
def test_removeFfmpeg_removes_restores_path_and_notifies():
    calls = []
    s = _stub(
        _ffmpeg=SimpleNamespace(remove=lambda: calls.append("remove")),
        _restore_ffmpeg_path=lambda: calls.append("restore"),
        _configure_apple_provider=lambda: calls.append("apple"),
        _logged_in=False,
        ffmpegStatusChanged=_Signal(),
    )
    s.removeFfmpeg = _bind(s, "removeFfmpeg")
    s.removeFfmpeg()
    assert calls == ["remove", "restore", "apple"], "the dangling managed path must not survive the removal"
    assert len(s.ffmpegStatusChanged.emits) == 1


# Slots: resumePendingUpdate. Signals: appUpdatePending, appUpdateStatusChanged.
def test_resumePendingUpdate_rearms_a_staged_update():
    emitted = []
    s = _stub(
        _updater=SimpleNamespace(resume_pending_apply=lambda: {"version": "2.0.0"}),
        threadpool=_InlinePool(),
        _emit_from_worker=lambda name, *a: emitted.append((name, *a)),
    )
    s.resumePendingUpdate = _bind(s, "resumePendingUpdate")
    s.resumePendingUpdate()
    assert ("appUpdatePending", "2.0.0") in emitted
    assert ("appUpdateStatusChanged",) in emitted, "the UI said restart to finish; it must say so again"


# Slots: resumePendingUpdate. Signals: appUpdatePending.
def test_resumePendingUpdate_is_quiet_when_nothing_is_staged():
    emitted = []
    s = _stub(
        _updater=SimpleNamespace(resume_pending_apply=lambda: None),
        threadpool=_InlinePool(),
        _emit_from_worker=lambda name, *a: emitted.append((name, *a)),
    )
    s.resumePendingUpdate = _bind(s, "resumePendingUpdate")
    s.resumePendingUpdate()
    assert emitted == [], "no staged tree means nothing to re-arm and nothing to say"


# Slots: startupFfmpegUpdateCheck. Signals: ffmpegUpdateChecked.
def test_startupFfmpegUpdateCheck_is_quiet_when_opted_out():
    started = []
    s = _stub(
        _waves_pref_bool=lambda key: False,
        _waves_prefs={},
        threadpool=SimpleNamespace(start=lambda w: started.append(True)),
    )
    s.startupFfmpegUpdateCheck = _bind(s, "startupFfmpegUpdateCheck")
    s.startupFfmpegUpdateCheck()
    assert started == [], "an opted-out install must never hit the network at startup"


# Slots: startupFfmpegUpdateCheck. Signals: ffmpegUpdateChecked.
def test_startupFfmpegUpdateCheck_fires_for_a_managed_install():
    emitted = []
    prefs = {"ffmpeg_auto_update": True, "ffmpeg_update_cadence": "daily", "ffmpeg_update_last_check": 0}
    s = _stub(
        _waves_pref_bool=lambda key: True,
        _waves_prefs=prefs,
        _save_waves_prefs=lambda: None,
        _user_ffmpeg_path=lambda: "",
        _ffmpeg=SimpleNamespace(
            status=lambda path: {"state": "managed"}, update_available=lambda: (False, "1.1", "1.1")
        ),
        threadpool=_InlinePool(),
        _emit_from_worker=lambda name, *a: emitted.append((name, *a)),
    )
    s.startupFfmpegUpdateCheck = _bind(s, "startupFfmpegUpdateCheck")
    s.startupFfmpegUpdateCheck()
    assert prefs["ffmpeg_update_last_check"] > 0, "the stamp must land before firing (no double trigger)"
    assert (("ffmpegUpdateChecked", False, "1.1", "1.1")) in emitted


# Slots: cancelAppUpdate.
def test_cancelAppUpdate_trips_the_abort():
    abort = threading.Event()
    s = _stub(_app_update_abort=abort)
    s.cancelAppUpdate = _bind(s, "cancelAppUpdate")
    s.cancelAppUpdate()
    assert abort.is_set(), "cancel must stop the in-flight app update"


# Slots: restartForUpdate.
def test_restartForUpdate_shuts_down_then_quits(monkeypatch):
    shutdowns = []
    relaunches = []
    quits = []
    s = _stub(
        shutdown=lambda: shutdowns.append(True),
        _updater=SimpleNamespace(os_key="linux", relaunch=lambda: relaunches.append(True)),
    )
    monkeypatch.setattr(bk.QtGui.QGuiApplication, "quit", staticmethod(lambda *a: quits.append(True)))
    s.restartForUpdate = _bind(s, "restartForUpdate")
    s.restartForUpdate()
    assert shutdowns == [True] and relaunches == [True] and quits == [True]


# Slots: openReleasesPage.
def test_openReleasesPage_opens_the_release_notes(monkeypatch):
    opened = []
    s = _stub(_updater=SimpleNamespace(releases_url=lambda: "https://example.test/releases"))
    monkeypatch.setattr(bk.QtGui.QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(str(url))))
    s.openReleasesPage = _bind(s, "openReleasesPage")
    s.openReleasesPage()
    assert any("https://example.test/releases" in o for o in opened), f"the notes link must reach the browser: {opened}"


# ---------------------------------------------------------------------------
# Video: playVideo, videoReady, peekVideo, videoPeekReady
# ---------------------------------------------------------------------------


def _video_stub(monkeypatch, *, logged_in=True):
    tidal = SimpleNamespace(get_object=lambda kind, vid: SimpleNamespace(get_url=lambda: "http://master.m3u8"))
    s = _stub(
        _logged_in=logged_in,
        providers={"tidal": tidal},
        _objs={"video": {}},
        threadpool=_InlinePool(),
        videoReady=_Signal(),
        videoPeekReady=_Signal(),
    )
    s._remember = lambda bucket, key, obj: s._objs[bucket].__setitem__(key, obj)
    s._video_album_fallback = lambda title, artist: ("alb1", "trk1")
    s._pick_video_stream = lambda url: ("http://variant-720.m3u8", 720, [360, 720])
    s._pick_peek_stream = lambda url: "http://variant-360.m3u8"
    monkeypatch.setattr(bk, "name_builder_title", lambda obj: "Title")
    monkeypatch.setattr(bk, "name_builder_artist", lambda obj: "Artist")
    monkeypatch.setattr(bk, "_artists_list", lambda obj: ["Artist"])
    monkeypatch.setattr(bk, "_artist_id", lambda obj: "art1")
    return s


# Slots: playVideo. Signals: videoReady.
def test_playVideo_resolves_the_full_stream_for_the_overlay(monkeypatch):
    s = _video_stub(monkeypatch)
    s.playVideo = _bind(s, "playVideo")
    s.playVideo("v1")
    assert len(s.videoReady.emits) == 1
    payload = s.videoReady.emits[0]
    assert payload["id"] == "v1" and payload["error"] is False
    assert payload["url"] == "http://variant-720.m3u8" and payload["res"] == 720
    assert payload["album_id"] == "alb1", "the title link must land somewhere"


# Slots: playVideo. Signals: videoReady.
def test_playVideo_is_quiet_when_signed_out(monkeypatch):
    s = _video_stub(monkeypatch, logged_in=False)
    s.playVideo = _bind(s, "playVideo")
    s.playVideo("v1")
    assert s.videoReady.emits == [], "nothing may resolve off the GUI thread while signed out"


# Slots: peekVideo. Signals: videoPeekReady.
def test_peekVideo_resolves_the_light_variant_for_the_card(monkeypatch):
    s = _video_stub(monkeypatch)
    s.peekVideo = _bind(s, "peekVideo")
    s.peekVideo("v9")
    assert len(s.videoPeekReady.emits) == 1
    payload = s.videoPeekReady.emits[0]
    assert payload == {"id": "v9", "url": "http://variant-360.m3u8", "error": False}


# ---------------------------------------------------------------------------
# Diagnostics: _emit_diagnostics_exported, diagnosticsExported,
# revealDiagnostics
# ---------------------------------------------------------------------------


# Slots: _emit_diagnostics_exported. Signals: diagnosticsExported.
def test_emit_diagnostics_exported_forwards_the_bundle_path():
    s = _stub(diagnosticsExported=_Signal())
    s._emit_diagnostics_exported = _bind(s, "_emit_diagnostics_exported")
    s._emit_diagnostics_exported("/tmp/waves-diag.zip")
    assert s.diagnosticsExported.emits == ["/tmp/waves-diag.zip"]


# Slots: revealDiagnostics.
def test_revealDiagnostics_opens_the_bundle_folder(monkeypatch):
    opened = []
    monkeypatch.setattr(bk.QtGui.QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(str(url))))
    s = _stub(settings=SimpleNamespace(file_path="/cfg/settings.json"))
    s.revealDiagnostics = _bind(s, "revealDiagnostics")
    s.revealDiagnostics("/tmp/out/waves-diag.zip")
    assert opened and "tmp" in opened[0] and "waves-diag.zip" not in opened[0], (
        "the file manager must open the containing folder, not the bundle"
    )


# ---------------------------------------------------------------------------
# Share / Apple runtime / settings: copyShareUrl, appleRuntimeStatus,
# removeAppleRuntime, resetSettingsDefaults, uiLog,
# appleRuntimeProgress (via installAppleRuntime)
# ---------------------------------------------------------------------------


# Slots: copyShareUrl.
def test_copyShareUrl_copies_the_link_and_confirms(monkeypatch):
    copied = []
    s = _stub(
        _objs={"track": {"t1": SimpleNamespace(share_url="https://tidal.test/t/1")}},
        statusChanged=_Signal(),
        _status="",
    )
    s._set_status = _bind(s, "_set_status")
    monkeypatch.setattr(
        bk.QtGui.QGuiApplication, "clipboard", staticmethod(lambda: SimpleNamespace(setText=copied.append))
    )
    s.copyShareUrl = _bind(s, "copyShareUrl")
    s.copyShareUrl("track", "t1")
    assert copied == ["https://tidal.test/t/1"]
    assert s._status == "Link copied"


# Slots: copyShareUrl.
def test_copyShareUrl_is_quiet_without_a_link(monkeypatch):
    copied = []
    s = _stub(_objs={"track": {}}, statusChanged=_Signal(), _status="")
    s._set_status = _bind(s, "_set_status")
    monkeypatch.setattr(
        bk.QtGui.QGuiApplication, "clipboard", staticmethod(lambda: SimpleNamespace(setText=copied.append))
    )
    s.copyShareUrl = _bind(s, "copyShareUrl")
    s.copyShareUrl("track", "missing")
    assert copied == [] and s._status == ""


# Slots: appleRuntimeStatus.
def test_appleRuntimeStatus_reports_the_managed_status():
    s = _stub(
        _apple_runtime=SimpleNamespace(status=lambda custom: {"state": "ready", "path": "/m"}),
        settings=SimpleNamespace(data=SimpleNamespace(path_binary_nm3u8dlre="")),
    )
    s.appleRuntimeStatus = _bind(s, "appleRuntimeStatus")
    assert s.appleRuntimeStatus() == {"state": "ready", "path": "/m"}


# Slots: appleRuntimeStatus.
def test_appleRuntimeStatus_is_missing_without_a_manager():
    s = _stub(_apple_runtime=None, settings=SimpleNamespace(data=SimpleNamespace(path_binary_nm3u8dlre="")))
    s.appleRuntimeStatus = _bind(s, "appleRuntimeStatus")
    assert s.appleRuntimeStatus() == {"state": "missing", "available": False, "managed": False, "path": ""}


# Slots: removeAppleRuntime. Signals: appleRuntimeStatusChanged.
def test_removeAppleRuntime_removes_and_reconfigures():
    calls = []
    s = _stub(
        _apple_runtime=SimpleNamespace(remove=lambda: calls.append("remove")),
        _configure_apple_provider=lambda: calls.append("configure"),
        appleRuntimeStatusChanged=_Signal(),
        appleStatusChanged=_Signal(),
    )
    s.removeAppleRuntime = _bind(s, "removeAppleRuntime")
    s.removeAppleRuntime()
    assert calls == ["remove", "configure"]
    assert len(s.appleRuntimeStatusChanged.emits) == 1
    assert len(s.appleStatusChanged.emits) == 1


# Slots: installAppleRuntime. Signals: appleRuntimeProgress.
def test_installAppleRuntime_progress_reaches_the_card():
    states = []

    class _Manager:
        def install(self, progress_cb, log_cb):
            progress_cb(0.5)
            log_cb("halfway")
            return {"version": "9.9"}

    s = _stub(
        _apple_runtime_inflight=False,
        _apple_runtime=_Manager(),
        _configure_apple_provider=lambda: states.append("configured"),
        threadpool=_InlinePool(),
        appleRuntimeProgress=_Signal(),
        appleRuntimeStateChanged=_Signal(),
        appleRuntimeStatusChanged=_Signal(),
        appleStatusChanged=_Signal(),
    )
    s.installAppleRuntime = _bind(s, "installAppleRuntime")
    s.installAppleRuntime()
    assert s.appleRuntimeProgress.emits == [0.5], "the card's bar must follow the install"
    assert ("downloading", "halfway") in s.appleRuntimeStateChanged.emits
    assert states == ["configured"]
    assert s._apple_runtime_inflight is False, "the next install must not be locked out"


# Slots: resetSettingsDefaults.
def test_resetSettingsDefaults_routes_every_default_through_applySettings():
    applied = []
    s = _stub(
        _factory_default_values=lambda: {"a": 1},
        applySettings=lambda values: applied.append(dict(values)),
        _video_user_quality=True,
        statusChanged=_Signal(),
        _status="",
    )
    s._set_status = _bind(s, "_set_status")
    s.resetSettingsDefaults = _bind(s, "resetSettingsDefaults")
    s.resetSettingsDefaults()
    assert applied == [{"a": 1}], "every side effect must stay on the one apply path"
    assert s._video_user_quality is False, "a reset is not an explicit quality choice"
    assert s._status == "Settings reset to defaults"


# Slots: uiLog.
def test_uiLog_routes_durations_and_point_events(monkeypatch):
    calls = []
    monkeypatch.setattr(bk.devlog, "done", lambda cat, msg, secs: calls.append(("done", cat, msg, secs)))
    monkeypatch.setattr(bk.devlog, "event", lambda cat, msg, **k: calls.append(("event", cat, msg)))
    s = _stub()
    s.uiLog = _bind(s, "uiLog")
    s.uiLog("nav", "home shown", 500.0)
    s.uiLog("nav", "clicked")
    assert calls[0] == ("done", "nav", "home shown", 0.5), "ms must arrive as seconds on the one timeline"
    assert calls[1] == ("event", "nav", "clicked")
