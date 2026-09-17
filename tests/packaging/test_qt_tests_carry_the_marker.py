"""Every test that drives Qt or spawns a child process carries a marker.

WHAT THIS FENCES OFF
--------------------
`--require-qml` turns the suite's silent Qt skips into failures, but it only
sees tests carrying the `qml` marker. A scenario that boots Main.qml in a
child interpreter without the marker therefore skips invisibly in a strict
run, and the run reports a complete pass while a whole surface was never
exercised (2026-09-16 audit TT-01/TT-08: one such test had a wrong
expectation and three more were unmarked).

The audit's marker rules: a test that spawns an interpreter or constructs Qt
itself is `qml` (Qt) or `integration` (non-Qt), never unmarked, and the
unmarked Qt nodes route their skips through the require-qml-aware helper.
This guard checks the marker half by parsing the test sources; the runtime
half is `require_qml` in the shared helper plus conftest's session-end check,
which fails a strict run when an UNMARKED test skipped for missing Qt. The
two are the static and behavioural sides of one rule.
"""

from __future__ import annotations

import ast
from types import SimpleNamespace

from support.paths import TESTS_ROOT

# Qt types whose construction means the test cannot run without PySide6.
_QT_TYPES = frozenset({"QCoreApplication", "QGuiApplication", "QQmlApplicationEngine", "QQmlEngine", "QQuickWindow"})

# Child-process calls whose arguments can name the test's own file or
# interpreter. A test that spawns one of these crosses a process boundary.
_CHILD_PROCESS_CALLS = frozenset({"subprocess.run", "subprocess.Popen", "subprocess.check_output", "subprocess.call"})


def _called_name(call: ast.Call) -> str:
    """The call's name as written: `run_scenario`, `qml.run_scenario` or
    `subprocess.run` (a bare attribute name would lose the qualifier, and
    `subprocess.run` cannot be told from any other `.run`)."""
    return ast.unparse(call.func)


def _leaf(name: str) -> str:
    return name.rsplit(".", 1)[-1]


def _constructs_qt(node: ast.AST) -> bool:
    """Whether this subtree calls a Qt constructor (AST, so a mention in a
    docstring or a constant list does not count)."""
    return any(isinstance(call, ast.Call) and _leaf(_called_name(call)) in _QT_TYPES for call in ast.walk(node))


def _uses_this_file(node: ast.AST) -> bool:
    return any(isinstance(name, ast.Name) and name.id == "__file__" for name in ast.walk(node))


def _uses_this_interpreter(node: ast.AST) -> bool:
    return "sys.executable" in ast.unparse(node)


def _boots_qml(node: ast.AST) -> bool:
    """Whether this test boots the shared QML harness or spawns itself."""
    for call in ast.walk(node):
        if not isinstance(call, ast.Call):
            continue
        name = _called_name(call)
        if _leaf(name) == "boot_main_qml":
            return True
        if _leaf(name) == "run_scenario" and _uses_this_file(call):
            # The standalone-script pattern: run_scenario(Path(__file__), ...).
            # The runner's own tests pass a throwaway script instead.
            return True
        if name in _CHILD_PROCESS_CALLS and _uses_this_file(call):
            # The same pattern spelled directly: a subprocess of this very
            # file with a scenario flag (the restart journeys do this).
            return True
    return False


def _spawns_child(node: ast.AST) -> bool:
    """Whether this test runs a child interpreter at all (Qt or not)."""
    for call in ast.walk(node):
        if not isinstance(call, ast.Call):
            continue
        if _called_name(call) in _CHILD_PROCESS_CALLS and (_uses_this_interpreter(call) or _uses_this_file(call)):
            return True
    return False


def _module_helpers(tree: ast.Module) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    """Module-level functions, by name, so the check can follow a test into
    the helper that really builds the app (e.g. `_qt_app()`)."""
    return {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _reaches(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    helpers: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
    predicate,
) -> bool:
    """Whether this test, or a module helper it calls, satisfies the predicate."""
    seen: set[str] = set()
    worklist: list[ast.AST] = [node]
    while worklist:
        current = worklist.pop()
        if predicate(current):
            return True
        for call in ast.walk(current):
            if not isinstance(call, ast.Call):
                continue
            name = _leaf(_called_name(call))
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


def _node_marks(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    text = " ".join(ast.unparse(decorator) for decorator in node.decorator_list)
    return {marker for marker in ("qml", "integration") if marker in text}


def test_every_qt_or_process_test_declares_its_marker():
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
            marks = _node_marks(node) if not module_marked else {"qml"}
            drives_qt = _reaches(node, helpers, lambda current: _constructs_qt(current) or _boots_qml(current))
            if drives_qt:
                if "qml" not in marks:
                    offenders.append(f"{path.relative_to(TESTS_ROOT)}::{node.name} (drives Qt, needs qml)")
                continue
            if _reaches(node, helpers, _spawns_child) and not marks:
                offenders.append(
                    f"{path.relative_to(TESTS_ROOT)}::{node.name} (spawns a child, needs qml or integration)"
                )

    assert not offenders, (
        "these tests drive Qt or spawn a child interpreter but declare no marker, "
        "so --require-qml cannot see them and their skips stay silent: " + ", ".join(offenders)
    )


def test_an_unmarked_qt_skip_fails_the_strict_session(monkeypatch):
    """conftest's net: a test that skipped for missing Qt without a Qt marker
    must fail a --require-qml session, or the guard's static half is the only
    thing standing between a missing marker and a green strict run."""
    import conftest
    from support import qml as qml_support

    monkeypatch.setattr(qml_support, "require_qml", lambda: True)
    monkeypatch.setattr(conftest, "_MARKED_FOR_QT", set())
    monkeypatch.setattr(conftest, "_UNMARKED_QT_SKIPS", [])
    report = SimpleNamespace(
        when="setup", skipped=True, nodeid="tests/x/test_y.py::test_z", longrepr="skipped: PySide6 is not importable"
    )
    conftest.pytest_runtest_logreport(report)
    assert conftest._UNMARKED_QT_SKIPS == ["tests/x/test_y.py::test_z"]

    session = SimpleNamespace(exitstatus=0)
    returned = conftest.pytest_sessionfinish(session, 0)
    assert returned != 0 and session.exitstatus != 0

    # A marked test's Qt skip is its own business (it converts it when
    # required); the net only catches the unmarked one.
    monkeypatch.setattr(conftest, "_MARKED_FOR_QT", {"tests/x/test_y.py::test_z"})
    monkeypatch.setattr(conftest, "_UNMARKED_QT_SKIPS", [])
    conftest.pytest_runtest_logreport(report)
    assert conftest._UNMARKED_QT_SKIPS == []
