"""The search page's surface prefs.

The unified results view keeps one SHOW ALL state per section
(``search_section_<section>_expanded``, declared defaults), while the retired
provider-keyed shapes (``search_provider_<id>_collapsed``,
``<id>_search_sec_<section>_expanded``) stay accepted so an upgraded install
keeps its stored values. waves.json's whitelist validates key SHAPES; the
legacy TIDAL section keys (``search_sec_*``) migrate through both hops once on
load.
"""

from __future__ import annotations

import json

from waves.desktop.backend import WavesBridge


class _PrefsStub:
    """Bare stand-in carrying only the waves-prefs surface, with the real
    load/save/migrate methods bound on and a real waves.json on disk."""

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


def test_the_unified_section_pref_round_trips(tmp_path):
    stub = _PrefsStub(tmp_path)
    stub.setWavesPref("search_section_albums_expanded", True)
    assert stub.wavesPref("search_section_albums_expanded") is True
    assert stub.wavesPref("search_section_tracks_expanded") is False


def test_a_provider_keyed_surface_pref_still_persists_as_a_stored_value(tmp_path):
    # The provider-keyed shapes are retired from the UI but stay accepted, so
    # an upgraded waves.json keeps the values it already carries.
    stub = _PrefsStub(tmp_path)
    stub.setWavesPref("search_provider_fake_collapsed", True)
    stub.setWavesPref("fake_search_sec_albums_expanded", True)
    assert stub.wavesPref("search_provider_fake_collapsed") is True
    assert stub.wavesPref("fake_search_sec_albums_expanded") is True


def test_an_unknown_pref_key_stays_refused(tmp_path):
    stub = _PrefsStub(tmp_path)
    stub.setWavesPref("not_a_waves_pref", True)
    assert stub.wavesPref("not_a_waves_pref") is None


def test_stored_provider_surface_keys_load_and_bad_shapes_do_not(tmp_path):
    _write_prefs(
        tmp_path,
        {
            "search_provider_fake_collapsed": True,
            "fake_search_sec_tracks_expanded": True,
            # A section the page does not render, and a key no shape claims:
            # neither is a surface pref, so neither loads.
            "fake_search_sec_typo_expanded": True,
            "provider_who_knows": True,
        },
    )
    stub = _PrefsStub(tmp_path)
    assert stub.wavesPref("search_provider_fake_collapsed") is True
    assert stub.wavesPref("fake_search_sec_tracks_expanded") is True
    assert stub.wavesPref("fake_search_sec_typo_expanded") is None
    assert stub.wavesPref("provider_who_knows") is None


def test_tidal_legacy_section_keys_migrate_through_both_shapes(tmp_path):
    _write_prefs(
        tmp_path,
        {
            "search_sec_albums_expanded": True,
            "search_sec_tracks_expanded": False,
        },
    )
    stub = _PrefsStub(tmp_path)
    # The provider-keyed hop keeps the stored value...
    assert stub.wavesPref("tidal_search_sec_albums_expanded") is True
    assert stub.wavesPref("tidal_search_sec_tracks_expanded") is False
    assert stub.wavesPref("search_sec_albums_expanded") is None, "the legacy key is not carried"
    # ...and the unified section flag follows it, so the expanded section
    # survives the grouped-search retirement.
    assert stub.wavesPref("search_section_albums_expanded") is True
    assert stub.wavesPref("search_section_tracks_expanded") is False

    # A value already stored under the unified name wins over the migration.
    _write_prefs(
        tmp_path,
        {
            "search_sec_albums_expanded": True,
            "tidal_search_sec_albums_expanded": True,
            "search_section_albums_expanded": False,
        },
    )
    stub = _PrefsStub(tmp_path)
    assert stub.wavesPref("tidal_search_sec_albums_expanded") is True
    assert stub.wavesPref("search_section_albums_expanded") is False
