"""The notification center's Settings card and its live prefs.

These pin what makes the controls real: they ship with the documented defaults,
they are offered with labels/help/bounds in a Notifications section, and an edit
reaches the bridge as a typed value (an int stays an int) and re-applies the
retention limits.
"""

from __future__ import annotations

from support.bridge_stub import BridgeStub

from waves.desktop.backend import WavesBridge


class _Stub(BridgeStub):
    """Bare object the real methods get bound onto."""


def _bind(stub, name):
    return getattr(WavesBridge, name).__get__(stub, type(stub))


def _prefs_stub():
    stub = _Stub()
    stub._default_waves_prefs = _bind(stub, "_default_waves_prefs")
    stub._waves_prefs = stub._default_waves_prefs()
    stub._waves_pref_bool = _bind(stub, "_waves_pref_bool")
    stub._waves_pref_int = _bind(stub, "_waves_pref_int")
    return stub


def test_notification_prefs_ship_with_the_documented_defaults():
    prefs = _prefs_stub()._waves_prefs
    assert prefs["notify_completion_toasts"] is True
    assert prefs["notification_motion"] is True
    assert prefs["notify_history_max"] == 200
    assert prefs["notify_history_days"] == 7


def test_notification_fields_are_offered_with_bounds_and_help():
    schema = WavesBridge.settingsSchema(_schema_stub())
    section = next((section for section in schema if section["id"] == "notifications"), None)
    assert section is not None, "the Notifications section must exist"
    assert section["group"] == "Notifications"
    fields = {field["key"]: field for field in section["fields"]}
    assert fields["notify_completion_toasts"]["type"] == "bool"
    assert fields["notification_motion"]["type"] == "bool"
    assert fields["notify_history_max"]["type"] == "int"
    assert fields["notify_history_max"]["minimum"] == 0
    assert fields["notify_history_max"]["maximum"] == 200
    assert fields["notify_history_days"]["type"] == "int"
    assert fields["notify_history_days"]["minimum"] == 1
    assert fields["notify_history_days"]["maximum"] == 30
    for field in fields.values():
        assert field["label"] and field["help"]


def test_editing_a_retention_pref_reapplies_the_limits_as_an_int():
    stub = _prefs_stub()
    stub._save_waves_prefs = lambda: None
    stub._factory_reset = False
    calls = []
    stub._apply_notification_limits = lambda: calls.append(True)
    stub.setWavesPref = _bind(stub, "setWavesPref")
    stub.setWavesPref("notify_history_max", "42")
    assert stub._waves_prefs["notify_history_max"] == 42
    assert calls, "the store limits only follow the pref when the edit re-applies them"


def test_completion_toast_pref_flips_to_a_bool():
    stub = _prefs_stub()
    stub._save_waves_prefs = lambda: None
    stub._factory_reset = False
    stub.setWavesPref = _bind(stub, "setWavesPref")
    stub.setWavesPref("notify_completion_toasts", False)
    assert stub._waves_prefs["notify_completion_toasts"] is False


def test_motion_pref_can_be_turned_off_and_notifies_the_stack():
    stub = _prefs_stub()
    stub._save_waves_prefs = lambda: None
    stub._factory_reset = False
    stub.setWavesPref = _bind(stub, "setWavesPref")
    fired = []

    class _Sig:
        def emit(self):
            fired.append(True)

    stub.notificationMotionChanged = _Sig()
    stub.setWavesPref("notification_motion", False)
    assert stub._waves_prefs["notification_motion"] is False
    assert fired, "the toast stack only re-reads motion when the signal fires"


def _schema_stub():
    """A bridge stub with just enough state for settingsSchema()."""
    from waves.model.cfg import HelpSettings
    from waves.model.cfg import Settings as CfgSettings

    class _Cfg:
        data = CfgSettings()
        help = HelpSettings()

    stub = _prefs_stub()
    stub.settings = _Cfg()
    stub._help = HelpSettings()
    stub._help_for = _bind(stub, "_help_for")
    stub._ffmpeg_flag_prefs = {}
    stub.ffmpegState = lambda: {"status": "none", "source": "none", "path": ""}
    stub._apple_live_flags = lambda: {"enabled": False}
    stub._apple_quarantine_note = lambda: ""
    stub._user_ffmpeg_path = lambda: ""
    stub._ffmpeg_detected_path = lambda: ""
    return stub
