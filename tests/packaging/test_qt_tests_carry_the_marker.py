"""Every test that drives Qt in-process or boots the real QML carries `qml`.

WHAT THIS FENCES OFF
--------------------
`--require-qml` turns the suite's silent Qt skips into failures, but it only
sees tests carrying the `qml` marker. A scenario that boots Main.qml in a
child interpreter without the marker therefore skips invisibly in a strict
run, and the run reports a complete pass while a whole surface was never
exercised (2026-09-16 audit TT-01/TT-08: one such test had a wrong
expectation and three more were unmarked).

The rule, from the audit's marker rules: a test that spawns an interpreter
or constructs Qt itself is `qml` (Qt) or `integration` (non-Qt), never
unmarked. This guard checks the mechanical half of that rule for the `qml`
marker, per test, so a partially marked module cannot hide the rest.
"""

from __future__ import annotations

import ast

from support.paths import TESTS_ROOT

# Qt types whose construction means the test cannot run without PySide6.
_QT_TYPES = frozenset({"QCoreApplication", "QGuiApplication", "QQmlApplicationEngine", "QQmlEngine", "QQuickWindow"})


def _called_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _constructs_qt(node: ast.AST) -> bool:
    """Whether this subtree calls a Qt constructor (AST, so a mention in a
    docstring or a constant list does not count)."""
    return any(isinstance(call, ast.Call) and _called_name(call) in _QT_TYPES for call in ast.walk(node))


def _uses_this_file(node: ast.AST) -> bool:
    return any(isinstance(name, ast.Name) and name.id == "__file__" for name in ast.walk(node))


def _boots_qml(node: ast.AST) -> bool:
    """Whether this test boots the shared QML harness or spawns itself."""
    for call in ast.walk(node):
        if not isinstance(call, ast.Call):
            continue
        name = _called_name(call)
        if name == "boot_main_qml":
            return True
        if name in ("run_scenario", "subprocess.run") and _uses_this_file(call):
            # The standalone-script patterns: run_scenario(Path(__file__), ...)
            # or a subprocess of this very file with a scenario flag. The
            # runner's own tests pass a throwaway script instead.
            return True
    return False


def _module_helpers(tree: ast.Module) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    """Module-level functions, by name, so the check can follow a test into
    the helper that really builds the app (e.g. `_qt_app()`)."""
    return {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _drives_qt(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    helpers: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
) -> bool:
    """Whether this test, or a module helper it reaches, touches Qt."""
    seen: set[str] = set()
    worklist: list[ast.AST] = [node]
    while worklist:
        current = worklist.pop()
        if _constructs_qt(current):
            return True
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)) and _boots_qml(current):
            return True
        for call in ast.walk(current):
            if not isinstance(call, ast.Call):
                continue
            name = _called_name(call)
            helper = helpers.get(name)
            if helper is not None and name not in seen:
                seen.add(name)
                worklist.append(helper)
    return False


def _module_pytestmark_has_qml(tree: ast.Module) -> bool:
    """A module-level `pytestmark` that names the qml marker."""
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "pytestmark" for target in node.targets):
            continue
        if "qml" in ast.unparse(node.value):
            return True
    return False


def _node_has_qml_mark(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any("qml" in ast.unparse(decorator) for decorator in node.decorator_list)


def test_every_qt_driving_test_declares_the_qml_marker():
    offenders: list[str] = []
    for path in sorted(TESTS_ROOT.rglob("test_*.py")):
        src = path.read_text()
        tree = ast.parse(src)
        module_marked = _module_pytestmark_has_qml(tree)
        # Module-scope construction cannot be covered by a node decorator.
        module_constructs = any(
            _constructs_qt(stmt)
            for stmt in tree.body
            if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        )
        if module_constructs and not module_marked:
            offenders.append(f"{path.relative_to(TESTS_ROOT)} (module scope)")
            continue
        helpers = _module_helpers(tree)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or not node.name.startswith("test_"):
                continue
            if _drives_qt(node, helpers) and not (module_marked or _node_has_qml_mark(node)):
                offenders.append(f"{path.relative_to(TESTS_ROOT)}::{node.name}")

    assert not offenders, (
        "these tests drive Qt (in-process or by booting Main.qml in a child) but "
        "declare no qml marker of their own and no module-level pytestmark, so "
        "--require-qml cannot see them and their skips stay silent: " + ", ".join(offenders)
    )
