"""Issue #25: the two-axis Providers area and the Apple Music section shell.

WHAT THIS FENCES OFF
--------------------
Settings gains a Providers area: a TIDAL section (its session and its quality
default) and an Apple Music section that is always visible behind an enable
switch (default off) with a status light and runtime-manage placeholders.
The quality split itself (``tidal_quality_audio`` / ``apple_quality_audio``)
and its migration landed with issue #24; this issue gives the split fields
their sections: TIDAL's quality moves out of Downloads into the TIDAL
section, ``apple_quality_audio`` renders in the Apple section for the first
time, and the shared sections' help text says it governs both providers.
Nothing sits behind the switch yet: flipping it records the choice and moves
the status light, nothing else.

The page-side status row and its live mirror are pinned by source assertions
(the repo's settings-page QML convention); the bridge side is exercised for
real on plain stubs.
"""

from __future__ import annotations

from threading import Lock
from types import SimpleNamespace

from waves.model.cfg import HelpSettings
from waves.model.cfg import Settings as ModelSettings
from waves.waves_ui.backend import WavesBridge, _apple_status


def _bind(stub, name):
    return getattr(WavesBridge, name).__get__(stub, type(stub))


def _prefs_stub():
    """The shared prefs stub (same shape test_settings_place_memory uses)."""
    from tests.test_settings_place_memory import _prefs_stub as _shared

    return _shared()


# ---- the schema: the Providers area ----------------------------------------------


def _schema(apple_enabled: bool = False, logged_in: bool = False):
    stub = _schema_stub(apple_enabled, logged_in)
    schema = WavesBridge.settingsSchema(stub)
    return {s["id"]: s for s in schema}


def _schema_stub(apple_enabled: bool = False, logged_in: bool = False):
    """A bridge stub with just enough state for settingsSchema(): a fresh
    defaults-only config (never the machine's own), the given Apple switch
    and TIDAL session state."""

    class _Cfg:
        data = ModelSettings()
        help = HelpSettings()

    stub = _prefs_stub()
    stub.settings = _Cfg()
    stub.settings.data.apple_enabled = apple_enabled
    stub._help = HelpSettings()
    stub._help_for = _bind(stub, "_help_for")
    stub._ffmpeg_flag_prefs = {}
    stub.ffmpegState = lambda: {"status": "none", "source": "none", "path": ""}
    stub._user_ffmpeg_path = lambda: ""
    stub._ffmpeg_detected_path = lambda: ""
    stub._logged_in = logged_in
    return stub


def _keys(section):
    return [f["key"] for f in section["fields"]]


def test_the_providers_area_renders_two_provider_sections():
    schema = WavesBridge.settingsSchema(_schema_stub())
    ids = [s["id"] for s in schema]
    assert "providers_tidal" in ids and "providers_apple" in ids
    tidal = next(s for s in schema if s["id"] == "providers_tidal")
    apple = next(s for s in schema if s["id"] == "providers_apple")
    assert tidal["group"].startswith("Providers ·")
    assert apple["group"].startswith("Providers ·")


def test_the_tidal_section_hosts_the_session_and_its_quality_default():
    sections = _schema()
    assert _keys(sections["providers_tidal"]) == ["provider_tidal_session", "tidal_quality_audio"]


def test_the_tidals_quality_default_no_longer_sits_under_downloads():
    sections = _schema()
    assert "tidal_quality_audio" not in _keys(sections["downloads"])
    # The rest of Downloads survives the move untouched, video quality
    # included (a TIDAL-only capability that keeps its section, spec §9.2.2).
    assert _keys(sections["downloads"])[:2] == ["download_base_path", "quality_video"]
    assert "download_dolby_atmos" in _keys(sections["downloads"])


def test_the_apple_section_holds_the_switch_row_and_the_quality():
    sections = _schema()
    apple = _keys(sections["providers_apple"])
    assert apple == ["provider_apple_status", "apple_quality_audio"]
    status = sections["providers_apple"]["fields"][0]
    # The switch rides the status row (the section's master control), never
    # the flag-tile grid, and the factory-reset walk still finds it.
    assert status["enabled_key"] == "apple_enabled"
    assert "apple_enabled" not in apple
    # The status light sits at its not-set-up vocabulary, with the two
    # runtime-manage placeholders that ship inert.
    assert status["actions"] == [{"label": "Update runtime"}, {"label": "Remove runtime"}]


def test_the_apple_switch_defaults_off_and_persists_as_an_engine_setting():
    assert ModelSettings().apple_enabled is False
    sections = _schema()
    status = sections["providers_apple"]["fields"][0]
    assert status["switch_value"] is False
    assert status["value"] == "off"


def test_the_status_light_flips_with_the_switch_and_the_session():
    on = WavesBridge.settingsSchema(_schema_stub(apple_enabled=True))
    status = next(s for s in on if s["id"] == "providers_apple")["fields"][0]
    assert status["value"] == "not_set_up"
    assert status["word"] == "Not set up"
    assert status["switch_value"] is True

    signed = WavesBridge.settingsSchema(_schema_stub(logged_in=True))
    session = next(s for s in signed if s["id"] == "providers_tidal")["fields"][0]
    assert session["value"] == "signed_in" and session["word"] == "Signed in"
    unsigned = WavesBridge.settingsSchema(_schema_stub())
    session = next(s for s in unsigned if s["id"] == "providers_tidal")["fields"][0]
    assert session["value"] == "not_signed_in" and session["word"] == "Not signed in"


def test_one_helper_serves_the_slot_and_the_schema():
    assert _apple_status(False) == {"state": "off", "word": "Off"}
    assert _apple_status(True) == {"state": "not_set_up", "word": "Not set up"}


# ---- the appleStatus() slot (the page's live mirror reads it) --------------------


def test_the_apple_status_slot_reports_off_and_not_set_up():
    stub = _schema_stub(apple_enabled=False)
    stub.appleStatus = _bind(stub, "appleStatus")
    assert stub.appleStatus() == {"state": "off", "word": "Off"}
    stub2 = _schema_stub(apple_enabled=True)
    stub2.appleStatus = _bind(stub2, "appleStatus")
    assert stub2.appleStatus() == {"state": "not_set_up", "word": "Not set up"}


# ---- applySettings: the switch persists and flips the light ----------------------


class _Stub:
    """Bare object the real applySettings gets bound onto."""


def _signal(seen=None):
    return SimpleNamespace(emit=lambda *a: seen.append(a) if seen is not None else None)


def _apply_stub(apple_enabled: bool = False):
    stub = _Stub()
    stub._waves_prefs = {}
    stub.settings = SimpleNamespace(
        data=SimpleNamespace(
            apple_enabled=apple_enabled,
            tidal_quality_audio="HIGH",
            apple_quality_audio="LOSSLESS",
            quality_video="480",
            download_base_path="/music",
            ffmpeg_source="system",
            downloads_concurrent_max=3,
        ),
        save=lambda: None,
    )
    stub._ffmpeg_flag_prefs = {}
    stub._settings_save_lock = Lock()
    stub._submit_settings_write = lambda: stub.settings.save()
    stub._restore_ffmpeg_flags = lambda: None
    stub._restore_ffmpeg_path = lambda: None
    stub._ffmpeg_source_label = lambda: "system"
    stub._waves_pref_bool = lambda key: False
    stub.ownershipChanged = _signal()
    stub.targetTierChanged = _signal()
    stub.skipExistingChanged = _signal()
    stub.ffmpegStatusChanged = _signal()
    stub.confirmCategoryDlChanged = _signal()
    stub.librarySourceChanged = _signal()
    stub.appleStatusChanged = _signal()
    stub.dl_pool = SimpleNamespace(setMaxThreadCount=lambda n: None)
    stub._logged_in = False
    stub._set_status = lambda text: None
    stub.providers = {"tidal": SimpleNamespace(apply_quality=lambda *a: None)}
    stub._reapply_quality = WavesBridge._reapply_quality.__get__(stub, _Stub)
    stub._reapply_provider_quality = WavesBridge._reapply_provider_quality.__get__(stub, _Stub)
    return stub


def _apply(stub, values):
    WavesBridge.applySettings.__get__(stub, type(stub))(values)


def test_saving_the_switch_persists_it():
    stub = _apply_stub()
    _apply(stub, {"apple_enabled": True})
    assert stub.settings.data.apple_enabled is True


def test_a_real_flip_emits_the_status_signal_an_unchanged_resubmit_does_not():
    stub = _apply_stub()
    seen = []
    stub.appleStatusChanged = _signal(seen)
    _apply(stub, {"apple_enabled": True})
    assert len(seen) == 1
    # A later save in the same visit resubmits the keys unchanged; that is
    # not a flip and must not move the light (the library keys' rule).
    _apply(stub, {"apple_enabled": True})
    assert len(seen) == 1
    _apply(stub, {"apple_enabled": False})
    assert len(seen) == 2


def test_a_flip_off_is_also_a_flip():
    stub = _apply_stub(apple_enabled=True)
    seen = []
    stub.appleStatusChanged = _signal(seen)
    _apply(stub, {"apple_enabled": False})
    assert len(seen) == 1


def test_an_untouched_switch_emits_nothing():
    stub = _apply_stub()
    seen = []
    stub.appleStatusChanged = _signal(seen)
    _apply(stub, {"tidal_quality_audio": "LOSSLESS"})
    assert seen == []


# ---- factory reset covers the switch ---------------------------------------------


def test_factory_reset_resets_the_apple_switch():
    stub = _schema_stub(apple_enabled=True)
    stub.settingsSchema = _bind(stub, "settingsSchema")
    stub._factory_default_values = _bind(stub, "_factory_default_values")
    values = stub._factory_default_values()
    assert values["apple_enabled"] is False


# ---- shared sections say they govern both providers ------------------------------


def test_shared_help_text_names_both_providers():
    help_settings = HelpSettings()
    assert "every enabled provider" in help_settings.download_dolby_atmos
    assert "every enabled provider" in help_settings.lyrics_embed
    assert "every enabled provider" in help_settings.lyrics_file
    assert "every enabled provider" in help_settings.lyrics_prefer_lrclib
    assert "every enabled provider" in _schema()["diagnostics"]["desc"]


def test_the_playlist_template_help_no_longers_claims_tidals_tree():
    # {folder_path} mirrors the playlist's folder tree on ITS PROVIDER; the
    # old wording hard-coded TIDAL, which stopped being the whole truth the
    # moment a second provider existed.
    assert "TIDAL folder tree" not in HelpSettings().format_playlist
    assert "its provider" in HelpSettings().format_playlist


def test_the_provider_sections_declarations_carry_the_area_vocabulary():
    from pathlib import Path

    src = Path(__file__).resolve().parent.parent / "waves" / "waves_ui" / "qml" / "SettingsPage.qml"
    qml = src.read_text(encoding="utf-8")
    # The status row delegate and the Apple light's live mirror are pinned
    # by source (the settings-page QML convention): the mirror re-reads
    # appleStatus() on the flip signal, and the row prefers it while it
    # holds a value.
    assert "onAppleStatusChanged" in qml
    assert '"apple_status"' in qml
    # The schema snapshots TIDAL's session, so login/logout must rebuild it.
    assert "onLoggedInChanged" in qml
    # The Apple switch is reachable without a pointer.
    assert "activeFocusOnTab: true" in qml
    assert "Accessible.role: Accessible.CheckBox" in qml
    assert "Keys.onPressed" in qml
    assert "!event.isAutoRepeat" in qml
    # Both provider sections have glyphs of their own.
    assert '"providers_tidal"' in qml and '"providers_apple"' in qml


def test_the_factory_reset_walk_still_finds_the_switch_through_the_composite():
    # _factory_default_values enumerates composite sub-keys by name; the
    # Apple status row's enabled_key is what makes RESET ALL SETTINGS reach
    # the switch. Pinned against the real schema walk above (see
    # test_factory_reset_resets_the_apple_switch); this asserts the
    # enumeration keys the walk reads are the ones the row declares.
    sections = _schema()
    status = sections["providers_apple"]["fields"][0]
    assert {status.get("key"), status.get("enabled_key")} == {"provider_apple_status", "apple_enabled"}
