"""Settings remembers its shape: sections collapsed by default, state kept.

The page used to hardcode Downloads open and forget everything else between
launches. Now every section starts collapsed on a first visit, the user's
opens/closes persist in the settings_open_sections pref (a JSON object of
id -> bool), and deep links (update notice, folder gate, lyrics link) open
their target section themselves. The QML half (exact scroll restore through
the save-armed schema rebuild included) is exercised by
scratchpad/settings_place_probe.py against the live Main.qml.
"""

from __future__ import annotations

import json

from support.settings_fakes import prefs_stub as _prefs_stub
from support.settings_fakes import schema_stub as _schema_stub

from waves.waves_ui.backend import WavesBridge


class _Stub:
    """Bare object the real methods get bound onto."""


def _bind(stub, name):
    return getattr(WavesBridge, name).__get__(stub, type(stub))


def test_open_sections_pref_defaults_to_untouched():
    assert _prefs_stub()._waves_prefs["settings_open_sections"] == ""


def test_no_section_ships_forced_open():
    schema = WavesBridge.settingsSchema(_schema_stub())
    forced = [s["id"] for s in schema if s.get("open") is True]
    assert forced == [], "every section must start collapsed on a first visit"


def test_open_sections_survive_a_round_trip_as_json():
    stub = _prefs_stub()
    stub._save_waves_prefs = lambda: None
    stub._factory_reset = False
    recorded = json.dumps({"advanced": True, "downloads": False})
    _bind(stub, "setWavesPref")("settings_open_sections", recorded)
    # setWavesPref str-coerces non-bool prefs; the JSON must come back intact
    # for the page to parse on the next launch.
    stored = stub._waves_prefs["settings_open_sections"]
    assert json.loads(stored) == {"advanced": True, "downloads": False}
