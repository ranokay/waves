"""The three hover escape hatches (Settings > Advanced).

Each one turns a piece of hover motion off without losing the plain fade:

* ``hover_control_motion`` — hover controls rise in with a bounce by default.
* ``art_hover_tilt`` — album and artist artwork tilts toward the cursor.
* ``video_hover_peek`` — resting on a video thumbnail grows a sound-on preview.

These pin the three things that make a toggle real: it ships on by default, it
is offered as a labelled bool in the Advanced section, and flipping it notifies
the QML, which re-reads the pref on that signal (see Main.qml's
``hoverMotion``, ``artFxVariant`` and ``peekOpen`` gates).
"""

from __future__ import annotations

import pytest

from waves.desktop.backend import WavesBridge

# (pref key, the changed signal QML listens to)
HOVER_PREFS = [
    ("hover_control_motion", "hoverMotionChanged"),
    ("art_hover_tilt", "artHoverTiltChanged"),
    ("video_hover_peek", "videoHoverPeekChanged"),
]


class _Stub:
    """Bare object the real methods get bound onto."""


def _bind(stub, name):
    return getattr(WavesBridge, name).__get__(stub, type(stub))


def _prefs_stub():
    stub = _Stub()
    stub._default_waves_prefs = _bind(stub, "_default_waves_prefs")
    stub._waves_prefs = stub._default_waves_prefs()
    stub._waves_pref_bool = _bind(stub, "_waves_pref_bool")
    return stub


@pytest.mark.parametrize(("key", "signal"), HOVER_PREFS)
def test_hover_pref_defaults_on(key, signal):
    assert _prefs_stub()._waves_prefs[key] is True


@pytest.mark.parametrize(("key", "signal"), HOVER_PREFS)
def test_pref_is_offered_in_the_advanced_section(key, signal):
    schema = WavesBridge.settingsSchema(_schema_stub())
    advanced = next(s for s in schema if s["id"] == "advanced")
    field = next((f for f in advanced["fields"] if f["key"] == key), None)
    assert field is not None, f"{key} must be reachable from Settings > Advanced"
    assert field["type"] == "bool"
    assert field["value"] is True
    # A power-user knob still has to explain itself.
    assert field["label"] and field["help"]


@pytest.mark.parametrize(("key", "signal"), HOVER_PREFS)
def test_flipping_the_pref_notifies_the_ui(key, signal):
    stub = _prefs_stub()
    stub._save_waves_prefs = lambda: None
    stub._factory_reset = False
    fired = []

    class _Sig:
        def emit(self):
            fired.append(True)

    setattr(stub, signal, _Sig())
    _bind(stub, "setWavesPref")(key, False)
    assert stub._waves_prefs[key] is False
    assert fired, f"QML only re-reads the pref when {signal} fires"


def _schema_stub():
    """A bridge stub with just enough state for settingsSchema().

    Built on a fresh defaults-only config, never the machine's own, so the
    test can't depend on (or print) the user's real settings.
    """
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
    # No ffmpeg probing from a unit test: the page prefills the detected
    # binary, which is machine state this test has no business reading.
    stub._user_ffmpeg_path = lambda: ""
    stub._ffmpeg_detected_path = lambda: ""
    return stub
