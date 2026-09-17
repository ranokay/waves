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
_QT_TYPES = frozenset({"QGuiApplication", "QQmlApplicationEngine", "QQmlEngine", "QQuickWindow"})


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


def _boots_qml(node: ast.FunctionDef | ast.AsyncFunctionDef, src: str) -> bool:
    """Whether this test boots the shared QML harness or spawns itself."""
    segment = ast.get_source_segment(src, node) or ""
    if "run_scenario(" in segment and "__file__" in segment:
        # The standalone-script pattern: the test runs its own module as a
        # child process to boot Main.qml. The runner's own tests pass a
        # throwaway script instead, so they stay exempt.
        return True
    if "str(Path(__file__).resolve())" in segment and "subprocess.run(" in segment:
        # The same pattern spelled directly: the test runs this very file
        # with a scenario flag (the restart journeys do this).
        return True
    return any(isinstance(call, ast.Call) and _called_name(call) == "boot_main_qml" for call in ast.walk(node))


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
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or not node.name.startswith("test_"):
                continue
            drives_qt = _constructs_qt(node) or _boots_qml(node, src)
            if drives_qt and not (module_marked or _node_has_qml_mark(node)):
                offenders.append(f"{path.relative_to(TESTS_ROOT)}::{node.name}")

    assert not offenders, (
        "these tests drive Qt (in-process or by booting Main.qml in a child) but "
        "declare no qml marker of their own and no module-level pytestmark, so "
        "--require-qml cannot see them and their skips stay silent: " + ", ".join(offenders)
    )
