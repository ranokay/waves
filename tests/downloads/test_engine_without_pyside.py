"""The download engine stays importable without PySide6.

The engine names only the neutral ``ProgressGui`` shape from
``waves.model.downloader``; the Qt-backed ``ProgressBars`` is built in the
desktop layer and satisfies that shape structurally.
"""

from __future__ import annotations

import ast
import subprocess
import sys

import pytest
from support.paths import REPO_ROOT

import waves.download
from waves.model.downloader import ProgressGui


def _parse(rel: str) -> ast.Module:
    return ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))


def test_engine_module_binds_no_pyside():
    assert "PySide6" not in vars(waves.download)


def test_engine_source_names_no_qt_or_gui_data():
    tree = _parse("waves/download.py")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("PySide6")
        elif isinstance(node, ast.ImportFrom):
            assert node.module != "PySide6"
            assert not (node.module or "").startswith("PySide6.")
            assert node.module != "waves.model.gui_data"


@pytest.mark.integration
def test_engine_imports_with_pyside_blocked():
    probe = """import importlib.abc, sys
class _B(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name == 'PySide6' or name.startswith('PySide6.'):
            raise ModuleNotFoundError('blocked for engine test')
sys.meta_path.insert(0, _B())
import waves.download
print('PySide6' in sys.modules)
print('waves.model.gui_data' in sys.modules)
"""
    out = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert out.returncode == 0, f"engine import failed with PySide6 blocked:\n{out.stderr}"
    assert out.stdout.split() == ["False", "False"]


def test_qt_backed_bars_still_satisfy_the_neutral_shape():
    tree = _parse("waves/model/gui_data.py")
    fields = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "ProgressBars":
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    fields.add(stmt.target.id)
    assert set(ProgressGui.__annotations__) <= fields
