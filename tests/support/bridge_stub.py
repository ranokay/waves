"""A base class for test stand-ins of WavesBridge.

A stand-in binds real bridge methods onto a small object of its own, and
those methods emit bridge signals, so the stand-in must answer every signal
name they reach. `BridgeStub` answers any public signal that WavesBridge or
one of its mixins declares with the suite's recording double (conftest's
`_Signal`), created on first read and kept on the instance so its `emits`
accumulate. Attributes the stand-in sets itself win, and any other missing
name still raises AttributeError.

Private signals stay absent. Each is a thread-crossing relay whose delivery
is behaviour: `_jobFinished` starts the next queued job, and bridge code
probes `_catalogEvent` and `_searchEvent` with getattr to deliver inline when
they are missing. A double that records a relay without delivering it would
change what the code does next without failing, so a stand-in models each
relay it reaches.
"""

from __future__ import annotations

from conftest import _Signal
from PySide6.QtCore import Signal

from waves.desktop.backend import WavesBridge

BRIDGE_SIGNALS = frozenset(
    name
    for klass in WavesBridge.__mro__
    if klass.__module__.startswith("waves.")
    for name, value in vars(klass).items()
    if isinstance(value, Signal) and not name.startswith("_")
)


class BridgeStub:
    """Base for a WavesBridge stand-in: every public bridge signal resolves.

    Keyword arguments become attributes, so `BridgeStub(_queue=[])` replaces
    a `SimpleNamespace` stand-in directly.
    """

    def __init__(self, **attrs):
        vars(self).update(attrs)

    def __getattr__(self, name: str):
        if name in BRIDGE_SIGNALS:
            signal = _Signal()
            setattr(self, name, signal)
            return signal
        raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")
