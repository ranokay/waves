"""Every test that drives Qt or spawns a child process carries a marker.

WHAT THIS FENCES OFF
--------------------
`--require-qml` turns the suite's silent Qt skips into failures, but it only
sees tests carrying the `qml` marker. A scenario that boots Main.qml in a
child interpreter without the marker therefore skips invisibly in a strict
run, and the run reports a complete pass while a whole surface was never
exercised.

The marker rules: a test that spawns an interpreter or constructs Qt
itself is `qml` (Qt) or `integration` (non-Qt, including `bash` script runs),
never unmarked; a host-tooling spawn already covered by `platform` counts too.
unmarked Qt nodes route their skips through the require-qml-aware helper.
This guard checks the marker half by parsing the test sources; the runtime
half is `require_qt()` in the shared helper (skip without Qt, fail under
`--require-qml`) plus conftest's configure-time refusal to run a
`--require-qml` session without PySide6. A test that only runs where Qt is
installed is Qt-marked even when it merely gates on the import.
"""

from __future__ import annotations

import ast
import re

from support.paths import TESTS_ROOT

# Any Qt constructor: Qt owns the Q-followed-by-uppercase namespace, so a
# call leaf like QThreadPool or QNetworkDiskCache is a Qt construction no
# matter which Qt module it came from. (A mention in a docstring or a
# constant list is not a call and does not count.)
_QT_CONSTRUCTOR = re.compile(r"Q[A-Z]\w*")

# Child-process calls whose arguments can name the test's own file or
# interpreter. A test that spawns one of these crosses a process boundary.
_CHILD_PROCESS_CALLS = frozenset({"subprocess.run", "subprocess.Popen", "subprocess.check_output", "subprocess.call"})

# A shell spawned by name: `subprocess.run([bash, ...])` crosses the same
# process boundary as `sys.executable` without naming the interpreter, so the
# old file/interpreter check stayed green on every bash-spawning test.
_BASH_SPAWN = re.compile(r"\bbash\b")


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
    return any(
        isinstance(call, ast.Call) and _QT_CONSTRUCTOR.fullmatch(_leaf(_called_name(call))) for call in ast.walk(node)
    )


def _gates_on_qt(node: ast.AST) -> bool:
    """Whether this subtree skips unless PySide6 imports (AST, so a mention
    in prose does not count). A test that cannot even be collected without
    Qt belongs in the Qt-marked group, wherever the import lives."""
    for call in ast.walk(node):
        if not isinstance(call, ast.Call) or _leaf(_called_name(call)) != "importorskip":
            continue
        if any(isinstance(arg, ast.Constant) and arg.value == "PySide6" for arg in call.args):
            return True
    return False


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
        if _called_name(call) in _CHILD_PROCESS_CALLS and (
            _uses_this_interpreter(call) or _uses_this_file(call) or _BASH_SPAWN.search(ast.unparse(call))
        ):
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


def _module_pytestmark_marks(tree: ast.Module) -> set[str]:
    """The markers a module-level `pytestmark` names (qml, integration, platform)."""
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "pytestmark" for target in node.targets):
            continue
        text = ast.unparse(node.value)
        return {marker for marker in ("qml", "integration", "platform") if marker in text}
    return set()


def _node_marks(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    text = " ".join(ast.unparse(decorator) for decorator in node.decorator_list)
    return {marker for marker in ("qml", "integration", "platform") if marker in text}


def test_every_qt_or_process_test_declares_its_marker():
    offenders: list[str] = []
    for path in sorted(TESTS_ROOT.rglob("test_*.py")):
        src = path.read_text()
        tree = ast.parse(src)
        module_marks = _module_pytestmark_marks(tree)
        # Module-scope construction cannot be covered by a node decorator.
        module_constructs = any(
            _constructs_qt(stmt)
            for stmt in tree.body
            if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        )
        if module_constructs and "qml" not in module_marks:
            offenders.append(f"{path.relative_to(TESTS_ROOT)} (module scope)")
            continue
        helpers = _module_helpers(tree)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or not node.name.startswith("test_"):
                continue
            marks = module_marks | _node_marks(node)
            drives_qt = _reaches(
                node, helpers, lambda current: _constructs_qt(current) or _boots_qml(current) or _gates_on_qt(current)
            )
            if drives_qt:
                if "qml" not in marks:
                    offenders.append(f"{path.relative_to(TESTS_ROOT)}::{node.name} (drives Qt, needs qml)")
                continue
            if _reaches(node, helpers, _spawns_child) and not (marks & {"qml", "integration", "platform"}):
                offenders.append(
                    f"{path.relative_to(TESTS_ROOT)}::{node.name} (spawns a child, needs qml, integration or platform)"
                )

    assert not offenders, (
        "these tests drive Qt or spawn a child interpreter but declare no marker, "
        "so --require-qml cannot see them and their skips stay silent: " + ", ".join(offenders)
    )
