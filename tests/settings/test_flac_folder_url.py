"""The FLAC card's folder dialog round-trip keeps every character of a path.

A folder named "AC#DC" or "What?" must open the dialog in that folder, not
its parent: ``pathUrl`` percent-encodes the path (a URL reads ``#`` as a
fragment and ``?`` as a query), and ``urlToPath`` decodes it back. The test
extracts the two functions once and runs them in a bare JS engine; it asserts
their behaviour, not their source text.
"""

from __future__ import annotations

import pytest
from support.paths import QML_DIR

pytestmark = pytest.mark.qml

SETTINGS = QML_DIR / "domains/settings/SettingsPage.qml"


def _function(name: str) -> str:
    source = SETTINGS.read_text(encoding="utf-8")
    start = source.index(f"  function {name}(")
    depth = 0
    for offset, char in enumerate(source[start:], start):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : offset + 1]
    raise AssertionError(f"unbalanced {name}")


def _engine():
    qjs = pytest.importorskip("PySide6.QtQml")
    from PySide6.QtGui import QGuiApplication

    _ = QGuiApplication.instance() or QGuiApplication([])
    engine = qjs.QJSEngine()
    for name in ("urlToPath", "pathUrl"):
        result = engine.evaluate(_function(name))
        assert not result.isError(), result.toString()
    return engine


def test_the_folder_dialog_url_keeps_every_character_of_the_path():
    engine = _engine()
    cases = {
        "/Music/AC#DC": "file:///Music/AC%23DC",
        "/Music/What?": "file:///Music/What%3F",
        "/Music/100% Pure": "file:///Music/100%25%20Pure",
        "C:/Music/AC#DC": "file:///C:/Music/AC%23DC",
        "C:\\Music\\Sub": "file:///C:/Music/Sub",
        "//nas/music/AC#DC": "file://nas/music/AC%23DC",
        "\\\\nas\\music": "file://nas/music",
        "": "",
    }
    for path, url in cases.items():
        got = engine.evaluate(f"pathUrl({path!r})").toString()
        assert got == url, (path, got)
        if url:
            back = engine.evaluate(f"urlToPath({url!r})").toString()
            assert back == path.replace("\\\\", "//").replace("\\", "/"), (url, back)
