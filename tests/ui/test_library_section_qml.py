"""Issue #222: the Library section renders the files on disk (ADR 0007).

WHAT THIS FENCES OFF
--------------------
My Music showed nothing of the user's own folder: the pane was sources only,
and there was no surface that answered "what music do I have on disk?".

This is the rendered half, on the real pane: a seeded library (the scan's own
rows, injected through the scanner's seams so no real audio is needed) fills
the section above the source groups, Saved is the default view, the two view
chips switch keep-alive lists, a tagged row carries its provider badge (its
item id's namespace) and an untagged row carries none, and an unconfigured
install gets the configure CTA instead of two empty lists.

Runs in a SUBPROCESS like the other Main.qml scenarios: building the bridge
installs process-global handlers that must not leak into the suite.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest
from support.qml import EXIT_OK, EXIT_REGRESSED, boot_main_qml, run_scenario
from support.qml_probe import scene_js


def _visible(scope: str, name: str) -> str:
    return scene_js(
        f"  var hit = findFirst({scope}, function (o) {{ return o.objectName === {json.dumps(name)}; }});\n"
        "  return hit !== null && hit.visible === true;\n"
    )


def _text_visible(scope: str, text: str) -> str:
    return scene_js(
        f"  var hit = findFirst({scope}, function (o) {{ return o.visible === true"
        f" && o.text !== undefined && String(o.text) === {json.dumps(text)}; }});\n"
        "  return hit !== null;\n"
    )


def _point(scope: str, name: str) -> str:
    """Scene coordinates of the first visible item with this objectName."""
    return scene_js(
        f"  var hit = findFirst({scope}, function (o) {{ return o.objectName === {json.dumps(name)}; }});\n"
        "  if (!hit || hit.visible !== true || hit.width <= 0 || hit.height <= 0) return null;\n"
        "  var p = hit.mapToItem(null, hit.width / 2, hit.height / 2);\n"
        "  if (p.x < 0 || p.y < 0 || p.x > root.width || p.y > root.height) return null;\n"
        "  return JSON.stringify([p.x, p.y]);\n"
    )


def _click(root, q, settle, point_expr: str, done_expr: str, wait: int = 350) -> bool:
    """Click where the expression says until the done predicate holds.

    The first activation resolves font aliases and can shift the layout, so
    the point is re-measured after the hover before every attempt (the gate
    pattern the other scenarios use).
    """
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    root.requestActivate()
    settle(150)
    for _ in range(3):
        raw = q(point_expr)
        if raw in ("", None):
            return False
        x, y = json.loads(raw)
        QTest.mouseMove(root, QPoint(int(x), int(y)))
        settle(120)
        raw = q(point_expr)  # fresh after the hover
        if raw in ("", None):
            return False
        x, y = json.loads(raw)
        QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, QPoint(int(x), int(y)))
        settle(wait)
        if q(done_expr):
            return True
    return False


def _write_book(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w"):
        pass


def _seed_library() -> tuple[str, dict, dict]:
    """A two-folder library: Waves saved three files (an Apple id, a legacy
    bare TIDAL id and a namespace no real provider owns), the user ripped one
    (untagged). Returns (root, tags, ids).
    """
    base = tempfile.mkdtemp(prefix="waves-library-section-")
    lib = os.path.join(base, "music")
    saved = os.path.join(lib, "A", "Saved")
    ripped = os.path.join(lib, "B", "Ripped")
    _write_book(os.path.join(saved, "01.flac"))
    _write_book(os.path.join(saved, "02.flac"))
    _write_book(os.path.join(saved, "03.flac"))
    _write_book(os.path.join(ripped, "01.mp3"))
    tags = {
        os.path.join(saved, "01.flac"): {
            "album": "Saved",
            "artist": "A",
            "date": "2000",
            "title": "First",
            "length": 95,
        },
        os.path.join(saved, "02.flac"): {
            "album": "Saved",
            "artist": "A",
            "date": "2000",
            "title": "Second",
            "length": 180,
        },
        os.path.join(saved, "03.flac"): {
            "album": "Saved",
            "artist": "A",
            "date": "2000",
            "title": "Third",
            "length": 240,
        },
        os.path.join(ripped, "01.mp3"): {"album": "Ripped", "artist": "B", "date": "1999", "title": "Tripped"},
    }
    ids = {
        os.path.join(saved, "01.flac"): "apple:91",
        os.path.join(saved, "02.flac"): "77",  # legacy TIDAL, read bare
        os.path.join(saved, "03.flac"): "fake:7",  # a third provider's namespace
    }
    return lib, tags, ids


def _register_fake_provider(bridge, logo: str) -> None:
    """A third provider with no capabilities: it contributes no shelf, so the
    only thing it can move is the Library section's badge for its namespace."""
    from waves.providers import ProviderDescriptor, StatusKind

    class _FakeProvider:
        id = "fake"
        name = "Fake Music"
        capabilities = frozenset()

        def descriptor(self):
            return ProviderDescriptor(id=self.id, name=self.name, logo=logo, status_kind=StatusKind.NONE)

    bridge.providers["fake"] = _FakeProvider()


def _install_library(bridge, lib: str, tags: dict, ids: dict) -> None:
    """Give the live bridge a scanned fixture library through the scanner's
    own seams (no real audio, no real scan process)."""
    from waves.library_index import LibraryIndex

    idx = LibraryIndex(
        os.path.join(os.path.dirname(lib), "library.sqlite3"),
        read_tags=lambda p: tags.get(p),
        read_item_id=lambda p: ids.get(p, ""),
    )
    idx.refresh(lib, force_full=True)
    bridge._library = idx
    bridge._library_root = lambda: lib


def _row_js(list_name: str, index: int, prop: str) -> str:
    return scene_js(
        f"  var row = findObject(root, {json.dumps(list_name)}).itemAtIndex({index});\n"
        f"  return row ? String(row.{prop}) : '(no row)';\n"
    )


def _row_count(list_name: str) -> str:
    return scene_js(f"  return findObject(root, {json.dumps(list_name)}).count;\n")


def _list_visible(list_name: str) -> str:
    """A done-predicate: the named list is the visible one."""
    return scene_js(f"  return findObject(libSection, {json.dumps(list_name)}).visible === true;\n")


def _row_badge_visible(list_name: str, index: int) -> str:
    return scene_js(
        f"  var row = findObject(root, {json.dumps(list_name)}).itemAtIndex({index});\n"
        "  if (!row) return false;\n"
        "  var b = findFirst(row, function (o) { return o.objectName === 'trackProviderBadge'; });\n"
        "  return b !== null && b.visible === true;\n"
    )


def _row_badge_logo(list_name: str, index: int) -> str:
    return scene_js(
        f"  var row = findObject(root, {json.dumps(list_name)}).itemAtIndex({index});\n"
        "  if (!row) return '(no row)';\n"
        "  var b = findFirst(row, function (o) { return o.objectName === 'trackProviderBadge'; });\n"
        "  return b ? String(b.logo) : '(no badge)';\n"
    )


def _row_badge_provider(list_name: str, index: int) -> str:
    return scene_js(
        f"  var row = findObject(root, {json.dumps(list_name)}).itemAtIndex({index});\n"
        "  if (!row) return '(no row)';\n"
        "  var b = findFirst(row, function (o) { return o.objectName === 'trackProviderBadge'; });\n"
        "  return b ? String(b.provider) : '(no badge)';\n"
    )


def _run_configured() -> int:  # noqa: C901 (one straight scenario)
    booted = boot_main_qml()
    if isinstance(booted, int):
        return booted
    root, q, settle, bridge = booted

    lib, tags, ids = _seed_library()
    # A mark no other provider uses: a fallback to Apple's or TIDAL's asset
    # would then fail the assertion instead of passing by coincidence.
    _register_fake_provider(bridge, "assets/providers/fake-music.png")
    _install_library(bridge, lib, tags, ids)
    q("root.refreshProviderSurfaces()")
    q("root.openLibrary()")
    settle(700)
    q("scrollDressing.visible = false")
    settle(120)

    failures: list[str] = []
    # The section opens on Saved (ADR 0007's default view) and names both
    # views, with the counts its own pages answered.
    if not bool(q(_visible("libSection", "libViewsFlow"))):
        failures.append("the Library section rendered no view strip")
    if not bool(q(_text_visible("libSection", "Saved · 3"))):
        failures.append("the Saved view did not name itself with its count")
    # The other view has not loaded yet, so it shows no count: a count is the
    # answer to a page, never a QML guess.
    if not bool(q(_text_visible("libSection", "All files"))):
        failures.append("the All-files view did not name itself")
    if not bool(q(_visible("libSection", "libSavedList"))):
        failures.append("Saved is not the section's opening view")
    if bool(q(_visible("libSection", "libAllList"))):
        failures.append("the All-files list rendered while Saved is the view")

    # Saved lists only the tagged files, each badged by its id's namespace.
    if q(_row_js("libSavedList", 0, "title")) != "First":
        failures.append("the Saved list's first row is not the first saved file")
    if q(_row_badge_provider("libSavedList", 0)) != "apple":
        failures.append("an Apple-saved file did not badge as Apple")
    if not bool(q(_row_badge_visible("libSavedList", 0))):
        failures.append("a tagged row carried no provider badge")
    if q(_row_badge_provider("libSavedList", 1)) != "tidal":
        failures.append("a legacy TIDAL id did not read as TIDAL's")
    # A namespace no two-provider fallback knows still badges with THAT
    # provider's descriptor mark, from the bridge's own registry.
    if q(_row_badge_provider("libSavedList", 2)) != "fake":
        failures.append("a third provider's namespace lost its identity")
    if q(_row_badge_logo("libSavedList", 2)) != "assets/providers/fake-music.png":
        failures.append("a third provider's badge did not render its own descriptor mark")
    if q(_row_count("libSavedList")) != 3:
        failures.append("Saved listed a file it should not (or lost one)")

    # Switching views shows everything, and the untagged row carries no badge.
    if not _click(root, q, settle, _point("libSection", "libViewChip-all"), _list_visible("libAllList")):
        failures.append("clicking All files did not switch the section")
    if bool(q(_visible("libSection", "libSavedList"))):
        failures.append("the Saved list stayed visible under All files")
    if q(_row_count("libAllList")) != 4:
        failures.append("All files did not list every audio file the scan sees")
    # The view's page answered its count, so the chip names it now.
    if not bool(q(_text_visible("libSection", "All files · 4"))):
        failures.append("the All-files view's count did not arrive with its page")
    if q(_row_js("libAllList", 3, "provider")) != "":
        failures.append("an untagged row claimed a provider")
    if bool(q(_row_badge_visible("libAllList", 3))):
        failures.append("an untagged row rendered a provider badge")
    # And back: the keep-alive list still holds its rows.
    if not _click(root, q, settle, _point("libSection", "libViewChip-saved"), _list_visible("libSavedList")):
        failures.append("clicking Saved did not switch back")

    # A read failure is a state, not an empty library: the bridge answers
    # total -1 and the section says so instead of "No saved files yet".
    def boom(*_a, **_k):
        raise RuntimeError("boom")

    bridge._library.files_page = boom
    q("libSection.reload()")
    settle(500)
    if not bool(q(_text_visible("libSection", "Could not read your music folder"))):
        failures.append("a failed page read as an empty library")
    if bool(q(_text_visible("libSection", "No saved files yet"))):
        failures.append("a failed page showed the empty sentence")

    for line in failures:
        print(f"REGRESSED: {line}", file=sys.stderr)
    return EXIT_REGRESSED if failures else EXIT_OK


def _run_configure_cta() -> int:
    booted = boot_main_qml()
    if isinstance(booted, int):
        return booted
    root, q, settle, _bridge = booted
    # boot_main_qml silences the scan (no library folder configured): the
    # section must explain itself rather than render two empty lists.
    q("root.openLibrary()")
    settle(300)
    q("scrollDressing.visible = false")
    settle(120)

    failures: list[str] = []
    if not bool(q(_visible("libSection", "libConfigureCta"))):
        failures.append("an unconfigured library showed no configure call to action")
    if bool(q(_visible("libSection", "libSavedList"))) or bool(q(_visible("libSection", "libAllList"))):
        failures.append("an unconfigured library rendered a file list")
    if not bool(q(_text_visible("libSection", "Choose a music folder"))):
        failures.append("the configure call to action had no folder-picking label")
    if not bool(q(_visible("libraryPane", "libSignInCta"))):
        failures.append("the section displaced the pane's sign-in empty state")
    if not _click(
        root,
        q,
        settle,
        _point("libSection", "libConfigureAction"),
        "root.settingsOpen === true && settingsPage.sectionOpen('library')",
    ):
        failures.append("the configure action did not land on the Settings library card")

    for line in failures:
        print(f"REGRESSED: {line}", file=sys.stderr)
    return EXIT_REGRESSED if failures else EXIT_OK


@pytest.mark.qml
def test_the_library_section_lists_saved_and_all_files():
    run_scenario(
        Path(__file__),
        "--run-configured",
        timeout=180,
        sandbox_prefix="waves-library-section-",
        failure_message="the Library section regressed",
    )


@pytest.mark.qml
def test_an_unconfigured_library_offers_the_folder_choice():
    run_scenario(
        Path(__file__),
        "--run-configure-cta",
        timeout=180,
        sandbox_prefix="waves-library-configure-",
        failure_message="the Library section's configure call to action regressed",
    )


if __name__ == "__main__" and "--run-configured" in sys.argv:
    raise SystemExit(_run_configured())

if __name__ == "__main__" and "--run-configure-cta" in sys.argv:
    raise SystemExit(_run_configure_cta())
