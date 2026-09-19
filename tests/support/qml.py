"""Offscreen QML scenario runner for the subprocess-based UI tests.

Building a real WavesBridge installs process-global handlers and a Qt
application that must not leak into the suite, so each QML scenario runs in
its own interpreter. The parent decides whether a scenario may skip: only a
positively absent PySide6 does, and every other non-zero exit fails the
test with the child's last output lines. That keeps an application import
error or a QML load failure from masquerading as a missing dependency, and
``--require-qml`` turns even the missing-dependency skip into a failure for
the GUI-required run.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from support.paths import QML_MAIN, REPO_ROOT, TESTS_ROOT

EXIT_OK = 0
EXIT_REGRESSED = 1
EXIT_NO_QT = 77
EXIT_PRECONDITION = 78

# The album the progress/queue scenarios seed into the search model and then
# drive through root.dlHolder("al-roll"); shared so every matrix scenario
# reads the same row shape. ROW is the parsed dict the payload seeder takes;
# the JSON string stays for the scenarios that splice it into a QML call.
ROLLING_ALBUM = json.dumps(
    {
        "id": "al-roll",
        "title": "Rolling Album",
        "artist": "Artist R",
        "artist_id": "r1",
        "art": "",
        "year": "2026",
        "date": "2026-01-01",
        "tracks": 10,
        "quality": "LOSSLESS",
        "popularity": 50,
    }
)
ROLLING_ALBUM_ROW = json.loads(ROLLING_ALBUM)

_REQUIRE_QML = False


def seed_tidal_search(q, bridge, *, artists=(), albums=(), tracks=(), videos=(), playlists=(), mixes=(), expanded=()):
    """Put one TIDAL group's rows on the search page of a booted Main.qml.

    Scenarios that drive a row widget (a progress bar, a hover, a row layout)
    need a live results page, not a real search: this emits the one-provider
    payload a TIDAL search produces (issue #292's group shape) and opens the
    sections the caller asks for. The caller owns ``openSearch()`` and any
    page state around it.
    """
    from support.search_fakes import qml_search_payload

    q("_searchSeq = _navSeq")
    bridge.searchResults.emit(
        qml_search_payload(
            artists=list(artists),
            albums=list(albums),
            tracks=list(tracks),
            videos=list(videos),
            playlists=list(playlists),
            mixes=list(mixes),
        )
    )
    for section in expanded:
        q(f"root.searchGroupFor('tidal').toggleExpanded('{section}')")


def set_require_qml(required: bool) -> None:
    """Record the run's ``--require-qml`` choice (called by conftest)."""
    global _REQUIRE_QML
    _REQUIRE_QML = bool(required)


def require_qml() -> bool:
    """Whether this run was started with ``--require-qml`` (set by conftest)."""
    return _REQUIRE_QML


def missing_qt() -> bool:
    """Whether PySide6 is positively absent, without importing it.

    Only a real absence may skip; a spec that cannot be inspected (a partially
    initialised module) is not evidence of absence and reads as present.
    """
    try:
        return importlib.util.find_spec("PySide6") is None
    except ImportError:
        return True
    except ValueError:
        return False


def sandbox_qml_settings() -> None:
    """Start a scenario from a clean QSettings slate, off the app's own domain.

    QML `Settings` objects use QSettings, which on macOS writes to the real
    ``~/Library/Preferences``; its native backend ignores ``setPath``, so the
    INI redirect only helps on other platforms. Each QML scenario subprocess
    runs under the scenario script's own application name (only the real
    entry point names the app), so clearing the default domain here wipes
    test-owned state only -- never the app's own domain -- and keeps a
    scenario idempotent across runs. Call it once the child has a QCore
    application, before any QML engine or bridge exists.
    """
    import tempfile

    from PySide6.QtCore import QCoreApplication, QSettings

    if QCoreApplication.applicationName() == "Waves":
        raise RuntimeError("sandbox_qml_settings must run before the real app configures QSettings")
    base = os.environ.get("XDG_CONFIG_HOME") or tempfile.mkdtemp(prefix="waves-qml-settings-")
    Path(base).mkdir(parents=True, exist_ok=True)
    QSettings.setPath(QSettings.NativeFormat, QSettings.UserScope, base)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, base)
    QSettings().clear()


def scenario_env(sandbox: str) -> dict[str, str]:
    """The environment one scenario child runs with: offscreen Qt, a private
    config directory, and the repo plus tests root importable from any depth."""
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["XDG_CONFIG_HOME"] = sandbox
    parts = [str(TESTS_ROOT), str(REPO_ROOT), env.get("PYTHONPATH", "")]
    env["PYTHONPATH"] = os.pathsep.join(part for part in parts if part)
    return env


def _tail(stdout: str | None, stderr: str | None, limit: int = 12, drop: tuple[str, ...] = ()) -> str:
    text = ((stdout or "") + (stderr or "")).strip()
    lines = [line for line in text.splitlines() if not any(token in line for token in drop)]
    return "\n".join(lines[-limit:])


def _skip_or_fail_missing_qt() -> None:
    message = "PySide6 / offscreen Qt unavailable"
    if require_qml():
        pytest.fail(f"{message} and --require-qml was given")
    pytest.skip(message)


def require_qt() -> None:
    """Skip this test when PySide6 is absent, or fail under --require-qml.

    The one call a Qt test makes at its entry point: a Qt-less contributor
    gets a skip, and a strict run treats the missing dependency as the
    failure it is. Tests that boot a scenario through :func:`run_scenario`
    never call this (the runner owns the check); tests that construct Qt
    in-process do.
    """
    if missing_qt():
        _skip_or_fail_missing_qt()


def make_tidal_my_music_source(root, q, settle, bridge) -> None:
    """Seed a signed-in TIDAL session so My Music renders its source group.

    The pane's groups come from the bridge's live sources (issue #259): a
    scenario that drives one flips the session flag the real sign-in would
    flip and re-reads the provider surfaces the same way the app does, then
    works through ``root.libGroupFor("tidal")``.
    """
    bridge._logged_in = True
    q("root.refreshProviderSurfaces()")
    settle(150)


def click_point(root, point, settle) -> None:
    """A real left click at a scene point, with the warm-up a gate needs.

    Imported lazily so a Qt-free interpreter can still import this module:
    activate the window, move the pointer, click, then a delayed second click
    for controls whose action only arms after a first press.
    """
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    root.requestActivate()
    settle(80)
    pos = QPoint(int(point.x()), int(point.y()))
    QTest.mouseMove(root, pos)
    settle(60)
    QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, pos)
    settle(80)
    QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, pos, 40)


def run_scenario(
    script: str | Path,
    *flags: str,
    timeout: int = 180,
    sandbox_prefix: str = "waves-qml-",
    failure_message: str = "",
    drop: tuple[str, ...] = (),
) -> str:
    """Run one QML scenario child and return its output tail.

    Skips only when PySide6 is positively absent from this interpreter;
    every other non-zero exit fails with the child's last output lines, so
    application import errors, QML load failures and regressions all read
    as failures. ``failure_message`` prefixes the failure when the caller
    has a sharper verdict than "the scenario failed", and ``drop`` removes
    known-noisy lines (Qt warnings) from the reported tail.
    """
    path = Path(script).resolve()
    if missing_qt():
        _skip_or_fail_missing_qt()
    sandbox = tempfile.mkdtemp(prefix=sandbox_prefix)
    try:
        try:
            proc = subprocess.run(  # noqa: S603 (fixed argv: this interpreter, a repo script)
                [sys.executable, str(path), *flags],
                env=scenario_env(sandbox),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            message = failure_message or "the QML scenario did not finish"
            pytest.fail(f"{message} (timed out after {timeout}s)\n{_tail(exc.stdout, exc.stderr, drop=drop)}")
        output = _tail(proc.stdout, proc.stderr, drop=drop)
        if proc.returncode != EXIT_OK:
            message = failure_message or "the QML scenario failed"
            pytest.fail(f"{message}\n{output}")
        return output
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


def boot_main_qml(keep_settings: bool = False):
    """Boot the real Main.qml offscreen inside a scenario child.

    Returns ``(root, q, settle, bridge)`` ready to drive, or ``EXIT_NO_QT``
    when this interpreter cannot host Qt. The session login, the library scan
    and the Browse fetch are silenced so the scenario owns every payload it
    asserts on; the root is resized, shown, and pushed past the boot overlay.
    ``keep_settings`` skips the store clear, so a second child can read what
    a first one persisted (the restart scenarios).

    Those three patches are why no scenario exercises the *composed* launch
    (real login racing the overlay, the launch sweep, the Browse fetch): with
    them real, the boot overlay and the welcome gate would eat the synthetic
    clicks a scenario drives (the audit's TT-10, quoted in issue #247). The
    composed launch is covered where it can be asserted honestly instead: the
    real entry point twice in ``tests/ui/test_cold_process_boot.py`` and the
    real bridge from isolated settings in ``tests/ui/test_bridge_boot_isolated.py``.
    """
    try:
        from PySide6.QtCore import QEventLoop, QTimer, QUrl
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtQml import QQmlApplicationEngine, QQmlEngine
        from PySide6.QtQuick import QQuickWindow
    except ImportError as exc:
        print(f"PySide6 unavailable: {exc}", file=sys.stderr)
        return EXIT_NO_QT

    from support.offline import PARK_LOGIN_QML, patch_offline

    patch_offline()  # before the bridge: its __init__ fires the sign-in check

    app = QGuiApplication.instance() or QGuiApplication([])
    if not keep_settings:
        sandbox_qml_settings()
    from waves.waves_ui.app import _load_mono
    from waves.waves_ui.backend import WavesBridge

    # Neither a library scan nor a Browse fetch is what these scenarios are
    # about, and both reach outside the sandbox.
    WavesBridge._library_root = lambda self: ""  # type: ignore[method-assign]
    WavesBridge.loadBrowse = lambda self, *a: None  # type: ignore[method-assign]

    bridge = WavesBridge(tidal=None)
    engine = QQmlApplicationEngine()
    # Main.qml resolves these at creation, so they must be set before load.
    engine.rootContext().setContextProperty("waves", bridge)
    engine.rootContext().setContextProperty("monoFont", _load_mono())
    engine.rootContext().setContextProperty("uiFontFamily", app.font().family())
    engine.load(QUrl.fromLocalFile(str(QML_MAIN)))
    roots = engine.rootObjects()
    if not roots:
        raise RuntimeError("Main.qml failed to load")
    root = roots[0]
    if not isinstance(root, QQuickWindow):
        raise TypeError("Main.qml's root object is not a window")

    q = _evaluator(QQmlEngine.contextForObject(root), root)

    def settle(ms: int) -> None:
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    root.resize(1280, 900)
    root.show()
    settle(300)
    q("bootOverlay.done = true")
    q("bootContentShown = 1")
    q(PARK_LOGIN_QML)
    # The engine owns the tree; keep it referenced for the scenario's life.
    boot_main_qml.engine = engine  # type: ignore[attr-defined]
    return root, q, settle, bridge


def _evaluator(context, scope):
    """A QML-expression evaluator: evaluate, raise on error, unwrap tuples."""
    from PySide6.QtQml import QQmlExpression

    def q(expr: str):
        e = QQmlExpression(context, scope, expr)
        r = e.evaluate()
        if e.hasError():
            raise RuntimeError(e.error().toString())
        return r[0] if isinstance(r, tuple) else r

    return q


def scoped_q(q, path: str):
    """Evaluator for expressions naming a split-out component's internal ids.

    Once a component leaves Main.qml (#315) its ids (``queueList``,
    ``queueGrip``, ``logsText``, …) are no longer in the root's QML context,
    so root-context expressions fail with a ReferenceError. Any object the
    component file itself created carries that file's context — the drawer's
    ``background`` is the stable handle — and expressions evaluated against
    it resolve the component's ids exactly as the pre-move expressions did.
    """

    from PySide6.QtQml import QQmlEngine

    scope = q(path)
    return _evaluator(QQmlEngine.contextForObject(scope), scope)
