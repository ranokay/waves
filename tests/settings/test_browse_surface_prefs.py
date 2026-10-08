"""The combined Browse landing's surface prefs (issue #600).

The landing remembers its source filter and its section arrangement — hidden
sections, collapsed sections and each provider's section order — in
waves.json. The arrangement maps are JSON objects carried as strings (the
Settings-open state's shape), so a provider the app has never heard of still
round-trips without wiring.
"""

from __future__ import annotations

import json

from waves.desktop.backend import WavesBridge


class _PrefsStub:
    """Bare stand-in carrying only the waves-prefs surface, with the real
    load/save methods bound on and a real waves.json on disk."""

    def __init__(self, tmp_path):
        self._waves_prefs_path = str(tmp_path / "waves.json")
        for name in (
            "_default_waves_prefs",
            "_load_waves_prefs",
            "_preserve_unreadable_prefs",
            "setWavesPref",
            "wavesPref",
        ):
            setattr(self, name, getattr(WavesBridge, name).__get__(self, _PrefsStub))
        self._save_waves_prefs = lambda: None
        self._waves_prefs = self._load_waves_prefs()


def _write_prefs(tmp_path, data: dict) -> None:
    (tmp_path / "waves.json").write_text(json.dumps(data), encoding="utf-8")


def test_the_browse_source_filter_defaults_to_all_and_round_trips(tmp_path):
    stub = _PrefsStub(tmp_path)
    assert stub.wavesPref("browse_source_filter") == "all"
    stub.setWavesPref("browse_source_filter", "stub")
    assert stub.wavesPref("browse_source_filter") == "stub"


def test_the_arrangement_maps_default_empty_and_round_trip(tmp_path):
    stub = _PrefsStub(tmp_path)
    assert stub.wavesPref("browse_sections_hidden") == ""
    assert stub.wavesPref("browse_sections_collapsed") == ""
    assert stub.wavesPref("browse_section_order") == ""

    hidden = {"stub|Stub shelf": True}
    collapsed = {"tidal|New albums": True}
    order = {"stub": ["First", "Second"]}
    stub.setWavesPref("browse_sections_hidden", json.dumps(hidden))
    stub.setWavesPref("browse_sections_collapsed", json.dumps(collapsed))
    stub.setWavesPref("browse_section_order", json.dumps(order))
    assert json.loads(stub.wavesPref("browse_sections_hidden")) == hidden
    assert json.loads(stub.wavesPref("browse_sections_collapsed")) == collapsed
    assert json.loads(stub.wavesPref("browse_section_order")) == order


def test_stored_browse_keys_load_and_unknown_keys_do_not(tmp_path):
    _write_prefs(
        tmp_path,
        {
            "browse_source_filter": "stub",
            "browse_sections_hidden": '{"stub|Shelf": true}',
            "browse_who_knows": True,
        },
    )
    stub = _PrefsStub(tmp_path)
    assert stub.wavesPref("browse_source_filter") == "stub"
    assert stub.wavesPref("browse_sections_hidden") == '{"stub|Shelf": true}'
    assert stub.wavesPref("browse_who_knows") is None
