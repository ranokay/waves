"""Bridge stand-ins answer every public bridge signal without declaring it.

A stand-in binds real WavesBridge methods, and a signal added to the bridge
used to break each stand-in whose method reached it, one test run at a time.
`support.bridge_stub.BridgeStub` derives the signal names from WavesBridge
itself, so a new public signal reaches every stand-in with no edit. Private
relays (`_catalogEvent`, `_searchEvent`) stay absent: bridge code probes them
with getattr and delivers inline without them. The guard at the end keeps
every stand-in class that binds bridge methods on that base.
"""

from __future__ import annotations

import ast

import pytest
from PySide6.QtCore import Signal
from support.bridge_stub import BRIDGE_SIGNALS, BridgeStub, RecordingSignal
from support.paths import TESTS_ROOT

from waves.desktop.backend import WavesBridge


def _declared_signals() -> set[str]:
    return {name for klass in WavesBridge.__mro__ for name, value in vars(klass).items() if isinstance(value, Signal)}


def test_every_public_bridge_signal_resolves_on_a_bare_stand_in():
    stub = BridgeStub()
    public = {name for name in _declared_signals() if not name.startswith("_")}

    assert public == set(BRIDGE_SIGNALS)
    assert all(isinstance(getattr(stub, name), RecordingSignal) for name in public)


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

    assert getattr(stub, "_catalogEvent", None) is None, "a stand-in delivers catalog results inline"
    assert getattr(stub, "_searchEvent", None) is None, "a stand-in delivers search results inline"
    with pytest.raises(AttributeError):
        _ = stub.noSuchSignal


def _binds_bridge_methods(cls: ast.ClassDef) -> bool:
    return any(
        isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Attribute)
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "WavesBridge"
        for node in ast.walk(cls)
    )


def _reaches_bridge_stub(cls: ast.ClassDef, local: dict[str, ast.ClassDef]) -> bool:
    """Follow the class's local bases; an imported root is scanned in its own file."""
    seen = set()
    while cls.name not in seen:
        seen.add(cls.name)
        names = [base.id for base in cls.bases if isinstance(base, ast.Name)]
        if "BridgeStub" in names:
            return True
        parents = [local[name] for name in names if name in local]
        if not parents:
            return bool(names) and all(name not in local for name in names) and "QueueMixin" not in names
        cls = parents[0]
    return False


def test_every_stand_in_class_that_binds_bridge_methods_is_a_bridge_stub():
    offenders = []
    for path in sorted(TESTS_ROOT.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "WavesBridge." not in text:
            continue
        tree = ast.parse(text)
        local = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
        offenders.extend(
            f"{path.relative_to(TESTS_ROOT)}:{cls.lineno} {cls.name}"
            for cls in local.values()
            if _binds_bridge_methods(cls) and not _reaches_bridge_stub(cls, local)
        )

    assert offenders == [], "give these stand-ins support.bridge_stub.BridgeStub as a base:\n" + "\n".join(offenders)
