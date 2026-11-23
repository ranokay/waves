"""The "Tracks shown in an open queue row" preference.

An open queue row lists its tracks in a box that stops growing at a number of
rows and scrolls inside after that (issue #727, upstream #54). That number is
a setting, and this pins the things that make it real: it ships at 12, it is
offered as a whole number with its range in Settings > Advanced, a saved value
is held inside the range (a stray string or a hand-edited waves.json can never
size the box off a cliff), a stored value is held there on load too, a change
notifies the QML, which re-reads the pref on that signal, and RESET ALL
SETTINGS restores it.

The live re-read itself is proved on the real Main.qml by
``test_queue_ledger_scroll.py`` (setting 6 rows shrinks the open box).
"""

from __future__ import annotations

import json

from settings.fakes import prefs_stub, schema_stub

from waves.desktop.backend import WavesBridge

KEY = "queue_ledger_rows"
DEFAULT = 12
LO, HI = 4, 40


def _bind(stub, name):
    return getattr(WavesBridge, name).__get__(stub, type(stub))


def _setter_stub():
    stub = prefs_stub()
    stub._save_waves_prefs = lambda: None
    stub._factory_reset = False
    return stub, stub.queueLedgerRowsChanged


def test_ships_at_twelve_rows():
    assert prefs_stub()._waves_prefs[KEY] == DEFAULT


def test_offered_in_advanced_as_a_bounded_number():
    schema = WavesBridge.settingsSchema(schema_stub())
    advanced = next(s for s in schema if s["id"] == "advanced")
    field = next((f for f in advanced["fields"] if f["key"] == KEY), None)
    assert field is not None, "the setting must be reachable from Settings > Advanced"
    assert field["type"] == "int"
    assert field["value"] == DEFAULT
    assert (field["minimum"], field["maximum"]) == (LO, HI)
    assert field["label"] and field["help"]


def test_a_change_is_saved_as_a_number_and_notifies_the_ui():
    stub, fired = _setter_stub()
    _bind(stub, "setWavesPref")(KEY, 20)
    assert stub._waves_prefs[KEY] == 20
    assert fired.emits, "Main.qml only re-reads the pref when queueLedgerRowsChanged fires"
    # The page hands numbers over as floats or strings too.
    _bind(stub, "setWavesPref")(KEY, "15")
    assert stub._waves_prefs[KEY] == 15


def test_a_saved_value_is_held_inside_the_range():
    stub, _ = _setter_stub()
    set_pref = _bind(stub, "setWavesPref")
    set_pref(KEY, 0)
    assert stub._waves_prefs[KEY] == LO
    set_pref(KEY, 10_000)
    assert stub._waves_prefs[KEY] == HI
    set_pref(KEY, 9)
    for garbage in ("lots", None, True):
        set_pref(KEY, garbage)
        assert stub._waves_prefs[KEY] == 9, f"{garbage!r} must keep the value it had"


def test_an_unchanged_value_does_not_notify():
    stub, fired = _setter_stub()
    _bind(stub, "setWavesPref")(KEY, DEFAULT)
    assert not fired.emits


def test_a_stored_value_is_held_inside_the_range_on_load(tmp_path):
    stub = prefs_stub()
    stub._load_waves_prefs = _bind(stub, "_load_waves_prefs")
    stub._waves_prefs_path = str(tmp_path / "waves.json")
    for stored, want in ((999, HI), (-3, LO), ("abc", DEFAULT), (None, DEFAULT), ("17", 17)):
        (tmp_path / "waves.json").write_text(json.dumps({KEY: stored}), encoding="utf-8")
        assert stub._load_waves_prefs()[KEY] == want, stored


def test_reset_all_settings_restores_twelve_rows():
    stub = schema_stub()
    stub.settingsSchema = _bind(stub, "settingsSchema")
    values = WavesBridge._factory_default_values(stub)
    assert values.get(KEY) == DEFAULT
