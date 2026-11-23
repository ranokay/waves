"""Download-folder gates and recovery."""

from __future__ import annotations

from unittest.mock import MagicMock

from waves.desktop import backend
from waves.desktop.backend import WavesBridge

# ----- download-folder gate ------------------------------------------------


def test_folder_gate_blank_blocks():
    assert WavesBridge._folder_gate_action("", False) == "block"
    assert WavesBridge._folder_gate_action("   ", False) == "block"
    assert WavesBridge._folder_gate_action(None, False) == "block"


def test_folder_gate_legacy_default_nudges_once():
    # Existing user still on the old default, not yet warned -> one-time nudge.
    assert WavesBridge._folder_gate_action("~/download", False) == "nudge"
    # Once marked prompted, it must never nag again.
    assert WavesBridge._folder_gate_action("~/download", True) == "ok"


def test_folder_gate_real_path_ok():
    assert WavesBridge._folder_gate_action("/Users/me/Music", False) == "ok"
    assert WavesBridge._folder_gate_action("/Users/me/Music", True) == "ok"


def test_download_gate_never_probes_the_filesystem():
    """The click-time gate runs on the GUI thread: it must stay pure string
    checks. The write probe of the folder (seconds against a stale network
    mount, and it froze the UI before the queue row could even appear) belongs
    to _gate_reachability on the download worker."""
    fake = MagicMock()
    fake._folder_gate_action = lambda *a: "ok"
    assert WavesBridge._download_gate(fake) == "ok"
    fake._probe_download_base.assert_not_called()


def _gate_fake():
    """MagicMock bridge with the real pending-download helpers bound on, so the
    gate/dialog tests exercise the genuine stash-and-replay behavior."""
    from threading import Lock

    fake = MagicMock()
    fake._base_ok = ("", 0.0)  # no recent write: the probe must be consulted
    fake._pending_lock = Lock()
    fake._pending_downloads = []
    fake._stash_pending_download = WavesBridge._stash_pending_download.__get__(fake)
    fake._run_pending_downloads = WavesBridge._run_pending_downloads.__get__(fake)
    # Saves go through the guarded helper, which undoes the transient ffmpeg
    # injections before writing (see tests/settings/test_settings_save_guard.py).
    fake._ffmpeg_flag_prefs = {}
    fake._ffmpeg_user_path = ""
    fake._restore_ffmpeg_flags = WavesBridge._restore_ffmpeg_flags.__get__(fake)
    fake._restore_ffmpeg_path = WavesBridge._restore_ffmpeg_path.__get__(fake)
    fake._save_settings = WavesBridge._save_settings.__get__(fake)
    # The disk seam behind _save_settings; route it into the fake's counter.
    fake._submit_settings_write = lambda: fake.settings.save()
    return fake


def test_gate_reachability_ok_proceeds():
    fake = _gate_fake()
    fake._probe_download_base = lambda: ("ok", "/some/folder")
    assert WavesBridge._gate_reachability(fake, lambda: None) is True


def test_gate_reachability_healed_persists_live_path():
    fake = _gate_fake()
    fake._probe_download_base = lambda: ("healed", "/Volumes/Music 1/Library")
    assert WavesBridge._gate_reachability(fake, lambda: None) is True
    assert fake.settings.data.download_base_path == "/Volumes/Music 1/Library"
    fake.settings.save.assert_called_once()


def test_gate_reachability_dead_holds_retry_and_warns():
    fake = _gate_fake()
    fake._probe_download_base = lambda: ("dead", "/Volumes/Gone/Library")
    retry = lambda: None
    assert WavesBridge._gate_reachability(fake, retry, "m1") is False
    assert fake._pending_downloads == [("m1", retry)]
    fake.downloadFolderUnreachable.emit.assert_called_once()


def test_keep_download_folder_marks_prompted_and_replays():
    # "Keep the default location": persist the decision and run every held download.
    ran = []
    fake = _gate_fake()
    fake._stash_pending_download("a", lambda: ran.append("a"))
    fake._stash_pending_download("b", lambda: ran.append("b"))
    WavesBridge.keepDownloadFolder(fake)
    assert fake.settings.data.download_folder_prompted is True
    fake.settings.save.assert_called_once()
    assert ran == ["a", "b"]  # every deferred download actually ran
    assert fake._pending_downloads == []  # and the holds were cleared


def test_dismiss_download_folder_nudge_drops_pending_without_running():
    # "Choose a new location" / dismiss: abandon the held downloads, persist nothing
    # (so an unresolved default is asked about again next time).
    ran = []
    fake = _gate_fake()
    fake._stash_pending_download("a", lambda: ran.append("go"))
    WavesBridge.dismissDownloadFolderNudge(fake)
    assert ran == []  # nothing downloaded
    assert fake._pending_downloads == []
    fake.settings.save.assert_not_called()


def test_reveal_download_path_opens_nearest_existing(tmp_path, monkeypatch):
    # Clicking the nudge's path opens the OS file manager at the download folder,
    # or the nearest existing ancestor if that folder doesn't exist yet.
    opened = []

    class _FakeDS:
        @staticmethod
        def openUrl(url):
            opened.append(url.toLocalFile())

    monkeypatch.setattr(backend.QtGui, "QDesktopServices", _FakeDS)
    fake = MagicMock()
    fake.settings.data.download_base_path = str(tmp_path)
    WavesBridge.revealDownloadPath(fake)
    assert opened[-1] == str(tmp_path)  # existing folder revealed as-is
    fake.settings.data.download_base_path = str(tmp_path / "does" / "not" / "exist")
    WavesBridge.revealDownloadPath(fake)
    assert opened[-1] == str(tmp_path)  # falls back to nearest existing ancestor
