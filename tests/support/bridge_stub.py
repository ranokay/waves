"""A base class for test stand-ins of WavesBridge.

A stand-in binds real bridge methods onto a small object of its own, and
those methods emit bridge signals, so the stand-in must answer every signal
name they reach. `BridgeStub` answers any public signal that WavesBridge or
one of its mixins declares with the suite's recording double
(`support.signals.RecordingSignal`), created on first read and kept on the
instance so its `emits` accumulate. Attributes the stand-in sets itself win, and any other missing
name still raises AttributeError.

Private signals stay absent. Each is a thread-crossing relay whose delivery
is behaviour: `_jobFinished` starts the next queued job, and bridge code
probes `_catalogEvent` and `_searchEvent` with getattr to deliver inline when
they are missing. A double that records a relay without delivering it would
change what the code does next without failing, so a stand-in models each
relay it reaches.

`watch_stand_ins` keeps every stand-in on this base: it records each bridge
or mixin method that runs on an object other than a BridgeStub, a real
bridge or a mock (`self` passed as None is a deliberate unbound call), and
conftest fails the test that ran it.
"""

from __future__ import annotations

import inspect
import sys
from unittest import mock

from PySide6.QtCore import Signal

from support.signals import RecordingSignal
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
            signal = RecordingSignal()
            setattr(self, name, signal)
            return signal
        raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")


# sys.monitoring ids 0-2 and 5 belong to debuggers, coverage, profilers and
# optimizers; 3 is free for this check.
_WATCH_TOOL = 3
_offenders: list[str] = []
_watching = False


def _bridge_methods() -> dict:
    """The code object of every bridge and mixin method that takes self."""
    methods = {}
    for klass in WavesBridge.__mro__:
        if not klass.__module__.startswith("waves."):
            continue
        for name, value in vars(klass).items():
            func = value.fget if isinstance(value, property) else value
            if inspect.isfunction(func) and func.__code__.co_varnames[:1] == ("self",):
                methods[func.__code__] = f"{klass.__name__}.{name}"
    return methods


def watch_stand_ins() -> None:
    """Start recording bridge methods that run on a stand-in outside this base."""
    global _watching
    if _watching:
        return
    try:
        sys.monitoring.use_tool_id(_WATCH_TOOL, "bridge-stand-ins")
    except ValueError:  # another tool holds the id; the check stands down
        return
    methods = _bridge_methods()

    def on_start(code, _offset):
        label = methods.get(code)
        if label is None:
            return
        stand_in = sys._getframe(1).f_locals.get("self")
        if stand_in is None or isinstance(stand_in, (BridgeStub, WavesBridge, mock.NonCallableMock)):
            return
        kind = type(stand_in)
        _offenders.append(f"{kind.__module__}.{kind.__qualname__} ran {label}")

    sys.monitoring.register_callback(_WATCH_TOOL, sys.monitoring.events.PY_START, on_start)
    for code in methods:
        sys.monitoring.set_local_events(_WATCH_TOOL, code, sys.monitoring.events.PY_START)
    _watching = True


def take_offenders() -> list[str]:
    """The stand-ins recorded since the last call, once each."""
    taken = list(dict.fromkeys(_offenders))
    _offenders.clear()
    return taken
