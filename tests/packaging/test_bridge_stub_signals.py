"""Bridge stand-ins answer every public bridge signal without declaring it.

A stand-in receives real WavesBridge methods, and those methods emit bridge
signals. `support.bridge_stub.BridgeStub` resolves each public signal the
bridge declares, so a signal added to the bridge reaches every stand-in with
no edit. Private relays stay absent (their delivery is behaviour; see the
module). The watcher conftest arms reports a stand-in outside the base.
"""

from __future__ import annotations

from unittest import mock

import pytest
from PySide6.QtCore import QMetaMethod, QObject
from support import bridge_stub
from support.bridge_stub import BRIDGE_SIGNALS, BridgeStub
from support.signals import RecordingSignal

from waves.desktop.backend import WavesBridge


def _qt_public_signals() -> set[str]:
    """The bridge's public signals as Qt's own meta-object lists them."""
    meta = WavesBridge.staticMetaObject
    names = {
        bytes(meta.method(i).name()).decode()
        for i in range(QObject.staticMetaObject.methodCount(), meta.methodCount())
        if meta.method(i).methodType() == QMetaMethod.MethodType.Signal
    }
    return {name for name in names if not name.startswith("_")}


def test_every_public_signal_qt_registers_on_the_bridge_resolves():
    stub = BridgeStub()

    assert set(BRIDGE_SIGNALS) == _qt_public_signals()
    assert all(isinstance(getattr(stub, name), RecordingSignal) for name in BRIDGE_SIGNALS)


def test_a_resolved_signal_keeps_its_emits_on_the_instance():
    stub = BridgeStub()

    stub.artistLoaded.emit({"id": "1"})
    stub.downloadState.emit("m1", "done")

    assert stub.artistLoaded.emits == [{"id": "1"}]
    assert stub.downloadState.emits == [("m1", "done")]
    assert BridgeStub().artistLoaded.emits == [], "each stand-in records its own emits"


def test_the_stand_ins_own_attributes_win():
    own = object()
    stub = BridgeStub(artistLoaded=own, _queue=[])

    assert stub.artistLoaded is own
    assert stub._queue == []


def test_private_relays_and_unknown_names_stay_absent():
    stub = BridgeStub()

    for relay in ("_catalogEvent", "_searchEvent", "_jobFinished"):
        assert getattr(stub, relay, None) is None, f"{relay} must be modelled by the stand-in that reaches it"
    with pytest.raises(AttributeError):
        _ = stub.noSuchSignal


def test_a_bridge_method_on_a_stand_in_outside_the_base_is_reported():
    class _Plain:
        def __init__(self):
            self._waves_prefs = {}

    bridge_stub.watch_stand_ins()
    bridge_stub.take_offenders()

    WavesBridge._waves_pref_bool(_Plain(), "x")

    assert bridge_stub.take_offenders() == [
        f"{_Plain.__module__}.{_Plain.__qualname__} ran WavesBridge._waves_pref_bool"
    ]


def test_bridge_stubs_mocks_and_unbound_calls_are_not_reported():
    bridge_stub.watch_stand_ins()
    bridge_stub.take_offenders()

    WavesBridge._waves_pref_bool(BridgeStub(_waves_prefs={}), "x")
    WavesBridge._waves_pref_bool(mock.MagicMock(), "x")
    WavesBridge.sanitizeFilenameReplacement(None, "_")

    assert bridge_stub.take_offenders() == []
