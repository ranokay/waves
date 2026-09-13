"""Repository paths, resolved from this file's own location.

Test modules move between domain folders, so a path must never come from a
test file's own depth: ``REPO_ROOT`` and the QML directory answer the same
wherever the caller sits.
"""

from __future__ import annotations

from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = TESTS_ROOT.parent
QML_DIR = REPO_ROOT / "waves" / "waves_ui" / "qml"
QML_MAIN = QML_DIR / "Main.qml"
