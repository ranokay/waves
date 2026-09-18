"""A real bridge boots from isolated settings (issue #247, audit TT-02/TT-10).

WHAT THIS FENCES OFF
--------------------
The QML scenarios build ``WavesBridge(tidal=None)`` with the session login
patched to a no-op and the library root and Browse fetch silenced
(``support/qml.py``'s boot harness), so the composed launch the app actually
performs -- the settings and prefs loaded from disk, the real cached-token
login resolving on its worker, the launch library sweep, the provider
registry -- had no test that starts it unmocked. This one does: the only
thing faked is the environment (the XDG dirs), and every assertion is the
boot's own outcome. A token-less isolated config resolves the session offline
by design (``login_resume`` finds no stored token), so nothing here touches
the network; the library master switch decides whether a scan is dispatched,
and here it is on with the download folder pointing inside the sandbox.
"""

from __future__ import annotations

import json
import time

import pytest

# `integration` because it crosses the disk/config boundary; `qml` because the
# bridge builds real Qt objects, so a Qt-less host must skip, not error.
pytestmark = [pytest.mark.qml, pytest.mark.integration]


def _wait_for(predicate, *, timeout: float = 30.0, step: float = 0.05) -> bool:
    """Poll a bridge property that a worker resolves, or the scan publishes."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return predicate()


def _pop_singletons() -> None:
    """Drop the process-wide instances a real boot mints.

    ``config.Settings`` and ``config.WavesTidal`` are ``SingletonMeta``
    instances whose ``file_path``/token path is read once, at whichever test
    first built them. A fresh boot here means fresh instances, and the pops
    around it keep this test's sandbox instances from leaking into every later
    test (the same dance tests/library/test_restart_upgrade_baseline.py does
    for Settings alone)."""
    from waves.config import Settings as LaunchSettings
    from waves.helper.decorator import SingletonMeta
    from waves.waves_ui.session import WavesTidal

    SingletonMeta._instances.pop(LaunchSettings, None)
    SingletonMeta._instances.pop(WavesTidal, None)


def test_a_real_bridge_boots_from_isolated_settings(tmp_path, monkeypatch):
    config = tmp_path / "config" / "Waves"
    config.mkdir(parents=True)
    library = tmp_path / "library"
    library.mkdir()
    # The saved launch state: the engine settings the schema writes, and the
    # Waves prefs beside them (the library sweep switched on, pointed at the
    # sandbox so nothing outside it is ever walked).
    (config / "settings.json").write_text(
        json.dumps({"download_base_path": str(library)}),
        encoding="utf-8",
    )
    (config / "waves.json").write_text(
        json.dumps({"search_sort": "name", "library_enabled": True, "library_source": "download"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))

    from waves.waves_ui.backend import WavesBridge

    _pop_singletons()
    bridge = WavesBridge()
    try:
        # The provider registry the app runs with, and the isolated settings
        # file read back (not the defaults).
        assert set(bridge.providers) == {"tidal", "apple"}
        assert bridge.settings.data.download_base_path == str(library)
        assert bridge.wavesPref("search_sort") == "name"
        # The real cached-token login resolved (offline: no token in the
        # sandbox) and left the app signed out, never latched "Signing in…".
        # The status is written just after the resolution signal, so wait on
        # the status itself.
        assert _wait_for(lambda: bridge.sessionResolved), "the login worker never resolved the session"
        assert bridge.loggedIn is False
        assert _wait_for(lambda: bridge.status == "Not signed in"), f"the login latched at {bridge.status!r}"
        # Apple's light is off until the component is enabled.
        assert bridge.appleEnabled is False
        assert bridge.appleStatus()["state"] == "off"
        # The library root resolves through the real master switch and source
        # prefs, and the launch sweep runs and publishes through the real path.
        assert bridge._library_root() == str(library)
        assert _wait_for(
            lambda: bridge.libraryScanStatus() == "ok"
        ), f"the launch sweep never finished: {bridge.libraryScanStatus()}"
        assert bridge.libraryIndexReady() is True
    finally:
        bridge.shutdown()
        _pop_singletons()
