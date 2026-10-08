"""A base class for test stand-ins of WavesBridge.

A stand-in binds real bridge methods onto a small object of its own, and
those methods emit bridge signals, so the stand-in must answer every signal
name they reach. Declared by hand, that list breaks every stand-in the moment
the bridge grows a signal. `BridgeStub` answers any public name WavesBridge
(or one of its mixins) declares as a Signal with a `RecordingSignal`, created
on first read and kept on the instance so its `emits` accumulate. Attributes the
stand-in sets itself win, and any other missing name still raises
AttributeError.
"""

from __future__ import annotations

from PySide6.QtCore import Signal

from waves.desktop.backend import WavesBridge

# Public signals only. A private one (`_catalogEvent`, `_searchEvent`) is a
# thread-crossing relay that bridge code probes with getattr: a stand-in
# without it gets inline delivery, so it must stay absent unless the
# stand-in models the relay itself.
BRIDGE_SIGNALS = frozenset(
    name
    for klass in WavesBridge.__mro__
    for name, value in vars(klass).items()
    if isinstance(value, Signal) and not name.startswith("_")
)


class RecordingSignal:
    """Minimal stand-in for a Qt signal: records every emit."""

    def __init__(self):
        self.emits: list = []

    def emit(self, *args):
        self.emits.append(args if len(args) != 1 else args[0])


class BridgeStub:
    """Base for a WavesBridge stand-in: every public bridge signal resolves.

    Keyword arguments become attributes, so `BridgeStub(_queue=[])` replaces
    a `SimpleNamespace` stand-in directly.
    """

    def __init__(self, **attrs):
        vars(self).update(attrs)

    def __getattr__(self, name: str):
        if name in BRIDGE_SIGNALS:
            signal = RecordingSignal()
            setattr(self, name, signal)
            return signal
        raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")
