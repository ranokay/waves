"""The QML import closure survives the bundle trim.

`tools/trim_qt_bundle.sh` deletes Qt/QML modules by deny-list, and the only
execution check is an idle smoke-launch: a lazily loaded page importing a
trimmed module would fail only in the field. This test parses every `import`
in `waves/desktop/qml/**` (plus any `Loader.source`/`createComponent` file
targets) and fails when an imported module is denied — or, the same relation
from the other side, when a deny-list entry names a module the app imports.
The deny-lists are parsed from the trim script itself, so the two cannot
drift apart.
"""

from __future__ import annotations

import re
from pathlib import Path

from support.paths import QML_DIR, REPO_ROOT

TRIM_SCRIPT = REPO_ROOT / "tools" / "trim_qt_bundle.sh"

_ARRAY_NAMES = ("QML_MODULES", "QTQUICK_QML_DIRS", "QT_LABS_DIRS", "CONTROLS_STYLES")

# Removals the script states as explicit `rm -rf` lines rather than arrays.
_EXTRA_DENIED = ("QtQml.StateMachine", "Qt.labs.platform")


def _deny_lists() -> dict[str, set[str]]:
    text = TRIM_SCRIPT.read_text()
    lists = {}
    for name in _ARRAY_NAMES:
        match = re.search(rf"^{name}=\(\s*(.*?)\s*\)", text, re.MULTILINE | re.DOTALL)
        assert match, f"{TRIM_SCRIPT} no longer defines {name}; update this test"
        lists[name] = set(match.group(1).split())
    for extra in ("QtQml/StateMachine", "labs/platform"):
        assert extra in text, f"{TRIM_SCRIPT} no longer removes {extra}; update _EXTRA_DENIED"
    return lists


def _denied_module_paths(lists: dict[str, set[str]]) -> set[str]:
    denied = set(lists["QML_MODULES"])
    denied.update(f"QtQuick.{sub.replace('/', '.')}" for sub in lists["QTQUICK_QML_DIRS"])
    denied.update(f"QtQuick.Controls.{style}" for style in lists["CONTROLS_STYLES"])
    denied.update(f"Qt.labs.{entry}" for entry in lists["QT_LABS_DIRS"])
    denied.update(_EXTRA_DENIED)
    return denied


def _qml_imports() -> set[str]:
    imports = set()
    files = sorted(QML_DIR.rglob("*.qml"))
    assert files, f"no QML files under {QML_DIR}; the closure scan is blind"
    for path in files:
        for match in re.finditer(r"^\s*import\s+([A-Za-z][\w.]*)", path.read_text(), re.MULTILINE):
            imports.add(match.group(1))
    assert imports, f"no QML imports parsed under {QML_DIR}; the import pattern is stale"
    return imports


def _dynamic_qml_targets() -> set[str]:
    """File targets loaded by name at runtime (`Loader.source`,
    `createComponent`): string literals ending in `.qml` only. Property
    bindings such as `front.source = src` carry no file name and are ignored.
    """
    pattern = re.compile(r"source\s*:\s*\"([^\"]+\.qml)\"|createComponent\s*\(\s*\"([^\"]+)\"", re.MULTILINE)
    targets = set()
    for path in QML_DIR.rglob("*.qml"):
        for match in pattern.finditer(path.read_text()):
            targets.add(match.group(1) or match.group(2))
    return targets


def test_qml_import_closure_survives_the_trim_denylists():
    denied = _denied_module_paths(_deny_lists())
    imports = _qml_imports()

    offending = sorted(imp for imp in imports if any(imp == entry or imp.startswith(entry + ".") for entry in denied))
    assert not offending, (
        "these QML imports are removed by tools/trim_qt_bundle.sh; "
        "either stop importing them or drop them from the deny-lists: " + ", ".join(offending)
    )


def test_dynamic_qml_targets_resolve_inside_the_scanned_tree():
    unresolvable = sorted(
        target
        for target in _dynamic_qml_targets()
        if not (QML_DIR / target).is_file() and not (QML_DIR / Path(target).name).is_file()
    )
    assert not unresolvable, (
        "these runtime QML targets resolve to no file under waves/desktop/qml, "
        "so the closure test above cannot see their imports: " + ", ".join(unresolvable)
    )
