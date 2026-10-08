"""Bridge stand-ins answer every public bridge signal without declaring it.

A stand-in receives real WavesBridge methods, and those methods emit bridge
signals. `support.bridge_stub.BridgeStub` resolves each public signal the
bridge declares, so a signal added to the bridge reaches every stand-in with
no edit. Private relays stay absent (their delivery is behaviour; see the
module). The wiring pin at the end keeps every stand-in on that base.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from conftest import _Signal
from PySide6.QtCore import QMetaMethod, QObject
from support.bridge_stub import BRIDGE_SIGNALS, BridgeStub
from support.paths import TESTS_ROOT

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
    assert all(isinstance(getattr(stub, name), _Signal) for name in BRIDGE_SIGNALS)


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


# A stand-in is any object that receives real bridge methods. These are the
# binding forms the suite uses; `x` is the stand-in.
#   WavesBridge.m(x, ...)                      <bridge expr>.__get__(x, ...)
#   setattr(x, name, <bridge expr>)             x.attr = <bridge expr>
#   helper(x, ...) where helper binds x         class body: m = WavesBridge.m
#   a method binding onto self
# x resolves to a class assigned from Cls(...), to the enclosing class for
# self, or to a SimpleNamespace (directly, or returned by a builder defined in
# the file or imported into it by name).

Function = ast.FunctionDef | ast.AsyncFunctionDef


def _names_bridge(node: ast.AST) -> bool:
    return any(
        (isinstance(n, ast.Name) and n.id == "WavesBridge")
        or (isinstance(n, ast.Attribute) and n.attr == "WavesBridge")
        for n in ast.walk(node)
    )


def _is_call_to(node: ast.AST, name: str) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return (isinstance(func, ast.Name) and func.id == name) or (isinstance(func, ast.Attribute) and func.attr == name)


def _bound_names(scope: ast.AST, helpers: set[str]) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(scope):
        if isinstance(node, ast.Call) and node.args:
            func = node.func
            binds = (
                (isinstance(func, ast.Attribute) and _names_bridge(func))
                or (_is_call_to(node, "setattr") and len(node.args) == 3 and _names_bridge(node.args[2]))
                or (isinstance(func, ast.Name) and func.id in helpers)
            )
            if binds and isinstance(node.args[0], ast.Name):
                names.add(node.args[0].id)
        elif isinstance(node, ast.Assign) and _names_bridge(node.value):
            names.update(
                t.value.id for t in node.targets if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name)
            )
    return names


def _functions(tree: ast.AST) -> list[Function]:
    return [n for n in ast.walk(tree) if isinstance(n, Function)]


def _binding_helpers(tree: ast.AST) -> set[str]:
    helpers: set[str] = set()
    for _ in range(2):  # a helper may bind through another helper
        for fn in _functions(tree):
            params = [a.arg for a in fn.args.args]
            if params and params[0] != "self" and params[0] in _bound_names(fn, helpers):
                helpers.add(fn.name)
    return helpers


def _namespace_builders(tree: ast.AST) -> dict[str, int]:
    """Functions returning a SimpleNamespace, with that namespace's line."""
    found: dict[str, int] = {}
    for fn in _functions(tree):
        made = {
            t.id: node.value.lineno
            for node in ast.walk(fn)
            if isinstance(node, ast.Assign) and _is_call_to(node.value, "SimpleNamespace")
            for t in node.targets
            if isinstance(t, ast.Name)
        }
        for node in ast.walk(fn):
            if isinstance(node, ast.Return) and node.value is not None:
                if _is_call_to(node.value, "SimpleNamespace"):
                    found[fn.name] = node.value.lineno
                elif isinstance(node.value, ast.Name) and node.value.id in made:
                    found[fn.name] = made[node.value.id]
    return found


def _builders_in_reach(path: Path, tree: ast.AST) -> dict[str, tuple[Path, int]]:
    """SimpleNamespace builders defined in the file or imported into it by name, with their source line."""
    builders = {name: (path, line) for name, line in _namespace_builders(tree).items()}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            module = TESTS_ROOT.joinpath(*node.module.split(".")).with_suffix(".py")
            if module.is_file():
                theirs = _namespace_builders(ast.parse(module.read_text(encoding="utf-8")))
                builders.update({a.asname or a.name: (module, theirs[a.name]) for a in node.names if a.name in theirs})
    return builders


def _self_binding_classes(class_nodes: dict[str, ast.ClassDef], helpers: set[str]) -> set[str]:
    """Classes binding bridge methods in their body or onto self."""
    return {
        cls.name
        for cls in class_nodes.values()
        if any(isinstance(s, ast.Assign) and _names_bridge(s.value) for s in cls.body)
        or any("self" in _bound_names(fn, helpers) for fn in cls.body if isinstance(fn, Function))
    }


def _stand_ins(path: Path, tree: ast.AST, class_nodes: dict[str, ast.ClassDef]) -> tuple[set[str], list[str]]:
    """(names of classes that stand in for the bridge, SimpleNamespace stand-in sites)."""
    helpers = _binding_helpers(tree)
    builders = _builders_in_reach(path, tree)
    stand_in_classes = _self_binding_classes(class_nodes, helpers)
    sites: list[str] = []
    for scope in [tree, *_functions(tree)]:
        bound = _bound_names(scope, helpers)
        for node in ast.walk(scope):
            if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)):
                continue
            if not any(isinstance(t, ast.Name) and t.id in bound for t in node.targets):
                continue
            func = node.value.func
            if _is_call_to(node.value, "SimpleNamespace"):
                sites.append(f"{path.relative_to(TESTS_ROOT)}:{node.value.lineno} SimpleNamespace")
            elif isinstance(func, ast.Name) and func.id in class_nodes:
                stand_in_classes.add(func.id)
            elif isinstance(func, ast.Name) and func.id in builders:
                where, line = builders[func.id]
                sites.append(f"{where.relative_to(TESTS_ROOT)}:{line} SimpleNamespace from {func.id}()")
    return stand_in_classes, sites


def _reaches_bridge_stub(name: str, tree: ast.AST, class_nodes: dict[str, ast.ClassDef]) -> bool:
    """Follow local bases. An imported root passes when it is a test class
    (its own file is scanned) or the real WavesBridge; a production base such
    as QueueMixin needs BridgeStub listed beside it."""
    imported_from = {
        alias.asname or alias.name: node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
        for alias in node.names
    }
    seen: set[str] = set()
    while name in class_nodes and name not in seen:
        seen.add(name)
        bases = [ast.unparse(b) for b in class_nodes[name].bases]
        if "BridgeStub" in bases:
            return True
        local = [b for b in bases if b in class_nodes]
        if local:
            name = local[0]
            continue
        return bool(bases) and all(
            b == "WavesBridge" or not imported_from.get(b, "waves").startswith("waves") for b in bases
        )
    return False


def test_wiring_every_bridge_stand_in_is_a_bridge_stub():
    # Fences: a signal added to WavesBridge reaches every stand-in with no stub
    # edit. No behavioural seam shows it: a stand-in that lacks the base only
    # fails once some future signal reaches it, so the pin reads the suite's
    # source for objects that receive bridge methods.
    offenders = []
    for path in sorted(TESTS_ROOT.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "WavesBridge" not in text or path.name == "bridge_stub.py":
            continue
        tree = ast.parse(text)
        class_nodes = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
        stand_in_classes, sites = _stand_ins(path, tree, class_nodes)
        offenders += sites
        offenders += [
            f"{path.relative_to(TESTS_ROOT)} class {name}"
            for name in sorted(stand_in_classes)
            if not _reaches_bridge_stub(name, tree, class_nodes)
        ]

    assert offenders == [], "make these support.bridge_stub.BridgeStub stand-ins:\n" + "\n".join(sorted(set(offenders)))
