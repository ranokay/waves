"""The search page's provider-keyed surface prefs (issue #292).

The provider group fold and each section's SHOW ALL state are keyed by
provider id, so a provider the app has never heard of saves and restores its
own state. waves.json's whitelist validates the key SHAPES (a known provider
is never enumerated), and TIDAL's legacy section keys (``search_sec_*``)
migrate to the provider-keyed shape once on load.
"""

from __future__ import annotations

import json

from waves.waves_ui.backend import WavesBridge


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


def test_a_provider_keyed_surface_pref_persists_with_no_default(tmp_path):
    # The shipped defaults declare no key for "fake": the shape rule accepts
    # and materializes it, so a third provider's fold and SHOW ALL state save
    # with no wiring edit.
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


def test_tidal_legacy_section_keys_migrate_once(tmp_path):
    _write_prefs(
        tmp_path,
        {
            "search_sec_albums_expanded": True,
            "search_sec_tracks_expanded": False,
        },
    )
    stub = _PrefsStub(tmp_path)
    assert stub.wavesPref("tidal_search_sec_albums_expanded") is True
    assert stub.wavesPref("tidal_search_sec_tracks_expanded") is False
    assert stub.wavesPref("search_sec_albums_expanded") is None, "the legacy key is not carried"

    # A value already stored under the new name wins over the legacy key.
    _write_prefs(
        tmp_path,
        {
            "search_sec_albums_expanded": True,
            "tidal_search_sec_albums_expanded": False,
        },
    )
    stub = _PrefsStub(tmp_path)
    assert stub.wavesPref("tidal_search_sec_albums_expanded") is False
