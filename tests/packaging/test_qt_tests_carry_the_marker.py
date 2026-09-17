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
marker, by parsing the test sources rather than trusting their names.
"""

from __future__ import annotations

import ast

from support.paths import TESTS_ROOT

# In-process Qt construction: without PySide6 these tests cannot run at all.
_QT_CONSTRUCTORS = ("QGuiApplication(", "QQmlApplicationEngine(", "QQmlEngine(", "QQuickWindow(")


def _calls_qt_helpers(node: ast.FunctionDef | ast.AsyncFunctionDef, src: str) -> bool:
    """Whether this test boots the shared QML harnesses or spawns itself."""
    segment = ast.get_source_segment(src, node) or ""
    if "run_scenario(" in segment and "__file__" in segment:
        # The standalone-script pattern: the test runs its own module as a
        # child process to boot Main.qml. The runner's own tests pass a
        # throwaway script instead, so they stay exempt.
        return True
    for call in ast.walk(node):
        if not isinstance(call, ast.Call):
            continue
        func = call.func
        if isinstance(func, ast.Name) and func.id == "boot_main_qml":
            return True
        if isinstance(func, ast.Attribute) and func.attr == "boot_main_qml":
            return True
    return False


def _marker_holders(src: str, tree: ast.Module) -> bool:
    """A module-level pytestmark, or any per-node decorator, names `qml`."""
    if "pytestmark" in src and "qml" in src.split("pytestmark", 1)[1].split("\n", 1)[0]:
        return True
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            text = ast.unparse(decorator)
            if "qml" in text:
                return True
    return False


def test_every_qt_driving_test_declares_the_qml_marker():
    offenders: list[str] = []
    for path in sorted(TESTS_ROOT.rglob("test_*.py")):
        src = path.read_text()
        tree = ast.parse(src)
        unmarked = not _marker_holders(src, tree)
        if not unmarked:
            continue
        constructed = any(token in src for token in _QT_CONSTRUCTORS)
        boots_qml = any(
            _calls_qt_helpers(node, src)
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
        )
        if constructed or boots_qml:
            offenders.append(str(path.relative_to(TESTS_ROOT)))

    assert not offenders, (
        "these test modules drive Qt (in-process or by booting Main.qml in a child) "
        "but declare no qml marker, so --require-qml cannot see them and their skips "
        "stay silent: " + ", ".join(offenders)
    )
